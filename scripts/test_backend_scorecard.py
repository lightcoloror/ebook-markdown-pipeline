from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]


def main() -> int:
    module = load_scorecard_module()
    checks = [
        {"name": "MarkItDown", "status": "ok", "detail": "importable"},
        {"name": "CnOCR", "status": "missing", "detail": "not installed"},
        {"name": "Tabula", "status": "ok", "detail": "tabula-py available"},
    ]
    capabilities = [
        {"name": "markitdown_baseline", "status": "ok", "detail": "baseline", "action": "compare"},
        {"name": "cnocr_chinese_ocr", "status": "missing", "detail": "missing", "action": "optional"},
        {"name": "pdf_table_extraction", "status": "ok", "detail": "Tabula", "action": "diagnose"},
    ]
    payload = module.build_scorecard(checks, capabilities, output=PROJECT_DIR / ".tmp" / "scorecard-test")
    if payload.get("schema_version") != module.SCHEMA_VERSION:
        raise AssertionError(f"Unexpected scorecard schema: {payload}")
    summary = payload.get("summary") or {}
    if "MarkItDown" not in summary.get("ready", []) or "CnOCR" not in summary.get("missing_optional", []):
        raise AssertionError(f"Expected ready and missing optional summaries: {payload}")
    markitdown = next(item for item in payload["backends"] if item["name"] == "MarkItDown")
    if markitdown["status"] != "ok" or markitdown["recommendation_score"] <= 0:
        raise AssertionError(f"Expected MarkItDown score: {markitdown}")
    cnocr = next(item for item in payload["backends"] if item["name"] == "CnOCR")
    if cnocr["status"] != "missing" or "optional missing is OK" not in cnocr["recommendation"]:
        raise AssertionError(f"Expected missing CnOCR to be non-fatal: {cnocr}")
    with tempfile.TemporaryDirectory(prefix="backend-scorecard-") as tmp:
        output = Path(tmp)
        module.write_scorecard(output, payload)
        if not (output / "backend-scorecard.json").exists() or not (output / "backend-scorecard.md").exists():
            raise AssertionError("Expected backend scorecard JSON/Markdown artifacts.")
        persisted = json.loads((output / "backend-scorecard.json").read_text(encoding="utf-8"))
        if persisted["schema_version"] != module.SCHEMA_VERSION:
            raise AssertionError(f"Unexpected persisted payload: {persisted}")
    print("Backend scorecard smoke test passed.")
    return 0


def load_scorecard_module():
    path = PROJECT_DIR / "scripts" / "generate_backend_scorecard.py"
    spec = importlib.util.spec_from_file_location("generate_backend_scorecard", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    raise SystemExit(main())
