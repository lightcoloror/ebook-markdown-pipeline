from __future__ import annotations

import tempfile
from pathlib import Path
import sys

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

from compare_ocr_providers import compare_ocr_providers  # noqa: E402


class FakeRapidOCREngine:
    def __call__(self, image_path: str):
        name = Path(image_path).stem
        return [([[0, 0], [100, 0], [100, 20], [0, 20]], f"Rapid {name}", 0.93)], 0.01


class FakeUmiEngine:
    def run(self, image_path: str):
        name = Path(image_path).stem
        return {
            "code": 100,
            "data": [
                {
                    "text": f"Umi {name}",
                    "score": 0.9,
                    "box": [[1, 2], [90, 2], [90, 22], [1, 22]],
                }
            ],
        }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ocr-provider-compare-") as tmp:
        root = Path(tmp)
        ocr_root = root / "ocr"
        ocr_root.mkdir()
        first = ocr_root / "chinese.png"
        second = ocr_root / "lowres.png"
        first.write_bytes(b"fake image 1")
        second.write_bytes(b"fake image 2")
        output = root / "out"

        payload = compare_ocr_providers(
            [first, second],
            output_dir=output,
            providers=["rapidocr", "umi"],
            rapidocr_engine_factory=lambda: FakeRapidOCREngine(),
            umi_engine_factory=lambda: FakeUmiEngine(),
        )
        if payload.get("status") != "ok":
            raise AssertionError(f"Expected comparison status ok: {payload}")
        if not Path(payload["json_report"]).exists() or not Path(payload["markdown_report"]).exists():
            raise AssertionError(f"Expected comparison reports: {payload}")
        by_provider = {item["provider"]: item for item in payload["providers"]}
        if by_provider["rapidocr"]["metrics"]["total_char_count"] <= 0:
            raise AssertionError(f"Expected RapidOCR char metrics: {payload}")
        if by_provider["umi"]["metrics"]["total_bbox_count"] != 2:
            raise AssertionError(f"Expected Umi bbox metrics: {payload}")
        rapid_categories = by_provider["rapidocr"].get("category_metrics") or {}
        if "image_ocr_chinese" not in rapid_categories or "image_ocr_lowres" not in rapid_categories:
            raise AssertionError(f"Expected per-category OCR metrics: {rapid_categories}")
        markdown = Path(payload["markdown_report"]).read_text(encoding="utf-8")
        if "OCR Provider Comparison" not in markdown or "By Category" not in markdown or "image_ocr_chinese" not in markdown:
            raise AssertionError(f"Unexpected markdown report: {markdown}")

        missing = compare_ocr_providers(
            [first],
            output_dir=root / "missing",
            providers=["umi"],
            umi_paddle_exe="missing.exe",
            umi_paddle_module="missing.py",
        )
        if missing["providers"][0]["status"] != "missing":
            raise AssertionError(f"Expected missing Umi dependency to be recorded: {missing}")
        if missing["status"] != "skipped":
            raise AssertionError(f"Expected all-missing optional providers to skip instead of fail: {missing}")

    print("OCR provider comparison test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
