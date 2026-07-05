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
        {"name": "MonkeyOCR worker", "status": "planned_only", "detail": "wrapper present; root not configured"},
        {"name": "DocLayout-YOLO baseline", "status": "needs_model", "detail": "wrapper present; model missing"},
        {"name": "pdf_table worker", "status": "planned_only", "detail": "wrapper present; pdftable missing"},
        {"name": "Surya wrapper", "status": "needs_model", "detail": "wrapper present; model missing"},
        {"name": "PaddleOCR-VL wrapper", "status": "needs_model", "detail": "wrapper present; model missing"},
    ]
    capabilities = [
        {"name": "markitdown_baseline", "status": "ok", "detail": "baseline", "action": "compare"},
        {"name": "cnocr_chinese_ocr", "status": "missing", "detail": "missing", "action": "optional"},
        {"name": "pdf_table_extraction", "status": "ok", "detail": "Tabula", "action": "diagnose"},
        {"name": "external_document_vlm_wrappers", "status": "degraded", "detail": "candidate wrappers present", "action": "plan first"},
        {"name": "layout_detector_baseline", "status": "degraded", "detail": "candidate wrapper present", "action": "plan first"},
        {"name": "external_table_worker", "status": "degraded", "detail": "candidate wrapper present", "action": "plan first"},
    ]
    wrapper_results = [
        {
            "backend": "monkeyocr",
            "mode": "fake",
            "status": "ok",
            "path": str(PROJECT_DIR / ".tmp" / "monkey" / "external-wrapper-result.json"),
            "artifact_count": 2,
            "artifact_types": ["layout_review_pdf", "markdown"],
            "metrics": {"page_count": 1, "markdown_chars": 240, "duration_seconds": 1.25, "model_cache_bytes": 1024, "fallback_path": "fast_pdf"},
            "warning_count": 1,
            "quality_signals": {"page_count": 1, "markdown_char_count": 240, "duration_seconds": 1.25, "model_cache_bytes": 1024, "warning_count": 1, "has_fallback_path": True},
        }
    ]
    candidate_artifacts = [
        {
            "backend": "surya",
            "mode": "layout",
            "status": "review",
            "path": str(PROJECT_DIR / ".tmp" / "surya" / "layout-candidates.json"),
            "artifact_type": "layout_candidates_json",
            "schema_version": "layout-candidates-v1",
            "page_count": 1,
            "block_count": 2,
            "table_count": None,
            "bbox_count": 2,
            "reading_order_count": 1,
            "markdown_char_count": 14,
            "quality_signals": {"page_count": 1, "block_count": 2, "bbox_count": 2, "reading_order_count": 1, "markdown_char_count": 14, "has_layout_evidence": True},
            "formula_count": None,
            "artifact_count": 1,
            "warning_count": 0,
        },
        {
            "backend": "paddleocr_vl",
            "mode": "doc_parser",
            "status": "review",
            "path": str(PROJECT_DIR / ".tmp" / "paddle" / "document-vlm-result.json"),
            "artifact_type": "document_vlm_result_json",
            "schema_version": "document-vlm-result-v1",
            "page_count": 1,
            "block_count": 3,
            "table_count": 1,
            "formula_count": 1,
            "bbox_count": 1,
            "reading_order_count": 1,
            "markdown_char_count": 90,
            "quality_signals": {"page_count": 1, "block_count": 3, "table_count": 1, "formula_count": 1, "bbox_count": 1, "reading_order_count": 1, "markdown_char_count": 90, "formula_latex_count": 1, "formula_bbox_count": 1, "formula_source_ref_count": 1, "formula_confidence_count": 1, "formula_evidence_completeness": 4, "has_table_evidence": True, "has_formula_evidence": True, "has_document_vlm_evidence": True, "needs_formula_retention_review": True},
            "artifact_count": 1,
            "warning_count": 0,
        },
    ]
    table_review_matrix_evidence = [
        {
            "path": str(PROJECT_DIR / ".tmp" / "bundle" / "layout-table-review-bundle.json"),
            "backend": "pdf_table",
            "mode": "table_review_matrix",
            "status": "review",
            "artifact_type": "table_review_matrix",
            "schema_version": "table-review-matrix-v1",
            "page_count": 1,
            "page_locator": "page:1",
            "table_count": 2,
            "artifact_count": 4,
            "warning_count": 1,
            "warnings_preview": ["check_card_layout_false_positive"],
            "quality_signals": {
                "evidence_count": 1,
                "candidate_artifact_count": 1,
                "table_review_matrix_count": 1,
                "page_count": 1,
                "table_count": 2,
                "table_backend_count": 1,
                "table_artifact_ref_count": 4,
                "table_markdown_excerpt_count": 2,
                "table_evidence_completeness": 4,
                "table_evidence_completeness_score": 1.0,
                "table_missing_evidence_count": 0,
                "table_conflict_count": 1,
                "warning_count": 1,
                "has_table_evidence": True,
                "has_table_html": True,
                "has_table_markdown": True,
                "has_table_cells_json": True,
                "has_table_overlay": True,
                "needs_card_layout_false_positive_review": True,
            },
        }
    ]
    payload = module.build_scorecard(checks, capabilities, output=PROJECT_DIR / ".tmp" / "scorecard-test", wrapper_results=wrapper_results, candidate_artifacts=[*candidate_artifacts, *table_review_matrix_evidence])
    if payload.get("schema_version") != module.SCHEMA_VERSION:
        raise AssertionError(f"Unexpected scorecard schema: {payload}")
    summary = payload.get("summary") or {}
    if "MarkItDown" not in summary.get("ready", []) or "CnOCR" not in summary.get("missing_optional", []):
        raise AssertionError(f"Expected ready and missing optional summaries: {payload}")
    if not summary.get("promotion_gate_counts"):
        raise AssertionError(f"Expected promotion gate summary counts: {payload}")
    markitdown = next(item for item in payload["backends"] if item["name"] == "MarkItDown")
    if markitdown["status"] != "ok" or markitdown["recommendation_score"] <= 0:
        raise AssertionError(f"Expected MarkItDown score: {markitdown}")
    if (markitdown.get("promotion_gate") or {}).get("decision") != "do_not_promote":
        raise AssertionError(f"Expected MarkItDown to stay unpromoted without evidence: {markitdown}")
    cnocr = next(item for item in payload["backends"] if item["name"] == "CnOCR")
    if cnocr["status"] != "missing" or "optional missing is OK" not in cnocr["recommendation"]:
        raise AssertionError(f"Expected missing CnOCR to be non-fatal: {cnocr}")
    monkey = next(item for item in payload["backends"] if item["name"] == "MonkeyOCR")
    if monkey["status"] != "degraded" or "candidate" not in monkey["default_policy"]:
        raise AssertionError(f"Expected MonkeyOCR candidate-only scorecard row: {monkey}")
    if not monkey.get("external_results") or monkey["external_results"][0].get("artifact_count") != 2:
        raise AssertionError(f"Expected MonkeyOCR external result evidence: {monkey}")
    monkey_signals = monkey.get("quality_signals") or {}
    if monkey_signals.get("markdown_char_count") != 240 or monkey_signals.get("duration_seconds") != 1.25 or monkey_signals.get("has_fallback_path") is not True:
        raise AssertionError(f"Expected MonkeyOCR quality signals: {monkey}")
    if (monkey.get("promotion_gate") or {}).get("decision") != "review_only":
        raise AssertionError(f"Expected MonkeyOCR to remain review-only from one wrapper result: {monkey}")
    layout = next(item for item in payload["backends"] if item["name"] == "DocLayout-YOLO")
    if layout["status"] != "degraded" or not layout["health"]:
        raise AssertionError(f"Expected DocLayout-YOLO candidate health: {layout}")
    surya = next(item for item in payload["backends"] if item["name"] == "Surya")
    if not surya.get("candidate_artifacts") or surya["candidate_artifacts"][0].get("block_count") != 2:
        raise AssertionError(f"Expected Surya candidate artifact evidence: {surya}")
    surya_signals = surya.get("quality_signals") or {}
    if surya_signals.get("bbox_count") != 2 or surya_signals.get("reading_order_count") != 1 or surya_signals.get("has_layout_evidence") is not True:
        raise AssertionError(f"Expected Surya layout quality signals: {surya}")
    if (surya.get("promotion_gate") or {}).get("decision") != "plan_or_fix_environment_first":
        raise AssertionError(f"Expected Surya model gate before promotion: {surya}")
    paddle = next(item for item in payload["backends"] if item["name"] == "PaddleOCR-VL")
    if not paddle.get("candidate_artifacts") or paddle["candidate_artifacts"][0].get("table_count") != 1:
        raise AssertionError(f"Expected PaddleOCR-VL document sidecar evidence: {paddle}")
    paddle_signals = paddle.get("quality_signals") or {}
    if paddle_signals.get("table_count") != 1 or paddle_signals.get("formula_count") != 1 or paddle_signals.get("has_document_vlm_evidence") is not True:
        raise AssertionError(f"Expected PaddleOCR-VL table/formula/VLM quality signals: {paddle}")
    if paddle_signals.get("formula_evidence_completeness") != 4 or paddle_signals.get("needs_formula_retention_review") is not True:
        raise AssertionError(f"Expected PaddleOCR-VL formula evidence completeness: {paddle}")
    if (paddle.get("promotion_gate") or {}).get("decision") != "plan_or_fix_environment_first":
        raise AssertionError(f"Expected PaddleOCR-VL model gate before promotion: {paddle}")
    table = next(item for item in payload["backends"] if item["name"] == "pdf_table")
    if table["status"] != "degraded" or "table pages only" not in table["default_policy"]:
        raise AssertionError(f"Expected pdf_table candidate-only scorecard row: {table}")
    table_signals = table.get("quality_signals") or {}
    if table_signals.get("table_review_matrix_count") != 1 or table_signals.get("table_evidence_completeness") != 4:
        raise AssertionError(f"Expected table matrix quality signals: {table}")
    if table_signals.get("table_evidence_completeness_score") != 1.0 or table_signals.get("table_conflict_count") != 1:
        raise AssertionError(f"Expected table matrix score/conflict signals: {table}")
    if table_signals.get("has_table_overlay") is not True or table_signals.get("needs_card_layout_false_positive_review") is not True:
        raise AssertionError(f"Expected table overlay and false-positive review signals: {table}")
    with tempfile.TemporaryDirectory(prefix="backend-scorecard-") as tmp:
        output = Path(tmp)
        module.write_scorecard(output, payload)
        if not (output / "backend-scorecard.json").exists() or not (output / "backend-scorecard.md").exists():
            raise AssertionError("Expected backend scorecard JSON/Markdown artifacts.")
        persisted = json.loads((output / "backend-scorecard.json").read_text(encoding="utf-8"))
        if persisted["schema_version"] != module.SCHEMA_VERSION:
            raise AssertionError(f"Unexpected persisted payload: {persisted}")
        markdown = (output / "backend-scorecard.md").read_text(encoding="utf-8")
        if "External Wrapper Evidence" not in markdown or "MonkeyOCR" not in markdown:
            raise AssertionError(f"Expected external wrapper evidence in Markdown: {markdown}")
        if "Candidate Artifact Evidence" not in markdown or "PaddleOCR-VL" not in markdown or "layout_candidates_json" not in markdown or "table_review_matrix" not in markdown:
            raise AssertionError(f"Expected candidate artifact evidence in Markdown: {markdown}")
        if "Evidence" not in markdown or "Warnings" not in markdown or "reading_order_count=1" not in markdown or "formula_evidence_completeness=4" not in markdown or "table_evidence_completeness=4" not in markdown or "table_evidence_completeness_score=1" not in markdown or "table_conflict_count=1" not in markdown:
            raise AssertionError(f"Expected quality signal columns and summary in Markdown: {markdown}")
        if "Promotion Gate" not in markdown or "plan_or_fix_environment_first" not in markdown:
            raise AssertionError(f"Expected promotion gate section in Markdown: {markdown}")
        result_root = output / "external-runs" / "monkey"
        result_root.mkdir(parents=True, exist_ok=True)
        result_path = result_root / "external-wrapper-result.json"
        result_path.write_text(
            json.dumps(
                {
                    "schema_version": "external-wrapper-result-v1",
                    "backend": "monkeyocr",
                    "mode": "fake",
                    "status": "ok",
                    "artifacts": [{"type": "markdown", "path": "sample.md"}],
                    "metrics": {"page_count": 1},
                    "warnings": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        sidecar_dir = output / "candidate-runs" / "surya"
        sidecar_dir.mkdir(parents=True, exist_ok=True)
        sidecar_path = sidecar_dir / "layout-candidates.json"
        sidecar_path.write_text(
            json.dumps(
                {
                    "schema_version": "layout-candidates-v1",
                    "backend": "surya",
                    "status": "review",
                    "mode": "layout",
                    "pages": [{"page": 1, "blocks": [{"label": "title", "bbox": [0, 0, 100, 20], "reading_order": 1, "text": "Title"}, {"label": "text", "bbox": [0, 30, 100, 60], "text": "Body"}]}],
                    "artifacts": [],
                    "warnings": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        collected = module.collect_external_wrapper_results([], [output])
        if len(collected) != 1 or collected[0].get("backend") != "monkeyocr":
            raise AssertionError(f"Expected collected external wrapper result: {collected}")
        review_bundle_path = output / "layout-table-review-bundle.json"
        review_bundle_path.write_text(
            json.dumps(
                {
                    "schema_version": "layout-table-review-bundle-v1",
                    "table_review_matrix": [
                        {
                            "schema_version": "table-review-matrix-v1",
                            "locator": "page:1",
                            "backend_count": 1,
                            "comparison_summary": {
                                "schema_version": "table-review-comparison-summary-v1",
                                "agrees_on_table_count": True,
                                "conflict_tags": ["single_backend_only", "card_layout_review_required"],
                            },
                            "rows": [
                                {
                                    "schema_version": "table-review-backend-row-v1",
                                    "backend": "pdf_table",
                                    "table_count": 2,
                                    "has_html": True,
                                    "has_markdown": True,
                                    "has_cells_json": True,
                                    "has_overlay": True,
                                    "markdown_excerpt_count": 2,
                                    "evidence_completeness_score": 1.0,
                                    "missing_evidence": [],
                                    "artifact_ref_count": 4,
                                    "artifact_refs": [],
                                    "warnings": ["check_card_layout_false_positive"],
                                }
                            ],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        collected_candidates = module.collect_candidate_artifacts([], [output])
        if len(collected_candidates) != 1 or collected_candidates[0].get("backend") != "surya" or collected_candidates[0].get("block_count") != 2:
            raise AssertionError(f"Expected collected candidate artifact: {collected_candidates}")
        collected_signals = collected_candidates[0].get("quality_signals") or {}
        if collected_signals.get("bbox_count") != 2 or collected_signals.get("reading_order_count") != 1:
            raise AssertionError(f"Expected collected candidate quality signals: {collected_candidates}")
        if collected_signals.get("layout_label_count") != 2 or collected_signals.get("layout_bbox_count") != 2:
            raise AssertionError(f"Expected collected layout evidence signals: {collected_candidates}")
        formula_path = sidecar_dir / "formula-candidates.json"
        formula_path.write_text(
            json.dumps(
                {
                    "schema_version": "formula-candidates-v1",
                    "backend": "pix2text",
                    "status": "review",
                    "mode": "text_formula",
                    "pages": [
                        {
                            "page": 1,
                            "source": "formula-page.png",
                            "formulas": [
                                {
                                    "latex": "x^2+y^2=z^2",
                                    "markdown": "$x^2+y^2=z^2$",
                                    "bbox": [1, 2, 9, 5],
                                    "confidence": 0.91,
                                    "source": "formula-page.png",
                                }
                            ],
                        }
                    ],
                    "artifacts": [{"type": "markdown", "path": "formula.md"}],
                    "warnings": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        collected_formulas = module.collect_candidate_artifacts([formula_path], [])
        formula_signals = collected_formulas[0].get("quality_signals") or {}
        if formula_signals.get("formula_evidence_completeness") != 5 or formula_signals.get("formula_latex_count") != 1 or formula_signals.get("formula_bbox_count") != 1:
            raise AssertionError(f"Expected collected formula evidence signals: {collected_formulas}")
        if formula_signals.get("needs_formula_retention_review") is not True:
            raise AssertionError(f"Expected formula retention review signal: {collected_formulas}")
        collected_matrix = module.collect_review_bundle_evidence([], [output])
        if len(collected_matrix) != 1 or collected_matrix[0].get("backend") != "pdf_table" or collected_matrix[0].get("artifact_type") != "table_review_matrix":
            raise AssertionError(f"Expected collected table review matrix evidence: {collected_matrix}")
        matrix_signals = collected_matrix[0].get("quality_signals") or {}
        if matrix_signals.get("table_evidence_completeness") != 4 or matrix_signals.get("needs_card_layout_false_positive_review") is not True:
            raise AssertionError(f"Expected collected matrix quality signals: {collected_matrix}")
        if matrix_signals.get("table_evidence_completeness_score") != 1.0 or matrix_signals.get("table_conflict_count") != 2:
            raise AssertionError(f"Expected collected matrix score/conflict signals: {collected_matrix}")
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
