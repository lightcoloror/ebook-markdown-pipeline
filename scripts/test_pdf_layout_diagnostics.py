from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.pdf_layout_diagnostics import analyze_pdf_layout_with_pdfplumber, pdfplumber_available  # noqa: E402


def make_text_pdf(path: Path) -> None:
    import pymupdf

    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 72), "Header")
    page.insert_text((72, 140), "Name    Amount    Date")
    page.insert_text((72, 165), "Alpha   100       2026-01-01")
    page.insert_text((72, 190), "Beta    200       2026-01-02")
    page.insert_text((72, 780), "Footer")
    document.save(path)
    document.close()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ebook-pdf-layout-diagnostics-") as tmp:
        tmpdir = Path(tmp)
        pdf = tmpdir / "sample.pdf"
        out = tmpdir / "tables"
        make_text_pdf(pdf)

        result = analyze_pdf_layout_with_pdfplumber(pdf, sample_pages=1, output_dir=out)
        if not pdfplumber_available():
            if result.get("status") != "missing_dependency":
                raise AssertionError(f"Missing pdfplumber should be reported clearly: {result}")
            return 0

        if result.get("status") != "ok":
            raise AssertionError(f"pdfplumber diagnostics should succeed for a simple PDF: {result}")
        if not result.get("pages") or result["pages"][0].get("text_chars", 0) <= 0:
            raise AssertionError(f"Expected page text diagnostics: {result}")
        diagnostics_json = out / "table-diagnostics.json"
        if not diagnostics_json.exists():
            raise AssertionError("Expected table-diagnostics.json artifact.")
        persisted = json.loads(diagnostics_json.read_text(encoding="utf-8"))
        if persisted.get("status") != "ok" or "summary" not in persisted:
            raise AssertionError(f"Unexpected persisted diagnostics: {persisted}")

    print("PDF layout diagnostics test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
