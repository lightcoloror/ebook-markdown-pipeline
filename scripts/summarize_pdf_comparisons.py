from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize multiple PDF pipeline comparison runs.")
    parser.add_argument("runs", nargs="+", type=Path, help="Comparison run directories.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    entries = []
    for run_dir in args.runs:
        payload = load_comparison(run_dir)
        entries.append(summarize_comparison(run_dir, payload))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_markdown(entries), encoding="utf-8")
    json_path = args.output.with_suffix(".json")
    json_path.write_text(json.dumps({"comparisons": entries}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {args.output}")
    print(f"Wrote {json_path}")
    return 0


def load_comparison(run_dir: Path) -> dict[str, Any]:
    final_path = run_dir / "pipeline-comparison.json"
    partial_path = run_dir / "pipeline-comparison.partial.json"
    path = final_path if final_path.exists() else partial_path
    if not path.exists():
        raise FileNotFoundError(f"No pipeline comparison JSON found under {run_dir}")
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    payload["_comparison_path"] = str(path)
    return payload


def summarize_comparison(run_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    comparisons = payload.get("comparisons") or []
    ok_items = [item for item in comparisons if item.get("status") == "ok"]
    best = best_item(ok_items)
    status_counts: dict[str, int] = {}
    for item in comparisons:
        status = str(item.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "run_dir": str(run_dir),
        "source": payload.get("source"),
        "comparison_path": payload.get("_comparison_path"),
        "final": payload.get("final"),
        "page_count": (payload.get("preflight") or {}).get("page_count"),
        "recommended_pipeline": (payload.get("preflight") or {}).get("recommended_pipeline"),
        "status_counts": status_counts,
        "best_pipeline": best.get("pipeline") if best else "",
        "best_actual_pipeline": best.get("actual_pipeline") or best.get("pipeline") if best else "",
        "best_score": (best.get("metrics") or {}).get("score") if best else "",
        "best_seconds": best.get("duration_seconds") if best else "",
        "best_headings": (best.get("metrics") or {}).get("headings") if best else "",
        "best_chars": (best.get("metrics") or {}).get("characters") if best else "",
        "comparisons": comparisons,
    }


def best_item(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not items:
        return None
    return sorted(
        items,
        key=lambda item: (
            int((item.get("metrics") or {}).get("score") or -1),
            int((item.get("metrics") or {}).get("headings") or 0),
            -float(item.get("duration_seconds") or 0),
        ),
        reverse=True,
    )[0]


def render_markdown(entries: list[dict[str, Any]]) -> str:
    lines = [
        "# PDF Pipeline Comparison Summary",
        "",
        "| Source | Pages | Recommended | Status counts | Best requested | Best actual | Score | Headings | Chars | Seconds | Report |",
        "| --- | ---: | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for entry in entries:
        source_name = Path(str(entry.get("source") or "")).name
        lines.append(
            f"| {escape_table(source_name)} | {entry.get('page_count', '')} | {entry.get('recommended_pipeline', '')} | "
            f"{escape_table(str(entry.get('status_counts') or {}))} | {entry.get('best_pipeline', '')} | "
            f"{entry.get('best_actual_pipeline', '')} | {entry.get('best_score', '')} | {entry.get('best_headings', '')} | "
            f"{entry.get('best_chars', '')} | {entry.get('best_seconds', '')} | `{entry.get('comparison_path', '')}` |"
        )
    lines.extend(["", "## Per-Pipeline Details", ""])
    for entry in entries:
        lines.append(f"### {Path(str(entry.get('source') or '')).name}")
        lines.append("")
        lines.append("| Requested | Actual | Status | Score | Headings | Chars | Seconds | Message |")
        lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: | --- |")
        for item in entry.get("comparisons") or []:
            metrics = item.get("metrics") or {}
            lines.append(
                f"| {item.get('pipeline', '')} | {item.get('actual_pipeline') or item.get('pipeline', '')} | "
                f"{item.get('status', '')} | {metrics.get('score', '')} | {metrics.get('headings', '')} | "
                f"{metrics.get('characters', '')} | {item.get('duration_seconds', '')} | "
                f"{escape_table(str(item.get('message') or ''))[:160]} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").replace("\r", " ")


if __name__ == "__main__":
    raise SystemExit(main())
