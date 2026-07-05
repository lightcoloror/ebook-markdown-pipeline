from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "academic-evidence-v1"
POLICY = {
    "mode": "side_evidence_only_no_default_route_change",
    "grobid": "consume_existing_json_or_explicit_inspect_only",
    "formulas": "review_retention_evidence_only",
    "remote_calls": "not_performed_by_this_artifact_builder",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_academic_evidence_artifacts(output: Path, payload: dict[str, Any]) -> dict[str, str]:
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "academic-evidence.json"
    markdown_path = output / "academic-evidence.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    markdown_path.write_text(render_academic_evidence_markdown(payload), encoding="utf-8", newline="\n")
    return {"json": str(json_path), "markdown": str(markdown_path)}


def build_academic_evidence(sources: list[Path]) -> dict[str, Any]:
    payloads = [(path, load_json(path)) for path in sources]
    grobid_items = [normalize_grobid_payload(path, payload) for path, payload in payloads if looks_like_grobid(payload)]
    formula_items = [normalize_formula_payload(path, payload) for path, payload in payloads if payload.get("schema_version") == "formula-candidates-v1"]
    bundle_items = [normalize_review_bundle(path, payload) for path, payload in payloads if payload.get("schema_version") == "layout-table-review-bundle-v1"]
    summary = summarize_academic_evidence(grobid_items, formula_items, bundle_items)
    return {
        "schema_version": SCHEMA_VERSION,
        "policy": POLICY,
        "source_names": [path.name for path, _ in payloads],
        "summary": summary,
        "grobid_evidence": grobid_items,
        "formula_evidence": formula_items,
        "review_bundle_evidence": bundle_items,
        "next_actions": next_actions(summary),
    }


def looks_like_grobid(payload: dict[str, Any]) -> bool:
    if payload.get("tool") == "grobid":
        return True
    grobid = payload.get("grobid")
    return isinstance(grobid, dict) and grobid.get("tool") == "grobid"


def normalize_grobid_payload(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("grobid") if isinstance(payload.get("grobid"), dict) else payload
    return {
        "source_name": path.name,
        "status": value.get("status"),
        "title": value.get("title") or "",
        "authors": value.get("authors") or [],
        "author_count": int(value.get("author_count") or len(value.get("authors") or [])),
        "doi": value.get("doi") or "",
        "year": value.get("year") or "",
        "abstract_chars": len(value.get("abstract_sample") or ""),
        "reference_count": int(value.get("reference_count") or 0),
        "section_heading_count": len(value.get("section_headings") or []),
        "section_headings_preview": (value.get("section_headings") or [])[:12],
        "tei_chars": int(value.get("tei_chars") or 0),
        "promotion_use": "academic metadata/reference side evidence only; do not replace Markdown conversion route",
    }


def normalize_formula_payload(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    pages = [item for item in payload.get("pages") or [] if isinstance(item, dict)]
    formulas = []
    for page in pages:
        page_number = page.get("page")
        for formula in page.get("formulas") or []:
            if isinstance(formula, dict):
                formulas.append({"page": page_number, **formula})
    return {
        "source_name": path.name,
        "backend": payload.get("backend") or payload.get("tool") or "",
        "status": payload.get("status"),
        "page_count": len(pages),
        "formula_count": len(formulas),
        "latex_count": sum(1 for item in formulas if item.get("latex") or item.get("formula") or item.get("markdown")),
        "bbox_count": sum(1 for item in formulas if item.get("bbox")),
        "confidence_count": sum(1 for item in formulas if item.get("confidence") not in {None, ""}),
        "source_ref_count": sum(1 for item in formulas if item.get("source")),
        "needs_formula_retention_review": bool(formulas),
    }


def normalize_review_bundle(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return {
        "source_name": path.name,
        "formula_review_matrix_count": int(summary.get("formula_review_matrix_count") or len(payload.get("formula_review_matrix") or [])),
        "formula_count": int(summary.get("formula_count") or 0),
        "promotion_review_count": int(summary.get("promotion_review_count") or len(payload.get("promotion_reviews") or [])),
        "next_action_count": len(payload.get("next_actions") or []),
    }


def summarize_academic_evidence(
    grobid_items: list[dict[str, Any]],
    formula_items: list[dict[str, Any]],
    bundle_items: list[dict[str, Any]],
) -> dict[str, Any]:
    formula_count = sum(int(item.get("formula_count") or 0) for item in formula_items)
    reference_count = sum(int(item.get("reference_count") or 0) for item in grobid_items)
    missing_formula_bbox = sum(max(int(item.get("formula_count") or 0) - int(item.get("bbox_count") or 0), 0) for item in formula_items)
    missing_formula_latex = sum(max(int(item.get("formula_count") or 0) - int(item.get("latex_count") or 0), 0) for item in formula_items)
    return {
        "grobid_source_count": len(grobid_items),
        "academic_title_count": sum(1 for item in grobid_items if item.get("title")),
        "doi_count": sum(1 for item in grobid_items if item.get("doi")),
        "reference_count": reference_count,
        "formula_source_count": len(formula_items),
        "formula_count": formula_count,
        "formula_missing_bbox_count": missing_formula_bbox,
        "formula_missing_latex_count": missing_formula_latex,
        "review_bundle_count": len(bundle_items),
        "needs_academic_review": bool(grobid_items or formula_items or bundle_items),
        "needs_formula_retention_review": formula_count > 0,
        "needs_grobid_followup": bool(grobid_items) and any(item.get("status") != "ok" for item in grobid_items),
    }


def next_actions(summary: dict[str, Any]) -> list[dict[str, Any]]:
    actions = []
    if summary.get("needs_grobid_followup"):
        actions.append(
            {
                "action": "inspect_grobid_status",
                "tool": "read_artifact",
                "safe_default": True,
                "destructive": False,
                "why": "GROBID evidence exists but did not report ok status",
            }
        )
    if summary.get("needs_formula_retention_review"):
        actions.append(
            {
                "action": "review_formula_retention",
                "tool": "read_artifact",
                "arguments": {"artifact_type": "formula_candidates_json"},
                "safe_default": True,
                "destructive": False,
                "why": "formula candidates should be reviewed before accepting Markdown as formula-complete",
            }
        )
    actions.append(
        {
            "action": "keep_academic_evidence_sidecar",
            "tool": "manual_review",
            "safe_default": True,
            "destructive": False,
            "why": "academic evidence is sidecar metadata and does not change the default PDF route",
        }
    )
    return actions


def render_academic_evidence_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "# Academic Evidence",
        "",
        f"- Schema: `{payload.get('schema_version')}`",
        f"- Sources: {', '.join(payload.get('source_names') or [])}",
        f"- GROBID sources: {summary.get('grobid_source_count', 0)}",
        f"- Titles: {summary.get('academic_title_count', 0)}",
        f"- DOI count: {summary.get('doi_count', 0)}",
        f"- References: {summary.get('reference_count', 0)}",
        f"- Formula sources: {summary.get('formula_source_count', 0)}",
        f"- Formulas: {summary.get('formula_count', 0)}",
        f"- Needs formula retention review: {summary.get('needs_formula_retention_review', False)}",
        "",
        "## GROBID Evidence",
        "",
    ]
    for item in payload.get("grobid_evidence") or []:
        lines.append(f"- `{item.get('source_name')}` {item.get('status')}: {item.get('title') or '(no title)'}; refs={item.get('reference_count', 0)}")
    if not payload.get("grobid_evidence"):
        lines.append("- (none)")
    lines.extend(["", "## Formula Evidence", ""])
    for item in payload.get("formula_evidence") or []:
        lines.append(f"- `{item.get('source_name')}` formulas={item.get('formula_count', 0)} latex={item.get('latex_count', 0)} bbox={item.get('bbox_count', 0)}")
    if not payload.get("formula_evidence"):
        lines.append("- (none)")
    return "\n".join(lines).rstrip() + "\n"
