from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path
from typing import Any


DOCLING_FORMATS = {".docx", ".pptx", ".xlsx", ".html", ".htm", ".md", ".csv"}


def docling_health() -> dict[str, str]:
    try:
        suppress_requests_dependency_warning()
        from docling.document_converter import DocumentConverter  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        detail = " ".join(str(exc).split())
        return {"status": "missing", "detail": f"{type(exc).__name__}: {detail}"}
    return {"status": "ok", "detail": "importable"}


def docling_available() -> bool:
    return docling_health()["status"] == "ok"


def docling_supported_format(path: Path) -> bool:
    return path.suffix.lower() in DOCLING_FORMATS or path.suffix.lower() == ".pdf"


def convert_with_docling(source: Path) -> dict[str, Any]:
    try:
        suppress_requests_dependency_warning()
        from docling.document_converter import DocumentConverter
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Docling is not available: {type(exc).__name__}: {exc}") from exc

    converter = DocumentConverter()
    result = converter.convert(str(source))
    document = getattr(result, "document", None)
    if document is None:
        raise RuntimeError(f"Docling returned no document for {source}")

    markdown = document.export_to_markdown()
    return {
        "markdown": markdown,
        "heading_candidates": extract_docling_heading_candidates(document),
        "status": str(getattr(result, "status", "")),
        "errors": serialize_docling_errors(getattr(result, "errors", [])),
        "timings": serialize_docling_value(getattr(result, "timings", None)),
    }


def extract_docling_heading_candidates(document: Any) -> list[dict[str, Any]]:
    """Best-effort extraction of Docling section headers for structure repair.

    Docling's public document model can expose headings through Pydantic
    objects, dict exports, or lightweight item objects depending on version.
    Keep this adapter permissive so the main pipeline can reuse Docling without
    pinning itself to one internal representation.
    """
    payload = serialize_docling_value(document)
    if not isinstance(payload, dict):
        return []
    texts = payload.get("texts") or []
    candidates: list[dict[str, Any]] = []
    for item in texts:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("type") or item.get("name") or "").lower()
        if "section" not in label and "heading" not in label and "title" not in label:
            continue
        title = str(item.get("text") or item.get("orig") or item.get("content") or "").strip()
        if not title:
            continue
        level = item.get("level") or item.get("heading_level")
        candidates.append(
            {
                "title": title,
                "level": int(level) if str(level or "").isdigit() else None,
                "source": "docling_heading",
                "page": docling_page_number(item),
                "bbox": docling_bbox(item),
                "score": 0.86,
                "reason": f"Docling text item label={label or 'unknown'}",
            }
        )
    return candidates


def docling_page_number(item: dict[str, Any]) -> int | None:
    provenance = item.get("prov") or item.get("provenance") or []
    if isinstance(provenance, list) and provenance:
        first = provenance[0]
        if isinstance(first, dict):
            page = first.get("page_no") or first.get("page") or first.get("page_number")
            return int(page) if str(page or "").isdigit() else None
    page = item.get("page_no") or item.get("page") or item.get("page_number")
    return int(page) if str(page or "").isdigit() else None


def docling_bbox(item: dict[str, Any]) -> list[float] | None:
    provenance = item.get("prov") or item.get("provenance") or []
    bbox = None
    if isinstance(provenance, list) and provenance and isinstance(provenance[0], dict):
        bbox = provenance[0].get("bbox")
    bbox = bbox or item.get("bbox")
    if isinstance(bbox, dict):
        values = [bbox.get(key) for key in ("l", "t", "r", "b")]
        if all(value is not None for value in values):
            return [float(value) for value in values]
        values = [bbox.get(key) for key in ("left", "top", "right", "bottom")]
        if all(value is not None for value in values):
            return [float(value) for value in values]
    if isinstance(bbox, list) and len(bbox) >= 4:
        return [float(value) for value in bbox[:4]]
    return None


def suppress_requests_dependency_warning() -> None:
    warnings.filterwarnings(
        "ignore",
        message=r"urllib3 .* doesn't match a supported version!",
        category=Warning,
        module=r"requests",
    )


def serialize_docling_errors(errors: Any) -> list[str]:
    if not errors:
        return []
    if isinstance(errors, list):
        return [str(item) for item in errors]
    return [str(errors)]


def serialize_docling_value(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, (str, int, float, bool, list, dict)):
        return value
    try:
        return json.loads(json.dumps(value, default=str))
    except Exception:
        return str(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Docling conversion and write a JSON result.")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args()
    try:
        payload = convert_with_docling(args.source)
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps({"ok": True, "result": payload}, ensure_ascii=False), encoding="utf-8")
        return 0
    except Exception as exc:  # noqa: BLE001
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps({"ok": False, "error": str(exc), "error_type": type(exc).__name__}, ensure_ascii=False),
            encoding="utf-8",
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
