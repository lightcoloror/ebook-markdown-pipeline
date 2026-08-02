from __future__ import annotations

import importlib
import json
import os
import re
import socket
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = "ebook-shared-vkp-gateway-v1"
DEFAULT_TASK_MAP = {
    "ocr_layout": {"connector_task": "online_ocr", "capability": "ocr"},
    "vlm_layout": {
        "connector_task": "multimodal_frame_analysis",
        "capability": "semantic_frame",
    },
    # VKP does not yet expose a document-structure-specific connector task.
    # The generic text route is kept behind this adapter so that mapping can
    # change without affecting ebook CLI/MCP/UI contracts.
    "text_structure": {
        "connector_task": "provider_task_benchmark",
        "capability": "text_llm",
    },
}


REQUIRED_ONLINE_ONLY_STAGES = {"ocr_layout", "text_structure"}
CONFIG_ENV_LOCK = threading.RLock()
PROFILE_CAPABILITY_TO_STAGE = {
    "ocr": "ocr_layout",
    "vision": "vlm_layout",
    "text": "text_structure",
}


class SharedVkpGatewayError(RuntimeError):
    pass


def shared_provider_catalog(
    profiles: Any,
    route_status: dict[str, Any],
) -> dict[str, Any]:
    """Summarize every VKP remote provider without exposing profile secrets or endpoints."""

    selected_by_provider: dict[str, set[str]] = {}
    for stage, item in route_status.items():
        route = item.get("route") if isinstance(item, dict) else {}
        deployments = route.get("deployments") if isinstance(route, dict) else []
        for deployment in deployments if isinstance(deployments, list) else []:
            if not isinstance(deployment, dict):
                continue
            provider = str(deployment.get("provider") or "").strip()
            if provider:
                selected_by_provider.setdefault(provider, set()).add(stage)

    grouped: dict[str, dict[str, Any]] = {}
    enabled_remote_profile_count = 0
    ebook_eligible_profile_count = 0
    credential_ready_profile_count = 0
    credential_status_available = False
    for row in profiles if isinstance(profiles, list) else []:
        if not isinstance(row, dict) or not bool(row.get("enabled", True)):
            continue
        if str(row.get("location") or "remote").strip().lower() != "remote":
            continue
        provider = str(row.get("provider") or "unknown").strip() or "unknown"
        raw_capabilities = row.get("capabilities")
        capabilities = {
            str(value).strip().lower()
            for value in (raw_capabilities if isinstance(raw_capabilities, list) else [raw_capabilities])
            if str(value or "").strip()
        }
        stages = {
            PROFILE_CAPABILITY_TO_STAGE[capability]
            for capability in capabilities
            if capability in PROFILE_CAPABILITY_TO_STAGE
        }
        enabled_remote_profile_count += 1
        if stages:
            ebook_eligible_profile_count += 1
        if "credential_status" in row or "api_key_configured" in row:
            credential_status_available = True
        if row.get("api_key_configured") is True or str(row.get("credential_status") or "") in {"ready", "configured"}:
            credential_ready_profile_count += 1
        bucket = grouped.setdefault(
            provider,
            {
                "provider": provider,
                "enabled_profile_count": 0,
                "capabilities": set(),
                "ebook_stages": set(),
                "selected_stages": set(),
            },
        )
        bucket["enabled_profile_count"] += 1
        bucket["capabilities"].update(capabilities)
        bucket["ebook_stages"].update(stages)
        bucket["selected_stages"].update(selected_by_provider.get(provider, set()))

    providers = []
    for provider in sorted(grouped):
        row = grouped[provider]
        providers.append(
            {
                "provider": provider,
                "enabled_profile_count": row["enabled_profile_count"],
                "capabilities": sorted(row["capabilities"]),
                "ebook_stages": sorted(row["ebook_stages"]),
                "selected_stages": sorted(row["selected_stages"]),
            }
        )
    return credential_safe_payload({
        "schema_version": "ebook-shared-vkp-provider-catalog-v1",
        "source": "vkp_model_api_settings",
        "provider_count": len(providers),
        "enabled_remote_profile_count": enabled_remote_profile_count,
        "ebook_eligible_profile_count": ebook_eligible_profile_count,
        "credential_status_available": credential_status_available,
        "credential_ready_profile_count": credential_ready_profile_count if credential_status_available else None,
        "providers": providers,
        "selected_route_providers": sorted(selected_by_provider),
        "credential_store": "vkp_windows_dpapi",
        "remote_requests_made": False,
        "selection_policy": "Change VKP route bindings; ebook inherits them without duplicating supplier credentials.",
    })


@dataclass(frozen=True)
class VkpModules:
    api_settings: Any
    gateway: Any
    consent: Any
    trusted_connector: Any


def discover_vkp_root(value: str | Path | None = None) -> Path:
    candidates: list[Path] = []
    if value:
        candidates.append(Path(value))
    env_value = str(os.environ.get("EBOOK_CONVERTER_VKP_ROOT") or "").strip()
    if env_value:
        candidates.append(Path(env_value))
    candidates.append(Path(__file__).resolve().parent.parent / "video-knowledge-pipeline")
    for candidate in candidates:
        root = candidate.expanduser().resolve()
        if (root / "src" / "video_knowledge_pipeline" / "model_gateway.py").is_file():
            return root
    rendered = ", ".join(str(item.expanduser()) for item in candidates)
    raise SharedVkpGatewayError(f"VKP source tree was not found. Checked: {rendered}")


def load_vkp_modules(vkp_root: str | Path | None = None) -> tuple[Path, VkpModules]:
    root = discover_vkp_root(vkp_root)
    src = root / "src"
    src_text = str(src)
    if src_text not in sys.path:
        sys.path.insert(0, src_text)
    modules = VkpModules(
        api_settings=importlib.import_module("video_knowledge_pipeline.model_api_settings"),
        gateway=importlib.import_module("video_knowledge_pipeline.model_gateway"),
        consent=importlib.import_module("video_knowledge_pipeline.model_connector_consent"),
        trusted_connector=importlib.import_module("video_knowledge_pipeline.trusted_model_connector"),
    )
    loaded_path = Path(modules.api_settings.__file__).resolve()
    try:
        loaded_path.relative_to(root)
    except ValueError as exc:
        raise SharedVkpGatewayError(
            f"video_knowledge_pipeline was already imported from another tree: {loaded_path}"
        ) from exc
    return root, modules


def shared_vkp_gateway_fast_health(vkp_root: str | Path | None = None) -> dict[str, Any]:
    """Read route bindings and probe the loopback port without importing VKP runtime modules."""
    root = discover_vkp_root(vkp_root)
    settings_env = str(os.environ.get("VKP_MODEL_API_SETTINGS_PATH") or "").strip()
    settings_path = (
        Path(settings_env).expanduser().resolve()
        if settings_env
        else root / ".local" / "model-api-settings.json"
    )
    gateway_config_path = root / "config" / "model-gateway.json"
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SharedVkpGatewayError(f"VKP route settings are unreadable: {settings_path}: {exc}") from exc
    bindings = settings.get("route_bindings") if isinstance(settings.get("route_bindings"), dict) else {}
    task_routes = settings.get("task_routes") if isinstance(settings.get("task_routes"), dict) else {}
    profiles = settings.get("profiles") if isinstance(settings.get("profiles"), list) else []
    profiles_by_id = {
        str(item.get("id") or ""): item
        for item in profiles
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    route_status: dict[str, Any] = {}
    for stage, mapping in DEFAULT_TASK_MAP.items():
        capability = str(mapping["capability"])
        binding = bindings.get(capability)
        remote_pool_id = (
            str(binding.get("remote_pool_id") or "")
            if isinstance(binding, dict)
            else str(binding or "")
        )
        profile_id = str(task_routes.get(capability) or "")
        profile = profiles_by_id.get(profile_id) or {}
        configured = bool(remote_pool_id or profile_id)
        route_status[stage] = {
            "status": "configured" if configured else "missing",
            "connector_task": mapping["connector_task"],
            "capability": capability,
            "probe": "route_binding_only",
        }
        if profile:
            route_status[stage]["route"] = {
                "deployments": [
                    {
                        key: profile.get(key)
                        for key in ("id", "provider", "model", "location")
                        if profile.get(key) not in (None, "")
                    }
                ]
            }

    gateway_config: dict[str, Any] = {}
    try:
        raw_gateway = json.loads(gateway_config_path.read_text(encoding="utf-8"))
        if isinstance(raw_gateway, dict):
            gateway_config = raw_gateway
    except (OSError, json.JSONDecodeError):
        gateway_config = {}
    host = str(gateway_config.get("host") or "127.0.0.1")
    port = int(gateway_config.get("port") or 18776)
    listening = False
    try:
        with socket.create_connection((host, port), timeout=0.2):
            listening = True
    except OSError:
        listening = False

    configured = [name for name, item in route_status.items() if item["status"] == "configured"]
    missing = [name for name, item in route_status.items() if item["status"] != "configured"]
    missing_required = [name for name in missing if name in REQUIRED_ONLINE_ONLY_STAGES]
    missing_optional = [name for name in missing if name not in REQUIRED_ONLINE_ONLY_STAGES]
    provider_catalog = shared_provider_catalog(profiles, route_status)
    status = "ready" if listening and not missing_required else ("on_demand" if not missing_required else "degraded")
    return credential_safe_payload({
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "ready": listening and not missing_required,
        "probe_mode": "fast_config_and_tcp",
        "vkp_root": str(root),
        "settings_path": str(settings_path),
        "gateway_config_path": str(gateway_config_path),
        "gateway": {
            "ready": listening,
            "host": host,
            "port": port,
            "probe": "tcp_connect",
        },
        "routes": route_status,
        "shared_provider_catalog": provider_catalog,
        "configured_stages": configured,
        "missing_stages": missing,
        "missing_required_stages": missing_required,
        "missing_optional_stages": missing_optional,
        "credential_store": "vkp_windows_dpapi",
        "remote_requests_made": False,
        "fallback": "MCP/CLI planning remains available; start the VKP gateway only for confirmed remote execution.",
    })


class SharedVkpGateway:
    """Use VKP's route registry and DPAPI secret store without copying API keys."""

    def __init__(
        self,
        vkp_root: str | Path | None = None,
        *,
        settings_path: str | Path | None = None,
        gateway_config_path: str | Path | None = None,
    ) -> None:
        self.root, self.modules = load_vkp_modules(vkp_root)
        self.settings_path = (
            Path(settings_path).expanduser().resolve()
            if settings_path
            else self.root / ".local" / "model-api-settings.json"
        )
        self.secrets_path = self.settings_path.with_name("model-api-secrets.json")
        self.gateway_config_path = (
            Path(gateway_config_path).expanduser().resolve()
            if gateway_config_path
            else self.root / "config" / "model-gateway.json"
        )

    def health(self) -> dict[str, Any]:
        route_status: dict[str, Any] = {}
        for stage, mapping in DEFAULT_TASK_MAP.items():
            try:
                route = self._resolve_route(str(mapping["capability"]))
                route_status[stage] = {
                    "status": "configured",
                    "connector_task": mapping["connector_task"],
                    "capability": mapping["capability"],
                    "route": sanitize_route(route),
                }
            except Exception as exc:  # noqa: BLE001
                route_status[stage] = {
                    "status": "missing",
                    "connector_task": mapping["connector_task"],
                    "capability": mapping["capability"],
                    "error": str(exc),
                }
        with self._configured_paths():
            public_settings = self.modules.api_settings.load_model_api_settings(
                settings_path=self.settings_path,
            )
            gateway = self.modules.gateway.model_gateway_runtime_readiness(
                gateway_config_path=self.gateway_config_path
            )
        configured = [name for name, item in route_status.items() if item["status"] == "configured"]
        missing = [name for name, item in route_status.items() if item["status"] != "configured"]
        missing_required = [name for name in missing if name in REQUIRED_ONLINE_ONLY_STAGES]
        missing_optional = [name for name in missing if name not in REQUIRED_ONLINE_ONLY_STAGES]
        ready = bool(gateway.get("ready")) and not missing_required
        status = "ready" if ready else ("on_demand" if not missing_required and not gateway.get("ready") else "degraded")
        provider_catalog = shared_provider_catalog(public_settings.get("profiles"), route_status)
        return credential_safe_payload({
            "schema_version": SCHEMA_VERSION,
            "status": status,
            "ready": ready,
            "vkp_root": str(self.root),
            "settings_path": str(self.settings_path),
            "gateway_config_path": str(self.gateway_config_path),
            "gateway": gateway,
            "routes": route_status,
            "shared_provider_catalog": provider_catalog,
            "configured_stages": configured,
            "missing_stages": missing,
            "missing_required_stages": missing_required,
            "missing_optional_stages": missing_optional,
            "credential_store": "vkp_windows_dpapi",
            "remote_requests_made": False,
            "fallback": "MCP/CLI planning remains available; start the VKP gateway only for confirmed remote execution.",
        })

    def ensure_gateway(
        self,
        *,
        start: bool = False,
        startup_timeout_seconds: float = 20.0,
        poll_interval_seconds: float = 0.25,
    ) -> dict[str, Any]:
        with self._configured_paths():
            readiness = self.modules.gateway.model_gateway_runtime_readiness(
                gateway_config_path=self.gateway_config_path
            )
            if readiness.get("ready") or not start:
                return readiness
            started = self.modules.gateway.start_model_gateway(
                gateway_config_path=self.gateway_config_path,
                settings_path=self.settings_path,
                secrets_path=self.secrets_path,
                execute=True,
            )
            followup = self.modules.gateway.model_gateway_runtime_readiness(
                gateway_config_path=self.gateway_config_path
            )
            poll_attempts = 1
            deadline = time.monotonic() + max(0.0, float(startup_timeout_seconds))
            while not followup.get("ready") and time.monotonic() < deadline:
                remaining = max(0.0, deadline - time.monotonic())
                time.sleep(min(max(0.01, float(poll_interval_seconds)), remaining))
                followup = self.modules.gateway.model_gateway_runtime_readiness(
                    gateway_config_path=self.gateway_config_path
                )
                poll_attempts += 1
        ready = bool(followup.get("ready"))
        return {
            "start": sanitize_gateway_start(started),
            "readiness": followup,
            "ready": ready,
            "startup_wait": {
                "timeout_seconds": max(0.0, float(startup_timeout_seconds)),
                "poll_interval_seconds": max(0.01, float(poll_interval_seconds)),
                "poll_attempts": poll_attempts,
                "timed_out": not ready,
            },
        }

    def execute(
        self,
        stage: str,
        artifact_paths: list[str | Path],
        *,
        instructions: str,
        run_dir: str | Path,
        max_estimated_cost_usd: float,
        confirm_data_export: bool,
        start_gateway: bool = False,
        max_retries_per_call: int = 1,
    ) -> dict[str, Any]:
        mapping = DEFAULT_TASK_MAP.get(stage)
        if not mapping:
            raise SharedVkpGatewayError(f"Unsupported shared VKP stage: {stage}")
        if not confirm_data_export:
            raise SharedVkpGatewayError("Remote execution requires confirm_data_export=true.")
        if float(max_estimated_cost_usd) <= 0:
            raise SharedVkpGatewayError("Remote execution requires a positive max_estimated_cost_usd.")
        paths = [Path(value).expanduser().resolve() for value in artifact_paths]
        missing = [str(path) for path in paths if not path.is_file()]
        if missing:
            raise SharedVkpGatewayError(f"Remote artifacts do not exist: {missing}")
        gateway = self.ensure_gateway(start=start_gateway)
        gateway_ready = bool(gateway.get("ready")) or bool((gateway.get("readiness") or {}).get("ready"))
        if not gateway_ready:
            raise SharedVkpGatewayError(
                "VKP LiteLLM gateway is not running. Retry with start_gateway=true or start it from VKP."
            )
        connector_task = str(mapping["connector_task"])
        route = self._resolve_route(str(mapping["capability"]))
        requested_retries = max(0, int(max_retries_per_call))
        route_retry_limit = max(0, int((route.get("retry_policy") or {}).get("max_retries") or 0))
        effective_retries = min(requested_retries, route_retry_limit)
        destination = Path(run_dir).expanduser().resolve()
        destination.mkdir(parents=True, exist_ok=True)
        consent_path = destination / f"{safe_slug(stage)}-consent.json"
        logical_calls = len(paths) if connector_task == "online_ocr" else 1
        max_calls = logical_calls * (1 + effective_retries)
        with self._configured_paths(allowed_roots=paths):
            consent = self.modules.consent.create_model_connector_consent(
                destination,
                task=connector_task,
                artifact_paths=paths,
                route_snapshot=route,
                instructions=instructions,
                purpose="ebook_markdown_pipeline online-only document conversion",
                expires_hours=24,
                max_calls=max_calls,
                max_estimated_cost_usd=float(max_estimated_cost_usd),
                max_retries_per_call=effective_retries,
                confirm_data_export=True,
                output_path=consent_path,
                write=True,
            )
            execution = self.modules.trusted_connector.execute_consented_model_task(
                consent_path,
                expected_route_revision=str(route.get("route_revision") or ""),
                write=True,
            )
        return credential_safe_payload({
            "schema_version": SCHEMA_VERSION,
            "stage": stage,
            "connector_task": connector_task,
            "route": sanitize_route(route),
            "consent_path": str(consent_path),
            "confirmed_data_export": True,
            "max_estimated_cost_usd": float(max_estimated_cost_usd),
            "runtime_artifact_scope": "exact_artifact_paths",
            "retry_policy": {
                "requested_max_retries_per_call": requested_retries,
                "route_max_retries": route_retry_limit,
                "effective_max_retries_per_call": effective_retries,
                "logical_calls": logical_calls,
                "authorized_attempts": max_calls,
            },
            "remote_requests_made": execution_remote_requests_made(execution, route=route),
            "execution": execution,
            "markdown": extract_markdown_from_execution(execution),
            "pages": extract_ocr_pages(execution),
        })

    def _resolve_route(self, capability: str) -> dict[str, Any]:
        with self._configured_paths():
            route = self.modules.api_settings.resolve_model_api_route(
                capability,
                execution_location="remote",
                settings_path=self.settings_path,
            )
        if not isinstance(route, dict) or not route.get("route_revision"):
            raise SharedVkpGatewayError(f"VKP has no configured remote route for {capability}.")
        return route

    @contextmanager
    def _configured_paths(self, *, allowed_roots: list[Path] | None = None) -> Iterator[None]:
        updates = {
            "VKP_MODEL_API_SETTINGS_PATH": str(self.settings_path),
            "VKP_MODEL_API_SECRETS_PATH": str(self.secrets_path),
        }
        if allowed_roots:
            updates["VKP_MODEL_RUNTIME_ALLOWED_ROOTS"] = os.pathsep.join(
                str(path) for path in allowed_roots
            )
        with CONFIG_ENV_LOCK:
            previous = {key: os.environ.get(key) for key in updates}
            os.environ.update(updates)
            try:
                yield
            finally:
                for key, value in previous.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value


def sanitize_route(route: dict[str, Any]) -> dict[str, Any]:
    deployments = []
    for raw in route.get("deployments") or []:
        if not isinstance(raw, dict):
            continue
        deployments.append(
            {
                key: raw.get(key)
                for key in ("id", "provider", "model", "adapter_backend", "location")
                if raw.get(key) not in (None, "")
            }
        )
    return {
        "route_id": str(route.get("route_id") or ""),
        "route_revision": str(route.get("route_revision") or ""),
        "virtual_model": str(route.get("virtual_model") or ""),
        "execution_location": str(route.get("execution_location") or ""),
        "deployments": deployments,
    }


def sanitize_gateway_start(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": payload.get("status"),
        "execute": bool(payload.get("execute")),
        "gateway": payload.get("gateway") or {},
        "render": {
            key: (payload.get("render") or {}).get(key)
            for key in ("model_count", "ready_for_start", "credential_blockers")
        },
        "secrets_in_command": bool(payload.get("secrets_in_command", False)),
        "remote_requests_made": bool(payload.get("remote_requests_made", False)),
        "error": payload.get("error"),
    }


def execution_remote_requests_made(
    execution: dict[str, Any],
    *,
    route: dict[str, Any] | None = None,
) -> bool:
    """Normalize VKP task wrappers that expose network evidence at different depths."""

    network_evidence = False
    explicit_true = False

    def inspect(value: Any) -> None:
        nonlocal explicit_true, network_evidence
        if isinstance(value, dict):
            if value.get("remote_requests_made") is True:
                explicit_true = True
            accounting = value.get("network_accounting")
            if isinstance(accounting, dict) and (
                int(accounting.get("gateway_request_bytes") or 0) > 0
                or int(accounting.get("gateway_response_bytes") or 0) > 0
            ):
                network_evidence = True
            for child in value.values():
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)

    inspect(execution)
    if explicit_true or network_evidence:
        return True
    resolved_route = route if isinstance(route, dict) else {}
    model_result = execution.get("model_result") if isinstance(execution.get("model_result"), dict) else {}
    return bool(
        execution.get("ok")
        and model_result.get("ok")
        and str(resolved_route.get("execution_location") or "") == "remote"
    )

def extract_ocr_pages(execution: dict[str, Any]) -> list[dict[str, Any]]:
    model_result = execution.get("model_result") if isinstance(execution.get("model_result"), dict) else {}
    content = model_result.get("content") if isinstance(model_result.get("content"), dict) else {}
    raw_pages = content.get("pages") if isinstance(content.get("pages"), list) else []
    pages = []
    for position, row in enumerate(raw_pages, start=1):
        if not isinstance(row, dict):
            continue
        markdown = extract_candidate_text(row)
        pages.append(
            {
                "index": int(row.get("index") or (position - 1)),
                "page_number": position,
                "markdown": markdown,
                "source_artifact_sha256": str(row.get("source_artifact_sha256") or ""),
                "evidence_status": str(row.get("evidence_status") or "candidate"),
            }
        )
    return pages


def extract_markdown_from_execution(execution: dict[str, Any]) -> str:
    pages = extract_ocr_pages(execution)
    if pages:
        return "\n\n".join(page["markdown"].strip() for page in pages if page["markdown"].strip()).strip()
    model_result = execution.get("model_result") if isinstance(execution.get("model_result"), dict) else {}
    return extract_candidate_text(model_result).strip()


def extract_candidate_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [extract_candidate_text(item) for item in value]
        return "\n\n".join(part for part in parts if part).strip()
    if not isinstance(value, dict):
        return ""
    for key in ("markdown", "output_text", "text"):
        if isinstance(value.get(key), str) and value[key].strip():
            return str(value[key]).strip()
    choices = value.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict):
            candidate = extract_candidate_text(message.get("content"))
            if candidate:
                return candidate
    for key in ("content", "runtime_result", "raw_output", "response", "result"):
        candidate = extract_candidate_text(value.get(key))
        if candidate:
            return candidate
    return ""


def safe_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", value.lower()).strip("-") or "task"


def redacted_json(payload: dict[str, Any]) -> str:
    """Serialize artifacts only when structured credential fields are absent."""
    findings = find_credential_fields(payload)
    if findings:
        raise SharedVkpGatewayError(
            "Credential-like fields were found in a shared gateway artifact: " + ", ".join(findings)
        )
    return json.dumps(payload, ensure_ascii=False, indent=2)


SAFE_CREDENTIAL_METADATA_KEYS = frozenset(
    {
        "api_keys_exposed",
        "api_keys_copied",
        "api_keys_persisted_in_artifacts",
        "credential_artifact_scan",
        "credential_ready_profile_count",
        "credential_status_available",
        "credential_store",
        "max_tokens",
        "token_budget",
        "token_count",
    }
)
CREDENTIAL_FIELD_NAMES = frozenset(
    {
        "access_token",
        "accesstoken",
        "api_key",
        "apikey",
        "auth_token",
        "authorization",
        "authtoken",
        "bearer",
        "client_secret",
        "clientsecret",
        "credentials",
        "password",
        "private_key",
        "privatekey",
        "refresh_token",
        "refreshtoken",
        "secret",
        "token",
        "x_api_key",
        "xapikey",
    }
)
CREDENTIAL_FIELD_SUFFIXES = (
    "_access_token",
    "_api_key",
    "_auth_token",
    "_client_secret",
    "_id_token",
    "_private_key",
    "_refresh_token",
    "_secret",
)


def is_credential_field_name(key: Any) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(key or "").strip().lower()).strip("_")
    if not normalized or normalized in SAFE_CREDENTIAL_METADATA_KEYS:
        return False
    compact = normalized.replace("_", "")
    if normalized in CREDENTIAL_FIELD_NAMES or compact in CREDENTIAL_FIELD_NAMES:
        return True
    return normalized.endswith(CREDENTIAL_FIELD_SUFFIXES)


def find_credential_fields(value: Any, *, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}.{key}"
            if is_credential_field_name(key) and item not in (None, "", False, [], {}):
                findings.append(child_path)
            findings.extend(find_credential_fields(item, path=child_path))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            findings.extend(find_credential_fields(item, path=f"{path}[{index}]"))
    return sorted(set(findings))


def contains_credential_value(value: Any) -> bool:
    return bool(find_credential_fields(value))


def credential_safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    findings = find_credential_fields(payload)
    if findings:
        raise SharedVkpGatewayError(
            "Credential-like fields were found before returning a shared gateway payload: " + ", ".join(findings)
        )
    result = dict(payload)
    result["credential_artifact_scan"] = {
        "performed": True,
        "passed": True,
        "matched_field_count": 0,
    }
    result["api_keys_exposed"] = False
    result["api_keys_copied"] = False
    return result
