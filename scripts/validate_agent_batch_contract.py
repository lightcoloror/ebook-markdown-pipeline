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
    validate_agent_batch_contract_payload,
)


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
    return validate_agent_batch_contract_payload(payload, path)


if __name__ == "__main__":
    raise SystemExit(main())
