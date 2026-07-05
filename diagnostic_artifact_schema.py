from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


DIAGNOSTIC_ARTIFACT_SCHEMA_VERSION = "diagnostic-artifact-schemas-v1"


@dataclass(frozen=True)
class DiagnosticArtifactSchema:
    artifact_type: str
    schema_version: str
    description: str
    promotion_use: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["registry_schema_version"] = DIAGNOSTIC_ARTIFACT_SCHEMA_VERSION
        return payload


DIAGNOSTIC_ARTIFACT_SCHEMAS: tuple[DiagnosticArtifactSchema, ...] = (
    DiagnosticArtifactSchema(
        artifact_type="pdf_metadata_json",
        schema_version="pypdf-diagnostics-v1",
        description="pypdf metadata/page-count diagnostics for lightweight PDF utility evidence.",
        promotion_use="metadata/outline side evidence only; not Markdown conversion",
    ),
    DiagnosticArtifactSchema(
        artifact_type="pdf_outline_json",
        schema_version="pypdf-outline-v1",
        description="pypdf outline/bookmark diagnostics for structure review side evidence.",
        promotion_use="outline comparison side evidence; prefer existing PDF conversion routes for Markdown",
    ),
    DiagnosticArtifactSchema(
        artifact_type="pdf_layout_evidence_json",
        schema_version="pdf-layout-evidence-v1",
        description="Lightweight PDF text/layout evidence for page text density, line counts, table/layout flags, and backend diagnostics.",
        promotion_use="route/debug side evidence for text-layer and layout-heavy PDFs; not final Markdown conversion",
    ),
    DiagnosticArtifactSchema(
        artifact_type="ocr_blocks_jsonl",
        schema_version="ocr-blocks-v1",
        description="Provider-normalized OCR block JSONL rows with text, bbox/confidence, image/page, provider, and status.",
        promotion_use="OCR provider comparison evidence; never route changes without scorecard evidence",
    ),
)

_BY_ARTIFACT_TYPE = {schema.artifact_type: schema for schema in DIAGNOSTIC_ARTIFACT_SCHEMAS}


def diagnostic_schema_for_artifact_type(artifact_type: str) -> DiagnosticArtifactSchema | None:
    return _BY_ARTIFACT_TYPE.get(str(artifact_type or ""))


def diagnostic_artifact_schema_payload() -> dict[str, Any]:
    return {
        "schema_version": DIAGNOSTIC_ARTIFACT_SCHEMA_VERSION,
        "execution_policy": "schema_only_no_model_execution",
        "remote_call_enabled": False,
        "model_install_enabled": False,
        "schemas": [schema.to_dict() for schema in DIAGNOSTIC_ARTIFACT_SCHEMAS],
    }


def summarize_diagnostic_json(payload: dict[str, Any], artifact_type: str) -> dict[str, Any]:
    schema = diagnostic_schema_for_artifact_type(artifact_type)
    if artifact_type == "pdf_metadata_json":
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        return {
            "kind": "pdf_metadata",
            "schema_version": payload.get("schema_version"),
            "expected_schema_version": schema.schema_version if schema else "",
            "schema_valid": payload.get("schema_version") == (schema.schema_version if schema else payload.get("schema_version")),
            "backend": payload.get("backend"),
            "page_count": payload.get("page_count"),
            "metadata_keys": sorted(str(key) for key in metadata),
            "promotion_use": schema.promotion_use if schema else "diagnostic side evidence",
        }
    if artifact_type == "pdf_outline_json":
        items = [item for item in payload.get("items") or [] if isinstance(item, dict)]
        return {
            "kind": "pdf_outline",
            "schema_version": payload.get("schema_version"),
            "expected_schema_version": schema.schema_version if schema else "",
            "schema_valid": payload.get("schema_version") == (schema.schema_version if schema else payload.get("schema_version")),
            "backend": payload.get("backend"),
            "outline_count": len(items),
            "preview": items[:8],
            "promotion_use": schema.promotion_use if schema else "diagnostic side evidence",
        }
    if artifact_type == "pdf_layout_evidence_json":
        pages = [item for item in payload.get("pages") or [] if isinstance(item, dict)]
        text_char_count = int(payload.get("text_char_count") or sum(int(page.get("text_chars") or 0) for page in pages))
        line_count = int(payload.get("line_count") or sum(int(page.get("line_count") or 0) for page in pages))
        table_count = int(payload.get("table_count") or sum(int(page.get("table_count") or 0) for page in pages))
        image_count = int(payload.get("image_count") or sum(int(page.get("image_count") or 0) for page in pages))
        rect_count = int(payload.get("rect_count") or sum(int(page.get("rect_count") or 0) for page in pages))
        curve_count = int(payload.get("curve_count") or sum(int(page.get("curve_count") or 0) for page in pages))
        flags = payload.get("flags") if isinstance(payload.get("flags"), dict) else {}
        return {
            "kind": "pdf_layout_evidence",
            "schema_version": payload.get("schema_version"),
            "expected_schema_version": schema.schema_version if schema else "",
            "schema_valid": payload.get("schema_version") == (schema.schema_version if schema else payload.get("schema_version")),
            "backend": payload.get("backend"),
            "page_count": len(pages) or payload.get("page_count"),
            "text_char_count": text_char_count,
            "line_count": line_count,
            "table_count": table_count,
            "image_count": image_count,
            "rect_count": rect_count,
            "curve_count": curve_count,
            "avg_chars_per_page": round(text_char_count / len(pages), 2) if pages else None,
            "flags": flags,
            "preview": pages[:5],
            "promotion_use": schema.promotion_use if schema else "PDF layout/text evidence",
        }
    return {}


def summarize_ocr_blocks_jsonl(records: list[dict[str, Any]], *, artifact_type: str = "ocr_blocks_jsonl") -> dict[str, Any]:
    schema = diagnostic_schema_for_artifact_type(artifact_type)
    providers: set[str] = set()
    statuses: dict[str, int] = {}
    block_count = 0
    bbox_count = 0
    text_chars = 0
    for record in records:
        provider = str(record.get("provider") or "")
        if provider:
            providers.add(provider)
        status = str(record.get("status") or "ok")
        statuses[status] = statuses.get(status, 0) + 1
        blocks = record.get("blocks") if isinstance(record.get("blocks"), list) else []
        block_count += len(blocks)
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("bbox") or block.get("box") or block.get("position"):
                bbox_count += 1
            text_chars += len(str(block.get("text") or ""))
    return {
        "kind": "ocr_blocks_jsonl",
        "schema_version": schema.schema_version if schema else "ocr-blocks-v1",
        "record_count": len(records),
        "providers": sorted(providers),
        "status_counts": statuses,
        "block_count": block_count,
        "bbox_count": bbox_count,
        "text_char_count": text_chars,
        "promotion_use": schema.promotion_use if schema else "OCR provider comparison evidence",
    }
