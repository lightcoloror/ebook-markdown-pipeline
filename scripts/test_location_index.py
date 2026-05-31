from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ebook_markdown_pipeline.document_locator import LocationRecord, build_location_index, query_location_index, write_sqlite


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

        chinese_index = root / "chinese.sqlite"
        write_sqlite(
            chinese_index,
            [
                LocationRecord(
                    source="manual.pdf",
                    kind="pdf_page",
                    page=7,
                    text="这是中文测试文本，合同金额 三十万。",
                    char_count=18,
                    engine="test",
                    status="ok",
                )
            ],
        )
        chinese = query_location_index(chinese_index, "合同金额", limit=5)
        if chinese["count"] != 1 or chinese["matches"][0]["page"] != 7:
            raise RuntimeError(f"Expected a Chinese substring hit on page 7: {json.dumps(chinese, ensure_ascii=False)}")

        missing = query_location_index(root / "missing.sqlite", "anything", limit=5)
        if missing["count"] != 0 or "not found" not in missing.get("message", "").lower():
            raise RuntimeError(f"Expected a stable missing-index response: {json.dumps(missing, ensure_ascii=False)}")

        broken_index = root / "broken.sqlite"
        sqlite3.connect(broken_index).close()
        broken = query_location_index(broken_index, "anything", limit=5)
        if broken["count"] != 0:
            raise RuntimeError(f"Expected a stable broken-index response: {json.dumps(broken, ensure_ascii=False)}")

        print("Location index smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
