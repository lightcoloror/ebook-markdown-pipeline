from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path
from typing import Any


DOCLING_FORMATS = {".docx", ".pptx", ".xlsx", ".html", ".htm", ".md", ".csv"}


def docling_available() -> bool:
    try:
        suppress_requests_dependency_warning()
        from docling.document_converter import DocumentConverter  # noqa: F401
    except Exception:
        return False
    return True


def docling_supported_format(path: Path) -> bool:
    return path.suffix.lower() in DOCLING_FORMATS or path.suffix.lower() == ".pdf"


def convert_with_docling(source: Path) -> dict[str, Any]:
    try:
        suppress_requests_dependency_warning()
        from docling.document_converter import DocumentConverter
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Docling is not installed. Install optional dependency with: pip install docling") from exc

    converter = DocumentConverter()
    result = converter.convert(str(source))
    document = getattr(result, "document", None)
    if document is None:
        raise RuntimeError(f"Docling returned no document for {source}")

    markdown = document.export_to_markdown()
    return {
        "markdown": markdown,
        "status": str(getattr(result, "status", "")),
        "errors": serialize_docling_errors(getattr(result, "errors", [])),
        "timings": serialize_docling_value(getattr(result, "timings", None)),
    }


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
