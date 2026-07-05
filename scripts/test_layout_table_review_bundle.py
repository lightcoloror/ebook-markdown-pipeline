from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_DIR / "scripts" / "build_layout_table_review_bundle.py"


def main() -> int:
    module = load_module()
    with tempfile.TemporaryDirectory(prefix="layout-table-review-bundle-") as tmp:
        root = Path(tmp)
        layout = root / "layout-candidates.json"
        table = root / "table-candidates.json"
        table_alt = root / "table-candidates-pdfplumber.json"
        formula = root / "formula-candidates.json"
        wrapper_dir = root / "external" / "monkey"
        wrapper_dir.mkdir(parents=True)
        wrapper = wrapper_dir / "external-wrapper-result.json"
        scorecard = root / "backend-scorecard.json"
        candidate_plan = root / "candidate-plan.json"
        layout.write_text(json.dumps({"schema_version": "layout-candidates-v1", "backend": "doclayout_yolo", "status": "review", "pages": [{"page": 1, "image": "page-1.png", "overlay_path": "page-1-layout.png", "blocks": [{"label": "text"}, {"label": "table"}], "markdown": "Layout text preview"}]}, ensure_ascii=False), encoding="utf-8")
        table.write_text(json.dumps({"schema_version": "table-candidates-v1", "backend": "pdf_table", "status": "review", "pages": [{"page": 1, "tables": [{"id": 1, "html_path": "table-1.html", "markdown": "| A | B |", "markdown_path": "table-1.md", "cells_path": "table-1-cells.json", "overlay_path": "table-1-overlay.png"}, {"id": 2}]}]}, ensure_ascii=False), encoding="utf-8")
        table_alt.write_text(json.dumps({"schema_version": "table-candidates-v1", "backend": "pdfplumber", "status": "review", "pages": [{"page": 1, "tables": [{"id": "p1", "markdown": "| X | Y |"}]}]}, ensure_ascii=False), encoding="utf-8")
        formula.write_text(json.dumps({"schema_version": "formula-candidates-v1", "backend": "pix2text", "status": "review", "pages": [{"page": 1, "source": "page-1.png", "formulas": [{"latex": "x", "markdown": "$x$", "bbox": [1, 2, 8, 9], "confidence": 0.91, "source": "page-1.png"}]}]}, ensure_ascii=False), encoding="utf-8")
        wrapper.write_text(json.dumps({"schema_version": "external-wrapper-result-v1", "backend": "monkeyocr", "mode": "fake", "status": "ok", "artifacts": [{"type": "markdown", "path": "a.md"}], "metrics": {"page_count": 1}}, ensure_ascii=False), encoding="utf-8")
        scorecard.write_text(
            json.dumps(
                {
                    "schema_version": "optional-backend-scorecard-v1",
                    "backends": [
                        {
                            "name": "DocLayout-YOLO",
                            "status": "needs_model",
                            "recommendation_score": 34,
                            "health_names": ["DocLayout-YOLO baseline"],
                            "capability_names": ["layout_detector_baseline"],
                            "quality_signals": {"evidence_count": 1, "block_count": 2, "has_layout_evidence": True},
                            "promotion_gate": {"decision": "plan_or_fix_environment_first", "status": "environment_not_ready", "evidence_count": 1, "reasons": ["backend status is needs_model"]},
                        },
                        {
                            "name": "pdf_table",
                            "status": "degraded",
                            "recommendation_score": 45,
                            "health_names": ["pdf_table worker"],
                            "capability_names": ["external_table_worker"],
                            "quality_signals": {"evidence_count": 1, "table_count": 2, "has_table_evidence": True},
                            "promotion_gate": {"decision": "review_only", "status": "insufficient_evidence", "evidence_count": 1, "reasons": ["needs shared-sample evidence"]},
                        },
                        {
                            "name": "MonkeyOCR",
                            "status": "degraded",
                            "recommendation_score": 44,
                            "health_names": ["MonkeyOCR worker"],
                            "capability_names": ["external_document_vlm_wrappers"],
                            "quality_signals": {"evidence_count": 1, "external_result_count": 1},
                            "promotion_gate": {"decision": "review_only", "status": "insufficient_quality_signals", "evidence_count": 1, "reasons": ["needs comparable signals"]},
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        candidate_plan.write_text(
            json.dumps(
                {
                    "schema_version": "candidate-benchmark-plan-v1",
                    "promotion_gate": {"required_evidence": ["same sample class", "scorecard"]},
                    "sample_classes": [
                        {
                            "class": "pdf_table",
                            "review_questions": ["Are true tables preserved as tables?"],
                            "expected_artifacts": ["table_candidates_json", "layout_candidates_json"],
                            "candidate_backend_previews": [
                                {
                                    "backend": "pdf_table",
                                    "registry_key": "pdf_table",
                                    "artifact_contract": ["table_markdown", "table_html"],
                                    "run_preview": {
                                        "schema_version": "candidate-run-preview-v1",
                                        "default_mode": "plan",
                                        "execution_policy": "plan_or_fake_first_no_model_install_no_service_start",
                                        "expected_artifacts": ["table_markdown", "table_html"],
                                    },
                                }
                            ],
                        }
                    ],
                    "samples": [
                        {
                            "id": "sample-table",
                            "path": "sample.pdf",
                            "category": "pdf_table",
                            "candidate_class": "pdf_table",
                            "exists": False,
                            "review_questions": ["Are card/infographic regions kept out of table output?"],
                            "expected_artifacts": ["table_candidates_json", "table_overlay_image"],
                            "candidate_backend_previews": [
                                {
                                    "backend": "pdf_table",
                                    "registry_key": "pdf_table",
                                    "artifact_contract": ["table_markdown", "table_html", "table_overlay_image"],
                                    "run_preview": {
                                        "schema_version": "candidate-run-preview-v1",
                                        "default_mode": "plan",
                                        "execution_policy": "plan_or_fake_first_no_model_install_no_service_start",
                                        "expected_artifacts": ["table_markdown", "table_html", "table_overlay_image"],
                                    },
                                }
                            ],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        payload = module.build_review_bundle([layout, table, table_alt, formula], [root / "external"], source=Path("sample.pdf"), output=root / "bundle", scorecards=[scorecard], candidate_plans=[candidate_plan], sample_id="sample-table")
        if payload.get("schema_version") != module.SCHEMA_VERSION:
            raise AssertionError(f"Unexpected review bundle schema: {payload}")
        summary = payload.get("summary") or {}
        if summary.get("artifact_count") != 5 or summary.get("table_count") != 3 or summary.get("formula_count") != 1:
            raise AssertionError(f"Expected artifact/table/formula counts: {payload}")
        if "doclayout_yolo" not in summary.get("backends", []) or "pdf_table" not in summary.get("backends", []) or "pdfplumber" not in summary.get("backends", []):
            raise AssertionError(f"Expected backends in summary: {payload}")
        if summary.get("promotion_review_count") != 3 or summary.get("promotion_gate_counts", {}).get("review_only") != 2:
            raise AssertionError(f"Expected promotion gate summary: {payload}")
        if summary.get("review_page_count") < 2:
            raise AssertionError(f"Expected page/document review index: {payload}")
        if summary.get("table_review_matrix_count") != 1:
            raise AssertionError(f"Expected one table review matrix page: {payload}")
        if summary.get("formula_review_matrix_count") != 1:
            raise AssertionError(f"Expected one formula review matrix page: {payload}")
        if not summary.get("benchmark_context_found") or summary.get("candidate_preview_count") != 1:
            raise AssertionError(f"Expected benchmark context summary: {payload}")
        context = payload.get("benchmark_context") or {}
        if context.get("sample_id") != "sample-table" or context.get("candidate_class") != "pdf_table":
            raise AssertionError(f"Expected matched benchmark context: {payload}")
        coverage = context.get("expected_artifact_coverage") or {}
        if coverage.get("schema_version") != "expected-artifact-coverage-v1" or "table_candidates_json" not in coverage.get("present", []):
            raise AssertionError(f"Expected expected-artifact coverage present list: {payload}")
        if "table_overlay_image" not in coverage.get("missing", []):
            raise AssertionError(f"Expected missing table overlay evidence: {payload}")
        review_pages = payload.get("review_pages") or []
        page_one = next((item for item in review_pages if item.get("locator") == "page:1"), {})
        if page_one.get("schema_version") != "layout-table-review-page-v1" or "layout_overlay" not in page_one.get("review_targets", []) or "table_candidates" not in page_one.get("review_targets", []) or "markdown_excerpt" not in page_one.get("review_targets", []):
            raise AssertionError(f"Expected review page targets: {payload}")
        if len(page_one.get("artifact_refs") or []) < 4 or not page_one.get("markdown_excerpts"):
            raise AssertionError(f"Expected review page artifact refs and excerpts: {payload}")
        matrix = payload.get("table_review_matrix") or []
        matrix_page = matrix[0] if matrix else {}
        matrix_rows = matrix_page.get("rows") or []
        pdf_table_row = next((item for item in matrix_rows if item.get("backend") == "pdf_table"), {})
        if matrix_page.get("schema_version") != "table-review-matrix-v1" or matrix_page.get("locator") != "page:1":
            raise AssertionError(f"Expected table review matrix page: {payload}")
        if not pdf_table_row.get("has_html") or not pdf_table_row.get("has_markdown") or not pdf_table_row.get("has_cells_json") or not pdf_table_row.get("has_overlay"):
            raise AssertionError(f"Expected complete pdf_table matrix evidence: {payload}")
        if pdf_table_row.get("table_count") != 2 or "check_card_layout_false_positive" not in pdf_table_row.get("warnings", []):
            raise AssertionError(f"Expected table count and card-layout warning: {payload}")
        if pdf_table_row.get("evidence_completeness_score") != 1 or pdf_table_row.get("missing_evidence"):
            raise AssertionError(f"Expected complete pdf_table evidence score: {payload}")
        pdfplumber_row = next((item for item in matrix_rows if item.get("backend") == "pdfplumber"), {})
        if pdfplumber_row.get("table_count") != 1 or pdfplumber_row.get("evidence_completeness_score") != 0.333:
            raise AssertionError(f"Expected partial pdfplumber matrix evidence: {payload}")
        if "table_overlay" not in pdfplumber_row.get("missing_evidence", []) or "table_cells_json" not in pdfplumber_row.get("missing_evidence", []):
            raise AssertionError(f"Expected pdfplumber missing evidence list: {payload}")
        comparison = matrix_page.get("comparison_summary") or {}
        if comparison.get("schema_version") != "table-review-comparison-summary-v1" or comparison.get("agrees_on_table_count") is not False:
            raise AssertionError(f"Expected table comparison summary disagreement: {payload}")
        if "table_count_disagreement" not in comparison.get("conflict_tags", []) or "missing_overlay_evidence" not in comparison.get("conflict_tags", []):
            raise AssertionError(f"Expected table comparison conflict tags: {payload}")
        if any(item.get("backend") == "doclayout_yolo" for item in matrix_rows):
            raise AssertionError(f"Layout-only backend should not become a table matrix row: {payload}")
        formula_matrix = payload.get("formula_review_matrix") or []
        formula_matrix_page = formula_matrix[0] if formula_matrix else {}
        formula_rows = formula_matrix_page.get("rows") or []
        pix2text_row = next((item for item in formula_rows if item.get("backend") == "pix2text"), {})
        if formula_matrix_page.get("schema_version") != "formula-review-matrix-v1" or formula_matrix_page.get("locator") != "page:1":
            raise AssertionError(f"Expected formula review matrix page: {payload}")
        if pix2text_row.get("formula_count") != 1 or not pix2text_row.get("has_latex_or_markdown") or not pix2text_row.get("has_bbox") or not pix2text_row.get("has_source_ref") or not pix2text_row.get("has_confidence"):
            raise AssertionError(f"Expected complete Pix2Text formula matrix evidence: {payload}")
        if "check_formula_retention" not in pix2text_row.get("warnings", []):
            raise AssertionError(f"Expected formula retention warning: {payload}")
        if "Are card/infographic regions kept out of table output?" not in payload.get("review_questions", []):
            raise AssertionError(f"Expected benchmark review question merge: {payload}")
        actions = payload.get("next_actions") or []
        if not any(item.get("action") == "plan_environment_or_model_fix" and item.get("backend") == "DocLayout-YOLO" for item in actions):
            raise AssertionError(f"Expected environment planning next action: {payload}")
        if not any(item.get("action") == "gather_shared_sample_evidence" and item.get("backend") == "pdf_table" for item in actions):
            raise AssertionError(f"Expected shared-sample next action: {payload}")
        if not any(item.get("action") == "collect_missing_expected_artifacts" for item in actions):
            raise AssertionError(f"Expected missing expected artifact next action: {payload}")
        if not any(item.get("action") == "review_page_index" for item in actions):
            raise AssertionError(f"Expected review page index next action: {payload}")
        if not any(item.get("action") == "review_table_matrix" for item in actions):
            raise AssertionError(f"Expected table matrix next action: {payload}")
        if not any(item.get("action") == "review_formula_matrix" for item in actions):
            raise AssertionError(f"Expected formula matrix next action: {payload}")
        if not any(item.get("action") == "review_formula_candidates" for item in actions):
            raise AssertionError(f"Expected formula candidates next action: {payload}")

        output = root / "bundle-cli"
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--output",
                str(output),
                "--artifact",
                str(layout),
                "--artifact",
                str(table),
                "--artifact",
                str(table_alt),
                "--artifact",
                str(formula),
                "--external-wrapper-root",
                str(root / "external"),
                "--scorecard",
                str(scorecard),
                "--candidate-plan",
                str(candidate_plan),
                "--sample-id",
                "sample-table",
            ],
            cwd=PROJECT_DIR,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(f"CLI failed:\nSTDOUT={completed.stdout}\nSTDERR={completed.stderr}")
        if not (output / "layout-table-review-bundle.json").exists() or not (output / "layout-table-review-bundle.md").exists():
            raise AssertionError("Expected review bundle JSON/Markdown artifacts.")
        markdown = (output / "layout-table-review-bundle.md").read_text(encoding="utf-8")
        if "Layout/Table Review Bundle" not in markdown or "compare_tables" not in markdown or "Promotion Gate Reviews" not in markdown or "Benchmark Context" not in markdown or "Readiness" not in markdown or "Review Pages" not in markdown or "Table Review Matrix" not in markdown or "Score" not in markdown or "Missing" not in markdown or "Formula Review Matrix" not in markdown or "review_table_matrix" not in markdown or "review_formula_matrix" not in markdown or "review_page_index" not in markdown or "Missing expected artifacts" not in markdown or "collect_missing_expected_artifacts" not in markdown:
            raise AssertionError(f"Expected review bundle Markdown content: {markdown}")
    print("Layout/table review bundle test passed.")
    return 0


def load_module():
    spec = importlib.util.spec_from_file_location("build_layout_table_review_bundle", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    raise SystemExit(main())
