from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline import default_options, normalize_command_options  # noqa: E402
from ebook_markdown_pipeline.batch_convert_books import (  # noqa: E402
    PDF_PIPELINE_MODES,
    collect_sources,
    detect_source_kind,
    find_missing_dependencies,
    pipeline_name,
    source_kind_for_conversion,
)
from ebook_markdown_pipeline.markitdown_backend import MARKITDOWN_FORMATS, markitdown_available, markitdown_supported_format  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ebook-markitdown-contract-") as tmp:
        tmpdir = Path(tmp)
        epub = tmpdir / "sample.epub"
        epub.write_bytes(b"not a real epub; routing only")
        pdf = tmpdir / "sample.pdf"
        pdf.write_bytes(b"%PDF-1.4\n% routing only\n")

        options = normalize_command_options(
            default_options(
                input=tmpdir,
                output=tmpdir / "out",
                document_pipeline_mode="markitdown",
                pdf_pipeline_mode="markitdown",
            )
        )
        sources = collect_sources(tmpdir, recursive=False, include_hidden=False)

        if ".epub" not in MARKITDOWN_FORMATS or ".pdf" not in MARKITDOWN_FORMATS:
            raise AssertionError("MarkItDown should declare EPUB and PDF support.")
        if "markitdown" not in PDF_PIPELINE_MODES:
            raise AssertionError("PDF pipeline modes should include markitdown.")
        if not markitdown_supported_format(epub) or not markitdown_supported_format(pdf):
            raise AssertionError("markitdown_supported_format should accept EPUB and PDF.")
        if detect_source_kind(epub) != "pandoc":
            raise AssertionError("Default EPUB routing should remain pandoc unless MarkItDown is explicitly selected.")
        if source_kind_for_conversion(epub, options) != "markitdown":
            raise AssertionError("Forced document mode should route EPUB to MarkItDown.")
        if pipeline_name(epub, options) != "markitdown":
            raise AssertionError(f"Forced EPUB pipeline should be MarkItDown, got {pipeline_name(epub, options)}")
        if pipeline_name(pdf, options) != "markitdown":
            raise AssertionError(f"Forced PDF pipeline should be MarkItDown, got {pipeline_name(pdf, options)}")
        if epub not in sources or pdf not in sources:
            raise AssertionError(f"EPUB/PDF should be collected as supported sources: {sources}")

        missing = find_missing_dependencies([epub, pdf], options)
        if markitdown_available():
            if missing:
                raise AssertionError(f"MarkItDown is importable, but dependencies are reported missing: {missing}")
        elif not any("markitdown" in item.lower() for item in missing):
            raise AssertionError(f"Missing MarkItDown should be reported clearly: {missing}")

    print("MarkItDown backend routing test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
