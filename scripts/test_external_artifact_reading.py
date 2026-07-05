from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from ebook_converter_mcp import infer_artifact_type, read_artifact  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="external-artifact-reading-") as tmp:
        root = Path(tmp)
        assert_external_wrapper_summary(root)
        assert_candidate_summary(root / "layout-candidates.json", "layout_candidates_json", {"block_count": 3, "page_count": 2})
        assert_candidate_summary(root / "table-candidates.json", "table_candidates_json", {"table_count": 3, "page_count": 2})
        assert_candidate_summary(root / "formula-candidates.json", "formula_candidates_json", {"formula_count": 2, "page_count": 1})
        assert_candidate_summary(root / "document-vlm-result.json", "document_vlm_result_json", {"block_count": 2, "table_count": 1, "page_count": 1})
        assert_pdf_diagnostic_summary(root)
        assert_pdf_layout_evidence_summary(root)
        assert_ocr_blocks_summary(root)
        assert_ocr_provider_comparison_summary(root)
        assert_high_level_review_artifact_summaries(root)
    print("External artifact reading contract test passed.")
    return 0


def assert_external_wrapper_summary(root: Path) -> None:
    wrapper = root / "external-wrapper-result.json"
    wrapper.write_text(
        json.dumps(
            {
                "schema_version": "external-wrapper-result-v1",
                "backend": "monkeyocr",
                "mode": "fake",
                "status": "ok",
                "input": "sample.pdf",
                "output_dir": str(root),
                "artifacts": [
                    {"type": "markdown", "path": str(root / "sample.md"), "label": "Markdown"},
                    {"type": "layout_review_pdf", "path": str(root / "layout.pdf"), "label": "Layout PDF"},
                ],
                "metrics": {"page_count": 1},
                "warnings": ["fake output"],
                "next_actions": [{"action": "review_layout"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    if infer_artifact_type(wrapper) != "external_wrapper_result_json":
        raise AssertionError("Expected external wrapper result artifact inference.")
    readable = read_artifact({"path": str(wrapper)})
    summary = readable.get("summary") or {}
    if summary.get("backend") != "monkeyocr" or summary.get("artifact_count") != 2:
        raise AssertionError(f"Expected wrapper artifact summary: {readable}")



def assert_pdf_diagnostic_summary(root: Path) -> None:
    metadata = root / "pypdf-metadata.json"
    metadata.write_text(
        json.dumps({"schema_version": "pypdf-diagnostics-v1", "backend": "pypdf", "page_count": 3, "metadata": {"Title": "Fixture"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    if infer_artifact_type(metadata) != "pdf_metadata_json":
        raise AssertionError(f"Expected pdf_metadata_json inference: {infer_artifact_type(metadata)}")
    readable = read_artifact({"path": str(metadata)})
    summary = readable.get("summary") or {}
    if summary.get("kind") != "pdf_metadata" or summary.get("page_count") != 3 or summary.get("schema_valid") is not True:
        raise AssertionError(f"Expected pypdf metadata summary: {readable}")

    outline = root / "pypdf-outline.json"
    outline.write_text(
        json.dumps({"schema_version": "pypdf-outline-v1", "backend": "pypdf", "items": [{"title": "Intro", "level": 1}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    if infer_artifact_type(outline) != "pdf_outline_json":
        raise AssertionError(f"Expected pdf_outline_json inference: {infer_artifact_type(outline)}")
    readable_outline = read_artifact({"path": str(outline)})
    outline_summary = readable_outline.get("summary") or {}
    if outline_summary.get("kind") != "pdf_outline" or outline_summary.get("outline_count") != 1:
        raise AssertionError(f"Expected pypdf outline summary: {readable_outline}")



def assert_pdf_layout_evidence_summary(root: Path) -> None:
    evidence = root / "pdfminer-layout-evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "schema_version": "pdf-layout-evidence-v1",
                "backend": "pdfminer_six",
                "status": "ok",
                "pages": [{"page": 1, "text_chars": 90, "line_count": 3, "table_count": 2, "image_count": 1}],
                "flags": {"text_layer_present": True, "low_text_density": False},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    if infer_artifact_type(evidence) != "pdf_layout_evidence_json":
        raise AssertionError(f"Expected pdf_layout_evidence_json inference: {infer_artifact_type(evidence)}")
    readable = read_artifact({"path": str(evidence)})
    summary = readable.get("summary") or {}
    if summary.get("kind") != "pdf_layout_evidence" or summary.get("text_char_count") != 90 or summary.get("table_count") != 2 or summary.get("image_count") != 1 or summary.get("schema_valid") is not True:
        raise AssertionError(f"Expected PDF layout evidence summary: {readable}")

def assert_ocr_blocks_summary(root: Path) -> None:
    blocks = root / "ocr-blocks.jsonl"
    blocks.write_text(
        json.dumps(
            {
                "schema_version": "ocr-blocks-v1",
                "provider": "tesseract",
                "status": "ok",
                "blocks": [{"text": "Fake", "bbox": [10, 20, 30, 40]}],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    if infer_artifact_type(blocks) != "ocr_blocks_jsonl":
        raise AssertionError(f"Expected ocr_blocks_jsonl inference: {infer_artifact_type(blocks)}")
    readable = read_artifact({"path": str(blocks)})
    summary = readable.get("summary") or {}
    if summary.get("kind") != "ocr_blocks_jsonl" or summary.get("block_count") != 1 or summary.get("bbox_count") != 1:
        raise AssertionError(f"Expected OCR blocks summary: {readable}")


def assert_ocr_provider_comparison_summary(root: Path) -> None:
    comparison = root / "ocr-provider-comparison.json"
    comparison.write_text(
        json.dumps(
            {
                "schema_version": "ocr-provider-comparison-v1",
                "status": "ok",
                "image_count": 2,
                "ocr_block_schema_version": "ocr-blocks-v1",
                "ocr_blocks_jsonl": str(root / "ocr-blocks.jsonl"),
                "provider_registry": {
                    "schema_version": "ocr-provider-registry-v1",
                    "providers": [
                        {"name": "rapidocr", "display_name": "RapidOCR", "executable": True},
                        {"name": "doctr", "display_name": "docTR", "executable": False, "status": "planned_only"},
                    ],
                },
                "summary": {"provider_count": 2, "ok_or_partial_count": 1, "missing_count": 1, "failed_count": 0},
                "providers": [
                    {
                        "provider": "rapidocr",
                        "display_name": "RapidOCR",
                        "status": "ok",
                        "metrics": {
                            "sample_count": 2,
                            "total_char_count": 18,
                            "total_block_count": 3,
                            "total_bbox_count": 2,
                            "bbox_coverage": 0.67,
                        },
                        "category_metrics": {"image_ocr_chinese": {"sample_count": 2}},
                    },
                    {
                        "provider": "doctr",
                        "display_name": "docTR",
                        "status": "missing_dependency",
                        "metrics": {
                            "sample_count": 0,
                            "total_char_count": 0,
                            "total_block_count": 0,
                            "total_bbox_count": 0,
                            "bbox_coverage": 0,
                        },
                        "category_metrics": {},
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    if infer_artifact_type(comparison) != "ocr_provider_comparison_json":
        raise AssertionError(f"Expected ocr_provider_comparison_json inference: {infer_artifact_type(comparison)}")
    readable = read_artifact({"path": str(comparison)})
    summary = readable.get("summary") or {}
    categories = summary.get("categories") or []
    providers = summary.get("providers") or []
    if (
        summary.get("kind") != "ocr_provider_comparison"
        or summary.get("provider_count") != 2
        or summary.get("registry_planned_count") != 1
        or "image_ocr_chinese" not in categories
        or not providers
        or providers[0].get("provider") != "rapidocr"
        or providers[0].get("total_char_count") != 18
    ):
        raise AssertionError(f"Expected OCR provider comparison summary: {readable}")

def assert_high_level_review_artifact_summaries(root: Path) -> None:
    bundle = root / "layout-table-review-bundle.json"
    bundle.write_text(
        json.dumps(
            {
                "schema_version": "layout-table-review-bundle-v1",
                "source": "sample.pdf",
                "summary": {
                    "artifact_count": 3,
                    "backends": ["pix2text", "pdf_table"],
                    "block_count": 1,
                    "table_count": 2,
                    "formula_count": 1,
                    "review_page_count": 1,
                    "table_review_matrix_count": 1,
                    "formula_review_matrix_count": 1,
                    "promotion_review_count": 2,
                    "benchmark_context_found": True,
                    "missing_expected_artifact_count": 1,
                },
                "benchmark_context": {"candidate_class": "pdf_formula"},
                "next_actions": [{"action": "review_formula_matrix"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    if infer_artifact_type(bundle) != "layout_table_review_bundle_json":
        raise AssertionError(f"Expected layout_table_review_bundle_json inference: {infer_artifact_type(bundle)}")
    bundle_summary = read_artifact({"path": str(bundle)}).get("summary") or {}
    if bundle_summary.get("kind") != "layout_table_review_bundle" or bundle_summary.get("formula_review_matrix_count") != 1 or bundle_summary.get("candidate_class") != "pdf_formula":
        raise AssertionError(f"Expected layout review bundle summary: {bundle_summary}")

    scorecard = root / "backend-scorecard.json"
    scorecard.write_text(
        json.dumps(
            {
                "schema_version": "optional-backend-scorecard-v1",
                "summary": {"status": "ok", "backend_count": 2, "ready": ["MarkItDown"], "promotion_gate_counts": {"review_only": 1}},
                "external_wrapper_result_count": 1,
                "candidate_artifact_count": 2,
                "backends": [{"name": "Pix2Text", "promotion_gate": {"decision": "review_only"}}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    if infer_artifact_type(scorecard) != "optional_backend_scorecard_json":
        raise AssertionError(f"Expected optional_backend_scorecard_json inference: {infer_artifact_type(scorecard)}")
    scorecard_summary = read_artifact({"path": str(scorecard)}).get("summary") or {}
    if scorecard_summary.get("kind") != "optional_backend_scorecard" or scorecard_summary.get("backend_count") != 2 or scorecard_summary.get("candidate_artifact_count") != 2:
        raise AssertionError(f"Expected backend scorecard summary: {scorecard_summary}")

    plan = root / "candidate-benchmark-plan.json"
    plan.write_text(
        json.dumps(
            {
                "schema_version": "candidate-benchmark-plan-v1",
                "execution_policy": "plan_only_no_model_install_no_service_start",
                "promotion_gate": {"required_evidence": ["same sample class"]},
                "sample_classes": [
                    {"class": "pdf_formula", "candidate_backends": ["Pix2Text"], "expected_artifacts": ["formula_candidates_json"]},
                    {"class": "pdf_table", "candidate_backends": ["pdf_table"], "expected_artifacts": ["table_candidates_json"]},
                ],
                "samples": [{"id": "sample-formula", "candidate_class": "pdf_formula"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    if infer_artifact_type(plan) != "candidate_benchmark_plan_json":
        raise AssertionError(f"Expected candidate_benchmark_plan_json inference: {infer_artifact_type(plan)}")
    plan_summary = read_artifact({"path": str(plan)}).get("summary") or {}
    if plan_summary.get("kind") != "candidate_benchmark_plan" or plan_summary.get("sample_class_count") != 2 or plan_summary.get("sample_count") != 1:
        raise AssertionError(f"Expected candidate benchmark plan summary: {plan_summary}")

def assert_candidate_summary(path: Path, artifact_type: str, expected: dict[str, int]) -> None:
    payload = candidate_payload_for(path.name)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    if infer_artifact_type(path) != artifact_type:
        raise AssertionError(f"Expected {artifact_type} inference for {path.name}, got {infer_artifact_type(path)}")
    readable = read_artifact({"path": str(path)})
    summary = readable.get("summary") or {}
    for key, value in expected.items():
        if summary.get(key) != value:
            raise AssertionError(f"Expected {key}={value} for {artifact_type}: {readable}")


def candidate_payload_for(name: str) -> dict:
    if name == "layout-candidates.json":
        return {
            "schema_version": "layout-candidates-v1",
            "backend": "doclayout_yolo",
            "status": "review",
            "pages": [
                {"page": 1, "blocks": [{"label": "table"}, {"label": "text"}]},
                {"page": 2, "blocks": [{"label": "title"}]},
            ],
            "warnings": ["candidate only"],
        }
    if name == "table-candidates.json":
        return {
            "schema_version": "table-candidates-v1",
            "backend": "pdf_table",
            "status": "review",
            "pages": [
                {"page": 1, "tables": [{"id": 1}, {"id": 2}]},
                {"page": 2, "table_count": 1},
            ],
        }
    if name == "formula-candidates.json":
        return {
            "schema_version": "formula-candidates-v1",
            "backend": "pix2text",
            "status": "review",
            "pages": [{"page": 1, "formulas": [{"latex": "x"}, {"latex": "y"}]}],
        }
    if name == "document-vlm-result.json":
        return {
            "schema_version": "document-vlm-result-v1",
            "backend": "dots_mocr",
            "status": "review",
            "pages": [{"page": 1, "blocks": [{"type": "text"}, {"type": "table"}], "table_count": 1}],
            "artifacts": [{"type": "markdown", "path": "sample.md"}],
        }
    raise AssertionError(f"No fixture payload for {name}")


if __name__ == "__main__":
    raise SystemExit(main())
