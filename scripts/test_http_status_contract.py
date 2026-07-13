from __future__ import annotations
import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))
from ebook_markdown_pipeline.http_status_contract import build_http_status_contract, explain_http_status, status_vocabulary

FIXTURE = PROJECT_DIR / "benchmarks" / "fixtures" / "ebook-http-status-contract.json"

def main() -> int:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    original = json.loads(FIXTURE.read_text(encoding="utf-8"))
    results = {item["id"]: build_http_status_contract(item["observation"]) for item in payload["cases"]}
    if payload != original:
        raise AssertionError("Status evaluation mutated fixtures")
    assert results["legacy-8765-stopped"]["http_runtime"]["status"] == "stopped-by-design"
    assert results["legacy-8765-stopped"]["legacy_8765"]["authoritative_for_current_runtime"] is False
    assert results["legacy-8765-stopped"]["cli"]["callable"] is True
    assert results["healthy-mock"]["http_runtime"]["status"] == "healthy"
    assert results["healthy-mock"]["discovery"]["preferred_entrypoint"] == "http"
    assert results["stale-pid"]["http_runtime"]["status"] == "stale-pid"
    assert "pid_process_missing" in results["stale-pid"]["http_runtime"]["reason_codes"]
    stopped = results["cli-ready-http-stopped"]
    assert stopped["relations"]["http_stopped_cli_callable"] is True
    assert stopped["discovery"]["preferred_entrypoint"] == "cli"
    missing = results["backend-missing-degraded-output"]
    assert missing["optional_backends"]["status"] == "degraded"
    assert missing["optional_backends"]["full_quality_support"] is False
    assert missing["relations"]["optional_missing_cli_callable"] is True
    assert missing["relations"]["artifact_exists_quality_failed"] is True
    assert missing["minimal_output"]["status"] == "degraded"
    assert set(status_vocabulary()["dimensions"]) == {"cli", "http_runtime", "optional_backends", "minimal_output"}
    assert "cli=ready" in explain_http_status(stopped)
    print("HTTP status contract test passed.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
