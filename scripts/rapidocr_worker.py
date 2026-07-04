from __future__ import annotations

import contextlib
import json
import os
import site
import sys
import traceback
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.ocr_providers import describe_raw_shape, normalize_rapidocr_blocks  # noqa: E402


def preload_nvidia_dll_dirs() -> list[str]:
    loaded: list[str] = []
    roots: list[Path] = []
    for raw in site.getsitepackages():
        roots.append(Path(raw) / "nvidia")
    user_site = site.getusersitepackages()
    if user_site:
        roots.append(Path(user_site) / "nvidia")
    explicit = os.environ.get("EBOOK_CONVERTER_RAPIDOCR_NVIDIA_ROOT", "").strip()
    if explicit:
        roots.append(Path(explicit).expanduser())
    for root in roots:
        if not root.exists():
            continue
        for bin_dir in root.rglob("bin"):
            try:
                os.add_dll_directory(str(bin_dir))
            except Exception:
                pass
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
            loaded.append(str(bin_dir))
    return loaded


def rapidocr_params() -> dict[str, Any]:
    model_root = os.environ.get("EBOOK_CONVERTER_RAPIDOCR_MODEL_DIR", "").strip()
    if not model_root:
        model_root = str(PROJECT_DIR / ".tmp" / "rapidocr-models")
    device = os.environ.get("EBOOK_CONVERTER_RAPIDOCR_DEVICE", "auto").strip().lower()
    use_cuda = device in {"auto", "cuda", "gpu"}
    params: dict[str, Any] = {"Global.model_root_dir": model_root}
    params["EngineConfig.onnxruntime.use_cuda"] = bool(use_cuda)
    params["EngineConfig.paddle.use_cuda"] = bool(use_cuda)
    params["EngineConfig.torch.use_cuda"] = bool(use_cuda)
    if use_cuda:
        raw_id = os.environ.get("EBOOK_CONVERTER_RAPIDOCR_CUDA_DEVICE_ID", "0").strip()
        try:
            device_id = max(0, int(raw_id))
        except ValueError:
            device_id = 0
        params["EngineConfig.onnxruntime.cuda_ep_cfg.device_id"] = device_id
        params["EngineConfig.paddle.cuda_ep_cfg.device_id"] = device_id
        params["EngineConfig.torch.cuda_ep_cfg.device_id"] = device_id
    return params


def build_engine():
    preload_nvidia_dll_dirs()
    from rapidocr import RapidOCR  # type: ignore

    with contextlib.redirect_stdout(sys.stderr):
        return RapidOCR(params=rapidocr_params())


def run_image(engine: Any, image: str) -> dict[str, Any]:
    with contextlib.redirect_stdout(sys.stderr):
        raw = engine(str(image))
    blocks = normalize_rapidocr_blocks(raw)
    return {
        "schema_version": "ocr-blocks-v1",
        "provider": "rapidocr",
        "provider_runtime": "external-worker",
        "source": str(image),
        "text": "\n".join(block["text"] for block in blocks if block.get("text")).strip(),
        "blocks": blocks,
        "raw_shape": describe_raw_shape(raw),
    }


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def main() -> int:
    try:
        engine = build_engine()
        emit({"ok": True, "event": "ready"})
    except Exception as exc:
        emit({"ok": False, "event": "init", "error": str(exc), "traceback": traceback.format_exc()})
        return 2

    for line in sys.stdin:
        try:
            request = json.loads(line)
            if request.get("command") == "shutdown":
                emit({"ok": True, "event": "shutdown"})
                return 0
            image = request.get("image")
            if not image:
                emit({"ok": False, "error": "missing image"})
                continue
            emit({"ok": True, "result": run_image(engine, str(image))})
        except Exception as exc:
            emit({"ok": False, "error": str(exc), "traceback": traceback.format_exc()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
