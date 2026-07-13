from __future__ import annotations

import sys
import tempfile
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.batch_convert_books import analyze_markdown_quality, deterministic_quality_risks  # noqa: E402


def risk_codes(path: Path, **kwargs) -> set[str]:
    quality = analyze_markdown_quality(path)
    if quality is None:
        raise AssertionError(f"Expected Markdown quality payload for {path}")
    payload = deterministic_quality_risks(quality, **kwargs)
    if payload.get("schema_version") != "deterministic-quality-risks-v1":
        raise AssertionError(f"Unexpected risk schema: {payload}")
    return set(payload.get("risk_codes") or [])


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="deterministic-quality-risks-") as tmp:
        root = Path(tmp)

        empty = root / "empty.md"
        empty.write_text("", encoding="utf-8")
        if "empty_document" not in risk_codes(empty):
            raise AssertionError("Expected empty document risk")

        headingless = root / "headingless.md"
        headingless.write_text(("This paragraph has content but no Markdown heading. " * 30).strip(), encoding="utf-8")
        if "heading_hierarchy_missing" not in risk_codes(headingless):
            raise AssertionError("Expected heading hierarchy risk")

        page_noise = root / "page-noise.md"
        page_noise.write_text("# Document\n\n" + "\n".join(str(index) for index in range(1, 25)) + "\nBody text.\n", encoding="utf-8")
        if "page_number_noise" not in risk_codes(page_noise):
            raise AssertionError("Expected page number noise risk")

        ocr = root / "ocr.md"
        ocr.write_text("# OCR Fixture\n\nRecognized local text.\n", encoding="utf-8")
        if "ocr_low_confidence" not in risk_codes(ocr, ocr_confidences=[0.42, 0.58, 0.91]):
            raise AssertionError("Expected low-confidence OCR risk")

        table = root / "table.md"
        table.write_text("# Table Fixture\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n", encoding="utf-8")
        table_codes = risk_codes(
            table,
            pdf_preflight={"table_like_pages": 1},
            pdf_layout_diagnostics={"summary": {"table_pages": [1], "table_count": 1}},
        )
        if "table_structure_risk" not in table_codes:
            raise AssertionError("Expected table structure risk")

    print("Deterministic quality risk contract test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
