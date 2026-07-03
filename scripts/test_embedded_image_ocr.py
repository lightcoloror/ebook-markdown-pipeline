from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.batch_convert_books import (  # noqa: E402
    enhance_embedded_images_in_markdown,
    inject_embedded_image_ocr_blocks,
    markdown_image_references,
)


def main() -> int:
    root = PROJECT_DIR / ".tmp-tests" / "embedded-image-ocr"
    resolved_root = root.resolve()
    allowed_root = (PROJECT_DIR / ".tmp-tests").resolve()
    if root.exists():
        if allowed_root not in resolved_root.parents:
            raise AssertionError(f"Refusing to clean unexpected test directory: {resolved_root}")
        shutil.rmtree(root)
    root.mkdir(parents=True)
    try:
        source = root / "mixed.docx"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("word/media/image1.png", b"fake-png")
        output = root / "mixed.md"
        markdown = '# Mixed\n\n<img src="media/image1.png" alt="demo" />\n'
        refs = markdown_image_references(markdown)
        if len(refs) != 1 or refs[0]["normalized"] != "media/image1.png":
            raise AssertionError(f"Unexpected image refs: {refs}")

        def fake_recognizer(image_path: Path) -> dict[str, object]:
            if image_path.name != "image1.png" or not image_path.exists():
                raise AssertionError(f"Unexpected OCR path: {image_path}")
            return {"provider": "fake", "text": "图片里的客户经营文字", "blocks": [{"text": "图片里的客户经营文字"}]}

        args = SimpleNamespace(embedded_image_ocr="auto", embedded_image_ocr_max=10)
        enhanced = enhance_embedded_images_in_markdown(markdown, source, output, args, ocr_recognizer=fake_recognizer)
        media = root / "media" / "image1.png"
        if not media.exists() or media.read_bytes() != b"fake-png":
            raise AssertionError("Expected embedded image to be extracted beside Markdown output.")
        if "embedded-image-ocr: media/image1.png" not in enhanced or "图片里的客户经营文字" not in enhanced:
            raise AssertionError(f"Expected OCR block to be inserted:\n{enhanced}")
        if inject_embedded_image_ocr_blocks(enhanced, {"media/image1.png": {"provider": "fake", "text": "repeat"}}) != enhanced:
            raise AssertionError("OCR injection should be idempotent when markers are already present.")
        report = getattr(args, "_embedded_image_ocr_reports", {})
        if not report or next(iter(report.values())).get("ocr_count") != 1:
            raise AssertionError(f"Expected embedded image OCR report: {report}")
    finally:
        if root.exists():
            shutil.rmtree(root)
    print("Embedded image OCR smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())