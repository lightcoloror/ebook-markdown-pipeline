from __future__ import annotations

import importlib.util
import importlib.metadata as importlib_metadata
import contextlib
import io
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any


OCR_BLOCK_SCHEMA_VERSION = "ocr-blocks-v1"
RAPIDOCR_PACKAGES = ("rapidocr_onnxruntime", "rapidocr")
PIX2TEXT_PACKAGE = "pix2text"
CNOCR_PACKAGE = "cnocr"
PROJECT_DIR = Path(__file__).resolve().parent


def rapidocr_available() -> bool:
    return bool(rapidocr_external_python()) or any(importlib.util.find_spec(name) is not None for name in RAPIDOCR_PACKAGES)


def rapidocr_package_name() -> str:
    external = rapidocr_external_python()
    if external:
        return f"external:{external}"
    for name in RAPIDOCR_PACKAGES:
        if importlib.util.find_spec(name) is not None:
            return name
    return ""


def rapidocr_external_python() -> str:
    value = os.environ.get("EBOOK_CONVERTER_RAPIDOCR_PYTHON", "").strip().strip('\"')
    if not value:
        return ""
    path = Path(value).expanduser()
    if not path.exists():
        return ""
    try:
        if path.resolve() == Path(sys.executable).resolve():
            return ""
    except OSError:
        pass
    return str(path)


def pix2text_available() -> bool:
    return importlib.util.find_spec(PIX2TEXT_PACKAGE) is not None


def cnocr_available() -> bool:
    return importlib.util.find_spec(CNOCR_PACKAGE) is not None


def create_rapidocr_engine():
    external_python = rapidocr_external_python()
    if external_python:
        return ExternalRapidOCREngine(external_python)
    params = rapidocr_default_params()
    package_name = rapidocr_package_name()
    if package_name == "rapidocr_onnxruntime":
        from rapidocr_onnxruntime import RapidOCR  # type: ignore

        try:
            return RapidOCR(params=params)
        except TypeError:
            return RapidOCR()
    if package_name == "rapidocr":
        from rapidocr import RapidOCR  # type: ignore

        try:
            return RapidOCR(params=params)
        except TypeError:
            return RapidOCR()
    raise FileNotFoundError("RapidOCR is not installed. Install rapidocr_onnxruntime or rapidocr to enable this provider.")


class ExternalRapidOCREngine:
    def __init__(self, python_executable: str):
        self.python_executable = python_executable
        self.process: subprocess.Popen[str] | None = None
        self.stdout_lines: queue.Queue[str] = queue.Queue(maxsize=200)
        self.stderr_tail: queue.Queue[str] = queue.Queue(maxsize=200)
        self.timeout_seconds = rapidocr_worker_timeout_seconds()

    def __call__(self, image_path: str):
        process = self._ensure_process()
        request = json.dumps({"image": str(image_path)}, ensure_ascii=False)
        if process.stdin is None or process.stdout is None:
            raise RuntimeError("External RapidOCR worker is not connected.")
        process.stdin.write(request + "\n")
        process.stdin.flush()
        while True:
            response = self._read_json_payload(process, context="ocr")
            if not response.get("ok"):
                raise RuntimeError(f"External RapidOCR worker failed: {response.get('error')}; stderr_tail={self._stderr_tail()}")
            if response.get("event"):
                continue
            return response.get("result") or {}

    def close(self) -> None:
        process = self.process
        self.process = None
        if not process:
            return
        try:
            if process.stdin:
                process.stdin.write(json.dumps({"command": "shutdown"}) + "\n")
                process.stdin.flush()
        except Exception:
            pass
        try:
            process.terminate()
        except Exception:
            pass

    def _ensure_process(self) -> subprocess.Popen[str]:
        if self.process and self.process.poll() is None:
            return self.process
        worker = PROJECT_DIR / "scripts" / "rapidocr_worker.py"
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("EBOOK_CONVERTER_RAPIDOCR_MODEL_DIR", str(rapidocr_model_root_dir()))
        env.setdefault("EBOOK_CONVERTER_RAPIDOCR_DEVICE", rapidocr_requested_device())
        process = subprocess.Popen(
            [self.python_executable, str(worker)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        self.process = process
        if process.stdout is not None:
            threading.Thread(target=self._drain_stdout, args=(process.stdout,), daemon=True).start()
        if process.stderr is not None:
            threading.Thread(target=self._drain_stderr, args=(process.stderr,), daemon=True).start()
        self._wait_until_ready(process)
        return process

    def _wait_until_ready(self, process: subprocess.Popen[str]) -> None:
        while True:
            payload = self._read_json_payload(process, context="init")
            if payload.get("event") == "ready" and payload.get("ok"):
                return
            if not payload.get("ok"):
                raise RuntimeError(f"External RapidOCR worker init failed: {payload.get('error')}; stderr_tail={self._stderr_tail()}")

    def _read_json_payload(self, process: subprocess.Popen[str], *, context: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            remaining = max(0.1, deadline - time.monotonic())
            if remaining <= 0.1 and time.monotonic() >= deadline:
                raise RuntimeError(f"External RapidOCR worker {context} timed out after {self.timeout_seconds:.1f}s. stderr_tail={self._stderr_tail()}")
            try:
                line = self.stdout_lines.get(timeout=remaining)
            except queue.Empty as exc:
                if process.poll() is not None:
                    raise RuntimeError(f"External RapidOCR worker exited during {context} with code {process.returncode}. stderr_tail={self._stderr_tail()}") from exc
                raise RuntimeError(f"External RapidOCR worker {context} timed out after {self.timeout_seconds:.1f}s. stderr_tail={self._stderr_tail()}") from exc
            line = line.strip()
            if not line:
                continue
            if not line.startswith("{"):
                self._push_stderr_tail(f"stdout-noise: {line}")
                continue
            return json.loads(line)

    def _drain_stdout(self, stream) -> None:
        for line in stream:
            self._push_stdout_line(line.rstrip())

    def _drain_stderr(self, stream) -> None:
        for line in stream:
            self._push_stderr_tail(line.rstrip())

    def _push_stdout_line(self, line: str) -> None:
        if self.stdout_lines.full():
            try:
                self.stdout_lines.get_nowait()
            except queue.Empty:
                pass
        self.stdout_lines.put_nowait(line)

    def _push_stderr_tail(self, line: str) -> None:
        if not line:
            return
        if self.stderr_tail.full():
            try:
                self.stderr_tail.get_nowait()
            except queue.Empty:
                pass
        self.stderr_tail.put_nowait(line)

    def _stderr_tail(self) -> list[str]:
        return list(self.stderr_tail.queue)[-20:]

    def __del__(self):
        self.close()


def create_cnocr_engine():
    if not cnocr_available():
        raise FileNotFoundError("CnOCR is not installed. Install cnocr to enable this provider.")
    from cnocr import CnOcr  # type: ignore

    kwargs = cnocr_default_params()
    if not kwargs:
        return CnOcr()
    try:
        return CnOcr(**kwargs)
    except TypeError:
        # CnOCR's constructor changed across releases. Env-driven tuning is
        # best-effort; a default engine is safer than failing health/comparison.
        return CnOcr()


def cnocr_default_params() -> dict[str, Any]:
    params: dict[str, Any] = {}
    rec_model_name = os.environ.get("EBOOK_CONVERTER_CNOCR_REC_MODEL_NAME", "").strip()
    det_model_name = os.environ.get("EBOOK_CONVERTER_CNOCR_DET_MODEL_NAME", "").strip()
    context = os.environ.get("EBOOK_CONVERTER_CNOCR_CONTEXT", "").strip()
    if rec_model_name:
        params["rec_model_name"] = rec_model_name
    if det_model_name:
        params["det_model_name"] = det_model_name
    if context:
        params["context"] = context
    return params


def rapidocr_model_root_dir() -> Path:
    explicit = os.environ.get("EBOOK_CONVERTER_RAPIDOCR_MODEL_DIR", "").strip()
    path = Path(explicit).expanduser() if explicit else PROJECT_DIR / ".tmp" / "rapidocr-models"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def rapidocr_default_params() -> dict[str, Any]:
    params: dict[str, Any] = {"Global.model_root_dir": str(rapidocr_model_root_dir())}
    device = rapidocr_selected_device()
    if device == "cuda":
        params["EngineConfig.onnxruntime.use_cuda"] = True
        params["EngineConfig.paddle.use_cuda"] = True
        params["EngineConfig.torch.use_cuda"] = True
        params["EngineConfig.onnxruntime.cuda_ep_cfg.device_id"] = rapidocr_cuda_device_id()
        params["EngineConfig.paddle.cuda_ep_cfg.device_id"] = rapidocr_cuda_device_id()
        params["EngineConfig.torch.cuda_ep_cfg.device_id"] = rapidocr_cuda_device_id()
    elif device == "cpu":
        params["EngineConfig.onnxruntime.use_cuda"] = False
        params["EngineConfig.paddle.use_cuda"] = False
        params["EngineConfig.torch.use_cuda"] = False
    return params


def rapidocr_requested_device() -> str:
    value = os.environ.get("EBOOK_CONVERTER_RAPIDOCR_DEVICE", "").strip().lower()
    if value in {"cuda", "gpu"}:
        return "cuda"
    if value in {"cpu", "off"}:
        return "cpu"
    return "auto"


def rapidocr_cuda_device_id() -> int:
    raw = os.environ.get("EBOOK_CONVERTER_RAPIDOCR_CUDA_DEVICE_ID", "0").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def rapidocr_allow_unstable_cuda() -> bool:
    value = os.environ.get("EBOOK_CONVERTER_RAPIDOCR_ALLOW_UNSTABLE_CUDA", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def rapidocr_worker_timeout_seconds() -> float:
    raw = os.environ.get("EBOOK_CONVERTER_RAPIDOCR_WORKER_TIMEOUT", "180").strip()
    try:
        return max(5.0, float(raw))
    except ValueError:
        return 180.0


def rapidocr_selected_device() -> str:
    info = rapidocr_runtime_info()
    return str(info.get("selected_device") or "cpu")


def choose_rapidocr_device(
    requested_device: str,
    *,
    cuda_provider_available: bool,
    cuda_dependencies_ok: bool,
    allow_unstable_cuda: bool = False,
) -> str:
    requested_device = requested_device if requested_device in {"auto", "cuda", "cpu"} else "auto"
    if requested_device == "cpu":
        return "cpu"
    if cuda_provider_available and (cuda_dependencies_ok or allow_unstable_cuda):
        return "cuda"
    return "cpu"


def onnxruntime_debug_info_text() -> str:
    try:
        import onnxruntime as ort  # type: ignore

        if not hasattr(ort, "print_debug_info"):
            return ""
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            ort.print_debug_info()
        return f"{stdout.getvalue()}\n{stderr.getvalue()}".strip()
    except Exception as exc:
        return f"onnxruntime debug info unavailable: {exc}"


def package_version(name: str) -> str:
    try:
        return importlib_metadata.version(name)
    except importlib_metadata.PackageNotFoundError:
        return ""
    except Exception:
        return ""


def parse_onnxruntime_cuda_build_version(debug_text: str) -> str:
    match = re.search(r"CUDA version used in build:\s*([0-9]+(?:\.[0-9]+)?)", debug_text or "")
    return match.group(1) if match else ""


def find_dll_on_path(name: str) -> str:
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        try:
            candidate = Path(entry) / name
            if candidate.exists():
                return str(candidate)
        except OSError:
            continue
    return ""


def cuda_dependency_probe(available_providers: list[str], debug_text: str) -> dict[str, Any]:
    if "CUDAExecutionProvider" not in available_providers:
        return {
            "status": "unavailable",
            "cuda_build_version": "",
            "required_dlls": [],
            "missing_dlls": [],
            "detail": "CUDAExecutionProvider is not listed by onnxruntime.",
        }

    cuda_build_version = parse_onnxruntime_cuda_build_version(debug_text)
    cuda_major = cuda_build_version.split(".", 1)[0] if cuda_build_version else ""
    if not cuda_major:
        return {
            "status": "unknown",
            "cuda_build_version": "",
            "required_dlls": [],
            "missing_dlls": [],
            "detail": "Could not determine the CUDA version used by the installed onnxruntime-gpu build.",
        }

    required_dlls = [f"cublasLt64_{cuda_major}.dll"]
    if cuda_major in {"12", "13"}:
        required_dlls.append("cudnn64_9.dll")

    found_dlls = {dll: find_dll_on_path(dll) for dll in required_dlls}
    missing_dlls = [dll for dll, dll_path in found_dlls.items() if not dll_path]
    nvidia_packages = {
        f"nvidia-cublas-cu{cuda_major}": package_version(f"nvidia-cublas-cu{cuda_major}"),
        f"nvidia-cudnn-cu{cuda_major}": package_version(f"nvidia-cudnn-cu{cuda_major}"),
    }
    missing_packages = [name for name, version in nvidia_packages.items() if not version]
    package_backed = not missing_packages

    if not missing_dlls or package_backed:
        status = "ok"
        detail = f"ONNX Runtime GPU build targets CUDA {cuda_build_version}; required DLLs are available via PATH or NVIDIA Python wheels."
    else:
        status = "missing_dependencies"
        detail = (
            f"ONNX Runtime GPU build targets CUDA {cuda_build_version}, but required runtime files are missing: "
            f"{', '.join(missing_dlls)}."
        )
    return {
        "status": status,
        "cuda_build_version": cuda_build_version,
        "required_dlls": required_dlls,
        "found_dlls": found_dlls,
        "missing_dlls": missing_dlls,
        "nvidia_packages": nvidia_packages,
        "missing_nvidia_packages": missing_packages,
        "detail": detail,
    }


def rapidocr_runtime_info() -> dict[str, Any]:
    available_providers: list[str] = []
    onnxruntime_version = ""
    debug_text = ""
    try:
        import onnxruntime as ort  # type: ignore

        onnxruntime_version = str(getattr(ort, "__version__", ""))
        available_providers = [str(provider) for provider in ort.get_available_providers()]
        debug_text = onnxruntime_debug_info_text()
    except Exception:
        pass
    requested_device = rapidocr_requested_device()
    external_python = rapidocr_external_python()
    dependency_probe = cuda_dependency_probe(available_providers, debug_text)
    allow_unstable = rapidocr_allow_unstable_cuda()
    selected_device = choose_rapidocr_device(
        requested_device,
        cuda_provider_available="CUDAExecutionProvider" in available_providers,
        cuda_dependencies_ok=dependency_probe.get("status") == "ok",
        allow_unstable_cuda=allow_unstable,
    )
    cuda_unusable = "CUDAExecutionProvider" in available_providers and dependency_probe.get("status") != "ok"
    final_selected_device = requested_device if external_python and requested_device != "auto" else selected_device
    external_mode = bool(external_python)
    recommended_action = ""
    if cuda_unusable and not external_mode:
        build = dependency_probe.get("cuda_build_version") or "unknown"
        missing = ", ".join(dependency_probe.get("missing_dlls") or dependency_probe.get("missing_nvidia_packages") or [])
        recommended_action = (
            f"RapidOCR is using CPU because onnxruntime-gpu {onnxruntime_version or 'unknown'} targets CUDA {build} "
            f"and required dependencies are missing ({missing or dependency_probe.get('status')}). "
            "Install the matching CUDA/cuDNN runtime or downgrade onnxruntime-gpu to a CUDA stack that matches this machine. "
            "Set EBOOK_CONVERTER_RAPIDOCR_ALLOW_UNSTABLE_CUDA=1 only for manual experiments."
        )
    return {
        "package": rapidocr_package_name(),
        "execution_mode": "external" if external_python else "in_process",
        "external_python": external_python,
        "worker_timeout_seconds": rapidocr_worker_timeout_seconds() if external_python else 0,
        "requested_device": requested_device,
        "selected_device": final_selected_device,
        "cuda_device_id": rapidocr_cuda_device_id(),
        "python_executable": sys.executable,
        "onnxruntime_version": onnxruntime_version,
        "onnxruntime_cpu_package_version": package_version("onnxruntime"),
        "onnxruntime_gpu_package_version": package_version("onnxruntime-gpu"),
        "multiple_onnxruntime_packages": bool(package_version("onnxruntime") and package_version("onnxruntime-gpu")),
        "available_providers": available_providers,
        "cuda_provider_available": "CUDAExecutionProvider" in available_providers,
        "cuda_dependency_status": dependency_probe.get("status"),
        "cuda_build_version": dependency_probe.get("cuda_build_version", ""),
        "cuda_dependency_detail": dependency_probe.get("detail", ""),
        "missing_cuda_dependencies": dependency_probe.get("missing_dlls", []),
        "missing_nvidia_cuda_packages": dependency_probe.get("missing_nvidia_packages", []),
        "cuda_requested_but_unavailable": requested_device == "cuda" and final_selected_device != "cuda",
        "cuda_provider_fallback_suppressed": (not external_mode) and selected_device == "cpu" and cuda_unusable,
        "allow_unstable_cuda": allow_unstable,
        "recommended_action": recommended_action,
    }


def recognize_image_with_rapidocr(image_path: Path, engine=None) -> dict[str, Any]:
    ocr_engine = engine or create_rapidocr_engine()
    raw = ocr_engine(str(image_path))
    blocks = normalize_rapidocr_blocks(raw)
    result = {
        "schema_version": OCR_BLOCK_SCHEMA_VERSION,
        "provider": "rapidocr",
        "source": str(image_path),
        "text": "\n".join(block["text"] for block in blocks if block.get("text")).strip(),
        "blocks": blocks,
        "raw_shape": describe_raw_shape(raw),
    }
    if isinstance(raw, dict) and raw.get("provider_runtime"):
        result["provider_runtime"] = str(raw.get("provider_runtime"))
    return result


def recognize_image_with_cnocr(image_path: Path, engine=None) -> dict[str, Any]:
    ocr_engine = engine or create_cnocr_engine()
    raw = run_cnocr_engine(ocr_engine, image_path)
    blocks = normalize_cnocr_blocks(raw)
    return {
        "schema_version": OCR_BLOCK_SCHEMA_VERSION,
        "provider": "cnocr",
        "source": str(image_path),
        "text": "\n".join(block["text"] for block in blocks if block.get("text")).strip(),
        "blocks": blocks,
        "raw_shape": describe_raw_shape(raw),
    }


def run_cnocr_engine(engine: Any, image_path: Path) -> Any:
    try:
        return engine.ocr(str(image_path))
    except TypeError:
        return engine.ocr(img_fp=str(image_path))


def normalize_rapidocr_blocks(raw: Any) -> list[dict[str, Any]]:
    items = extract_rapidocr_items(raw)
    blocks = []
    for index, item in enumerate(items, start=1):
        block = normalize_rapidocr_item(item, index=index)
        if block:
            blocks.append(block)
    return blocks


def normalize_cnocr_blocks(raw: Any) -> list[dict[str, Any]]:
    items = extract_cnocr_items(raw)
    blocks = []
    for index, item in enumerate(items, start=1):
        block = normalize_cnocr_item(item, index=index)
        if block:
            blocks.append(block)
    return blocks


def extract_cnocr_items(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, tuple):
        return extract_cnocr_items(raw[0])
    if isinstance(raw, dict):
        for key in ("results", "result", "data", "blocks", "lines"):
            value = raw.get(key)
            if isinstance(value, list):
                return value
        if {"text", "score"}.issubset(raw) or {"text", "position"}.issubset(raw):
            return [raw]
    if hasattr(raw, "to_dict"):
        try:
            return extract_cnocr_items(raw.to_dict())
        except Exception:
            pass
    if isinstance(raw, list):
        return raw
    return []


def normalize_cnocr_item(item: Any, *, index: int) -> dict[str, Any] | None:
    text = ""
    score = None
    bbox = None
    if isinstance(item, dict):
        text = str(item.get("text") or item.get("txt") or item.get("content") or "").strip()
        score = item.get("score") or item.get("confidence") or item.get("prob")
        bbox = normalize_ocr_box(item.get("position") or item.get("bbox") or item.get("box") or item.get("points"))
    elif isinstance(item, (list, tuple)):
        if len(item) >= 1:
            text = str(item[0] or "").strip()
        if len(item) >= 2:
            score = item[1]
        if len(item) >= 3:
            bbox = normalize_ocr_box(item[2])
    else:
        text = str(item or "").strip()
    if not text:
        return None
    block: dict[str, Any] = {
        "index": index,
        "text": text,
        "provider": "cnocr",
    }
    normalized_score = normalize_score(score)
    if normalized_score is not None:
        block["score"] = normalized_score
    if bbox:
        block["bbox"] = bbox
    return block


def extract_rapidocr_items(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, tuple):
        return extract_rapidocr_items(raw[0])
    if isinstance(raw, dict):
        for key in ("results", "result", "data", "blocks"):
            value = raw.get(key)
            if isinstance(value, list):
                return value
        if {"boxes", "txts"}.issubset(raw):
            return rows_from_parallel_values(raw.get("boxes"), raw.get("txts"), raw.get("scores"))
    if hasattr(raw, "to_dict"):
        try:
            return extract_rapidocr_items(raw.to_dict())
        except Exception:
            pass
    if all(hasattr(raw, name) for name in ("boxes", "txts")):
        return rows_from_parallel_values(getattr(raw, "boxes"), getattr(raw, "txts"), getattr(raw, "scores", None))
    if isinstance(raw, list):
        return raw
    return []


def rows_from_parallel_values(boxes: Any, texts: Any, scores: Any = None) -> list[Any]:
    boxes_list = list(optional_sequence(boxes))
    texts_list = list(optional_sequence(texts))
    scores_list = list(optional_sequence(scores))
    rows = []
    for index, text in enumerate(texts_list):
        rows.append(
            [
                boxes_list[index] if index < len(boxes_list) else None,
                text,
                scores_list[index] if index < len(scores_list) else None,
            ]
        )
    return rows


def optional_sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        try:
            value = value.tolist()
        except Exception:
            pass
    return list(value)


def normalize_rapidocr_item(item: Any, *, index: int) -> dict[str, Any] | None:
    text = ""
    score = None
    bbox = None
    if isinstance(item, dict):
        text = str(item.get("text") or item.get("txt") or item.get("content") or "").strip()
        score = item.get("score") or item.get("confidence") or item.get("prob")
        bbox = normalize_ocr_box(item.get("bbox") or item.get("box") or item.get("points"))
    elif isinstance(item, (list, tuple)):
        if len(item) >= 2:
            bbox = normalize_ocr_box(item[0])
            text = str(item[1] or "").strip()
        if len(item) >= 3:
            score = item[2]
    else:
        text = str(item or "").strip()
    if not text:
        return None
    block: dict[str, Any] = {
        "index": index,
        "text": text,
        "provider": "rapidocr",
    }
    normalized_score = normalize_score(score)
    if normalized_score is not None:
        block["score"] = normalized_score
    if bbox:
        block["bbox"] = bbox
    return block


def normalize_score(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 4)
    except Exception:
        return None


def normalize_ocr_box(raw_box: Any) -> list[float] | None:
    if raw_box is None:
        return None
    try:
        if hasattr(raw_box, "tolist"):
            raw_box = raw_box.tolist()
        if not raw_box:
            return None
        if isinstance(raw_box, dict):
            values = [raw_box.get(key) for key in ("x1", "y1", "x2", "y2")]
            if all(value is not None for value in values):
                return [round(float(value), 2) for value in values]
        if len(raw_box) == 4 and all(isinstance(value, (int, float)) for value in raw_box):
            x1, y1, x2, y2 = [float(value) for value in raw_box]
            return [round(min(x1, x2), 2), round(min(y1, y2), 2), round(max(x1, x2), 2), round(max(y1, y2), 2)]
        points = []
        for point in raw_box:
            if isinstance(point, dict):
                points.append((float(point.get("x")), float(point.get("y"))))
            elif len(point) >= 2:
                points.append((float(point[0]), float(point[1])))
        if not points:
            return None
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        return [round(min(xs), 2), round(min(ys), 2), round(max(xs), 2), round(max(ys), 2)]
    except Exception:
        return None


def describe_raw_shape(raw: Any) -> str:
    if raw is None:
        return "none"
    if isinstance(raw, tuple):
        return f"tuple[{len(raw)}]"
    if isinstance(raw, list):
        return f"list[{len(raw)}]"
    if isinstance(raw, dict):
        return "dict[" + ",".join(sorted(str(key) for key in raw.keys())[:8]) + "]"
    return type(raw).__name__
