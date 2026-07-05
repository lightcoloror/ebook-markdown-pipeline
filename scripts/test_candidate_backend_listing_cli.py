from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_DIR / "scripts" / "list_candidate_backends.py"


def main() -> int:
    json_result = run_cli("--backend", "dots_mocr")
    payload = json.loads(json_result.stdout)
    if payload.get("schema_version") != "candidate-backend-list-v1" or payload.get("remote_call_enabled"):
        raise AssertionError(f"Candidate backend CLI must stay non-executing: {payload}")
    rows = payload.get("backends") or []
    readiness = (rows[0].get("readiness_contract") if rows else {}) or {}
    if payload.get("count") != 1 or rows[0].get("display_name") != "dots.mocr":
        raise AssertionError(f"Expected dots.mocr backend row: {payload}")
    if "needs_server" not in readiness.get("missing_states", []):
        raise AssertionError(f"Expected dots.mocr manual service readiness: {payload}")

    markdown_result = run_cli("--artifact-type", "layout_candidates_json", "--format", "markdown")
    markdown = markdown_result.stdout
    if "# Candidate Backends" not in markdown or "DocLayout-YOLO" not in markdown:
        raise AssertionError(f"Expected Markdown candidate listing with DocLayout-YOLO: {markdown}")
    if "Remote calls enabled: `false`" not in markdown or "Model install enabled: `false`" not in markdown:
        raise AssertionError(f"Markdown listing should preserve non-executing policy: {markdown}")

    print("Candidate backend listing CLI test passed.")
    return 0


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", str(SCRIPT), *args],
        cwd=PROJECT_DIR,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


if __name__ == "__main__":
    raise SystemExit(main())