from __future__ import annotations

import tempfile
from pathlib import Path
import sys

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.batch_convert_books import default_options, dependency_health_report, environment_capability_summary  # noqa: E402
from ebook_markdown_pipeline.ocr_providers import normalize_rapidocr_blocks, recognize_image_with_rapidocr  # noqa: E402
from ebook_markdown_pipeline.image_book_rebuilder import rebuild_image_book_from_sources  # noqa: E402
import ebook_markdown_pipeline.image_book_rebuilder as rebuilder  # noqa: E402


class FakeRapidOCREngine:
    def __call__(self, image_path: str):
        return (
            [
                ([[0, 0], [80, 0], [80, 20], [0, 20]], "第一章 快速开始", 0.98),
                ([[0, 30], [120, 30], [120, 55], [0, 55]], "正文内容", 0.91),
            ],
            0.01,
        )


def main() -> int:
    blocks = normalize_rapidocr_blocks(
        {
            "boxes": [
                [[1, 2], [9, 2], [9, 8], [1, 8]],
            ],
            "txts": ["Fake OCR block"],
            "scores": [0.88],
        }
    )
    if blocks != [
        {
            "index": 1,
            "text": "Fake OCR block",
            "provider": "rapidocr",
            "score": 0.88,
            "bbox": [1.0, 2.0, 9.0, 8.0],
        }
    ]:
        raise AssertionError(f"Unexpected normalized RapidOCR blocks: {blocks}")

    with tempfile.TemporaryDirectory(prefix="rapidocr-provider-") as tmp:
        root = Path(tmp)
        image = root / "001.png"
        image.write_bytes(b"fake image bytes")
        direct = recognize_image_with_rapidocr(image, FakeRapidOCREngine())
        if direct.get("provider") != "rapidocr" or len(direct.get("blocks") or []) != 2:
            raise AssertionError(f"Unexpected direct RapidOCR result: {direct}")

        output = root / "out"
        original_create = rebuilder.create_rapidocr_engine
        try:
            rebuilder.create_rapidocr_engine = lambda: FakeRapidOCREngine()
            result = rebuild_image_book_from_sources([image], output, ocr_mode="auto", ocr_provider="rapidocr")
        finally:
            rebuilder.create_rapidocr_engine = original_create
        pages_text = Path(result["pages"]).read_text(encoding="utf-8")
        book_text = Path(result["book"]).read_text(encoding="utf-8")
        if '"provider": "rapidocr"' not in pages_text or "第一章 快速开始" not in book_text:
            raise AssertionError(f"Expected RapidOCR provider output in pages/book: {pages_text}\n{book_text}")

    checks = dependency_health_report([], default_options(), fast=True)
    if not any(item.get("name") == "RapidOCR" for item in checks):
        raise AssertionError(f"RapidOCR should be listed in health checks: {checks}")
    capabilities = environment_capability_summary(checks)
    if not any(item.get("name") == "rapidocr_fallback" for item in capabilities):
        raise AssertionError(f"RapidOCR fallback capability should be listed: {capabilities}")

    print("RapidOCR provider contract test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
