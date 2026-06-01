from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline import default_options, normalize_command_options  # noqa: E402
from ebook_markdown_pipeline.batch_convert_books import (  # noqa: E402
    PDF_FORMATS,
    SUPPORTED_FORMATS,
    analyze_markdown_quality,
    detect_source_kind,
    inspect_pdf_preflight,
    selected_pdf_pipeline_label,
)
from ebook_markdown_pipeline.document_locator import IMAGE_EXTENSIONS  # noqa: E402


SAMPLE_SCHEMA_VERSION = "benchmark-samples-v1"
RUN_SCHEMA_VERSION = "benchmark-run-v1"
PDF_COMPARE_SCHEMA_VERSION = "pdf-pipeline-compare-v1"
AGENT_STRESS_SCHEMA_VERSION = "agent-stress-v1"


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def load_samples(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    samples = payload.get("samples", payload if isinstance(payload, list) else [])
    if not isinstance(samples, list):
        raise ValueError(f"Invalid sample manifest: {path}")
    return samples


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_id(value: str) -> str:
    value = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", value, flags=re.UNICODE).strip("-._")
    return value[:80] or "sample"


def classify_sample(path: Path) -> str:
    if path.is_dir():
        image_count = len([item for item in path.iterdir() if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS])
        return "image_set" if image_count else "directory"
    suffix = path.suffix.lower()
    if suffix in PDF_FORMATS:
        try:
            options = normalize_command_options(default_options())
            preflight = inspect_pdf_preflight(path, options, sample_pages=6)
            if preflight.scanned_likely:
                return "scanned_pdf"
            if preflight.complex_layout_likely:
                return "complex_pdf"
        except Exception:
            pass
        return "pdf"
    if suffix in {".epub", ".azw", ".azw3", ".mobi", ".fb2"}:
        return "ebook"
    if suffix in {".docx", ".pptx", ".xlsx", ".html", ".htm", ".md", ".csv"}:
        return "docling_doc"
    if suffix in {".txt", ".rtf", ".odt"}:
        return "text_doc"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    return "unknown"


def recommendation_for(path: Path) -> str:
    kind = detect_source_kind(path) if path.is_file() else "directory"
    if kind == "pdf":
        try:
            options = normalize_command_options(default_options())
            return selected_pdf_pipeline_label(path, options)
        except Exception as exc:  # noqa: BLE001
            return f"pdf_preflight_failed: {exc}"
    if kind != "unsupported":
        return kind
    if path.is_dir():
        return "image_book_or_location_index"
    return "unsupported"


def markdown_metrics(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    quality = analyze_markdown_quality(path)
    if not quality:
        return {}
    return {
        "score": quality.score,
        "level": quality.level,
        "headings": quality.headings,
        "page_headings": quality.page_headings,
        "characters": quality.characters,
        "nonempty_lines": quality.nonempty_lines,
        "page_number_lines": quality.page_number_lines,
        "short_line_ratio": quality.short_line_ratio,
        "reasons": quality.reasons,
        "table_like_lines": count_table_like_lines(path),
    }


def count_table_like_lines(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return 0
    return sum(1 for line in text.splitlines() if line.count("|") >= 2 or "\t" in line)
