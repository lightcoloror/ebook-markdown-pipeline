from __future__ import annotations
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))
from ebook_markdown_pipeline.offline_quality_router import ROUTE_STATUSES, STAGE_NAMES, evaluate_offline_quality, explain_offline_route, quality_vocabulary

def report(level: str = "good", characters: int = 1200, risks: list[str] | None = None) -> dict:
    return {"status": "ok", "output": "synthetic.md", "output_exists": True, "quality": {"level": level, "characters": characters, "nonempty_lines": 20, "headings": 3}, "quality_risks": {"risk_codes": list(risks or [])}}

def main() -> int:
    vocabulary = quality_vocabulary()
    assert tuple(vocabulary["stages"]) == STAGE_NAMES
    assert tuple(vocabulary["route_statuses"]) == ROUTE_STATUSES
    minimal = evaluate_offline_quality(report(), source_kind="text_pdf", artifact_exists=True)
    assert_route(minimal, "minimal-deliverable", True, True)
    degraded_source = report("poor")
    original = report("poor")
    degraded = evaluate_offline_quality(degraded_source, source_kind="epub", artifact_exists=True)
    assert_route(degraded, "degraded", True, False)
    assert degraded_source == original
    mixed_report = report()
    mixed_report["asset_evidence"] = {"asset_count": 2, "missing_count": 0}
    mixed = evaluate_offline_quality(mixed_report, source_kind="mixed_image", artifact_exists=True)
    assert_route(mixed, "degraded", True, False)
    assert mixed["manual_review_required"] and "ocr" in mixed["manual_review_stages"]
    scan = report("poor", 0, ["empty_document"])
    scan["quality"]["nonempty_lines"] = 0
    proposed = evaluate_offline_quality(scan, source_kind="scanned_pdf", capabilities={"local_ocr": "ok"}, artifact_exists=False)
    assert_route(proposed, "fallback-proposed", False, False)
    assert proposed["fallback_proposal"]["backend"] == "rapidocr"
    assert proposed["fallback_proposal"]["automatic"] is False
    blocked = evaluate_offline_quality(scan, source_kind="scanned_pdf", capabilities={"local_ocr": "missing"}, artifact_exists=False)
    assert_route(blocked, "blocked", False, False)
    assert blocked["fallback_proposal"]["available"] is False
    table = evaluate_offline_quality(report(risks=["table_structure_risk"]), source_kind="text_pdf", artifact_exists=True)
    assert table["stages"]["table"]["status"] == "degraded"
    assert table["manual_review_required"]
    explanation = explain_offline_route(proposed)
    assert "route=fallback-proposed" in explanation and "fallback=rapidocr" in explanation
    print("Offline quality router contract test passed.")
    return 0

def assert_route(payload: dict, expected: str, artifact: bool, quality: bool) -> None:
    assert payload["schema_version"] == "offline-stage-quality-v1"
    assert payload["route"]["status"] == expected
    assert payload["artifact"]["exists"] is artifact
    assert payload["quality"]["passed"] is quality
    assert set(payload["stages"]) == set(STAGE_NAMES)

if __name__ == "__main__":
    raise SystemExit(main())
