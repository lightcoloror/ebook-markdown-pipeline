from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline import default_options, normalize_command_options
from ebook_markdown_pipeline.batch_convert_books import (
    collect_sources,
    detect_source_kind,
    find_missing_dependencies,
    pipeline_name,
)
from ebook_markdown_pipeline.docling_backend import DOCLING_FORMATS, docling_available, docling_supported_format
from ebook_markdown_pipeline.document_inspector import inspect_document


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ebook-docling-contract-") as tmp:
        tmpdir = Path(tmp)
        docx = tmpdir / "sample.docx"
        docx.write_bytes(b"not a real docx; routing only")
        options = normalize_command_options(default_options(input=tmpdir, output=tmpdir / "out"))
        sources = collect_sources(tmpdir, recursive=False, include_hidden=False)

        if ".docx" not in DOCLING_FORMATS:
            raise AssertionError("DOCX should be a Docling format")
        if not docling_supported_format(docx):
            raise AssertionError("docling_supported_format should accept DOCX")
        if detect_source_kind(docx) != "docling":
            raise AssertionError(f"DOCX should route to docling, got {detect_source_kind(docx)}")
        if pipeline_name(docx, options) != "docling":
            raise AssertionError(f"DOCX pipeline should be docling, got {pipeline_name(docx, options)}")
        if docx not in sources:
            raise AssertionError(f"DOCX should be collected as supported source: {sources}")

        inspected = inspect_document(docx)
        if inspected["kind"] != "docling" or inspected["recommendation"] != "convert_document_docling":
            raise AssertionError(f"Docling inspection failed: {inspected}")
        missing = find_missing_dependencies([docx], options)
        if docling_available():
            if missing:
                raise AssertionError(f"Docling is importable, but dependencies are reported missing: {missing}")
        elif not any("docling" in item.lower() for item in missing):
            raise AssertionError(f"Missing Docling should be reported clearly: {missing}")

    print("Docling backend routing test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
