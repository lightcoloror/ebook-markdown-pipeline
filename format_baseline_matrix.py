from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "format-baseline-matrix-v1"
POLICY = {
    "mode": "consume_existing_reports_only",
    "conversion": "not_performed_by_this_builder",
    "tika": "inspect_only_side_evidence",
    "promotion": "compare_baselines_before_route_change",
}
BASELINE_FAMILIES = {
    "pandoc": "structured_external_converter",
    "docling": "structured_document_object",
    "markitdown": "fast_llm_friendly_markdown_baseline",
    "tika": "metadata_text_sample_inspect_only",
    "mammoth": "docx_style_map_reference",
    "kreuzberg": "clean_extract_api_reference",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_format_baseline_matrix_artifacts(output: Path, payload: dict[str, Any]) -> dict[str, str]:
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "format-baseline-matrix.json"
    markdown_path = output / "format-baseline-matrix.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    markdown_path.write_text(render_format_baseline_matrix_markdown(payload), encoding="utf-8", newline="\n")
    return {"json": str(json_path), "markdown": str(markdown_path)}


def build_format_baseline_matrix(sources: list[Path]) -> dict[str, Any]:
    rows = [row_from_report(path, load_json(path)) for path in sources]
    rows.sort(key=lambda item: (item.get("source_name") or "", item.get("baseline") or ""))
    summary = summarize_rows(rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "policy": POLICY,
        "baseline_families": BASELINE_FAMILIES,
        "source_names": [path.name for path in sources],
        "summary": summary,
        "rows": rows,
        "next_actions": next_actions(summary),
    }


def row_from_report(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    pipeline = str(payload.get("pipeline") or payload.get("actual_pipeline") or payload.get("document_pipeline_mode") or "")
    baseline = infer_baseline(payload, pipeline, path.name)
    quality = payload.get("quality") if isinstance(payload.get("quality"), dict) else {}
    tika = payload.get("tika") if isinstance(payload.get("tika"), dict) else {}
    structure = payload.get("structure_repair") if isinstance(payload.get("structure_repair"), dict) else {}
    return {
        "report_name": path.name,
        "source_name": Path(str(payload.get("source") or "")).name,
        "output_name": Path(str(payload.get("output") or "")).name,
        "baseline": baseline,
        "baseline_family": BASELINE_FAMILIES.get(baseline, "conversion_report"),
        "status": payload.get("status"),
        "pipeline": pipeline,
        "detected_format": payload.get("detected_format"),
        "duration_seconds": payload.get("duration_seconds"),
        "output_exists": bool(payload.get("output_exists")),
        "output_size_bytes": int(payload.get("output_size_bytes") or 0),
        "quality_level": quality.get("level"),
        "quality_score": quality.get("score"),
        "heading_count": int(quality.get("headings") or 0),
        "characters": int(quality.get("characters") or 0),
        "short_line_ratio": float(quality.get("short_line_ratio") or 0),
        "page_number_lines": int(quality.get("page_number_lines") or 0),
        "table_like_lines": int(quality.get("table_like_lines") or 0),
        "structure_decision_count": int(structure.get("decision_count") or 0),
        "tika_status": tika.get("status") or "",
        "tika_detected_mime": tika.get("detected_mime") or "",
        "tika_text_chars": int(tika.get("text_chars") or 0),
        "risks": row_risks(quality, tika, baseline),
    }


def infer_baseline(payload: dict[str, Any], pipeline: str, name: str) -> str:
    text = " ".join(
        [
            pipeline,
            str(payload.get("message") or ""),
            str(payload.get("tool") or ""),
            name,
        ]
    ).lower()
    for baseline in ("markitdown", "docling", "pandoc", "tika", "mammoth", "kreuzberg"):
        if baseline in text:
            return baseline
    return "unknown"


def row_risks(quality: dict[str, Any], tika: dict[str, Any], baseline: str) -> list[str]:
    risks = []
    level = str(quality.get("level") or "")
    if level in {"review", "poor", "failed"}:
        risks.append(f"quality_{level}")
    if int(quality.get("headings") or 0) == 0:
        risks.append("missing_headings")
    if float(quality.get("short_line_ratio") or 0) >= 0.35:
        risks.append("ocr_or_linebreak_noise")
    if int(quality.get("table_like_lines") or 0) > 0:
        risks.append("table_shape_needs_review")
    if baseline == "tika" and tika:
        risks.append("inspect_only_not_markdown_route")
    return risks


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    baseline_counts: dict[str, int] = {}
    risk_counts: dict[str, int] = {}
    quality_counts: dict[str, int] = {}
    for row in rows:
        baseline = str(row.get("baseline") or "unknown")
        baseline_counts[baseline] = baseline_counts.get(baseline, 0) + 1
        level = str(row.get("quality_level") or row.get("status") or "unknown")
        quality_counts[level] = quality_counts.get(level, 0) + 1
        for risk in row.get("risks") or []:
            risk_counts[risk] = risk_counts.get(risk, 0) + 1
    best = best_available_baseline(rows)
    return {
        "row_count": len(rows),
        "baseline_counts": baseline_counts,
        "quality_counts": quality_counts,
        "risk_counts": risk_counts,
        "best_available_baseline": best,
        "needs_human_compare": len(rows) > 1 or bool(risk_counts),
        "tika_inspect_rows": baseline_counts.get("tika", 0),
    }


def best_available_baseline(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    scored = sorted(rows, key=row_rank)
    best = scored[0]
    return {
        "baseline": best.get("baseline"),
        "report_name": best.get("report_name"),
        "quality_level": best.get("quality_level"),
        "quality_score": best.get("quality_score"),
        "heading_count": best.get("heading_count"),
        "risks": best.get("risks") or [],
    }


def row_rank(row: dict[str, Any]) -> tuple[int, int, int, str]:
    level_rank = {"good": 0, "ok": 1, "review": 2, "poor": 3, "failed": 4}
    return (
        level_rank.get(str(row.get("quality_level") or row.get("status") or ""), 5),
        -int(row.get("quality_score") or 0),
        len(row.get("risks") or []),
        str(row.get("baseline") or ""),
    )


def next_actions(summary: dict[str, Any]) -> list[dict[str, Any]]:
    actions = [
        {
            "action": "review_format_baseline_matrix",
            "tool": "read_artifact",
            "arguments": {"artifact_type": "format_baseline_matrix_json"},
            "safe_default": True,
            "destructive": False,
            "why": "compare existing conversion/inspect reports before changing routing",
        }
    ]
    if summary.get("tika_inspect_rows"):
        actions.append(
            {
                "action": "keep_tika_inspect_only",
                "tool": "manual_review",
                "safe_default": True,
                "destructive": False,
                "why": "Tika metadata/text evidence should not become final Markdown by itself",
            }
        )
    if summary.get("needs_human_compare"):
        actions.append(
            {
                "action": "compare_docling_markitdown_pandoc_outputs",
                "tool": "manual_review",
                "safe_default": True,
                "destructive": False,
                "why": "route promotion needs side-by-side structure and quality evidence",
            }
        )
    return actions


def render_format_baseline_matrix_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "# Format Baseline Matrix",
        "",
        f"- Schema: `{payload.get('schema_version')}`",
        f"- Rows: {summary.get('row_count', 0)}",
        f"- Baselines: {summary.get('baseline_counts', {})}",
        f"- Risks: {summary.get('risk_counts', {})}",
        f"- Best available baseline: `{(summary.get('best_available_baseline') or {}).get('baseline', '')}`",
        "",
        "| Baseline | Status | Quality | Score | Headings | Chars | Risks | Report |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload.get("rows") or []:
        lines.append(
            "| "
            + " | ".join(
                [
                    escape_md(str(row.get("baseline") or "")),
                    escape_md(str(row.get("status") or "")),
                    escape_md(str(row.get("quality_level") or "")),
                    str(row.get("quality_score") or ""),
                    str(row.get("heading_count") or 0),
                    str(row.get("characters") or 0),
                    escape_md(", ".join(row.get("risks") or [])),
                    escape_md(str(row.get("report_name") or "")),
                ]
            )
            + " |"
        )
    return "\n".join(lines).rstrip() + "\n"


def escape_md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
