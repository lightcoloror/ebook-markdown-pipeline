from __future__ import annotations

import argparse
import json
import multiprocessing
import queue
import subprocess
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
    parser.add_argument("--sample-timeout", type=float, default=0, help="Maximum seconds per sample. 0 disables per-sample timeout.")
    parser.add_argument("--no-partial", action="store_true", help="Do not write benchmark-results.partial.json after each sample.")
    parser.add_argument(
        "--pdf-mode-for-benchmark",
        choices=["auto", "fast", "pymupdf4llm", "mineru", "marker", "umi", "docling"],
        default="auto",
        help="PDF pipeline for benchmark runs. 'fast' aliases to pymupdf4llm so large sample runs do not default to slow model/OCR pipelines.",
    )
    args = parser.parse_args()

    samples = load_samples(args.manifest)
    if args.limit:
        samples = samples[: args.limit]
    args.output.mkdir(parents=True, exist_ok=True)

    results = []
    for sample in samples:
        result = run_sample_with_timeout(
            sample,
            args.output,
            overwrite=args.overwrite,
            skip_heavy=args.skip_heavy,
            sample_timeout=args.sample_timeout,
            pdf_mode_for_benchmark=args.pdf_mode_for_benchmark,
        )
        results.append(result)
        print(json.dumps({"id": sample.get("id"), "status": result.get("status"), "duration_seconds": result.get("duration_seconds")}, ensure_ascii=False))
        if not args.no_partial:
            write_run_payload(args, results, final=False)

    payload = write_run_payload(args, results, final=True)
    (args.output / "benchmark-summary.md").write_text(render_benchmark_summary(payload), encoding="utf-8")
    (args.output / "docling-decision.md").write_text(render_docling_decision(payload), encoding="utf-8")
    return 0


def write_run_payload(args: argparse.Namespace, results: list[dict], *, final: bool) -> dict:
    payload = {
        "schema_version": RUN_SCHEMA_VERSION,
        "created_at": now(),
        "manifest": str(args.manifest),
        "output": str(args.output),
        "sample_timeout_seconds": args.sample_timeout,
        "pdf_mode_for_benchmark": args.pdf_mode_for_benchmark,
        "final": final,
        "summary": summarize_results(results),
        "results": results,
    }
    write_json(args.output / ("benchmark-results.json" if final else "benchmark-results.partial.json"), payload)
    if not final:
        (args.output / "benchmark-summary.partial.md").write_text(render_benchmark_summary(payload), encoding="utf-8")
        (args.output / "docling-decision.partial.md").write_text(render_docling_decision(payload), encoding="utf-8")
    return payload


def run_sample_with_timeout(
    sample: dict,
    output_root: Path,
    *,
    overwrite: bool,
    skip_heavy: bool,
    sample_timeout: float,
    pdf_mode_for_benchmark: str,
) -> dict:
    if sample_timeout <= 0:
        return run_sample(sample, output_root, overwrite=overwrite, skip_heavy=skip_heavy, pdf_mode_for_benchmark=pdf_mode_for_benchmark)
    result_queue: multiprocessing.Queue = multiprocessing.Queue(maxsize=1)
    started = time.monotonic()
    process = multiprocessing.Process(
        target=_run_sample_worker,
        args=(sample, output_root, overwrite, skip_heavy, pdf_mode_for_benchmark, result_queue),
    )
    process.start()
    process.join(sample_timeout)
    if process.is_alive():
        terminate_process_tree(process)
        source = Path(sample["path"])
        sample_id = safe_id(str(sample.get("id") or source.stem))
        return {
            "id": sample_id,
            "source": str(source),
            "category": str(sample.get("category") or ""),
            "recommended_pipeline": sample.get("recommended_pipeline"),
            "benchmark_pdf_mode": effective_pdf_mode(source, pdf_mode_for_benchmark),
            "status": "timeout",
            "output": str(output_root / sample_id),
            "failure_reason": f"sample exceeded timeout: {sample_timeout}s",
            "duration_seconds": round(time.monotonic() - started, 3),
        }
    try:
        payload = result_queue.get_nowait()
    except queue.Empty:
        source = Path(sample["path"])
        sample_id = safe_id(str(sample.get("id") or source.stem))
        return {
            "id": sample_id,
            "source": str(source),
            "category": str(sample.get("category") or ""),
            "recommended_pipeline": sample.get("recommended_pipeline"),
            "benchmark_pdf_mode": effective_pdf_mode(source, pdf_mode_for_benchmark),
            "status": "failed",
            "output": str(output_root / sample_id),
            "failure_reason": f"sample process exited with code {process.exitcode} and no result",
            "duration_seconds": round(time.monotonic() - started, 3),
        }
    return payload


def terminate_process_tree(process: multiprocessing.Process) -> None:
    if process.pid and sys.platform.startswith("win"):
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        process.terminate()
    process.join(10)
    if process.is_alive():
        process.kill()
        process.join(5)


def _run_sample_worker(sample: dict, output_root: Path, overwrite: bool, skip_heavy: bool, pdf_mode_for_benchmark: str, result_queue: multiprocessing.Queue) -> None:
    try:
        result_queue.put(run_sample(sample, output_root, overwrite=overwrite, skip_heavy=skip_heavy, pdf_mode_for_benchmark=pdf_mode_for_benchmark))
    except Exception as exc:  # noqa: BLE001
        source = Path(sample["path"])
        sample_id = safe_id(str(sample.get("id") or source.stem))
        result_queue.put(
            {
                "id": sample_id,
                "source": str(source),
                "category": str(sample.get("category") or ""),
                "recommended_pipeline": sample.get("recommended_pipeline"),
                "benchmark_pdf_mode": effective_pdf_mode(source, pdf_mode_for_benchmark),
                "status": "failed",
                "output": str(output_root / sample_id),
                "failure_reason": str(exc),
                "duration_seconds": 0,
            }
        )


def run_sample(sample: dict, output_root: Path, *, overwrite: bool, skip_heavy: bool, pdf_mode_for_benchmark: str = "auto") -> dict:
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
        "benchmark_pdf_mode": effective_pdf_mode(source, pdf_mode_for_benchmark),
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
        options = normalize_command_options(
            default_options(
                output=output_dir,
                overwrite=overwrite,
                resume=False,
                pdf_pipeline_mode=effective_pdf_mode(source, pdf_mode_for_benchmark),
            )
        )
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


def effective_pdf_mode(source: Path, pdf_mode_for_benchmark: str) -> str:
    if source.suffix.lower() != ".pdf":
        return "auto"
    if pdf_mode_for_benchmark == "fast":
        return "pymupdf4llm"
    return pdf_mode_for_benchmark


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
    return {"count": len(results), "status_counts": counts, "quality_counts": quality_counts, "docling_policy": recommend_docling_policy(results)}


def recommend_docling_policy(results: list[dict]) -> dict:
    docling_items = [item for item in results if item.get("category") == "docling_doc"]
    if not docling_items:
        return {
            "decision": "insufficient_data",
            "recommendation": "没有 Docling 文档样本，暂时保持 Docling 为可选后端。",
            "sample_count": 0,
        }
    ok_items = [item for item in docling_items if item.get("status") == "ok"]
    good_items = [item for item in ok_items if (item.get("metrics") or {}).get("level") == "good"]
    review_or_poor = [item for item in ok_items if (item.get("metrics") or {}).get("level") in {"review", "poor"}]
    success_rate = len(ok_items) / max(len(docling_items), 1)
    good_rate = len(good_items) / max(len(docling_items), 1)
    if success_rate >= 0.8 and good_rate >= 0.6:
        decision = "enable_docling_for_docling_formats"
        recommendation = "Docling 文档样本表现较稳定，可考虑对 DOCX/PPTX/XLSX/HTML/CSV 默认使用 Docling。"
    elif success_rate >= 0.5:
        decision = "keep_optional_collect_more"
        recommendation = "Docling 有一定可用性，但质量或失败率仍需更多样本验证，暂时保持可选。"
    else:
        decision = "keep_optional"
        recommendation = "Docling 样本成功率偏低，继续保持可选后端，不建议默认启用。"
    return {
        "decision": decision,
        "recommendation": recommendation,
        "sample_count": len(docling_items),
        "success_count": len(ok_items),
        "good_count": len(good_items),
        "review_or_poor_count": len(review_or_poor),
        "success_rate": round(success_rate, 3),
        "good_rate": round(good_rate, 3),
    }


def render_benchmark_summary(payload: dict) -> str:
    lines = [
        "# Benchmark Summary",
        "",
        f"- Created: {payload['created_at']}",
        f"- Samples: {payload['summary']['count']}",
        f"- Status: {payload['summary']['status_counts']}",
        f"- Quality: {payload['summary']['quality_counts']}",
        f"- Docling decision: {payload['summary']['docling_policy']['decision']}",
        f"- PDF benchmark mode: {payload.get('pdf_mode_for_benchmark', 'auto')}",
        "",
        "| Status | Quality | Seconds | Category | PDF mode | Sample | Failure |",
        "| --- | --- | ---: | --- | --- | --- | --- |",
    ]
    for item in payload["results"]:
        metrics = item.get("metrics") or {}
        lines.append(
            f"| {item.get('status')} | {metrics.get('level', '')} {metrics.get('score', '')} | "
            f"{item.get('duration_seconds', '')} | {item.get('category', '')} | {item.get('benchmark_pdf_mode', '')} | "
            f"{Path(item.get('source', '')).name} | {escape_table(str(item.get('failure_reason') or ''))[:220]} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def render_docling_decision(payload: dict) -> str:
    policy = payload["summary"]["docling_policy"]
    lines = [
        "# Docling Default Decision",
        "",
        f"- Decision: `{policy['decision']}`",
        f"- Recommendation: {policy['recommendation']}",
        f"- Sample count: {policy['sample_count']}",
        f"- Success count: {policy.get('success_count', 0)}",
        f"- Good count: {policy.get('good_count', 0)}",
        f"- Success rate: {policy.get('success_rate', 0)}",
        f"- Good rate: {policy.get('good_rate', 0)}",
        "",
        "## Relevant Samples",
        "",
        "| Status | Quality | Seconds | Sample | Failure |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for item in payload["results"]:
        if item.get("category") != "docling_doc":
            continue
        metrics = item.get("metrics") or {}
        lines.append(
            f"| {item.get('status')} | {metrics.get('level', '')} {metrics.get('score', '')} | "
            f"{item.get('duration_seconds', '')} | {Path(item.get('source', '')).name} | "
            f"{escape_table(str(item.get('failure_reason') or ''))[:220]} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").replace("\r", " ")


if __name__ == "__main__":
    raise SystemExit(main())
