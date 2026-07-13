from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.service_readiness import service_readiness_payload  # noqa: E402


def main() -> int:
    payload = service_readiness_payload(check_listener=False)
    if payload.get("schema_version") != "ebook-service-readiness-v1":
        raise AssertionError(f"Unexpected service readiness schema: {payload}")
    if payload.get("status") != "stopped-by-design":
        raise AssertionError(f"HTTP should be stopped-by-design when listener check is skipped: {payload}")
    if payload.get("http", {}).get("configured_url") != "http://127.0.0.1:9241":
        raise AssertionError(f"Service readiness should read config/http.env: {payload}")
    if payload.get("http", {}).get("auto_start") is not False:
        raise AssertionError(f"Service readiness must never auto-start HTTP: {payload}")
    if "mcp" not in payload.get("preferred_entrypoints", []):
        raise AssertionError(f"MCP should remain a preferred entrypoint: {payload}")
    if "hard-coding 8765" not in payload.get("fallback", {}).get("do_not_assume_port", ""):
        raise AssertionError(f"Fallback guidance should reject stale fixed ports: {payload}")

    required = service_readiness_payload(require_http=True, check_listener=False)
    if required.get("status") != "needs_manual_start":
        raise AssertionError(f"Required HTTP should ask for manual start when not listening: {required}")

    completed = subprocess.run(
        [sys.executable, "-B", "scripts/check_service_readiness.py", "--json"],
        cwd=PROJECT_DIR,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=True,
    )
    cli_payload = json.loads(completed.stdout)
    if cli_payload.get("schema_version") != "ebook-service-readiness-v1":
        raise AssertionError(f"CLI readiness output has wrong schema: {cli_payload}")
    if cli_payload.get("status") not in {"ready", "stopped-by-design"}:
        raise AssertionError(f"CLI readiness should be ready or stopped-by-design for optional HTTP: {cli_payload}")

    print("Service readiness contract test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

