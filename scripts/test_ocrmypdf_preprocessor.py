from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline import default_options, normalize_command_options  # noqa: E402
from ebook_markdown_pipeline.batch_convert_books import (  # noqa: E402
    PDF_PIPELINE_MODES,
    dependency_health_report,
    find_missing_dependencies,
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

        # Availability is environment-dependent; this call should be safe either way.
        ocrmypdf_available()

    print("OCRmyPDF preprocessing contract test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
