from __future__ import annotations

import tempfile
from pathlib import Path
import sys

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.batch_convert_books import default_options, dependency_health_report, environment_capability_summary  # noqa: E402
from ebook_markdown_pipeline.ocr_providers import choose_rapidocr_device, normalize_ocr_box, normalize_rapidocr_blocks, rapidocr_default_params, rapidocr_model_root_dir, rapidocr_runtime_info, recognize_image_with_rapidocr, rows_from_parallel_values  # noqa: E402
from ebook_markdown_pipeline.image_book_rebuilder import rebuild_image_book_from_sources  # noqa: E402
import ebook_markdown_pipeline.image_book_rebuilder as rebuilder  # noqa: E402


class ArrayLike:
    def __init__(self, value):
        self.value = value

    def tolist(self):
        return self.value


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

    array_blocks = normalize_rapidocr_blocks(
        {
            "boxes": ArrayLike([[[2, 3], [10, 3], [10, 12], [2, 12]]]),
            "txts": ArrayLike(["Array-like OCR block"]),
            "scores": None,
        }
    )
    if array_blocks != [
        {
            "index": 1,
            "text": "Array-like OCR block",
            "provider": "rapidocr",
            "bbox": [2.0, 3.0, 10.0, 12.0],
        }
    ]:
        raise AssertionError(f"Unexpected array-like RapidOCR blocks: {array_blocks}")

    rows = rows_from_parallel_values(ArrayLike([]), ArrayLike(["Text without box"]), ArrayLike([]))
    if rows != [[None, "Text without box", None]]:
        raise AssertionError(f"Unexpected rows with empty array-like boxes/scores: {rows}")

    if normalize_ocr_box(ArrayLike([[5, 6], [12, 6], [12, 14], [5, 14]])) != [5.0, 6.0, 12.0, 14.0]:
        raise AssertionError("Array-like OCR boxes should normalize through tolist().")

    if choose_rapidocr_device("auto", cuda_provider_available=True, cuda_dependencies_ok=False) != "cpu":
        raise AssertionError("RapidOCR auto mode should use CPU when CUDA dependencies are missing.")
    if choose_rapidocr_device("cuda", cuda_provider_available=True, cuda_dependencies_ok=False) != "cpu":
        raise AssertionError("RapidOCR explicit CUDA should be blocked when dependencies are missing by default.")
    if choose_rapidocr_device("cuda", cuda_provider_available=True, cuda_dependencies_ok=False, allow_unstable_cuda=True) != "cuda":
        raise AssertionError("RapidOCR unstable CUDA override should preserve the old manual experiment path.")
    if choose_rapidocr_device("auto", cuda_provider_available=True, cuda_dependencies_ok=True) != "cuda":
        raise AssertionError("RapidOCR auto mode should use CUDA when provider and dependencies are healthy.")

    with tempfile.TemporaryDirectory(prefix="rapidocr-provider-") as tmp:
        root = Path(tmp)
        model_root = root / "models"
        import os

        old_model_root = os.environ.get("EBOOK_CONVERTER_RAPIDOCR_MODEL_DIR")
        old_device = os.environ.get("EBOOK_CONVERTER_RAPIDOCR_DEVICE")
        old_device_id = os.environ.get("EBOOK_CONVERTER_RAPIDOCR_CUDA_DEVICE_ID")
        os.environ["EBOOK_CONVERTER_RAPIDOCR_MODEL_DIR"] = str(model_root)
        os.environ["EBOOK_CONVERTER_RAPIDOCR_DEVICE"] = "cpu"
        os.environ.pop("EBOOK_CONVERTER_RAPIDOCR_CUDA_DEVICE_ID", None)
        try:
            if rapidocr_model_root_dir() != model_root.resolve():
                raise AssertionError("RapidOCR model root should follow EBOOK_CONVERTER_RAPIDOCR_MODEL_DIR")
            params = rapidocr_default_params()
            expected_cpu_params = {
                "Global.model_root_dir": str(model_root.resolve()),
                "EngineConfig.onnxruntime.use_cuda": False,
                "EngineConfig.paddle.use_cuda": False,
                "EngineConfig.torch.use_cuda": False,
            }
            if params != expected_cpu_params:
                raise AssertionError(f"CPU RapidOCR params should explicitly avoid CUDA provider fallback noise: {params}")

            os.environ["EBOOK_CONVERTER_RAPIDOCR_DEVICE"] = "cuda"
            os.environ["EBOOK_CONVERTER_RAPIDOCR_CUDA_DEVICE_ID"] = "1"
            runtime = rapidocr_runtime_info()
            if runtime.get("requested_device") != "cuda":
                raise AssertionError(f"RapidOCR runtime info should report requested CUDA: {runtime}")
            cuda_params = rapidocr_default_params()
            if runtime.get("selected_device") == "cuda":
                if cuda_params.get("EngineConfig.onnxruntime.use_cuda") is not True:
                    raise AssertionError(f"Healthy CUDA RapidOCR params should request ONNXRuntime CUDA: {cuda_params}")
                if cuda_params.get("EngineConfig.onnxruntime.cuda_ep_cfg.device_id") != 1:
                    raise AssertionError(f"CUDA RapidOCR params should preserve device id: {cuda_params}")
            elif cuda_params.get("EngineConfig.onnxruntime.use_cuda") is not False:
                raise AssertionError(f"Unhealthy CUDA should be suppressed to CPU params: runtime={runtime} params={cuda_params}")
        finally:
            if old_model_root is None:
                os.environ.pop("EBOOK_CONVERTER_RAPIDOCR_MODEL_DIR", None)
            else:
                os.environ["EBOOK_CONVERTER_RAPIDOCR_MODEL_DIR"] = old_model_root
            if old_device is None:
                os.environ.pop("EBOOK_CONVERTER_RAPIDOCR_DEVICE", None)
            else:
                os.environ["EBOOK_CONVERTER_RAPIDOCR_DEVICE"] = old_device
            if old_device_id is None:
                os.environ.pop("EBOOK_CONVERTER_RAPIDOCR_CUDA_DEVICE_ID", None)
            else:
                os.environ["EBOOK_CONVERTER_RAPIDOCR_CUDA_DEVICE_ID"] = old_device_id

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
