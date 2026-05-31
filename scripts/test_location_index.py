from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ebook_markdown_pipeline.document_locator import build_location_index, query_location_index


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ebook-location-smoke-") as tmp:
        root = Path(tmp)
        input_dir = root / "inputs"
        output_dir = root / "index"
        input_dir.mkdir()

        pdf_path = input_dir / "sample.pdf"
        document = fitz.open()
        first = document.new_page()
        first.insert_text((72, 72), "Invoice number INV-2026-001\nCustomer Alpha")
        second = document.new_page()
        second.insert_text((72, 72), "Contract amount 300000\nCustomer Beta")
        document.save(pdf_path)
        document.close()

        build = build_location_index(input_dir, output_dir, recursive=True, ocr_mode="never")
        if build["record_count"] != 2:
            raise RuntimeError(f"Expected two page records: {build}")

        result = query_location_index(Path(build["sqlite"]), "300000", limit=5)
        if result["count"] != 1 or result["matches"][0]["page"] != 2:
            raise RuntimeError(f"Expected a hit on page 2: {json.dumps(result, ensure_ascii=False)}")

        print("Location index smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
