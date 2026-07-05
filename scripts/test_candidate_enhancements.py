from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import fitz

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.batch_convert_books import PdfPreflight  # noqa: E402
from ebook_markdown_pipeline.document_inspector import (  # noqa: E402
    candidate_enhancements_for_directory,
    candidate_enhancements_for_pdf,
    inspect_document,
)


def main() -> int:
    assert_pdf_candidate_enhancements()
    assert_baseline_recommendations()
    assert_image_inspection_candidates()
    assert_directory_candidate_rollup()
    print("Candidate enhancement contract test passed.")
    return 0


def assert_pdf_candidate_enhancements() -> None:
    preflight = PdfPreflight(
        page_count=12,
        sampled_pages=4,
        bookmark_count=0,
        text_page_ratio=0.25,
        avg_text_chars=60.0,
        avg_text_blocks=18.0,
        image_page_ratio=0.75,
        avg_image_area_ratio=0.42,
        toc_like_pages=0,
        table_like_pages=2,
        two_column_like_pages=1,
        slide_aspect_page_ratio=0.0,
        presentation_like=False,
        scanned_likely=True,
        complex_layout_likely=True,
        recommended_pipeline="mineru",
        reasons=["fixture"],
    )
    payload = candidate_enhancements_for_pdf(preflight, {"mode": "layout_aware_structure_recovery"})
    backends = {item.get("backend") for item in payload.get("candidates") or []}
    expected = {"MonkeyOCR", "dots.mocr", "DocLayout-YOLO", "pdf_table"}
    if not payload.get("recommended") or not expected.issubset(backends):
        raise AssertionError(f"Expected PDF candidate wrapper recommendations: {payload}")
    if payload.get("remote_call_enabled") or payload.get("model_install_enabled"):
        raise AssertionError(f"Candidate recommendations must not enable execution: {payload}")
    by_backend = {item.get("backend"): item for item in payload.get("candidates") or []}
    monkey = by_backend["MonkeyOCR"]
    if monkey.get("registry_key") != "monkeyocr" or not monkey.get("canonical_artifact_contract"):
        raise AssertionError(f"Expected registry metadata on MonkeyOCR candidate: {monkey}")
    preview = monkey.get("run_preview") or {}
    if preview.get("schema_version") != "candidate-run-preview-v1" or preview.get("model_install_enabled"):
        raise AssertionError(f"Expected non-executing run preview on MonkeyOCR candidate: {monkey}")
    if "layout_review_pdf" not in (preview.get("expected_artifacts") or []):
        raise AssertionError(f"Expected preview artifact list from registry: {preview}")


def assert_baseline_recommendations() -> None:
    with tempfile.TemporaryDirectory(prefix="baseline-recommendations-") as tmp:
        root = Path(tmp)
        docx = root / "sample.docx"
        docx.write_bytes(b"fake docx for inspect-only contract")
        inspected_doc = inspect_document(docx)
        baseline = inspected_doc.get("baseline_recommendations") or {}
        items = baseline.get("items") or []
        backends = {item.get("backend") for item in items}
        if baseline.get("schema_version") != "baseline-recommendations-v1" or not {"Docling", "MarkItDown"}.issubset(backends):
            raise AssertionError(f"Expected Docling/MarkItDown baseline recommendations for DOCX: {inspected_doc}")
        markitdown = next(item for item in items if item.get("backend") == "MarkItDown")
        if markitdown.get("pipeline_mode") != "markitdown" or markitdown.get("before_heavy") is not True:
            raise AssertionError(f"Expected explicit MarkItDown cheap baseline metadata: {markitdown}")

        pdf = root / "sample.pdf"
        document = fitz.open()
        page = document.new_page(width=300, height=400)
        page.insert_text((72, 72), "Hello text layer")
        document.save(pdf)
        document.close()
        inspected_pdf = inspect_document(pdf)
        pdf_baseline = inspected_pdf.get("baseline_recommendations") or {}
        pdf_backends = {item.get("backend") for item in pdf_baseline.get("items") or []}
        if "PyMuPDF4LLM" not in pdf_backends or "MarkItDown" not in pdf_backends:
            raise AssertionError(f"Expected PDF cheap baseline recommendations: {inspected_pdf}")
        if any(item.get("backend") in {"MonkeyOCR", "dots.mocr"} for item in pdf_baseline.get("items") or []):
            raise AssertionError(f"Heavy candidate wrappers must not appear in baseline recommendations: {inspected_pdf}")

def assert_image_inspection_candidates() -> None:
    with tempfile.TemporaryDirectory(prefix="candidate-enhancement-image-") as tmp:
        image_path = Path(tmp) / "wide.png"
        pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 1200, 500), 0)
        pixmap.clear_with(255)
        pixmap.save(str(image_path))
        inspected = inspect_document(image_path)
        payload = inspected.get("candidate_enhancements") or {}
        backends = {item.get("backend") for item in payload.get("candidates") or []}
        if not {"MonkeyOCR", "dots.mocr"}.issubset(backends):
            raise AssertionError(f"Expected wide image candidate wrapper guidance: {inspected}")
        actions = inspected.get("next_actions") or []
        if not any(item.get("tool") == "external_wrapper_plan" for item in actions):
            raise AssertionError(f"Expected external wrapper plan next action: {inspected}")
        first_candidate = (payload.get("candidates") or [])[0]
        if (first_candidate.get("run_preview") or {}).get("execution_policy") != "plan_or_fake_first_no_model_install_no_service_start":
            raise AssertionError(f"Expected image candidate run preview: {inspected}")


def assert_directory_candidate_rollup() -> None:
    sample_files = [
        {
            "candidate_enhancements": {
                "recommended": True,
                "candidates": [
                    {"backend": "dots.mocr", "capability": "image_vlm_layout_provider"},
                    {"backend": "dots.mocr", "capability": "image_vlm_layout_provider"},
                ],
            }
        }
    ]
    payload = candidate_enhancements_for_directory(sample_files, document_count=0, image_count=10)
    candidates = payload.get("candidates") or []
    keys = {(item.get("backend"), item.get("capability")) for item in candidates}
    if len(keys) != len(candidates):
        raise AssertionError(f"Expected deduped directory candidates: {payload}")
    if not any(item.get("backend") == "MonkeyOCR" for item in candidates):
        raise AssertionError(f"Expected image-folder MonkeyOCR candidate: {payload}")


if __name__ == "__main__":
    raise SystemExit(main())
