from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "quality-improvement-queue-v1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a review/poor quality improvement queue from benchmark results.")
    parser.add_argument("--benchmark-results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-paths", action="store_true", help="Include full local source/output/report paths in the queue.")
    args = parser.parse_args()

    payload = build_quality_improvement_queue(load_json(args.benchmark_results), include_paths=args.include_paths)
    args.output.mkdir(parents=True, exist_ok=True)
    write_json(args.output / "quality-improvement-queue.json", payload)
    (args.output / "quality-improvement-queue.md").write_text(render_markdown(payload), encoding="utf-8", newline="\n")
    print(json.dumps({"status": "ok", "queue": str(args.output / "quality-improvement-queue.json"), "count": payload["summary"]["count"]}, ensure_ascii=False))
    return 0


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


def build_quality_improvement_queue(payload: dict[str, Any], *, include_paths: bool = False) -> dict[str, Any]:
    items = []
    for result in payload.get("results") or []:
        metrics = result.get("metrics") or {}
        level = str(metrics.get("level") or result.get("status") or "")
        if level not in {"review", "poor", "failed"}:
            continue
        item = queue_item(result, include_paths=include_paths)
        items.append(item)
    items.sort(key=queue_sort_key)
    categories: dict[str, int] = {}
    levels: dict[str, int] = {}
    for item in items:
        levels[item["quality_level"]] = levels.get(item["quality_level"], 0) + 1
        for category in item["issue_categories"]:
            categories[category] = categories.get(category, 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "source_schema_version": payload.get("schema_version"),
        "benchmark": {
            "created_at": payload.get("created_at"),
            "manifest": payload.get("manifest") if include_paths else Path(str(payload.get("manifest") or "")).name,
            "output": payload.get("output") if include_paths else Path(str(payload.get("output") or "")).name,
        },
        "summary": {
            "count": len(items),
            "quality_levels": levels,
            "issue_categories": categories,
        },
        "items": items,
    }


def queue_item(result: dict[str, Any], *, include_paths: bool) -> dict[str, Any]:
    metrics = result.get("metrics") or {}
    conversion = first_dict(result.get("conversion_results") or [])
    source = str(result.get("source") or conversion.get("source") or "")
    output = str(result.get("output") or conversion.get("output") or "")
    report = str(conversion.get("report") or "")
    reasons = [str(item) for item in metrics.get("reasons") or []]
    categories = classify_issue_categories(metrics, reasons)
    item = {
        "id": str(result.get("id") or Path(source).stem or "sample"),
        "category": str(result.get("category") or "unknown"),
        "quality_level": str(metrics.get("level") or result.get("status") or "unknown"),
        "quality_score": metrics.get("score"),
        "issue_categories": categories,
        "recommended_focus": recommended_focus(categories),
        "reasons": reasons,
        "metrics": {
            "headings": metrics.get("headings"),
            "page_headings": metrics.get("page_headings"),
            "characters": metrics.get("characters"),
            "short_line_ratio": metrics.get("short_line_ratio"),
            "page_number_lines": metrics.get("page_number_lines"),
            "table_like_lines": metrics.get("table_like_lines"),
        },
        "source_name": Path(source).name,
        "output_name": Path(output).name,
        "next_step": recommended_next_step(categories, str(result.get("category") or "")),
    }
    if include_paths:
        item.update({"source": source, "output": output, "report": report})
    return item


def first_dict(values: list[Any]) -> dict[str, Any]:
    return values[0] if values and isinstance(values[0], dict) else {}


def classify_issue_categories(metrics: dict[str, Any], reasons: list[str]) -> list[str]:
    text = " ".join(reasons).lower()
    categories: list[str] = []
    if int(metrics.get("headings") or 0) == 0 or "markdown 标题" in text or "章节层级" in text or "heading" in text:
        categories.append("weak_heading_structure")
    if "ocr" in text or "短行" in text or "断行" in text or "乱码" in text or float(metrics.get("short_line_ratio") or 0) >= 0.35:
        categories.append("ocr_noise_or_linebreaks")
    if "html" in text or "目录" in text or "toc" in text:
        categories.append("html_or_toc_residue")
    if "页码" in text or int(metrics.get("page_number_lines") or 0) > 0:
        categories.append("page_number_noise")
    if int(metrics.get("table_like_lines") or 0) > 0 or "表格" in text or "table" in text:
        categories.append("table_or_layout_review")
    if not categories:
        categories.append("manual_review_unknown")
    return categories


def recommended_focus(categories: list[str]) -> str:
    if "weak_heading_structure" in categories:
        return "structure_repair"
    if "ocr_noise_or_linebreaks" in categories:
        return "ocr_cleanup"
    if "html_or_toc_residue" in categories:
        return "markdown_cleanup"
    if "table_or_layout_review" in categories:
        return "table_layout_review"
    return "manual_review"


def recommended_next_step(categories: list[str], category: str) -> str:
    if "weak_heading_structure" in categories and category in {"scanned_pdf", "complex_pdf", "pdf"}:
        return "Run page-range PDF pipeline comparison or safe structure enhancement; do not overwrite existing Markdown."
    if "weak_heading_structure" in categories:
        return "Run local structure enhancement and inspect TOC/body heading alignment."
    if "ocr_noise_or_linebreaks" in categories:
        return "Inspect OCR source pages and tune OCR cleanup before changing default backends."
    if "html_or_toc_residue" in categories:
        return "Improve Markdown cleanup rules and verify with a public fixture."
    if "table_or_layout_review" in categories:
        return "Inspect table diagnostics before promoting any table extractor."
    return "Open output and report, then record manual review status."


def queue_sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
    level_rank = {"failed": 0, "poor": 1, "review": 2}
    focus_rank = {
        "structure_repair": 0,
        "ocr_cleanup": 1,
        "markdown_cleanup": 2,
        "table_layout_review": 3,
        "manual_review": 4,
    }
    return (
        level_rank.get(str(item.get("quality_level")), 9),
        focus_rank.get(str(item.get("recommended_focus")), 9),
        str(item.get("id")),
    )


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Quality Improvement Queue",
        "",
        f"- Schema: `{payload['schema_version']}`",
        f"- Count: {payload['summary']['count']}",
        f"- Quality levels: {payload['summary']['quality_levels']}",
        f"- Issue categories: {payload['summary']['issue_categories']}",
        "",
        "| Level | Focus | Source | Issues | Next step |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in payload.get("items") or []:
        issues = ", ".join(item.get("issue_categories") or [])
        lines.append(
            "| "
            + " | ".join(
                [
                    escape_md(str(item.get("quality_level") or "")),
                    escape_md(str(item.get("recommended_focus") or "")),
                    escape_md(str(item.get("source_name") or item.get("id") or "")),
                    escape_md(issues),
                    escape_md(str(item.get("next_step") or "")),
                ]
            )
            + " |"
        )
    return "\n".join(lines).rstrip() + "\n"


def escape_md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())

