from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "document-intelligence-blocks-v1"
POLICY = {
    "mode": "normalize_existing_sidecars_only",
    "cloud_calls": "not_performed_by_this_builder",
    "provider_use": "schema inspiration only unless explicit provider output is supplied",
    "promotion": "review block relationships before changing extraction routes",
}
KNOWN_INPUT_SCHEMAS = {
    "layout-candidates-v1": "layout_candidates",
    "table-candidates-v1": "table_candidates",
    "formula-candidates-v1": "formula_candidates",
    "document-vlm-result-v1": "document_vlm_result",
    "pdf-layout-evidence-v1": "pdf_layout_evidence",
    "ocr-blocks-v1": "ocr_blocks",
}


def load_json_or_jsonl(path: Path) -> Any:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return json.loads(text)


def write_document_intelligence_blocks_artifacts(output: Path, payload: dict[str, Any]) -> dict[str, str]:
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "document-intelligence-blocks.json"
    markdown_path = output / "document-intelligence-blocks.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    markdown_path.write_text(render_document_intelligence_blocks_markdown(payload), encoding="utf-8", newline="\n")
    return {"json": str(json_path), "markdown": str(markdown_path)}


def build_document_intelligence_blocks(sources: list[Path]) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    source_summaries: list[dict[str, Any]] = []
    for path in sources:
        payload = load_json_or_jsonl(path)
        normalized = normalize_source(path, payload)
        source_summaries.append(normalized["source"])
        blocks.extend(normalized["blocks"])
        relationships.extend(normalized["relationships"])
    summary = summarize(blocks, relationships, source_summaries)
    return {
        "schema_version": SCHEMA_VERSION,
        "policy": POLICY,
        "source_names": [path.name for path in sources],
        "summary": summary,
        "sources": source_summaries,
        "blocks": blocks,
        "relationships": relationships,
        "next_actions": next_actions(summary),
    }


def normalize_source(path: Path, payload: Any) -> dict[str, Any]:
    if isinstance(payload, list):
        return normalize_ocr_blocks(path, payload)
    if not isinstance(payload, dict):
        return empty_source(path, "unknown")
    schema = str(payload.get("schema_version") or "")
    if schema == "layout-candidates-v1":
        return normalize_layout_candidates(path, payload)
    if schema == "table-candidates-v1":
        return normalize_table_candidates(path, payload)
    if schema == "formula-candidates-v1":
        return normalize_formula_candidates(path, payload)
    if schema == "document-vlm-result-v1":
        return normalize_document_vlm(path, payload)
    if schema == "pdf-layout-evidence-v1":
        return normalize_pdf_layout_evidence(path, payload)
    return empty_source(path, schema or "unknown")


def empty_source(path: Path, schema: str) -> dict[str, Any]:
    return {"source": source_summary(path, schema, "unsupported"), "blocks": [], "relationships": []}


def source_summary(path: Path, schema: str, kind: str) -> dict[str, Any]:
    return {"name": path.name, "schema_version": schema, "kind": kind}


def normalize_layout_candidates(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    blocks = []
    for page in payload.get("pages") or []:
        page_number = page.get("page")
        for block in page.get("blocks") or page.get("layout") or []:
            if not isinstance(block, dict):
                continue
            blocks.append(block_item(path, page_number, "layout", block.get("label") or block.get("type") or "block", block))
    return {"source": source_summary(path, payload.get("schema_version"), "layout_candidates"), "blocks": blocks, "relationships": []}


def normalize_table_candidates(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    blocks = []
    relationships = []
    for page in payload.get("pages") or []:
        page_number = page.get("page")
        for table_index, table in enumerate(page.get("tables") or [], start=1):
            if not isinstance(table, dict):
                continue
            table_block = block_item(path, page_number, "table", "table", table, ordinal=table_index)
            blocks.append(table_block)
            for cell_index, cell in enumerate(table.get("cells") or [], start=1):
                if not isinstance(cell, dict):
                    continue
                cell_block = block_item(path, page_number, "table_cell", "cell", cell, ordinal=cell_index, parent_id=table_block["block_id"])
                blocks.append(cell_block)
                relationships.append({"type": "child", "from": table_block["block_id"], "to": cell_block["block_id"]})
    return {"source": source_summary(path, payload.get("schema_version"), "table_candidates"), "blocks": blocks, "relationships": relationships}


def normalize_formula_candidates(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    blocks = []
    for page in payload.get("pages") or []:
        page_number = page.get("page")
        for index, formula in enumerate(page.get("formulas") or [], start=1):
            if isinstance(formula, dict):
                blocks.append(block_item(path, page_number, "formula", "formula", formula, ordinal=index))
    return {"source": source_summary(path, payload.get("schema_version"), "formula_candidates"), "blocks": blocks, "relationships": []}


def normalize_document_vlm(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    blocks = []
    pages = payload.get("pages") if isinstance(payload.get("pages"), list) else []
    for page in pages:
        page_number = page.get("page") if isinstance(page, dict) else None
        for index, block in enumerate((page or {}).get("blocks") or [], start=1):
            if isinstance(block, dict):
                blocks.append(block_item(path, page_number, "document_vlm", block.get("label") or block.get("type") or "block", block, ordinal=index))
    if not blocks and payload.get("markdown"):
        blocks.append(block_item(path, 1, "document_vlm", "markdown", {"text": payload.get("markdown"), "confidence": payload.get("confidence")}))
    return {"source": source_summary(path, payload.get("schema_version"), "document_vlm_result"), "blocks": blocks, "relationships": []}


def normalize_pdf_layout_evidence(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    blocks = []
    for page in payload.get("pages") or []:
        if not isinstance(page, dict):
            continue
        page_number = page.get("page")
        flags = []
        for flag in ("table_like", "image_heavy", "two_column_like", "header_footer_candidate"):
            if page.get(flag):
                flags.append(flag)
        blocks.append(block_item(path, page_number, "page_diagnostic", "page", {"text": ",".join(flags), "confidence": 1.0, "flags": flags}))
    return {"source": source_summary(path, payload.get("schema_version"), "pdf_layout_evidence"), "blocks": blocks, "relationships": []}


def normalize_ocr_blocks(path: Path, payload: list[Any]) -> dict[str, Any]:
    blocks = []
    for index, item in enumerate(payload, start=1):
        if isinstance(item, dict):
            blocks.append(block_item(path, item.get("page") or item.get("page_number") or 1, "ocr", "text", item, ordinal=index))
    return {"source": source_summary(path, "ocr-blocks-v1", "ocr_blocks"), "blocks": blocks, "relationships": []}


def block_item(
    path: Path,
    page: Any,
    kind: str,
    label: str,
    raw: dict[str, Any],
    *,
    ordinal: int = 1,
    parent_id: str = "",
) -> dict[str, Any]:
    text = raw.get("text") or raw.get("markdown") or raw.get("latex") or raw.get("html") or raw.get("content") or ""
    block_id = f"{path.stem}:{kind}:{page or 0}:{ordinal}"
    return {
        "block_id": block_id,
        "source_name": path.name,
        "page": page,
        "kind": kind,
        "label": label,
        "bbox": raw.get("bbox") or raw.get("box") or raw.get("polygon") or [],
        "confidence": raw.get("confidence") or raw.get("score"),
        "text_chars": len(str(text)),
        "text_preview": str(text).strip()[:160],
        "parent_id": parent_id,
        "relationship_hints": relationship_hints(kind, raw),
    }


def relationship_hints(kind: str, raw: dict[str, Any]) -> list[str]:
    hints = []
    if raw.get("reading_order") not in {None, ""}:
        hints.append("reading_order")
    if kind in {"table", "table_cell"}:
        hints.append("table_structure")
    if kind == "formula":
        hints.append("formula_retention")
    if raw.get("source"):
        hints.append("source_ref")
    return hints


def summarize(blocks: list[dict[str, Any]], relationships: list[dict[str, Any]], sources: list[dict[str, Any]]) -> dict[str, Any]:
    kind_counts: dict[str, int] = {}
    missing_bbox = 0
    missing_confidence = 0
    for block in blocks:
        kind = str(block.get("kind") or "unknown")
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        if not block.get("bbox"):
            missing_bbox += 1
        if block.get("confidence") in {None, ""}:
            missing_confidence += 1
    return {
        "source_count": len(sources),
        "block_count": len(blocks),
        "relationship_count": len(relationships),
        "kind_counts": kind_counts,
        "missing_bbox_count": missing_bbox,
        "missing_confidence_count": missing_confidence,
        "needs_relationship_review": bool(relationships) or kind_counts.get("table", 0) > 0 or kind_counts.get("formula", 0) > 0,
    }


def next_actions(summary: dict[str, Any]) -> list[dict[str, Any]]:
    actions = [
        {
            "action": "review_document_intelligence_blocks",
            "tool": "read_artifact",
            "arguments": {"artifact_type": "document_intelligence_blocks_json"},
            "safe_default": True,
            "destructive": False,
            "why": "inspect normalized blocks and relationships before route or extraction changes",
        }
    ]
    if summary.get("needs_relationship_review"):
        actions.append(
            {
                "action": "review_block_relationships",
                "tool": "manual_review",
                "safe_default": True,
                "destructive": False,
                "why": "table/form/formula relationships need human review before promotion",
            }
        )
    return actions


def render_document_intelligence_blocks_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "# Document Intelligence Blocks",
        "",
        f"- Schema: `{payload.get('schema_version')}`",
        f"- Sources: {summary.get('source_count', 0)}",
        f"- Blocks: {summary.get('block_count', 0)}",
        f"- Relationships: {summary.get('relationship_count', 0)}",
        f"- Kinds: {summary.get('kind_counts', {})}",
        f"- Missing bbox: {summary.get('missing_bbox_count', 0)}",
        f"- Missing confidence: {summary.get('missing_confidence_count', 0)}",
        "",
        "| Kind | Label | Page | BBox | Confidence | Preview |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for block in (payload.get("blocks") or [])[:100]:
        lines.append(
            "| "
            + " | ".join(
                [
                    escape_md(str(block.get("kind") or "")),
                    escape_md(str(block.get("label") or "")),
                    str(block.get("page") or ""),
                    "yes" if block.get("bbox") else "no",
                    str(block.get("confidence") or ""),
                    escape_md(str(block.get("text_preview") or "")),
                ]
            )
            + " |"
        )
    return "\n".join(lines).rstrip() + "\n"


def escape_md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
