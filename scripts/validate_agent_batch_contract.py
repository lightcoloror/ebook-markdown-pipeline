from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
RUNNER_DIR = PROJECT_DIR / "examples" / "agent-batch"
sys.path.insert(0, str(RUNNER_DIR))

from agent_batch_http import (  # noqa: E402
    AGENT_BATCH_CONTRACT_CAPABILITIES,
    AGENT_BATCH_CONTRACT_VERSION,
    AGENT_BATCH_PLAN_SCHEMA_VERSION,
    AGENT_BATCH_SCHEMA_VERSION,
)


REQUIRED_RESULT_FIELDS = {
    "schema_version",
    "contract",
    "manifest",
    "created_at",
    "summary",
    "selection",
    "artifact_summary",
    "next_actions",
    "results",
}
REQUIRED_PLAN_FIELDS = {
    "schema_version",
    "contract",
    "manifest",
    "created_at",
    "summary",
    "selection",
    "validation",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate agent batch plan/results handoff contract.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--json", action="store_true", help="Print machine-readable validation output.")
    args = parser.parse_args()

    payload = json.loads(args.path.read_text(encoding="utf-8-sig"))
    result = validate_payload(payload, args.path)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        status = "ok" if result["ok"] else "failed"
        print(f"Agent batch contract validation {status}: {args.path}")
        for item in result["errors"]:
            print(f"- {item}")
    return 0 if result["ok"] else 2


def validate_payload(payload: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    schema_version = payload.get("schema_version")
    errors: list[str] = []
    if schema_version == AGENT_BATCH_SCHEMA_VERSION:
        required = REQUIRED_RESULT_FIELDS
        payload_kind = "results"
    elif schema_version == AGENT_BATCH_PLAN_SCHEMA_VERSION:
        required = REQUIRED_PLAN_FIELDS
        payload_kind = "plan"
    else:
        required = set()
        payload_kind = "unknown"
        errors.append(f"unsupported schema_version: {schema_version!r}")

    missing = sorted(field for field in required if field not in payload)
    if missing:
        errors.append(f"missing required fields: {', '.join(missing)}")

    contract = payload.get("contract") or {}
    if contract.get("schema_version") != AGENT_BATCH_CONTRACT_VERSION:
        errors.append(f"contract.schema_version must be {AGENT_BATCH_CONTRACT_VERSION}")
    if contract.get("payload_schema_version") != schema_version:
        errors.append("contract.payload_schema_version must match payload schema_version")
    capabilities = set(contract.get("capabilities") or [])
    missing_capabilities = sorted(set(AGENT_BATCH_CONTRACT_CAPABILITIES) - capabilities)
    if missing_capabilities:
        errors.append(f"missing capabilities: {', '.join(missing_capabilities)}")
    declared_required = set(contract.get("required_fields") or [])
    missing_declared = sorted(required - declared_required)
    if missing_declared:
        errors.append(f"contract.required_fields missing: {', '.join(missing_declared)}")

    return {
        "ok": not errors,
        "path": str(path) if path else "",
        "schema_version": schema_version,
        "payload_kind": payload_kind,
        "contract_schema_version": contract.get("schema_version"),
        "errors": errors,
    }


if __name__ == "__main__":
    raise SystemExit(main())
