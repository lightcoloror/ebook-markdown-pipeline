from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark_utils import RUN_SCHEMA_VERSION, load_samples, markdown_metrics, now, safe_id, write_json  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline import default_options, normalize_command_options, write_batch_summary  # noqa: E402
from ebook_markdown_pipeline.batch_convert_books import (  # noqa: E402
    analyze_sources,
    collect_sources,
    convert_sources,
    find_missing_dependencies,
)
from ebook_markdown_pipeline.document_locator import build_location_index
from ebook_markdown_pipeline.image_book_rebuilder import rebuild_image_book


def main() -> int:
    parser = argparse.ArgumentParser(description="Run benchmark samples and write repeatable quality reports.")
    parser.add_argument("--manifest", type=Path, default=PROJECT_DIR / "benchmarks" / "samples.local.json")
    parser.add_argument("--output", type=Path, default=PROJECT_DIR / "benchmarks" / "runs" / time.strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-heavy", action="store_true", help="Skip PDF OCR/model-heavy categories.")
    args = parser.parse_args()

    samples = load_samples(args.manifest)
    if args.limit:
        samples = samples[: args.limit]
    args.output.mkdir(parents=True, exist_ok=True)

    results = []
    for sample in samples:
        result = run_sample(sample, args.output, overwrite=args.overwrite, skip_heavy=args.skip_heavy)
        results.append(result)
        print(json.dumps({"id": sample.get("id"), "status": result.get("status"), "duration_seconds": result.get("duration_seconds")}, ensure_ascii=False))

    payload = {
        "schema_version": RUN_SCHEMA_VERSION,
        "created_at": now(),
        "manifest": str(args.manifest),
        "output": str(args.output),
        "summary": summarize_results(results),
        "results": results,
    }
    write_json(args.output / "benchmark-results.json", payload)
    (args.output / "benchmark-summary.md").write_text(render_benchmark_summary(payload), encoding="utf-8")
    return 0


def run_sample(sample: dict, output_root: Path, *, overwrite: bool, skip_heavy: bool) -> dict:
    sample_id = safe_id(str(sample.get("id") or Path(sample["path"]).stem))
    source = Path(sample["path"])
    output_dir = output_root / sample_id
    output_dir.mkdir(parents=True, exist_ok=True)
    category = str(sample.get("category") or "")
    started = time.monotonic()
    base = {
        "id": sample_id,
        "source": str(source),
        "category": category,
        "recommended_pipeline": sample.get("recommended_pipeline"),
        "status": "unknown",
        "output": str(output_dir),
    }
    if not source.exists():
        return {**base, "status": "missing", "failure_reason": "source not found", "duration_seconds": 0}
    if skip_heavy and category in {"scanned_pdf", "complex_pdf"}:
        return {**base, "status": "skipped", "failure_reason": "skipped heavy category", "duration_seconds": 0}

    try:
        if category == "image_set" or source.is_dir():
            result = rebuild_image_book(source, output_dir, recursive=True, ocr_mode="auto")
            return finish_result(base, started, "ok", artifacts=result.get("artifacts", []), metrics={"page_count": result.get("page_count")})
        if source.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}:
            result = build_location_index(source, output_dir, recursive=False, ocr_mode="auto")
            return finish_result(base, started, "ok", artifacts=result.get("artifacts", []), metrics={"record_count": result.get("record_count")})
        options = normalize_command_options(default_options(output=output_dir, overwrite=overwrite, resume=False))
        sources = collect_sources(source, recursive=False, include_hidden=False)
        if not sources:
            return finish_result(base, started, "failed", failure_reason="no supported sources")
        missing = find_missing_dependencies(sources, options)
        if missing:
            return finish_result(base, started, "failed", failure_reason="; ".join(missing))
        plans = analyze_sources(sources, source if source.is_dir() else source.parent, output_dir, options)
        results = convert_sources(sources, source if source.is_dir() else source.parent, output_dir, options)
        options.output = output_dir
        write_batch_summary(results, options)
        first = results[0]
        output_path = Path(first.output) if first.output else None
        metrics = markdown_metrics(output_path)
        return finish_result(
            base,
            started,
            "ok" if all(item.status in {"ok", "skipped"} for item in results) else "failed",
            failure_reason="; ".join(item.message for item in results if item.status == "failed" and item.message),
            metrics=metrics,
            conversion_results=[asdict(item) for item in results],
            plans=[asdict(item) for item in plans],
        )
    except Exception as exc:  # noqa: BLE001
        return finish_result(base, started, "failed", failure_reason=str(exc))


def finish_result(base: dict, started: float, status: str, **updates) -> dict:
    payload = dict(base)
    payload.update(updates)
    payload["status"] = status
    payload["duration_seconds"] = round(time.monotonic() - started, 3)
    return payload


def summarize_results(results: list[dict]) -> dict:
    counts = {}
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    quality_counts = {}
    for item in results:
        level = (item.get("metrics") or {}).get("level")
        if level:
            quality_counts[level] = quality_counts.get(level, 0) + 1
    return {"count": len(results), "status_counts": counts, "quality_counts": quality_counts}


def render_benchmark_summary(payload: dict) -> str:
    lines = [
        "# Benchmark Summary",
        "",
        f"- Created: {payload['created_at']}",
        f"- Samples: {payload['summary']['count']}",
        f"- Status: {payload['summary']['status_counts']}",
        f"- Quality: {payload['summary']['quality_counts']}",
        "",
        "| Status | Quality | Seconds | Category | Sample | Failure |",
        "| --- | --- | ---: | --- | --- | --- |",
    ]
    for item in payload["results"]:
        metrics = item.get("metrics") or {}
        lines.append(
            f"| {item.get('status')} | {metrics.get('level', '')} {metrics.get('score', '')} | "
            f"{item.get('duration_seconds', '')} | {item.get('category', '')} | "
            f"{Path(item.get('source', '')).name} | {escape_table(str(item.get('failure_reason') or ''))[:220]} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").replace("\r", " ")


if __name__ == "__main__":
    raise SystemExit(main())
