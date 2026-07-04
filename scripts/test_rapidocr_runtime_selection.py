from __future__ import annotations

from pathlib import Path
import sys

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.ocr_providers import choose_rapidocr_device, rapidocr_default_params, rapidocr_runtime_info  # noqa: E402


def main() -> int:
    if choose_rapidocr_device("auto", cuda_provider_available=True, cuda_dependencies_ok=False) != "cpu":
        raise AssertionError("auto mode must avoid noisy CUDA fallback when dependencies are missing")
    if choose_rapidocr_device("cuda", cuda_provider_available=True, cuda_dependencies_ok=False) != "cpu":
        raise AssertionError("explicit CUDA must be blocked by default when dependencies are missing")
    if choose_rapidocr_device("cuda", cuda_provider_available=True, cuda_dependencies_ok=False, allow_unstable_cuda=True) != "cuda":
        raise AssertionError("unstable override should preserve manual CUDA experiments")
    if choose_rapidocr_device("auto", cuda_provider_available=True, cuda_dependencies_ok=True) != "cuda":
        raise AssertionError("auto mode should use CUDA when provider and dependencies are healthy")
    if choose_rapidocr_device("cpu", cuda_provider_available=True, cuda_dependencies_ok=True) != "cpu":
        raise AssertionError("explicit CPU must stay CPU")

    runtime = rapidocr_runtime_info()
    if runtime.get("requested_device") not in {"auto", "cuda", "cpu"}:
        raise AssertionError(f"unexpected requested_device: {runtime}")
    if runtime.get("selected_device") not in {"cuda", "cpu"}:
        raise AssertionError(f"unexpected selected_device: {runtime}")
    params = rapidocr_default_params()
    if runtime.get("selected_device") == "cpu" and params.get("EngineConfig.onnxruntime.use_cuda") is not False:
        raise AssertionError(f"CPU selection must explicitly disable ONNXRuntime CUDA: {params}")
    print("RapidOCR runtime selection test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
