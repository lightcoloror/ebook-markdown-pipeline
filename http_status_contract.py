from __future__ import annotations

import copy
from typing import Any, Mapping
from urllib.parse import urlparse

SCHEMA_VERSION = "ebook-http-status-contract-v1"
HTTP_STATES = ("healthy", "stopped-by-design", "stale-pid", "unknown")
CLI_STATES = ("ready", "degraded", "blocked")
OPTIONAL_STATES = ("ready", "degraded", "unknown")
OUTPUT_STATES = ("minimal-deliverable", "degraded", "blocked", "fallback-proposed")


def status_vocabulary() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "dimensions": ["cli", "http_runtime", "optional_backends", "minimal_output"],
        "http_states": list(HTTP_STATES),
        "cli_states": list(CLI_STATES),
        "optional_states": list(OPTIONAL_STATES),
        "output_states": list(OUTPUT_STATES),
        "invariants": {
            "http_stopped_implies_cli_unusable": False,
            "optional_missing_implies_cli_blocked": False,
            "minimal_deliverable_implies_quality_passed": False,
            "legacy_port_is_authoritative": False,
            "auto_start": False,
        },
    }


def build_http_status_contract(observation: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = copy.deepcopy(dict(observation))
    configured_url = str(snapshot.get("configured_url") or "")
    configured_port = _configured_port(configured_url, snapshot.get("configured_port"))
    listener = _mapping(snapshot.get("listener"))
    pid = _mapping(snapshot.get("pid"))
    cli_health = _mapping(snapshot.get("cli_health"))
    quality_route = _mapping(snapshot.get("quality_route"))
    optional = {str(key): str(value) for key, value in _mapping(snapshot.get("optional_backends")).items()}
    legacy = _mapping(snapshot.get("legacy_8765"))

    http_state, http_reasons = _http_state(listener, pid)
    cli_state = _cli_state(cli_health)
    missing = sorted(key for key, value in optional.items() if value in {"missing", "planned_only", "blocked"})
    degraded = sorted(key for key, value in optional.items() if value in {"degraded", "limited"})
    optional_state = "degraded" if missing or degraded else "ready" if optional else "unknown"

    route = _mapping(quality_route.get("route"))
    artifact = _mapping(quality_route.get("artifact"))
    quality = _mapping(quality_route.get("quality"))
    output_state = str(route.get("status") or "blocked")
    if output_state not in OUTPUT_STATES:
        output_state = "blocked"

    cli_callable = cli_state in {"ready", "degraded"}
    preferred_entrypoint = "http" if http_state == "healthy" else "cli" if cli_callable else "none"
    legacy_state = str(legacy.get("state") or "unknown")
    legacy_authoritative = configured_port == 8765

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "callable" if cli_callable else "blocked",
        "cli": {
            "status": cli_state,
            "callable": cli_callable,
            "health_schema": cli_health.get("schema_version"),
            "minimal_ok": bool(cli_health.get("minimal_ok")),
            "reason": "minimal CLI capabilities are ready" if cli_state == "ready" else "CLI is not fully ready",
        },
        "http_runtime": {
            "status": http_state,
            "configured_url": configured_url,
            "configured_port": configured_port,
            "listener_checked": bool(listener.get("checked")),
            "listener_listening": bool(listener.get("listening")),
            "pid": pid,
            "reason_codes": http_reasons,
            "auto_start": False,
            "requires_manual_start": http_state != "healthy",
        },
        "legacy_8765": {
            "port": 8765,
            "observed_state": legacy_state,
            "evidence_ref": legacy.get("evidence_ref"),
            "authoritative_for_current_runtime": legacy_authoritative,
            "interpretation": "configured listener evidence" if legacy_authoritative else "legacy observation only; read config/http.env",
        },
        "optional_backends": {
            "status": optional_state,
            "missing": missing,
            "degraded": degraded,
            "full_quality_support": not missing and not degraded,
            "does_not_block_cli": cli_callable,
        },
        "minimal_output": {
            "status": output_state,
            "artifact_exists": bool(artifact.get("exists")),
            "quality_passed": bool(quality.get("passed")),
            "deliverable": bool(route.get("deliverable")),
            "manual_review_required": bool(quality_route.get("manual_review_required")),
            "fallback_proposal": copy.deepcopy(quality_route.get("fallback_proposal") or {}),
        },
        "discovery": {
            "preferred_entrypoint": preferred_entrypoint,
            "cli_command": "python batch_convert_books.py --health-check",
            "http_url_source": "config/http.env",
            "http_available": http_state == "healthy",
            "offline_quality_route_available": cli_callable,
        },
        "relations": {
            "http_stopped_cli_callable": http_state in {"stopped-by-design", "stale-pid"} and cli_callable,
            "optional_missing_cli_callable": bool(missing) and cli_callable,
            "artifact_exists_quality_failed": bool(artifact.get("exists")) and not bool(quality.get("passed")),
            "minimal_deliverable_quality_separate": output_state == "minimal-deliverable" and "passed" in quality,
        },
        "vocabulary": status_vocabulary(),
    }


def explain_http_status(contract: Mapping[str, Any]) -> str:
    cli = _mapping(contract.get("cli"))
    http = _mapping(contract.get("http_runtime"))
    optional = _mapping(contract.get("optional_backends"))
    output = _mapping(contract.get("minimal_output"))
    discovery = _mapping(contract.get("discovery"))
    return (
        f"cli={cli.get('status')}; http={http.get('status')}; "
        f"optional={optional.get('status')}; output={output.get('status')}; "
        f"entrypoint={discovery.get('preferred_entrypoint')}"
    )


def _http_state(listener: Mapping[str, Any], pid: Mapping[str, Any]) -> tuple[str, list[str]]:
    if bool(listener.get("listening")):
        return "healthy", ["listener_responding"]
    pid_exists = bool(pid.get("file_exists"))
    process_alive = bool(pid.get("process_alive"))
    command_matches = bool(pid.get("command_matches"))
    if pid_exists and (not process_alive or not command_matches):
        reasons = ["pid_file_present"]
        reasons.append("pid_process_missing" if not process_alive else "pid_command_mismatch")
        return "stale-pid", reasons
    if bool(listener.get("checked")):
        return "stopped-by-design", ["listener_absent", "auto_start_disabled"]
    return "unknown", ["listener_not_checked"]


def _cli_state(health: Mapping[str, Any]) -> str:
    if bool(health.get("minimal_ok")):
        return "ready" if str(health.get("status")) in {"core_ok", "degraded_optional"} else "degraded"
    return "blocked"


def _configured_port(url: str, value: Any) -> int | None:
    try:
        if value is not None:
            return int(value)
        return urlparse(url).port
    except (TypeError, ValueError):
        return None


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}
