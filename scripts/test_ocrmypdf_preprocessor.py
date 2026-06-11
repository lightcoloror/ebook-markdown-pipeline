from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline import default_options, normalize_command_options  # noqa: E402
from ebook_markdown_pipeline.batch_convert_books import (  # noqa: E402
    PDF_PIPELINE_MODES,
    PdfPreflight,
    dependency_health_report,
    find_missing_dependencies,
    ocrmypdf_text_layer_summary,
    pipeline_name,
)
from ebook_markdown_pipeline.document_inspector import inspect_pdf  # noqa: E402
from ebook_markdown_pipeline.ocrmypdf_preprocessor import ocrmypdf_available  # noqa: E402


def make_blank_scanned_like_pdf(path: Path) -> None:
    import pymupdf

    document = pymupdf.open()
    document.new_page(width=595, height=842)
    document.save(path)
    document.close()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ebook-ocrmypdf-contract-") as tmp:
        tmpdir = Path(tmp)
        pdf = tmpdir / "blank-scanned-like.pdf"
        make_blank_scanned_like_pdf(pdf)
        options = normalize_command_options(
            default_options(
                input=pdf,
                output=tmpdir / "out",
                pdf_pipeline_mode="ocrmypdf",
                ocrmypdf_command="definitely-missing-ocrmypdf-command",
            )
        )

        if "ocrmypdf" not in PDF_PIPELINE_MODES:
            raise AssertionError("PDF pipeline modes should include ocrmypdf.")
        if pipeline_name(pdf, options) != "ocrmypdf+pymupdf4llm":
            raise AssertionError(f"OCRmyPDF pipeline label should be explicit, got {pipeline_name(pdf, options)}")

        missing = find_missing_dependencies([pdf], options)
        if not any("ocrmypdf" in item.lower() for item in missing):
            raise AssertionError(f"Missing OCRmyPDF command should be reported clearly: {missing}")

        checks = dependency_health_report([pdf], options, fast=True)
        ocrmypdf_check = next((item for item in checks if item.get("name") == "OCRmyPDF"), None)
        if not ocrmypdf_check or ocrmypdf_check.get("status") != "missing":
            raise AssertionError(f"OCRmyPDF health check should be missing for a bad command: {ocrmypdf_check}")

        inspection = inspect_pdf(pdf, sample_pages=1)
        if not inspection.get("preflight", {}).get("scanned_likely"):
            raise AssertionError(f"Blank PDF fixture should be treated as weak text layer/scanned-like: {inspection}")
        actions = inspection.get("next_actions") or []
        if not any(action.get("pdf_pipeline_mode") == "ocrmypdf" for action in actions):
            raise AssertionError(f"Scanned-like PDF should recommend OCRmyPDF preprocessing as a next action: {actions}")

        before = PdfPreflight(
            page_count=10,
            sampled_pages=2,
            bookmark_count=0,
            text_page_ratio=0.0,
            avg_text_chars=12.0,
            avg_text_blocks=0.0,
            image_page_ratio=1.0,
            avg_image_area_ratio=0.8,
            toc_like_pages=0,
            table_like_pages=0,
            two_column_like_pages=0,
            slide_aspect_page_ratio=0.0,
            presentation_like=False,
            scanned_likely=True,
            complex_layout_likely=False,
            recommended_pipeline="ocrmypdf",
            reasons=["weak text layer"],
        )
        after = PdfPreflight(
            page_count=10,
            sampled_pages=2,
            bookmark_count=0,
            text_page_ratio=1.0,
            avg_text_chars=212.0,
            avg_text_blocks=8.0,
            image_page_ratio=1.0,
            avg_image_area_ratio=0.8,
            toc_like_pages=0,
            table_like_pages=0,
            two_column_like_pages=0,
            slide_aspect_page_ratio=0.0,
            presentation_like=False,
            scanned_likely=False,
            complex_layout_likely=False,
            recommended_pipeline="pymupdf4llm",
            reasons=["text layer present"],
        )
        summary = ocrmypdf_text_layer_summary(before, after)
        expected = {
            "before_text_page_ratio": 0.0,
            "after_text_page_ratio": 1.0,
            "text_page_ratio_delta": 1.0,
            "before_avg_text_chars": 12.0,
            "after_avg_text_chars": 212.0,
            "avg_text_chars_delta": 200.0,
            "before_sampled_text_characters": 24,
            "after_sampled_text_characters": 424,
            "sampled_ocr_characters_added": 400,
            "before_scanned_likely": True,
            "after_scanned_likely": False,
        }
        if summary != expected:
            raise AssertionError(f"OCRmyPDF text-layer summary should be stable and machine-readable: {summary}")

        # Availability is environment-dependent; this call should be safe either way.
        ocrmypdf_available()

    print("OCRmyPDF preprocessing contract test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
