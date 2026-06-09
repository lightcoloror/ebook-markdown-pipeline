from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


MARKITDOWN_FORMATS = {".epub", ".docx", ".pptx", ".xlsx", ".html", ".htm", ".pdf"}


def markitdown_available() -> bool:
    try:
        from markitdown import MarkItDown  # noqa: F401
    except Exception:
        return False
    return True


def markitdown_supported_format(path: Path) -> bool:
    return path.suffix.lower() in MARKITDOWN_FORMATS


def convert_with_markitdown(source: Path) -> dict[str, Any]:
    try:
        from markitdown import MarkItDown
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("MarkItDown is not installed. Install optional dependency with: pip install markitdown") from exc

    converter = MarkItDown()
    result = converter.convert(str(source))
    markdown = str(getattr(result, "text_content", "") or "")
    if not markdown.strip():
        raise RuntimeError(f"MarkItDown returned no Markdown text for {source}")
    return {
        "markdown": markdown,
        "title": getattr(result, "title", None),
        "metadata": serialize_markitdown_value(getattr(result, "__dict__", {})),
    }


def serialize_markitdown_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool, list, dict)):
        return value
    try:
        return json.loads(json.dumps(value, default=str))
    except Exception:
        return str(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run MarkItDown conversion and write a JSON result.")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args()
    try:
        payload = convert_with_markitdown(args.source)
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
