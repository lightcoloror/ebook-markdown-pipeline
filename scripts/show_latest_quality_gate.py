from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
LATEST_DIR = PROJECT_DIR / "benchmarks" / "runs" / "latest"
QUALITY_GATE_DIR = PROJECT_DIR / "benchmarks" / "runs" / "quality-gate"


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the latest local quality-gate handoff summary.")
    parser.add_argument("--profile", choices=["release"], default="release")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON instead of Markdown.")
    args = parser.parse_args()

    payload = load_latest_release()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(payload), end="")
    return 0 if payload.get("found") else 4


def load_latest_release() -> dict[str, Any]:
    preferred = LATEST_DIR / "release-index.json"
    if preferred.exists():
        return {"found": True, "source": str(preferred), "payload": read_json(preferred)}

    candidates = sorted(QUALITY_GATE_DIR.glob("*/release-summary.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if candidates:
        return {"found": True, "source": str(candidates[0]), "payload": read_json(candidates[0])}

    return {
        "found": False,
        "source": "",
        "message": "No release quality-gate summary found. Run: python scripts\\run_quality_gate.py --profile release",
    }


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return payload if isinstance(payload, dict) else {"value": payload}


def render_markdown(result: dict[str, Any]) -> str:
    if not result.get("found"):
        return f"# Latest Quality Gate\n\n- Status: missing\n- Message: {result.get('message', '')}\n"
    payload = result.get("payload") or {}
    summary = payload.get("summary") or {}
    lines = [
        "# Latest Quality Gate",
        "",
        f"- Source: `{result.get('source', '')}`",
        f"- Status: {summary.get('status', 'unknown')}",
        f"- Output: `{payload.get('output', '')}`",
        f"- Failed steps: {', '.join(summary.get('failed_steps') or []) or 'none'}",
        "",
        "| Step | Status | Exit | Report |",
        "| --- | --- | ---: | --- |",
    ]
    for step in payload.get("steps") or []:
        if not isinstance(step, dict):
            continue
        lines.append(f"| {step.get('name', '')} | {step.get('status', '')} | {step.get('exit_code', '')} | `{step.get('report', '')}` |")
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
