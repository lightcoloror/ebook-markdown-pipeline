from __future__ import annotations

import tempfile
from pathlib import Path
import sys

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.batch_convert_books import default_options, dependency_health_report, environment_capability_summary  # noqa: E402
from ebook_markdown_pipeline.ocr_providers import normalize_cnocr_blocks, recognize_image_with_cnocr  # noqa: E402


class FakeCnOCREngine:
    def ocr(self, image_path: str):
        name = Path(image_path).stem
        return [
            {
                "text": f"中文标题 {name}",
                "score": 0.96,
                "position": [[0, 0], [80, 0], [80, 20], [0, 20]],
            },
            {
                "text": "正文内容",
                "score": 0.9,
                "position": [[0, 30], [120, 30], [120, 55], [0, 55]],
            },
        ]


def main() -> int:
    blocks = normalize_cnocr_blocks(
        [
            {
                "text": "中文 OCR block",
                "score": 0.88,
                "position": [[1, 2], [9, 2], [9, 8], [1, 8]],
            }
        ]
    )
    if blocks != [
        {
            "index": 1,
            "text": "中文 OCR block",
            "provider": "cnocr",
            "score": 0.88,
            "bbox": [1.0, 2.0, 9.0, 8.0],
        }
    ]:
        raise AssertionError(f"Unexpected normalized CnOCR blocks: {blocks}")

    with tempfile.TemporaryDirectory(prefix="cnocr-provider-") as tmp:
        image = Path(tmp) / "中文样本.png"
        image.write_bytes(b"fake image bytes")
        direct = recognize_image_with_cnocr(image, FakeCnOCREngine())
        if direct.get("provider") != "cnocr" or len(direct.get("blocks") or []) != 2:
            raise AssertionError(f"Unexpected direct CnOCR result: {direct}")
        if "中文标题" not in direct.get("text", ""):
            raise AssertionError(f"Expected joined CnOCR text: {direct}")

    checks = dependency_health_report([], default_options(), fast=True)
    if not any(item.get("name") == "CnOCR" for item in checks):
        raise AssertionError(f"CnOCR should be listed in health checks: {checks}")
    capabilities = environment_capability_summary(checks)
    if not any(item.get("name") == "cnocr_chinese_ocr" for item in capabilities):
        raise AssertionError(f"CnOCR capability should be listed: {capabilities}")

    print("CnOCR provider contract test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
