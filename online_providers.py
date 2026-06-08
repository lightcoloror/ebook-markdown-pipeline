from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


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
    if provider_type == "embedding":
        return FakeEmbeddingProvider()
    raise ValueError(f"Unsupported fake provider type: {provider_type}")


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
