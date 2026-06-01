from __future__ import annotations

import argparse
import multiprocessing
import queue
import sys
import time
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark_utils import PDF_COMPARE_SCHEMA_VERSION, markdown_metrics, now, safe_id, write_json  # noqa: E402
from run_benchmarks import terminate_process_tree  # noqa: E402

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
    parser.add_argument("--pipeline-timeout", type=float, default=0, help="Maximum seconds per pipeline. 0 disables timeout.")
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
        comparisons.append(run_pipeline_with_timeout(source, args.output, pipeline, overwrite=args.overwrite, pipeline_timeout=args.pipeline_timeout))
        partial_payload = build_payload(args, source, preflight, comparisons, final=False)
        write_json(args.output / "pipeline-comparison.partial.json", partial_payload)
        (args.output / "pipeline-comparison.partial.md").write_text(render_comparison_markdown(partial_payload), encoding="utf-8")

    payload = build_payload(args, source, preflight, comparisons, final=True)
    write_json(args.output / "pipeline-comparison.json", payload)
    (args.output / "pipeline-comparison.md").write_text(render_comparison_markdown(payload), encoding="utf-8")
    return 0 if any(item["status"] == "ok" for item in comparisons) else 3


def build_payload(args: argparse.Namespace, source: Path, preflight: dict, comparisons: list[dict], *, final: bool) -> dict:
    return {
        "schema_version": PDF_COMPARE_SCHEMA_VERSION,
        "created_at": now(),
        "source": str(source),
        "pipeline_timeout_seconds": args.pipeline_timeout,
        "final": final,
        "preflight": preflight,
        "comparisons": comparisons,
    }


def run_pipeline_with_timeout(source: Path, output_root: Path, pipeline: str, *, overwrite: bool, pipeline_timeout: float) -> dict:
    if pipeline_timeout <= 0:
        return run_pipeline(source, output_root, pipeline, overwrite=overwrite)
    result_queue: multiprocessing.Queue = multiprocessing.Queue(maxsize=1)
    started = time.monotonic()
    process = multiprocessing.Process(
        target=_run_pipeline_worker,
        args=(source, output_root, pipeline, overwrite, result_queue),
    )
    process.start()
    process.join(pipeline_timeout)
    if process.is_alive():
        terminate_process_tree(process)
        return {
            "pipeline": pipeline,
            "status": "timeout",
            "message": f"pipeline exceeded timeout: {pipeline_timeout}s",
            "output": str(output_root / safe_id(pipeline) / f"{source.stem}.md"),
            "duration_seconds": round(time.monotonic() - started, 3),
            "metrics": {},
        }
    try:
        return result_queue.get_nowait()
    except queue.Empty:
        return {
            "pipeline": pipeline,
            "status": "failed",
            "message": f"pipeline process exited with code {process.exitcode} and no result",
            "output": str(output_root / safe_id(pipeline) / f"{source.stem}.md"),
            "duration_seconds": round(time.monotonic() - started, 3),
            "metrics": {},
        }


def _run_pipeline_worker(source: Path, output_root: Path, pipeline: str, overwrite: bool, result_queue: multiprocessing.Queue) -> None:
    try:
        result_queue.put(run_pipeline(source, output_root, pipeline, overwrite=overwrite))
    except Exception as exc:  # noqa: BLE001
        result_queue.put(
            {
                "pipeline": pipeline,
                "status": "failed",
                "message": str(exc),
                "output": str(output_root / safe_id(pipeline) / f"{source.stem}.md"),
                "duration_seconds": 0,
                "metrics": {},
            }
        )


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
        f"- Pipeline timeout seconds: {payload.get('pipeline_timeout_seconds', 0)}",
        f"- Final: {payload.get('final', True)}",
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
