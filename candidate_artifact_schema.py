from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


CANDIDATE_ARTIFACT_SCHEMA_VERSION = "candidate-artifact-schemas-v1"


@dataclass(frozen=True)
class CandidateArtifactSchema:
    artifact_type: str
    schema_version: str
    required_top_level: tuple[str, ...]
    page_collection: str
    item_collection: str
    count_field: str
    description: str
    promotion_use: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["registry_schema_version"] = CANDIDATE_ARTIFACT_SCHEMA_VERSION
        return payload


CANDIDATE_ARTIFACT_SCHEMAS: tuple[CandidateArtifactSchema, ...] = (
    CandidateArtifactSchema(
        artifact_type="layout_candidates_json",
        schema_version="layout-candidates-v1",
        required_top_level=("schema_version", "backend", "pages"),
        page_collection="pages",
        item_collection="blocks",
        count_field="block_count",
        description="Layout block/bbox candidates from DocLayout-YOLO, Surya, Docling, MinerU, Marker, dots.mocr, MonkeyOCR, or similar backends.",
        promotion_use="review overlay and reading-order evidence only; do not silently mutate final Markdown",
    ),
    CandidateArtifactSchema(
        artifact_type="table_candidates_json",
        schema_version="table-candidates-v1",
        required_top_level=("schema_version", "backend", "pages"),
        page_collection="pages",
        item_collection="tables",
        count_field="table_count",
        description="Table candidates with cells/HTML/Markdown/bbox evidence from pdfplumber, Camelot, Tabula, pdf_table, Docling, MinerU, Marker, or VLM parsers.",
        promotion_use="compare true table preservation against card/infographic false positives before promotion",
    ),
    CandidateArtifactSchema(
        artifact_type="formula_candidates_json",
        schema_version="formula-candidates-v1",
        required_top_level=("schema_version", "backend", "pages"),
        page_collection="pages",
        item_collection="formulas",
        count_field="formula_count",
        description="Formula candidates with source page/image bbox and LaTeX/Markdown text from Pix2Text, UniMERNet, MinerU, Marker, Docling, or VLM parsers.",
        promotion_use="formula retention review side evidence; never a generic PDF parser by itself",
    ),
    CandidateArtifactSchema(
        artifact_type="document_vlm_result_json",
        schema_version="document-vlm-result-v1",
        required_top_level=("schema_version", "backend", "pages"),
        page_collection="pages",
        item_collection="blocks",
        count_field="block_count",
        description="Normalized document-VLM page result for MonkeyOCR, dots.mocr, olmOCR, PaddleOCR-VL, Qwen-VL, MinerU VLM, or similar engines.",
        promotion_use="heavy route evidence for scanned/layout-heavy/table/formula/infographic pages only",
    ),
)

_BY_ARTIFACT_TYPE = {schema.artifact_type: schema for schema in CANDIDATE_ARTIFACT_SCHEMAS}
_BY_SCHEMA_VERSION = {schema.schema_version: schema for schema in CANDIDATE_ARTIFACT_SCHEMAS}


def candidate_schema_for_artifact_type(artifact_type: str) -> CandidateArtifactSchema | None:
    return _BY_ARTIFACT_TYPE.get(str(artifact_type or ""))


def candidate_schema_for_payload(payload: dict[str, Any], artifact_type: str = "") -> CandidateArtifactSchema | None:
    schema = candidate_schema_for_artifact_type(artifact_type)
    if schema:
        return schema
    return _BY_SCHEMA_VERSION.get(str(payload.get("schema_version") or ""))


def candidate_artifact_schema_payload() -> dict[str, Any]:
    return {
        "schema_version": CANDIDATE_ARTIFACT_SCHEMA_VERSION,
        "execution_policy": "schema_only_no_model_execution",
        "remote_call_enabled": False,
        "model_install_enabled": False,
        "schemas": [schema.to_dict() for schema in CANDIDATE_ARTIFACT_SCHEMAS],
    }


def validate_candidate_artifact(payload: dict[str, Any], artifact_type: str = "") -> dict[str, Any]:
    schema = candidate_schema_for_payload(payload, artifact_type)
    errors: list[str] = []
    warnings: list[str] = []
    if schema is None:
        return {
            "ok": False,
            "artifact_type": artifact_type,
            "schema_version": payload.get("schema_version"),
            "errors": ["unknown candidate artifact schema"],
            "warnings": [],
        }
    for field in schema.required_top_level:
        if field not in payload:
            errors.append(f"missing top-level field: {field}")
    if payload.get("schema_version") != schema.schema_version:
        errors.append(f"expected schema_version={schema.schema_version}")
    pages = payload.get(schema.page_collection)
    if not isinstance(pages, list):
        errors.append(f"{schema.page_collection} must be a list")
        pages = []
    else:
        for index, page in enumerate(pages, start=1):
            if not isinstance(page, dict):
                errors.append(f"page[{index}] must be an object")
                continue
            if not any(key in page for key in {"page", "page_number", "image", "source"}):
                warnings.append(f"page[{index}] has no page/image/source locator")
            items = page.get(schema.item_collection)
            if items is not None and not isinstance(items, list):
                errors.append(f"page[{index}].{schema.item_collection} must be a list when present")
    summary = summarize_candidate_artifact(payload, schema.artifact_type)
    return {
        "ok": not errors,
        "artifact_type": schema.artifact_type,
        "schema_version": schema.schema_version,
        "errors": errors,
        "warnings": warnings,
        "summary": summary,
    }


def summarize_candidate_artifact(payload: dict[str, Any], artifact_type: str = "") -> dict[str, Any]:
    schema = candidate_schema_for_payload(payload, artifact_type)
    pages = [item for item in payload.get("pages") or [] if isinstance(item, dict)]
    block_count = count_page_items(pages, "blocks")
    table_count = count_page_items(pages, "tables")
    formula_count = count_page_items(pages, "formulas")
    artifacts = [item for item in payload.get("artifacts") or [] if isinstance(item, dict)]
    warnings = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
    return {
        "kind": artifact_type or (schema.artifact_type if schema else "candidate_json"),
        "candidate_schema_known": bool(schema),
        "schema_version": payload.get("schema_version"),
        "expected_schema_version": schema.schema_version if schema else "",
        "backend": payload.get("backend"),
        "status": payload.get("status"),
        "page_count": len(pages) or payload.get("page_count"),
        "block_count": block_count or payload.get("block_count"),
        "table_count": table_count or payload.get("table_count"),
        "formula_count": formula_count or payload.get("formula_count"),
        "artifact_count": len(artifacts),
        "warnings": [str(item) for item in warnings[:5]],
        "promotion_use": schema.promotion_use if schema else "review candidate evidence before promotion",
    }


def count_page_items(pages: list[dict[str, Any]], key: str) -> int:
    total = 0
    count_field = key[:-1] + "_count" if key.endswith("s") else f"{key}_count"
    for page in pages:
        items = page.get(key)
        if isinstance(items, list):
            total += len(items)
        total += int(page.get(count_field) or 0)
    return total
