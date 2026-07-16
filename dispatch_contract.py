from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse


SCHEMA_VERSION = "ebook-dispatch-contract-v1"
PROJECT_DIR = Path(__file__).resolve().parent

FAILURE_CLASSES = {
    "dependency_missing": "Skip the unavailable module and use the next local fallback.",
    "service_stopped": "Do not auto-start; use a fallback or report needs_manual_start.",
    "model_not_prepared": "Do not download a model; keep the candidate disabled.",
    "timeout": "Keep the failed report and try the next bounded fallback.",
    "empty_output": "Treat empty or implausibly small output as failure.",
    "quality_gate_failed": "Preserve artifacts and require review before delivery.",
    "unsupported_input": "Re-inspect and move to the matching material route.",
    "artifact_parse_error": "Preserve raw artifacts; never fabricate normalized output.",
    "external_boundary": "Stop before upload, model download, or service start.",
}

MODULE_SPECS = (
    {"key": "pandoc_calibre", "role": "structured ebook and Office conversion", "capability": "structured_ebooks"},
    {"key": "pymupdf4llm", "role": "fast text-layer PDF Markdown", "capability": "pdf_fast_text"},
    {"key": "mineru", "role": "complex PDF recovery through fixed localhost API", "capability": "pdf_structure_recovery"},
    {"key": "marker", "role": "short layout-heavy PDF conversion", "capability": "pdf_marker_layout"},
    {"key": "docling", "role": "structured comparison and provenance", "capability": "docling_documents"},
    {"key": "markitdown", "role": "fast multi-format comparison", "capability": "markitdown_baseline"},
    {"key": "rapidocr", "role": "lightweight local image OCR", "capability": "rapidocr_fallback"},
    {"key": "pdfplumber", "role": "PDF layout/table diagnostics", "capability": "pdf_layout_diagnostics"},
    {"key": "paddleocr", "role": "scanned/photo table structure candidate", "checks": ("PaddleOCR-json.exe", "Umi PaddleOCR module", "PaddleOCR-VL wrapper")},
    {"key": "surya", "role": "OCR/layout/reading-order candidate", "checks": ("Surya wrapper",)},
    {"key": "gmft_table", "role": "text-layer PDF table candidate", "candidate": "gmft_table"},
    {"key": "table_transformer", "role": "GMFT model dependency", "candidate": "gmft_table"},
    {"key": "pdf_table", "role": "legacy heavy table comparison", "candidate": "pdf_table", "checks": ("pdf_table worker",)},
    {"key": "table_to_xlsx", "role": "scanned table to XLSX draft", "candidate": "table_to_xlsx"},
)

ROUTE_SPECS = (
    (
        "structured_ebook_or_office",
        ["epub", "office", "html", "text"],
        [("pandoc_calibre", "primary conversion"), ("markitdown", "comparison fallback"), ("docling", "structured comparison when ready")],
        ["weak headings", "missing images or tables", "all outputs fail quality checks"],
    ),
    (
        "pdf_text_layer_standard",
        ["pdf", "text_layer", "low_layout_risk"],
        [("pymupdf4llm", "primary Markdown"), ("markitdown", "shape comparison"), ("marker", "short layout fallback")],
        ["ambiguous reading order", "table or formula risk", "low text coverage"],
    ),
    (
        "pdf_complex_layout",
        ["pdf", "multi_column_or_layout_heavy"],
        [("mineru", "fixed --api-url recovery"), ("marker", "short-document fallback"), ("pymupdf4llm", "minimal local output"), ("markitdown", "last baseline")],
        ["fallback loses layout", "multi-column conflict", "formula or table evidence incomplete"],
    ),
    (
        "pdf_scanned_or_image_only",
        ["pdf", "no_or_low_text_layer", "scanned"],
        [("mineru", "OCR/layout when API ready"), ("rapidocr", "page-image local OCR"), ("marker", "short selected comparison")],
        ["low OCR volume", "uncertain page order", "handwriting/formula/table risk"],
    ),
    (
        "pdf_table_text_layer",
        ["pdf", "text_layer", "table_heavy"],
        [("pymupdf4llm", "base Markdown"), ("pdfplumber", "geometry diagnostics"), ("gmft_table", "candidate experiment"), ("pdf_table", "legacy comparison")],
        ["row/column disagreement", "merged cells", "card-layout false positive"],
    ),
    (
        "table_photo_scan_to_xlsx",
        ["image_or_scan", "excel_like_table", "xlsx_requested"],
        [("paddleocr", "future structure recognition"), ("rapidocr", "text salvage"), ("table_to_xlsx", "candidate XLSX draft")],
        ["always review XLSX", "merged/rotated cells", "formula or style fidelity"],
    ),
    (
        "formula_or_reading_order_page",
        ["pdf_or_image", "formula_or_reading_order_risk"],
        [("mineru", "structured recovery when API ready"), ("surya", "candidate enhancement"), ("rapidocr", "plain text fallback")],
        ["formula loss", "backend order conflict", "plain OCR loses semantics"],
    ),
)
