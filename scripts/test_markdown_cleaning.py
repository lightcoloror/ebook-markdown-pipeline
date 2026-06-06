from __future__ import annotations

import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.batch_convert_books import analyze_markdown_quality, clean_umi_ocr_markdown  # noqa: E402


def main() -> int:
    repeated_pages = ["# OCR Book", ""]
    for page in range(1, 7):
        repeated_pages.extend(
            [
                f"<!-- Page {page} -->",
                "",
                str(page),
                "名老中医之路",
                "",
                f"这是第 {page} 页的正文内容，包含足够长的一句话用于判断它不是标题。",
                "",
                f"名老中医之路 - {page}",
                "",
            ]
        )
    cleaned = clean_umi_ocr_markdown("\n".join(repeated_pages))
    if "## 名老中医之路" in cleaned:
        raise AssertionError(f"Repeated OCR running title should not be promoted as heading:\n{cleaned}")
    if "removed repeated OCR header/footer: 名老中医之路" not in cleaned:
        raise AssertionError(f"Repeated OCR header should be marked as removed:\n{cleaned}")
    if "removed repeated OCR header/footer: 名老中医之路 - 6" not in cleaned:
        raise AssertionError(f"Repeated OCR footer with variable page number should be removed:\n{cleaned}")
    if "removed OCR page number: 1" not in cleaned:
        raise AssertionError(f"Page-edge numbers should be hidden:\n{cleaned}")

    tmp = PROJECT_DIR / ".tmp" / "cleaning-quality-smoke.md"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(cleaned, encoding="utf-8")
    quality = analyze_markdown_quality(tmp)
    if quality is None or quality.page_number_lines != 0 or quality.repeated_noise_lines != 0:
        raise AssertionError(f"Expected OCR cleanup to reduce page/noise metrics: {quality}")
    tmp.unlink(missing_ok=True)

    real_heading = clean_umi_ocr_markdown(
        "# OCR Book\n\n<!-- Page 1 -->\n\n出版者的话\n\n这是一个足够长的正文段落，说明短标题仍应被提升。\n"
    )
    if "## 出版者的话" not in real_heading:
        raise AssertionError(f"Real OCR page title should still be promoted:\n{real_heading}")

    print("Markdown cleaning smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
