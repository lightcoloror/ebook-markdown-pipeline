from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.diagnostic_artifact_schema import (  # noqa: E402
    DIAGNOSTIC_ARTIFACT_SCHEMA_VERSION,
    diagnostic_artifact_schema_payload,
    summarize_diagnostic_json,
    summarize_ocr_blocks_jsonl,
)


def main() -> int:
    payload = diagnostic_artifact_schema_payload()
    if payload.get("schema_version") != DIAGNOSTIC_ARTIFACT_SCHEMA_VERSION:
        raise AssertionError(f"Unexpected diagnostic schema payload: {payload}")
    if payload.get("remote_call_enabled") or payload.get("model_install_enabled"):
        raise AssertionError(f"Diagnostic schema registry must be non-executing: {payload}")
    types = {item.get("artifact_type") for item in payload.get("schemas") or []}
    expected = {"pdf_metadata_json", "pdf_outline_json", "pdf_layout_evidence_json", "ocr_blocks_jsonl"}
    if not expected.issubset(types):
        raise AssertionError(f"Expected diagnostic artifact schemas: {payload}")

    metadata = summarize_diagnostic_json(
        {"schema_version": "pypdf-diagnostics-v1", "backend": "pypdf", "page_count": 2, "metadata": {"Title": "A"}},
        "pdf_metadata_json",
    )
    if metadata.get("schema_valid") is not True or metadata.get("page_count") != 2 or metadata.get("metadata_keys") != ["Title"]:
        raise AssertionError(f"Expected metadata summary: {metadata}")
    outline = summarize_diagnostic_json(
        {"schema_version": "pypdf-outline-v1", "backend": "pypdf", "items": [{"title": "Intro", "level": 1}]},
        "pdf_outline_json",
    )
    if outline.get("schema_valid") is not True or outline.get("outline_count") != 1:
        raise AssertionError(f"Expected outline summary: {outline}")
    layout = summarize_diagnostic_json(
        {
            "schema_version": "pdf-layout-evidence-v1",
            "backend": "pdfminer_six",
            "pages": [{"page": 1, "text_chars": 120, "line_count": 4}],
            "flags": {"text_layer_present": True},
        },
        "pdf_layout_evidence_json",
    )
    if layout.get("schema_valid") is not True or layout.get("text_char_count") != 120 or layout.get("page_count") != 1:
        raise AssertionError(f"Expected layout evidence summary: {layout}")
    blocks = summarize_ocr_blocks_jsonl(
        [
            {
                "schema_version": "ocr-blocks-v1",
                "provider": "tesseract",
                "status": "ok",
                "blocks": [{"text": "hello", "bbox": [1, 2, 3, 4]}],
            }
        ]
    )
    if blocks.get("block_count") != 1 or blocks.get("bbox_count") != 1 or blocks.get("providers") != ["tesseract"]:
        raise AssertionError(f"Expected OCR block summary: {blocks}")
    print("Diagnostic artifact schema contract test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
