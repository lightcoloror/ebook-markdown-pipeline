from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
WORKSPACE_DIR = PROJECT_DIR.parent
sys.path.insert(0, str(PROJECT_DIR.parent))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

from ebook_markdown_pipeline.shared_vkp_gateway import (  # noqa: E402
    shared_vkp_gateway_fast_health,
)
from external_wrapper_utils import run_command  # noqa: E402


SCHEMA_VERSION = "ebook-online-mode-completion-audit-v1"
ONLINE_STAGES = {"ocr_layout", "vlm_layout", "text_structure"}
SOURCE_FIELDS = {
    "intent",
    "decision",
    "reason",
    "evidence",
    "scope",
    "commit",
    "local_review_subdir",
    "reviewed_modules",
    "local_validation",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit the online-only implementation without calling a model supplier or reading API keys."
        )
    )
    parser.add_argument("--vkp-root", type=Path)
    parser.add_argument("--supplier-smoke-report", type=Path)
    parser.add_argument("--require-live-supplier-smoke", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_completion_audit(
        PROJECT_DIR,
        workspace_dir=WORKSPACE_DIR,
        vkp_root=args.vkp_root,
        supplier_smoke_report=args.supplier_smoke_report,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(payload))
    if payload["status"] == "degraded":
        return 2
    if args.require_live_supplier_smoke and payload["status"] != "complete":
        return 3
    return 0


def build_completion_audit(
    project_dir: Path,
    *,
    workspace_dir: Path,
    vkp_root: str | Path | None = None,
    supplier_smoke_report: str | Path | None = None,
    health_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    health = health_payload
    if health is None:
        try:
            health = shared_vkp_gateway_fast_health(vkp_root)
        except Exception as exc:  # noqa: BLE001
            health = {
                "status": "degraded",
                "routes": {},
                "shared_provider_catalog": {},
                "audit_error_type": type(exc).__name__,
            }

    checks.extend(audit_shared_gateway(health))
    checks.append(audit_public_interfaces(project_dir))
    checks.append(audit_source_reuse(project_dir, workspace_dir))
    checks.append(audit_decision_log(project_dir))
    live_check = audit_supplier_smoke(supplier_smoke_report)
    checks.append(live_check)

    baseline_checks = [item for item in checks if item["id"] != "live_supplier_smoke"]
    baseline_passed = all(bool(item.get("passed")) for item in baseline_checks)
    live_passed = bool(live_check.get("passed"))
    status = "complete" if baseline_passed and live_passed else (
        "ready_for_live_smoke" if baseline_passed else "degraded"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "network_requests_made": False,
        "api_keys_read_or_exposed": False,
        "baseline_passed": baseline_passed,
        "live_supplier_smoke_passed": live_passed,
        "checks": checks,
        "recommended_followup": (
            {
                "tool": "run_online_supplier_smoke",
                "arguments": {
                    "execute": True,
                    "confirm_data_export": True,
                    "max_estimated_cost_usd": "REQUIRED_POSITIVE_NUMBER",
                    "start_shared_gateway": True,
                },
                "safe_default": False,
                "destructive": False,
                "why": "This is the only remaining production proof and it sends a generated synthetic image to remote providers.",
            }
            if status == "ready_for_live_smoke"
            else None
        ),
    }


def audit_shared_gateway(health: dict[str, Any]) -> list[dict[str, Any]]:
    routes = health.get("routes") if isinstance(health.get("routes"), dict) else {}
    configured = {
        stage
        for stage in ONLINE_STAGES
        if isinstance(routes.get(stage), dict) and routes[stage].get("status") == "configured"
    }
    catalog = (
        health.get("shared_provider_catalog")
        if isinstance(health.get("shared_provider_catalog"), dict)
        else {}
    )
    providers = catalog.get("providers") if isinstance(catalog.get("providers"), list) else []
    visible_stages = {
        str(stage)
        for provider in providers
        if isinstance(provider, dict)
        for stage in provider.get("ebook_stages") or []
    }
    selected_stages = {
        str(stage)
        for provider in providers
        if isinstance(provider, dict)
        for stage in provider.get("selected_stages") or []
    }
    return [
        {
            "id": "online_three_stage_routes",
            "passed": configured == ONLINE_STAGES,
            "evidence": {
                "configured_stages": sorted(configured),
                "required_stages": sorted(ONLINE_STAGES),
                "gateway_runtime_status": health.get("status"),
            },
            "scope": "Remote OCR, VLM layout, and text-structure route readiness; no supplier request.",
        },
        {
            "id": "single_vkp_credential_source",
            "passed": (
                health.get("credential_store") == "vkp_windows_dpapi"
                and catalog.get("source") == "vkp_model_api_settings"
                and catalog.get("api_keys_exposed") is False
                and catalog.get("api_keys_copied") is False
            ),
            "evidence": {
                "credential_store": health.get("credential_store"),
                "catalog_source": catalog.get("source"),
                "api_keys_exposed": catalog.get("api_keys_exposed"),
                "api_keys_copied": catalog.get("api_keys_copied"),
            },
            "scope": "VKP remains the only provider settings and DPAPI credential source.",
        },
        {
            "id": "compatible_provider_catalog",
            "passed": (
                int(catalog.get("provider_count") or 0) > 0
                and int(catalog.get("ebook_eligible_profile_count") or 0) > 0
                and ONLINE_STAGES.issubset(visible_stages)
                and ONLINE_STAGES.issubset(selected_stages)
            ),
            "evidence": {
                "provider_count": int(catalog.get("provider_count") or 0),
                "enabled_remote_profile_count": int(catalog.get("enabled_remote_profile_count") or 0),
                "ebook_eligible_profile_count": int(catalog.get("ebook_eligible_profile_count") or 0),
                "visible_stages": sorted(visible_stages),
                "selected_stages": sorted(selected_stages),
                "selection_policy": catalog.get("selection_policy"),
            },
            "scope": "Every VKP remote profile with OCR, vision, or text capability is discoverable without copying keys.",
        },
    ]


def audit_public_interfaces(project_dir: Path) -> dict[str, Any]:
    expectations = {
        "online_document_pipeline.py": ("def run_online_document_pipeline",),
        "scripts/run_online_document_pipeline.py": ("run_online_document_pipeline",),
        "book_converter_ui.py": ("online_only",),
        "ebook_converter_http.py": ("start_online_conversion",),
        "ebook_converter_mcp.py": ("start_online_conversion",),
    }
    missing: list[str] = []
    for relative, markers in expectations.items():
        path = project_dir / relative
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            missing.append(relative)
            continue
        if not all(marker in text for marker in markers):
            missing.append(relative)
    return {
        "id": "public_interfaces",
        "passed": not missing,
        "evidence": {
            "interfaces": sorted(expectations),
            "missing_or_incomplete": missing,
        },
        "scope": "CLI, UI, HTTP, and MCP/Agent entrypoints retain one online-only orchestration contract.",
    }


def audit_source_reuse(project_dir: Path, workspace_dir: Path) -> dict[str, Any]:
    manifest_path = project_dir / "docs" / "ONLINE_ONLY_SOURCE_REUSE_MANIFEST.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        manifest = {}
    rows = manifest.get("sources") if isinstance(manifest.get("sources"), list) else []
    evidence: list[dict[str, Any]] = []
    all_valid = len(rows) >= 5
    for row in rows:
        if not isinstance(row, dict):
            all_valid = False
            continue
        name = str(row.get("name") or "unknown")
        missing_fields = sorted(field for field in SOURCE_FIELDS if not row.get(field))
        relative = str(row.get("local_review_subdir") or "")
        repo = (workspace_dir / relative).resolve() if relative else workspace_dir / "__missing__"
        expected_commit = str(row.get("commit") or "")
        head = run_command(["git", "-C", str(repo), "rev-parse", "HEAD"], None, 20)
        status = run_command(["git", "-C", str(repo), "status", "--porcelain"], None, 20)
        actual_commit = head.stdout.strip() if head.returncode == 0 else ""
        dirty_count = len([line for line in status.stdout.splitlines() if line.strip()]) if status.returncode == 0 else -1
        valid = (
            not missing_fields
            and repo.is_dir()
            and head.returncode == 0
            and status.returncode == 0
            and actual_commit == expected_commit
            and dirty_count == 0
        )
        all_valid = all_valid and valid
        evidence.append(
            {
                "name": name,
                "expected_commit": expected_commit,
                "actual_commit": actual_commit,
                "clean": dirty_count == 0,
                "missing_manifest_fields": missing_fields,
                "passed": valid,
            }
        )
    global_ledger = manifest.get("global_source_ledger") if isinstance(manifest.get("global_source_ledger"), dict) else {}
    return {
        "id": "pinned_source_reuse",
        "passed": all_valid,
        "evidence": {
            "source_count": len(rows),
            "sources": evidence,
            "global_ledger_registration_status": global_ledger.get("registration_status"),
            "global_ledger_fail_closed": global_ledger.get("decision"),
        },
        "scope": "Pinned local source worktrees and five-field reuse decisions; no source download or supplier call.",
    }


def audit_decision_log(project_dir: Path) -> dict[str, Any]:
    path = project_dir / "docs" / "ONLINE_ONLY_MODE_ARCHITECTURE_AND_SOURCE_REUSE_2026-08-01.md"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    return audit_decision_rows(lines)


def audit_decision_rows(lines: list[str]) -> dict[str, Any]:
    rows: list[tuple[str, int]] = []
    malformed: list[str] = []
    for line in lines:
        if not line.startswith("| OAPI-"):
            continue
        normalized = line.replace(r"\|", "&#124;")
        columns = [column.strip() for column in normalized.strip().strip("|").split("|")]
        record_id = columns[0] if columns else "unknown"
        rows.append((record_id, len(columns)))
        if len(columns) != 6 or any(not value for value in columns):
            malformed.append(record_id)
    ids = [item[0] for item in rows]
    duplicates = sorted({record_id for record_id in ids if ids.count(record_id) > 1})
    return {
        "id": "five_field_decision_log",
        "passed": len(rows) >= 1 and not malformed and not duplicates,
        "evidence": {
            "record_count": len(rows),
            "latest_record": ids[-1] if ids else None,
            "malformed_records": malformed,
            "duplicate_records": duplicates,
            "required_columns": ["id", "intent", "decision", "reason", "evidence", "scope"],
        },
        "scope": "Every OAPI change records intent, decision, reason, evidence, and effective scope.",
    }


def audit_supplier_smoke(report_path: str | Path | None) -> dict[str, Any]:
    if not report_path:
        return {
            "id": "live_supplier_smoke",
            "passed": False,
            "status": "pending_user_authorization",
            "evidence": {
                "network_requests_made_by_audit": False,
                "required_fixture": "generated non-sensitive image",
                "required_user_controls": ["confirm_data_export", "positive_cost_ceiling"],
            },
            "scope": "Production proof only; absent evidence does not weaken no-network contract tests.",
        }
    path = Path(report_path).expanduser().resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    return audit_supplier_smoke_payload(payload)


def audit_supplier_smoke_payload(payload: dict[str, Any]) -> dict[str, Any]:
    assertions = payload.get("stage_assertions") if isinstance(payload.get("stage_assertions"), list) else []
    names = {str(item.get("name") or "") for item in assertions if isinstance(item, dict)}
    required = {
        "pipeline_completed",
        "ocr_layout_completed",
        "vlm_layout_completed",
        "text_structure_completed",
    }
    passed = (
        payload.get("schema_version") == "ebook-online-supplier-smoke-v1"
        and payload.get("status") == "passed"
        and payload.get("provider_mode") == "vkp_shared"
        and payload.get("execution_requested") is True
        and (payload.get("safety") or {}).get("confirmed_data_export") is True
        and float((payload.get("safety") or {}).get("max_estimated_cost_usd") or 0) > 0
        and required.issubset(names)
        and all(bool(item.get("passed")) for item in assertions if isinstance(item, dict))
    )
    return {
        "id": "live_supplier_smoke",
        "passed": passed,
        "status": "passed" if passed else "invalid_or_failed_evidence",
        "evidence": {
            "provider_mode": payload.get("provider_mode"),
            "execution_requested": payload.get("execution_requested"),
            "assertion_names": sorted(names),
            "all_assertions_passed": bool(assertions) and all(
                bool(item.get("passed")) for item in assertions if isinstance(item, dict)
            ),
        },
        "scope": "Strict production evidence for OCR, VLM, and structure requests through the shared VKP gateway.",
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Online Mode Completion Audit",
        "",
        f"- Status: `{payload.get('status')}`",
        f"- Network requests made by audit: `{str(bool(payload.get('network_requests_made'))).lower()}`",
        f"- API keys read or exposed: `{str(bool(payload.get('api_keys_read_or_exposed'))).lower()}`",
        "",
        "| Check | Passed | Scope |",
        "| --- | --- | --- |",
    ]
    for item in payload.get("checks") or []:
        scope = str(item.get("scope") or "").replace("|", "\\|")
        lines.append(f"| {item.get('id')} | {str(bool(item.get('passed'))).lower()} | {scope} |")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
