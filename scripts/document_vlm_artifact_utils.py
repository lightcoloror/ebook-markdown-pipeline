from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DOCUMENT_VLM_RESULT_SCHEMA_VERSION = "document-vlm-result-v1"


def write_document_vlm_result(
    path: Path,
    *,
    backend: str,
    source: Path,
    markdown_path: Path,
    markdown: str,
    mode: str = "markdown",
    raw_dir: Path | None = None,
    command: list[str] | None = None,
    status: str = "review",
    warnings: list[str] | None = None,
) -> Path:
    payload = document_vlm_result_payload(
        backend=backend,
        source=source,
        markdown_path=markdown_path,
        markdown=markdown,
        mode=mode,
        raw_dir=raw_dir,
        command=command,
        status=status,
        warnings=warnings,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    return path


def document_vlm_result_payload(
    *,
    backend: str,
    source: Path,
    markdown_path: Path,
    markdown: str,
    mode: str = "markdown",
    raw_dir: Path | None = None,
    command: list[str] | None = None,
    status: str = "review",
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    blocks = markdown_to_blocks(markdown)
    artifacts: list[dict[str, Any]] = [
        {"type": "markdown", "path": str(markdown_path), "label": f"{backend} Markdown"},
    ]
    if raw_dir is not None:
        artifacts.append({"type": "raw_output_dir", "path": str(raw_dir), "label": f"{backend} raw output"})
    payload: dict[str, Any] = {
        "schema_version": DOCUMENT_VLM_RESULT_SCHEMA_VERSION,
        "backend": backend,
        "status": status,
        "mode": mode,
        "input": str(source),
        "markdown": str(markdown_path),
        "pages": [
            {
                "page": 1,
                "source": str(source),
                "blocks": blocks,
            }
        ],
        "block_count": len(blocks),
        "artifacts": artifacts,
        "warnings": warnings or [],
        "promotion_use": "document-VLM review side evidence; explicit experiments only",
    }
    if command:
        payload["command"] = command
    return payload


def markdown_to_blocks(markdown: str) -> list[dict[str, Any]]:
    text = str(markdown or "").strip()
    if not text:
        return []
    return [
        {
            "type": "markdown_text",
            "text_preview": text[:1000],
            "text_char_count": len(text),
            "origin": "wrapper_markdown",
        }
    ]
