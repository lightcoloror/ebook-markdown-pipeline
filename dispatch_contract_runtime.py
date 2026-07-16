from __future__ import annotations

import copy
from typing import Any, Mapping
from urllib.parse import urlparse

from .dispatch_contract import FAILURE_CLASSES, MODULE_SPECS, PROJECT_DIR, ROUTE_SPECS, SCHEMA_VERSION


def build_dispatch_contract(
    *,
    service: Mapping[str, Any],
    health: Mapping[str, Any] | None = None,
    mineru_service: Mapping[str, Any] | None = None,
    candidate_registry: Mapping[str, Any] | None = None,
    require_http: bool = False,
) -> dict[str, Any]:
    service_payload = copy.deepcopy(dict(service))
    health_payload = copy.deepcopy(dict(health or {}))
    mineru_payload = copy.deepcopy(dict(mineru_service or {}))
    candidate_payload = copy.deepcopy(dict(candidate_registry or {}))
    http = _mapping(service_payload.get("http"))
    configured_url = str(http.get("configured_url") or "")
    configured_port = urlparse(configured_url).port if configured_url else None
    cli_status = "ready" if health_payload.get("minimal_ok") is True else "blocked" if health_payload else "unknown"
    http_status = str(service_payload.get("status") or "unknown")
    if require_http and http_status != "ready":
        overall = "needs_manual_start"
    elif cli_status == "blocked" and http_status != "ready":
        overall = "blocked"
    elif cli_status == "unknown":
        overall = "unknown"
    else:
        overall = http_status if http_status in {"ready", "stopped-by-design", "needs_manual_start"} else "degraded"
    modules = build_module_statuses(health_payload, mineru_payload, candidate_payload)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": overall,
        "status_code": overall.replace("-", "_"),
        "execution_policy": "read_only_discovery_no_service_start_no_model_download_no_conversion",
        "project": {
            "path": str(PROJECT_DIR),
            "config_source": str(http.get("config_path") or PROJECT_DIR / "config" / "http.env"),
            "current_http_url": configured_url,
            "current_http_port": configured_port,
        },
        "legacy_8765": {
            "port": 8765,
            "classification": "current_contract" if configured_port == 8765 else "stale_contract",
            "authoritative": configured_port == 8765,
            "listener_absence_is_outage": configured_port == 8765 and require_http,
            "guidance": "Read config/http.env; never infer current health from port 8765 alone.",
        },
        "entrypoints": {
            "mcp": {"status": "on_demand", "command": str(PROJECT_DIR / "start_mcp.cmd"), "requires_http": False},
            "cli": {"status": cli_status, "command": "python batch_convert_books.py --health-check", "requires_http": False},
            "http": {"status": http_status, "url": configured_url, "auto_start": False, "requires_manual_start": http_status != "ready"},
            "desktop_ui": {"status": "manual", "command": "python book_converter_ui.py", "requires_http": False},
        },
        "health": {
            "schema_version": health_payload.get("schema_version"),
            "status": health_payload.get("status") or "not_checked",
            "minimal_ok": health_payload.get("minimal_ok"),
            "optional_missing_is_ok": health_payload.get("optional_missing_is_ok"),
        },
        "mineru_service": mineru_payload or {"status": "not_checked"},
        "modules": modules,
        "failure_classes": copy.deepcopy(FAILURE_CLASSES),
        "routes": build_routes(modules),
        "consumers": build_consumers(cli_status, http_status, configured_url),
        "boundaries": {
            "auto_start_http": False,
            "auto_start_mineru": False,
            "implicit_mineru_temporary_api": False,
            "auto_download_models": False,
            "remote_calls": False,
            "telegram_send": False,
            "shared_registry_write": False,
        },
    }


def build_module_statuses(health: Mapping[str, Any], mineru: Mapping[str, Any], registry: Mapping[str, Any]) -> list[dict[str, Any]]:
    capabilities = {str(item.get("name")): item for item in health.get("capabilities") or [] if isinstance(item, Mapping)}
    checks = {str(item.get("name")): item for item in health.get("checks") or [] if isinstance(item, Mapping)}
    candidates = {str(item.get("key")): item for item in registry.get("backends") or [] if isinstance(item, Mapping)}
    rows: list[dict[str, Any]] = []
    for spec in MODULE_SPECS:
        detail = "No live health evidence was collected."
        upstream = "unknown"
        if spec.get("capability"):
            item = capabilities.get(str(spec["capability"]), {})
            upstream = str(item.get("status") or "unknown")
            detail = str(item.get("detail") or detail)
        if spec.get("checks"):
            matched = [checks[name] for name in spec["checks"] if name in checks]
            if matched:
                values = [str(item.get("status") or "unknown") for item in matched]
                upstream = "ok" if "ok" in values else "planned_only" if "planned_only" in values else "missing" if all(value == "missing" for value in values) else "degraded"
                detail = "; ".join(f"{item.get('name')}={item.get('status')}" for item in matched)
        candidate = candidates.get(str(spec.get("candidate") or ""))
        if candidate and upstream == "unknown":
            upstream = "planned_only"
            detail = str(candidate.get("default_policy") or "candidate-only plan/fake")
        status = _normalize_status(upstream)
        if spec["key"] == "mineru" and status in {"ready", "degraded"}:
            service_status = str(mineru.get("status") or "not_checked")
            status = "ready" if service_status == "ready" else "needs_manual_start" if service_status == "stopped" else "unknown" if service_status == "not_checked" else "blocked"
            detail = f"{detail}; fixed MinerU API status={service_status}"
        rows.append({"key": spec["key"], "role": spec["role"], "status": status, "detail": detail, "candidate_only": bool(candidate), "execution_action": _execution_action(status)})
    return rows


def build_routes(modules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {str(item["key"]): item for item in modules}
    routes: list[dict[str, Any]] = []
    for route_id, match, steps, review in ROUTE_SPECS:
        resolved_steps = []
        for order, (module_key, purpose) in enumerate(steps, start=1):
            module = by_key.get(module_key, {"status": "unknown", "execution_action": "inspect_health"})
            resolved_steps.append({
                "order": order,
                "module": module_key,
                "purpose": purpose,
                "module_status": module["status"],
                "execution_action": module["execution_action"],
                "on_failure": _failure_policy(module_key),
            })
        routes.append({
            "id": route_id,
            "match": list(match),
            "steps": resolved_steps,
            "manual_review_when": list(review),
            "delivery_gate": "quality_and_artifact_checks_then_manual_review_when_triggered",
        })
    return routes


def build_consumers(cli_status: str, http_status: str, configured_url: str) -> dict[str, Any]:
    host_ready = cli_status == "ready"
    return {
        "local_tools": {
            "status": "ready" if host_ready else "degraded",
            "discover": "D:\\used-by-codex\\scripts\\local-tools.ps1 discover ebook_markdown_pipeline",
            "runtime_status": "python scripts\\check_dispatch_contract.py",
            "fallback": "Use MCP stdio or host CLI; never guess a port.",
        },
        "openclaw_windows": {"status": "ready" if host_ready else "degraded", "preferred": "MCP stdio", "fallback": "host CLI plus artifact handoff"},
        "openclaw_docker": {
            "status": "ready" if http_status == "ready" else "needs_manual_start",
            "preferred": configured_url.replace("127.0.0.1", "host.docker.internal") if configured_url else "read config/http.env",
            "fallback": "Run host-side MCP/CLI and hand off agent-batch-results.json/run_summary.md.",
            "auto_start": False,
        },
        "telegram": {"status": "plan_only", "role": "message transport only; never a parser backend", "fallback": "Return a route plan or manual-start request; do not auto-send or auto-start."},
        "control_console": {"status": "read_only", "source": SCHEMA_VERSION, "display_fields": ["status_code", "project", "entrypoints", "modules", "routes", "consumers"]},
    }


def _failure_policy(module_key: str) -> list[str]:
    if module_key == "mineru":
        return ["service_stopped", "dependency_missing", "timeout", "quality_gate_failed"]
    if module_key in {"gmft_table", "table_transformer", "pdf_table", "table_to_xlsx", "paddleocr", "surya"}:
        return ["dependency_missing", "model_not_prepared", "quality_gate_failed"]
    return ["dependency_missing", "empty_output", "timeout", "quality_gate_failed"]


def _normalize_status(value: str) -> str:
    return {"ok": "ready", "ready": "ready", "degraded": "degraded", "warning": "degraded", "missing": "missing", "blocked": "blocked", "planned_only": "planned_only", "needs_env": "planned_only", "needs_model": "planned_only"}.get(value, "unknown")


def _execution_action(status: str) -> str:
    return {"ready": "eligible", "degraded": "eligible_with_review", "needs_manual_start": "manual_start_required_or_skip", "planned_only": "plan_or_fake_only", "missing": "skip_to_next_fallback", "blocked": "stop_and_report"}.get(status, "inspect_health")


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}
