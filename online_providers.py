from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol


PROVIDER_CONFIG_SCHEMA_VERSION = "online-model-providers-v1"
DEFAULT_PROVIDER_CONFIG = Path(__file__).resolve().parent / "config" / "online_models.example.json"


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    type: str
    base_url: str = ""
    model: str = ""
    api_key_env: str = ""
    timeout_seconds: int = 60
    max_concurrency: int = 1
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def api_key_available(self) -> bool:
        return bool(self.api_key_env and os.environ.get(self.api_key_env))

    def health(self) -> dict[str, Any]:
        if self.name.startswith("fake_"):
            status = "ok"
            detail = "fake provider for tests and dry-run contracts"
        elif not self.base_url:
            status = "missing"
            detail = "base_url is not configured"
        elif self.api_key_env and not self.api_key_available:
            status = "missing_key"
            detail = f"missing environment variable {self.api_key_env}"
        else:
            status = "configured"
            detail = "provider is configured but not live-tested"
        return {
            "name": self.name,
            "type": self.type,
            "model": self.model,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "api_key_available": self.api_key_available,
            "timeout_seconds": self.timeout_seconds,
            "max_concurrency": self.max_concurrency,
            "status": status,
            "detail": detail,
        }


@dataclass(frozen=True)
class ProviderRegistry:
    schema_version: str
    default_mode: str
    providers: dict[str, ProviderConfig]
    routing: dict[str, str] = field(default_factory=dict)
    safety: dict[str, Any] = field(default_factory=dict)

    def provider_for_route(self, route: str) -> ProviderConfig | None:
        name = self.routing.get(route)
        if not name:
            return None
        return self.providers.get(name)

    def health(self) -> dict[str, Any]:
        provider_health = [provider.health() for provider in self.providers.values()]
        return {
            "schema_version": self.schema_version,
            "default_mode": self.default_mode,
            "provider_count": len(self.providers),
            "providers": provider_health,
            "routing": dict(self.routing),
            "safety": dict(self.safety),
            "configured_count": sum(1 for item in provider_health if item["status"] in {"ok", "configured"}),
            "missing_key_count": sum(1 for item in provider_health if item["status"] == "missing_key"),
        }


class OcrLayoutProvider(Protocol):
    def recognize_layout(self, image: bytes, *, mime_type: str = "image/png", prompt: str = "") -> dict[str, Any]:
        ...


class VlmLayoutProvider(Protocol):
    def describe_layout(self, image: bytes, *, mime_type: str = "image/png", prompt: str = "") -> dict[str, Any]:
        ...


class TextStructureProvider(Protocol):
    def repair_structure(self, markdown: str, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        ...


class TableRepairProvider(Protocol):
    def repair_table(self, table_markdown: str, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        ...


class EmbeddingProvider(Protocol):
    def embed_texts(self, texts: list[str]) -> dict[str, Any]:
        ...


class FakeOcrLayoutProvider:
    def recognize_layout(self, image: bytes, *, mime_type: str = "image/png", prompt: str = "") -> dict[str, Any]:
        return {
            "provider": "fake_ocr_layout",
            "mime_type": mime_type,
            "prompt": prompt,
            "blocks": [
                {
                    "text": "Fake OCR block",
                    "bbox": [0, 0, 100, 24],
                    "page": 1,
                    "block_type": "text",
                    "confidence": 1.0,
                    "reading_order": 1,
                }
            ],
            "input_bytes": len(image),
        }


class FakeVlmLayoutProvider:
    def describe_layout(self, image: bytes, *, mime_type: str = "image/png", prompt: str = "") -> dict[str, Any]:
        return {
            "provider": "fake_vlm_layout",
            "mime_type": mime_type,
            "prompt": prompt,
            "markdown": "# Fake Layout\n\n- Fake visual block",
            "blocks": [{"text": "Fake visual block", "block_type": "heading", "confidence": 1.0}],
            "input_bytes": len(image),
        }


class FakeTextStructureProvider:
    def repair_structure(self, markdown: str, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        lines = markdown.splitlines()
        repaired = "\n".join(f"# {line}" if idx == 0 and line and not line.startswith("#") else line for idx, line in enumerate(lines))
        return {
            "provider": "fake_text_structure",
            "markdown": repaired,
            "decisions": [
                {
                    "line_number": 1,
                    "action": "promoted_to_heading" if lines and not lines[0].startswith("#") else "kept",
                    "confidence": 1.0,
                    "reason": "fake provider deterministic test output",
                }
            ],
            "context": context or {},
        }


class FakeEmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> dict[str, Any]:
        vectors = [[float(len(text)), float(sum(ord(ch) for ch in text) % 997)] for text in texts]
        return {"provider": "fake_embedding", "vectors": vectors, "dimension": 2}


class FakeTableRepairProvider:
    def repair_table(self, table_markdown: str, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "provider": "fake_table_repair",
            "markdown": table_markdown.strip(),
            "tables": [{"markdown": table_markdown.strip(), "confidence": 1.0}],
            "decisions": [{"action": "kept_table", "confidence": 1.0, "reason": "fake provider deterministic test output"}],
            "context": context or {},
        }


Transport = Callable[[str, dict[str, str], dict[str, Any], int], dict[str, Any]]


class OnlineProviderError(RuntimeError):
    def __init__(self, message: str, *, provider: str, retryable: bool = False, status_code: int | None = None) -> None:
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable
        self.status_code = status_code

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": "online_provider_error",
            "provider": self.provider,
            "message": str(self),
            "retryable": self.retryable,
            "status_code": self.status_code,
        }


def default_json_transport(url: str, headers: dict[str, str], payload: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - user-configured local/remote API endpoint
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        retryable = exc.code in {408, 409, 425, 429, 500, 502, 503, 504}
        raise OnlineProviderError(body or str(exc), provider=url, retryable=retryable, status_code=exc.code) from exc
    except urllib.error.URLError as exc:
        raise OnlineProviderError(str(exc), provider=url, retryable=True) from exc


class OpenAICompatibleProvider:
    def __init__(self, config: ProviderConfig, *, transport: Transport | None = None) -> None:
        self.config = config
        self.transport = transport or default_json_transport

    def repair_structure(self, markdown: str, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        prompt = (
            "Repair Markdown heading hierarchy. Return JSON with keys: markdown, decisions, confidence. "
            "Do not invent missing content.\n\n"
            f"Context JSON:\n{json.dumps(context or {}, ensure_ascii=False)}\n\nMarkdown:\n{markdown}"
        )
        response = self.chat(prompt)
        return normalize_text_structure_response(response, provider=self.config.name, source_markdown=markdown)

    def describe_layout(self, image: bytes, *, mime_type: str = "image/png", prompt: str = "") -> dict[str, Any]:
        user_prompt = prompt or (
            "Extract the visual document layout. Return JSON with keys: markdown, blocks, tables, warnings. "
            "Preserve reading order and do not force non-table card layouts into Markdown tables."
        )
        response = self.chat(user_prompt, image=image, mime_type=mime_type)
        return normalize_vlm_layout_response(response, provider=self.config.name)

    def recognize_layout(self, image: bytes, *, mime_type: str = "image/png", prompt: str = "") -> dict[str, Any]:
        user_prompt = prompt or (
            "Run OCR with layout. Return JSON with keys: blocks, markdown, warnings. "
            "Each block should include text, bbox, page, block_type, confidence, and reading_order when possible."
        )
        response = self.chat(user_prompt, image=image, mime_type=mime_type)
        return normalize_ocr_layout_response(response, provider=self.config.name)

    def repair_table(self, table_markdown: str, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        prompt = (
            "Repair only true tables. Return JSON with keys: markdown, tables, decisions, confidence. "
            "If the input is not a real table, return it unchanged and explain why.\n\n"
            f"Context JSON:\n{json.dumps(context or {}, ensure_ascii=False)}\n\nTable candidate:\n{table_markdown}"
        )
        response = self.chat(prompt)
        return normalize_table_repair_response(response, provider=self.config.name, source_table=table_markdown)

    def embed_texts(self, texts: list[str]) -> dict[str, Any]:
        payload = {"model": self.config.model, "input": texts}
        response = self.post("/embeddings", payload)
        vectors = [item.get("embedding", []) for item in response.get("data", []) if isinstance(item, dict)]
        return {"provider": self.config.name, "model": self.config.model, "vectors": vectors, "raw": response}

    def chat(self, prompt: str, *, image: bytes | None = None, mime_type: str = "image/png") -> dict[str, Any]:
        payload = build_openai_compatible_chat_payload(self.config, prompt=prompt, image=image, mime_type=mime_type)
        return self.post("/chat/completions", payload)

    def post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = self.endpoint_url(endpoint)
        headers = {"Content-Type": "application/json"}
        api_key = os.environ.get(self.config.api_key_env) if self.config.api_key_env else ""
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        elif self.config.api_key_env:
            raise OnlineProviderError(
                f"Missing API key environment variable {self.config.api_key_env}",
                provider=self.config.name,
                retryable=False,
            )
        return self.transport(url, headers, payload, self.config.timeout_seconds)

    def endpoint_url(self, endpoint: str) -> str:
        return f"{self.config.base_url.rstrip('/')}{endpoint}"


def load_provider_registry(path: str | Path | None = None) -> ProviderRegistry:
    config_path = Path(path) if path else Path(os.environ.get("EBOOK_CONVERTER_ONLINE_MODELS_CONFIG") or DEFAULT_PROVIDER_CONFIG)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    schema_version = str(payload.get("schema_version") or PROVIDER_CONFIG_SCHEMA_VERSION)
    providers: dict[str, ProviderConfig] = {}
    for name, raw in (payload.get("providers") or {}).items():
        raw_dict = dict(raw or {})
        known = {
            "name": name,
            "type": str(raw_dict.pop("type", "")),
            "base_url": str(raw_dict.pop("base_url", "")),
            "model": str(raw_dict.pop("model", "")),
            "api_key_env": str(raw_dict.pop("api_key_env", "")),
            "timeout_seconds": int(raw_dict.pop("timeout_seconds", 60) or 60),
            "max_concurrency": int(raw_dict.pop("max_concurrency", 1) or 1),
            "extra": raw_dict,
        }
        providers[name] = ProviderConfig(**known)
    return ProviderRegistry(
        schema_version=schema_version,
        default_mode=str(payload.get("default_mode") or "local"),
        providers=providers,
        routing=dict(payload.get("routing") or {}),
        safety=dict(payload.get("safety") or {}),
    )


def fake_provider_for_type(provider_type: str) -> Any:
    if provider_type in {"ocr_layout", "ocr"}:
        return FakeOcrLayoutProvider()
    if provider_type in {"vlm_layout", "vlm"}:
        return FakeVlmLayoutProvider()
    if provider_type in {"text_structure_llm", "text_structure"}:
        return FakeTextStructureProvider()
    if provider_type in {"table_parser", "table_repair"}:
        return FakeTableRepairProvider()
    if provider_type == "embedding":
        return FakeEmbeddingProvider()
    raise ValueError(f"Unsupported fake provider type: {provider_type}")


def openai_compatible_provider(config: ProviderConfig, *, transport: Transport | None = None) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(config, transport=transport)


def build_openai_compatible_chat_payload(
    config: ProviderConfig,
    *,
    prompt: str,
    image: bytes | None = None,
    mime_type: str = "image/png",
) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    if image is not None:
        data = base64.b64encode(image).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{data}"}})
    return {
        "model": config.model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
    }


def normalize_text_structure_response(response: dict[str, Any], *, provider: str, source_markdown: str) -> dict[str, Any]:
    content = extract_openai_message_content(response)
    parsed = parse_json_object(content)
    markdown = str(parsed.get("markdown") or content or source_markdown)
    decisions = parsed.get("decisions") if isinstance(parsed.get("decisions"), list) else []
    return {
        "provider": provider,
        "markdown": markdown,
        "decisions": decisions,
        "confidence": parsed.get("confidence"),
        "raw": response,
    }


def normalize_vlm_layout_response(response: dict[str, Any], *, provider: str) -> dict[str, Any]:
    content = extract_openai_message_content(response)
    parsed = parse_json_object(content)
    markdown = str(parsed.get("markdown") or content or "")
    blocks = parsed.get("blocks") if isinstance(parsed.get("blocks"), list) else []
    tables = parsed.get("tables") if isinstance(parsed.get("tables"), list) else []
    warnings = parsed.get("warnings") if isinstance(parsed.get("warnings"), list) else []
    return {
        "provider": provider,
        "markdown": markdown,
        "blocks": blocks,
        "tables": tables,
        "warnings": warnings,
        "raw": response,
    }


def normalize_ocr_layout_response(response: dict[str, Any], *, provider: str) -> dict[str, Any]:
    content = extract_openai_message_content(response)
    parsed = parse_json_object(content)
    blocks = parsed.get("blocks") if isinstance(parsed.get("blocks"), list) else []
    markdown = str(parsed.get("markdown") or content or "")
    warnings = parsed.get("warnings") if isinstance(parsed.get("warnings"), list) else []
    return {
        "provider": provider,
        "markdown": markdown,
        "blocks": blocks,
        "warnings": warnings,
        "raw": response,
    }


def normalize_table_repair_response(response: dict[str, Any], *, provider: str, source_table: str) -> dict[str, Any]:
    content = extract_openai_message_content(response)
    parsed = parse_json_object(content)
    markdown = str(parsed.get("markdown") or content or source_table)
    tables = parsed.get("tables") if isinstance(parsed.get("tables"), list) else [{"markdown": markdown}]
    decisions = parsed.get("decisions") if isinstance(parsed.get("decisions"), list) else []
    return {
        "provider": provider,
        "markdown": markdown,
        "tables": tables,
        "decisions": decisions,
        "confidence": parsed.get("confidence"),
        "raw": response,
    }


def extract_openai_message_content(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else {}
        content = message.get("content") if isinstance(message, dict) else ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            return "\n".join(parts)
    if isinstance(response.get("content"), str):
        return str(response["content"])
    return ""


def parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        return {}
    if stripped.startswith("```"):
        stripped = strip_json_fence(stripped)
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(stripped[start : end + 1])
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
    return {}


def strip_json_fence(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def provider_registry_health(path: str | Path | None = None) -> dict[str, Any]:
    try:
        registry = load_provider_registry(path)
    except FileNotFoundError as exc:
        return {"ok": False, "error": "config_not_found", "message": str(exc)}
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": "invalid_json", "message": str(exc)}
    payload = registry.health()
    payload["ok"] = True
    return payload
