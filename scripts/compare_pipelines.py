from __future__ import annotations

import argparse
import sys
import time
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark_utils import PDF_COMPARE_SCHEMA_VERSION, markdown_metrics, now, safe_id, write_json  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline import default_options, normalize_command_options  # noqa: E402
from ebook_markdown_pipeline.batch_convert_books import convert_one, inspect_pdf_preflight  # noqa: E402


DEFAULT_PIPELINES = ["pymupdf4llm", "mineru", "umi", "docling"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare PDF conversion quality across pipelines.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--pipelines", nargs="+", default=DEFAULT_PIPELINES)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-missing", action="store_true", default=True)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    source = args.input
    options = normalize_command_options(default_options(output=args.output, overwrite=args.overwrite, resume=False))
    try:
        preflight = asdict(inspect_pdf_preflight(source, options, sample_pages=8))
    except Exception as exc:  # noqa: BLE001
        preflight = {"error": str(exc)}

    comparisons = []
    for pipeline in args.pipelines:
        comparisons.append(run_pipeline(source, args.output, pipeline, overwrite=args.overwrite))

    payload = {
        "schema_version": PDF_COMPARE_SCHEMA_VERSION,
        "created_at": now(),
        "source": str(source),
        "preflight": preflight,
        "comparisons": comparisons,
    }
    write_json(args.output / "pipeline-comparison.json", payload)
    (args.output / "pipeline-comparison.md").write_text(render_comparison_markdown(payload), encoding="utf-8")
    return 0 if any(item["status"] == "ok" for item in comparisons) else 3


def run_pipeline(source: Path, output_root: Path, pipeline: str, *, overwrite: bool) -> dict:
    pipeline_dir = output_root / safe_id(pipeline)
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    output_path = pipeline_dir / f"{source.stem}.md"
    options = normalize_command_options(
        default_options(
            output=pipeline_dir,
            output_format="markdown",
            pdf_pipeline_mode=pipeline,
            overwrite=overwrite,
            resume=False,
        )
    )
    started = time.monotonic()
    result = convert_one(source, source.parent, pipeline_dir, options, output_path=output_path)
    metrics = markdown_metrics(Path(result.output) if result.output else None)
    return {
        "pipeline": pipeline,
        "status": result.status,
        "message": result.message,
        "output": result.output,
        "duration_seconds": round(time.monotonic() - started, 3),
        "metrics": metrics,
    }


def render_comparison_markdown(payload: dict) -> str:
    lines = [
        f"# PDF Pipeline Comparison: {Path(payload['source']).name}",
        "",
        f"- Created: {payload['created_at']}",
        f"- Source: `{payload['source']}`",
        "",
        "## Preflight",
        "",
        "```json",
        __import__("json").dumps(payload.get("preflight", {}), ensure_ascii=False, indent=2),
        "```",
        "",
        "## Results",
        "",
        "| Pipeline | Status | Seconds | Score | Headings | Chars | Table lines | Page noise | Output | Message | Manual score | Notes |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |",
    ]
    for item in payload["comparisons"]:
        metrics = item.get("metrics") or {}
        lines.append(
            f"| {item['pipeline']} | {item['status']} | {item.get('duration_seconds', '')} | "
            f"{metrics.get('score', '')} | {metrics.get('headings', '')} | {metrics.get('characters', '')} | "
            f"{metrics.get('table_like_lines', '')} | {metrics.get('page_number_lines', '')} | "
            f"`{item.get('output') or ''}` | {escape_table(str(item.get('message') or ''))[:120]} |  |  |"
        )
    return "\n".join(lines).rstrip() + "\n"


def escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").replace("\r", " ")


if __name__ == "__main__":
    raise SystemExit(main())
