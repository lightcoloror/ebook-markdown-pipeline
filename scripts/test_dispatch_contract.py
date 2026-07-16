from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.candidate_backend_registry import candidate_backend_registry_payload  # noqa: E402
from ebook_markdown_pipeline.dispatch_contract_runtime import build_dispatch_contract  # noqa: E402


def fixture_service(status: str = "stopped-by-design") -> dict:
    return {
        "status": status,
        "http": {
            "configured_url": "http://127.0.0.1:9241",
            "config_path": str(PROJECT_DIR / "config" / "http.env"),
            "listener": {"checked": True, "listening": status == "ready", "host": "127.0.0.1", "port": 9241},
            "auto_start": False,
        },
    }


def fixture_health() -> dict:
    capabilities = [
        {"name": "structured_ebooks", "status": "ok", "detail": "ready"},
        {"name": "pdf_fast_text", "status": "ok", "detail": "ready"},
        {"name": "pdf_structure_recovery", "status": "ok", "detail": "command/cache ready"},
        {"name": "pdf_marker_layout", "status": "ok", "detail": "ready"},
        {"name": "docling_documents", "status": "missing", "detail": "tokenizers conflict"},
        {"name": "markitdown_baseline", "status": "ok", "detail": "ready"},
        {"name": "rapidocr_fallback", "status": "ok", "detail": "ready"},
        {"name": "pdf_layout_diagnostics", "status": "ok", "detail": "ready"},
    ]
    checks = [
        {"name": "PaddleOCR-json.exe", "status": "missing"},
        {"name": "Umi PaddleOCR module", "status": "missing"},
        {"name": "PaddleOCR-VL wrapper", "status": "missing"},
        {"name": "Surya wrapper", "status": "missing"},
        {"name": "pdf_table worker", "status": "planned_only"},
    ]
    return {"schema_version": "health-check-v2", "status": "degraded_optional", "minimal_ok": True, "optional_missing_is_ok": True, "capabilities": capabilities, "checks": checks}


def main() -> int:
    registry = candidate_backend_registry_payload()
    stopped = build_dispatch_contract(
        service=fixture_service(),
        health=fixture_health(),
        mineru_service={"status": "stopped", "configured_url": "http://127.0.0.1:8000"},
        candidate_registry=registry,
    )
    if stopped.get("schema_version") != "ebook-dispatch-contract-v1":
        raise AssertionError(stopped)
    if stopped.get("status") != "stopped-by-design" or stopped.get("status_code") != "stopped_by_design":
        raise AssertionError(stopped)
    if stopped["legacy_8765"]["classification"] != "stale_contract" or stopped["legacy_8765"]["authoritative"]:
        raise AssertionError(stopped["legacy_8765"])
    modules = {item["key"]: item for item in stopped["modules"]}
    expected = {"pymupdf4llm": "ready", "mineru": "needs_manual_start", "marker": "ready", "docling": "missing", "paddleocr": "missing", "surya": "missing", "gmft_table": "planned_only", "table_transformer": "planned_only"}
    if {key: modules[key]["status"] for key in expected} != expected:
        raise AssertionError(modules)
    complex_route = next(item for item in stopped["routes"] if item["id"] == "pdf_complex_layout")
    if complex_route["steps"][0]["execution_action"] != "manual_start_required_or_skip":
        raise AssertionError(complex_route)
    if stopped["consumers"]["openclaw_docker"]["status"] != "needs_manual_start" or stopped["consumers"]["telegram"]["status"] != "plan_only":
        raise AssertionError(stopped["consumers"])
    if stopped["boundaries"]["auto_download_models"] or stopped["boundaries"]["auto_start_http"]:
        raise AssertionError(stopped["boundaries"])

    required = build_dispatch_contract(service=fixture_service("needs_manual_start"), health=fixture_health(), mineru_service={"status": "ready"}, candidate_registry=registry, require_http=True)
    required_modules = {item["key"]: item for item in required["modules"]}
    if required["status"] != "needs_manual_start" or required_modules["mineru"]["status"] != "ready":
        raise AssertionError(required)

    completed = subprocess.run(
        [sys.executable, "-B", "scripts/check_dispatch_contract.py", "--skip-health", "--skip-mineru-status", "--no-listener-check"],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(f"CLI failed:\n{completed.stdout}\n{completed.stderr}")
    cli = json.loads(completed.stdout)
    if cli.get("schema_version") != "ebook-dispatch-contract-v1" or cli["legacy_8765"]["authoritative"]:
        raise AssertionError(cli)
    print("Dispatch contract test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
