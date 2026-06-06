from __future__ import annotations

from pathlib import Path
from typing import Any


PDF_PIPELINES = {"auto", "fast", "pymupdf4llm", "mineru", "marker", "umi", "docling"}
PIPELINE_TEXT_ALIASES = [
    ("pymupdf4llm", "pymupdf4llm"),
    ("pymupdf", "pymupdf4llm"),
    ("mineru", "mineru"),
    ("marker", "marker"),
    ("umi-ocr", "umi"),
    ("umi_ocr", "umi"),
    ("umi ocr", "umi"),
    ("umi", "umi"),
    ("docling", "docling"),
]


def recommended_action_for_plan(plan: Any) -> str:
    output = Path(str(getattr(plan, "output", "") or ""))
    if output.exists():
        return "跳过或续跑 / Skip or Resume"
    detected_format = str(getattr(plan, "detected_format", "") or "").upper()
    pipeline = str(getattr(plan, "pipeline", "") or "").lower()
    if detected_format == "PDF" and "mineru" in pipeline:
        return "直接转换，长任务 / Convert, long task"
    return "直接转换 / Convert"


def normalize_pdf_pipeline(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    if normalized == "umi-ocr":
        return "umi"
    if normalized == "pymupdf":
        return "pymupdf4llm"
    return normalized if normalized in PDF_PIPELINES else ""


def pipeline_from_suggestion_text(value: str) -> str:
    text = str(value or "").lower()
    if "compare" in text or "对比" in text:
        return "auto"
    for needle, pipeline in PIPELINE_TEXT_ALIASES:
        if needle in text:
            return pipeline
    return ""
