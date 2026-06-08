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
    extract_epub_toc_titles,
    find_missing_dependencies,
    normalize_heading_key,
    pdf_outline_heading_candidates,
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
    parser.add_argument("--min-success-rate", type=float, default=None, help="Optional quality gate: minimum ok / total ratio.")
    parser.add_argument("--min-good-rate", type=float, default=None, help="Optional quality gate: minimum good / scored ratio.")
    parser.add_argument("--max-review-poor-rate", type=float, default=None, help="Optional quality gate: maximum review-or-poor / scored ratio.")
    parser.add_argument("--max-timeout-rate", type=float, default=None, help="Optional quality gate: maximum timeout / total ratio.")
    parser.add_argument("--max-failed-rate", type=float, default=None, help="Optional quality gate: maximum failed / total ratio.")
    parser.add_argument("--fail-on-quality-gate", action="store_true", help="Exit non-zero when any configured quality gate fails.")
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
    gates = payload["summary"].get("quality_gates") or {}
    if args.fail_on_quality_gate and gates.get("status") == "failed":
        print(json.dumps({"quality_gates": gates}, ensure_ascii=False, indent=2))
        return 4
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
        "summary": summarize_results(results, args=args),
        "results": results,
    }
    write_json(args.output / ("benchmark-results.json" if final else "benchmark-results.partial.json"), payload)
    write_json(args.output / ("quality-regression-summary.json" if final else "quality-regression-summary.partial.json"), quality_regression_summary(payload))
    if not final:
        (args.output / "benchmark-summary.partial.md").write_text(render_benchmark_summary(payload), encoding="utf-8")
        (args.output / "docling-decision.partial.md").write_text(render_docling_decision(payload), encoding="utf-8")
        (args.output / "quality-regression-summary.partial.md").write_text(render_quality_regression_summary(payload), encoding="utf-8")
    else:
        (args.output / "quality-regression-summary.md").write_text(render_quality_regression_summary(payload), encoding="utf-8")
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
        metrics = enrich_quality_metrics(markdown_metrics(output_path), source=source, output_path=output_path, category=category)
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


def enrich_quality_metrics(metrics: dict, *, source: Path, output_path: Path | None, category: str) -> dict:
    enriched = dict(metrics or {})
    enriched.setdefault("toc_match_ratio", toc_match_ratio(source, output_path))
    enriched.setdefault("ocr_characters", ocr_character_count(enriched, category=category))
    return enriched


def toc_match_ratio(source: Path, output_path: Path | None) -> float:
    if output_path is None or not output_path.exists():
        return 0.0
    titles = toc_or_outline_titles(source)
    if not titles:
        return 0.0
    markdown_titles = markdown_heading_keys(output_path)
    if not markdown_titles:
        return 0.0
    matched = sum(1 for title in titles if normalize_heading_key(title) in markdown_titles)
    return round(matched / max(len(titles), 1), 3)


def toc_or_outline_titles(source: Path) -> list[str]:
    suffix = source.suffix.lower()
    if suffix == ".epub":
        return extract_epub_toc_titles(source)
    if suffix == ".pdf":
        return [str(item.get("title") or "") for item in pdf_outline_heading_candidates(source)]
    return []


def markdown_heading_keys(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return set()
    keys: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        title = stripped.lstrip("#").strip()
        key = normalize_heading_key(title)
        if key:
            keys.add(key)
    return keys


def ocr_character_count(metrics: dict, *, category: str) -> int:
    if category in {"scanned_pdf", "image", "image_infographic", "image_set", "image_set_duplicates"}:
        return int(metrics.get("characters") or 0)
    return 0


def finish_result(base: dict, started: float, status: str, **updates) -> dict:
    payload = dict(base)
    payload.update(updates)
    payload["status"] = status
    payload["duration_seconds"] = round(time.monotonic() - started, 3)
    return payload


def summarize_results(results: list[dict], args: argparse.Namespace | None = None) -> dict:
    counts = {}
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    quality_counts = {}
    unscored_count = 0
    for item in results:
        level = (item.get("metrics") or {}).get("level")
        if level:
            quality_counts[level] = quality_counts.get(level, 0) + 1
        else:
            unscored_count += 1
    summary = {
        "count": len(results),
        "status_counts": counts,
        "quality_counts": quality_counts,
        "unscored_count": unscored_count,
        "docling_policy": recommend_docling_policy(results),
        "quality_regression": quality_regression_summary({"results": results})["summary"],
        "quality_gates": evaluate_quality_gates(results, args),
    }
    return summary


def evaluate_quality_gates(results: list[dict], args: argparse.Namespace | None = None) -> dict:
    thresholds = quality_gate_thresholds(args)
    total = len(results)
    scored = [item for item in results if item.get("metrics")]
    ok_count = sum(1 for item in results if item.get("status") == "ok")
    timeout_count = sum(1 for item in results if item.get("status") == "timeout")
    failed_count = sum(1 for item in results if item.get("status") == "failed")
    good_count = sum(1 for item in scored if (item.get("metrics") or {}).get("level") == "good")
    review_poor_count = sum(1 for item in scored if (item.get("metrics") or {}).get("level") in {"review", "poor"})
    metrics = {
        "success_rate": ratio(ok_count, total),
        "good_rate": ratio(good_count, len(scored)),
        "review_poor_rate": ratio(review_poor_count, len(scored)),
        "timeout_rate": ratio(timeout_count, total),
        "failed_rate": ratio(failed_count, total),
        "total": total,
        "scored": len(scored),
    }
    checks = []
    for name, threshold in thresholds.items():
        actual = metrics.get(name)
        if actual is None:
            continue
        operator = "min" if name in {"success_rate", "good_rate"} else "max"
        passed = actual >= threshold if operator == "min" else actual <= threshold
        checks.append({"name": name, "operator": operator, "threshold": threshold, "actual": actual, "passed": passed})
    if not checks:
        status = "not_configured"
    elif all(item["passed"] for item in checks):
        status = "passed"
    else:
        status = "failed"
    return {
        "status": status,
        "metrics": metrics,
        "thresholds": thresholds,
        "checks": checks,
    }


def quality_gate_thresholds(args: argparse.Namespace | None) -> dict[str, float]:
    if args is None:
        return {}
    raw = {
        "success_rate": getattr(args, "min_success_rate", None),
        "good_rate": getattr(args, "min_good_rate", None),
        "review_poor_rate": getattr(args, "max_review_poor_rate", None),
        "timeout_rate": getattr(args, "max_timeout_rate", None),
        "failed_rate": getattr(args, "max_failed_rate", None),
    }
    return {name: float(value) for name, value in raw.items() if value is not None}


def ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 3) if denominator else 0.0


def quality_regression_summary(payload: dict) -> dict:
    results = payload.get("results") or []
    scored = [item for item in results if item.get("metrics")]
    status_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    for item in results:
        status_counts[item.get("status", "unknown")] = status_counts.get(item.get("status", "unknown"), 0) + 1
        category = str(item.get("category") or "unknown")
        category_counts[category] = category_counts.get(category, 0) + 1
    heading_counts = [int((item.get("metrics") or {}).get("headings") or 0) for item in scored]
    page_heading_counts = [int((item.get("metrics") or {}).get("page_headings") or 0) for item in scored]
    characters = [int((item.get("metrics") or {}).get("characters") or 0) for item in scored]
    toc_match_ratios = [float((item.get("metrics") or {}).get("toc_match_ratio") or 0) for item in scored]
    ocr_characters = [int((item.get("metrics") or {}).get("ocr_characters") or 0) for item in scored]
    repeated_noise = [int((item.get("metrics") or {}).get("repeated_noise_lines") or 0) for item in scored]
    durations = [float(item.get("duration_seconds") or 0) for item in results]
    fallback_count = sum(1 for item in results if "fallback" in str(item.get("actual_pipeline") or item.get("pipeline") or "").lower())
    summary = {
        "total": len(results),
        "scored": len(scored),
        "status_counts": status_counts,
        "category_counts": category_counts,
        "avg_headings": average(heading_counts),
        "page_heading_ratio": round(sum(page_heading_counts) / max(sum(heading_counts), 1), 3),
        "avg_characters": average(characters),
        "avg_toc_match_ratio": average_float(toc_match_ratios),
        "ocr_characters": sum(ocr_characters),
        "repeated_noise_lines": sum(repeated_noise),
        "avg_duration_seconds": average_float(durations),
        "max_duration_seconds": max(durations) if durations else 0.0,
        "fallback_count": fallback_count,
        "review_or_poor": sum(1 for item in scored if (item.get("metrics") or {}).get("level") in {"review", "poor"}),
    }
    return {
        "schema_version": "quality-regression-summary-v1",
        "created_at": payload.get("created_at") or now(),
        "manifest": payload.get("manifest", ""),
        "summary": summary,
        "quality_gates": (payload.get("summary") or {}).get("quality_gates") or {"status": "not_configured", "checks": []},
    }


def average(values: list[int]) -> float:
    return round(sum(values) / max(len(values), 1), 3)


def average_float(values: list[float]) -> float:
    return round(sum(values) / max(len(values), 1), 3)


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
        f"- Unscored: {payload['summary'].get('unscored_count', 0)}",
        f"- Quality gates: {payload['summary'].get('quality_gates', {}).get('status', 'not_configured')}",
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


def render_quality_regression_summary(payload: dict) -> str:
    report = quality_regression_summary(payload)
    summary = report["summary"]
    gates = report.get("quality_gates") or {}
    lines = [
        "# Quality Regression Summary",
        "",
        f"- Created: {report['created_at']}",
        f"- Manifest: `{report.get('manifest', '')}`",
        f"- Total: {summary['total']}",
        f"- Scored: {summary['scored']}",
        f"- Status: {summary['status_counts']}",
        f"- Categories: {summary['category_counts']}",
        f"- Average headings: {summary['avg_headings']}",
        f"- Page heading ratio: {summary['page_heading_ratio']}",
        f"- Average characters: {summary['avg_characters']}",
        f"- Average TOC match ratio: {summary['avg_toc_match_ratio']}",
        f"- OCR characters: {summary['ocr_characters']}",
        f"- Repeated noise lines: {summary['repeated_noise_lines']}",
        f"- Average duration seconds: {summary['avg_duration_seconds']}",
        f"- Max duration seconds: {summary['max_duration_seconds']}",
        f"- Fallback count: {summary['fallback_count']}",
        f"- Review or poor: {summary['review_or_poor']}",
        f"- Quality gates: {gates.get('status', 'not_configured')}",
    ]
    checks = gates.get("checks") or []
    if checks:
        lines.extend(["", "## Quality Gates", "", "| Gate | Operator | Threshold | Actual | Passed |", "| --- | --- | ---: | ---: | --- |"])
        for item in checks:
            lines.append(
                f"| {escape_table(str(item.get('name', '')))} | {item.get('operator', '')} | "
                f"{item.get('threshold', '')} | {item.get('actual', '')} | {item.get('passed', '')} |"
            )
    return "\n".join(lines).rstrip() + "\n"


def escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").replace("\r", " ")


if __name__ == "__main__":
    raise SystemExit(main())
