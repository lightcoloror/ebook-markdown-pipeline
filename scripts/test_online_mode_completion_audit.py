from __future__ import annotations

import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

from audit_online_mode_completion import (  # noqa: E402
    audit_decision_rows,
    audit_shared_gateway,
    audit_supplier_smoke,
    audit_supplier_smoke_payload,
)


def main() -> int:
    assert_health_contract()
    assert_decision_contract()
    assert_supplier_smoke_contract()
    print("Online mode completion audit tests passed.")
    return 0


def assert_health_contract() -> None:
    health = {
        "status": "on_demand",
        "credential_store": "vkp_windows_dpapi",
        "routes": {
            stage: {"status": "configured"}
            for stage in ("ocr_layout", "vlm_layout", "text_structure")
        },
        "shared_provider_catalog": {
            "source": "vkp_model_api_settings",
            "provider_count": 3,
            "enabled_remote_profile_count": 4,
            "ebook_eligible_profile_count": 4,
            "api_keys_exposed": False,
            "api_keys_copied": False,
            "selection_policy": "shared",
            "providers": [
                {
                    "provider": "ocr-provider",
                    "ebook_stages": ["ocr_layout"],
                    "selected_stages": ["ocr_layout"],
                },
                {
                    "provider": "vlm-provider",
                    "ebook_stages": ["vlm_layout"],
                    "selected_stages": ["vlm_layout"],
                },
                {
                    "provider": "text-provider",
                    "ebook_stages": ["text_structure"],
                    "selected_stages": ["text_structure"],
                },
            ],
        },
    }
    checks = audit_shared_gateway(health)
    if not all(item.get("passed") for item in checks):
        raise AssertionError(checks)
    health["shared_provider_catalog"]["api_keys_copied"] = True
    failed = {item["id"]: item for item in audit_shared_gateway(health)}
    if failed["single_vkp_credential_source"]["passed"]:
        raise AssertionError("Copied-key configuration must fail the shared credential audit.")


def assert_decision_contract() -> None:
    lines = [
        "| ID | 意图 | 决策 | 理由 | 证据 | 生效范围 |",
        "|---|---|---|---|---|---|",
        "| OAPI-001 | intent | decision | reason | evidence | scope |",
    ]
    check = audit_decision_rows(lines)
    if not check["passed"]:
        raise AssertionError(check)
    if audit_decision_rows(lines + ["| OAPI-002 | broken |"])["passed"]:
        raise AssertionError("Malformed decision rows must fail the audit.")


def assert_supplier_smoke_contract() -> None:
    pending = audit_supplier_smoke(None)
    if pending["passed"] or pending["status"] != "pending_user_authorization":
        raise AssertionError(pending)
    payload = {
        "schema_version": "ebook-online-supplier-smoke-v1",
        "status": "passed",
        "provider_mode": "vkp_shared",
        "execution_requested": True,
        "safety": {
            "confirmed_data_export": True,
            "max_estimated_cost_usd": 0.1,
        },
        "stage_assertions": [
            {"name": name, "passed": True}
            for name in (
                "pipeline_completed",
                "ocr_layout_completed",
                "vlm_layout_completed",
                "text_structure_completed",
            )
        ],
    }
    if not audit_supplier_smoke_payload(payload)["passed"]:
        raise AssertionError("Valid supplier smoke evidence was rejected.")
    payload["safety"]["confirmed_data_export"] = False
    if audit_supplier_smoke_payload(payload)["passed"]:
        raise AssertionError("Unconfirmed data export must fail the supplier audit.")

if __name__ == "__main__":
    raise SystemExit(main())
