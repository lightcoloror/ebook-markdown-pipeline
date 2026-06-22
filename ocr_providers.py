from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any


OCR_BLOCK_SCHEMA_VERSION = "ocr-blocks-v1"
RAPIDOCR_PACKAGES = ("rapidocr_onnxruntime", "rapidocr")
PIX2TEXT_PACKAGE = "pix2text"
CNOCR_PACKAGE = "cnocr"
PROJECT_DIR = Path(__file__).resolve().parent


def rapidocr_available() -> bool:
    return any(importlib.util.find_spec(name) is not None for name in RAPIDOCR_PACKAGES)


def rapidocr_package_name() -> str:
    for name in RAPIDOCR_PACKAGES:
        if importlib.util.find_spec(name) is not None:
            return name
    return ""


def pix2text_available() -> bool:
    return importlib.util.find_spec(PIX2TEXT_PACKAGE) is not None


def cnocr_available() -> bool:
    return importlib.util.find_spec(CNOCR_PACKAGE) is not None


def create_rapidocr_engine():
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
    return {"Global.model_root_dir": str(rapidocr_model_root_dir())}


def recognize_image_with_rapidocr(image_path: Path, engine=None) -> dict[str, Any]:
    ocr_engine = engine or create_rapidocr_engine()
    raw = ocr_engine(str(image_path))
    blocks = normalize_rapidocr_blocks(raw)
    return {
        "schema_version": OCR_BLOCK_SCHEMA_VERSION,
        "provider": "rapidocr",
        "source": str(image_path),
        "text": "\n".join(block["text"] for block in blocks if block.get("text")).strip(),
        "blocks": blocks,
        "raw_shape": describe_raw_shape(raw),
    }


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
