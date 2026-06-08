from __future__ import annotations

import json
import importlib.util
import argparse
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import fitz

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.ebook_converter_http import build_handler


RUN_BENCHMARKS_PATH = PROJECT_DIR / "scripts" / "run_benchmarks.py"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ebook-benchmark-tools-") as tmp:
        root = Path(tmp)
        sample_root = root / "samples"
        sample_root.mkdir()
        txt = sample_root / "sample.txt"
        txt.write_text("# Benchmark\n\nThis is a benchmark text sample.", encoding="utf-8")
        pdf = sample_root / "sample.pdf"
        document = fitz.open()
        page = document.new_page()
        page.insert_text((72, 72), "Benchmark PDF\nContract amount 300000")
        document.save(pdf)
        document.close()

        manifest = root / "samples.json"
        run_cmd("discover_benchmark_samples.py", str(sample_root), "--output", str(manifest), "--limit", "10")
        manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
        if len(manifest_payload.get("samples", [])) < 2:
            raise RuntimeError(f"Expected discovered TXT and PDF samples: {manifest_payload}")

        run_dir = root / "run"
        run_cmd(
            "run_benchmarks.py",
            "--manifest",
            str(manifest),
            "--output",
            str(run_dir),
            "--limit",
            "1",
            "--overwrite",
            "--sample-timeout",
            "20",
            "--pdf-mode-for-benchmark",
            "fast",
            "--min-success-rate",
            "0.5",
            "--max-timeout-rate",
            "0.5",
            "--fail-on-quality-gate",
        )
        if (
            not (run_dir / "benchmark-results.json").exists()
            or not (run_dir / "benchmark-results.partial.json").exists()
            or not (run_dir / "benchmark-summary.md").exists()
            or not (run_dir / "docling-decision.md").exists()
            or not (run_dir / "quality-regression-summary.json").exists()
            or not (run_dir / "quality-regression-summary.md").exists()
        ):
            raise RuntimeError("Benchmark runner did not write expected reports.")
        run_payload = json.loads((run_dir / "benchmark-results.json").read_text(encoding="utf-8"))
        if run_payload.get("pdf_mode_for_benchmark") != "fast":
            raise RuntimeError(f"Expected benchmark PDF mode in report: {run_payload}")
        gates = (run_payload.get("summary") or {}).get("quality_gates") or {}
        if gates.get("status") != "passed" or not gates.get("checks"):
            raise RuntimeError(f"Expected passing benchmark quality gates: {run_payload}")
        quality_payload = json.loads((run_dir / "quality-regression-summary.json").read_text(encoding="utf-8"))
        if quality_payload.get("schema_version") != "quality-regression-summary-v1":
            raise RuntimeError(f"Expected quality regression summary: {quality_payload}")
        if quality_payload.get("quality_gates", {}).get("status") != "passed":
            raise RuntimeError(f"Expected quality gates in regression summary: {quality_payload}")
        summary_fields = quality_payload.get("summary") or {}
        for field in ["avg_toc_match_ratio", "ocr_characters", "structure_repair_decisions", "structure_repair_promoted", "avg_duration_seconds", "max_duration_seconds"]:
            if field not in summary_fields:
                raise RuntimeError(f"Expected quality metric {field}: {quality_payload}")
        benchmark_module = load_run_benchmarks()
        failed_gate = benchmark_module.evaluate_quality_gates(
            [{"status": "failed", "metrics": {"level": "poor"}}],
            argparse.Namespace(
                min_success_rate=1.0,
                min_good_rate=None,
                max_review_poor_rate=None,
                max_timeout_rate=None,
                max_failed_rate=0.0,
            ),
        )
        if failed_gate.get("status") != "failed":
            raise RuntimeError(f"Expected failing quality gate: {failed_gate}")
        structure_report = root / "structure.report.json"
        structure_report.write_text(
            json.dumps(
                {
                    "structure_repair": {
                        "action_counts": {"promoted_to_heading": 2},
                        "decisions": [
                            {"action": "promoted_to_heading", "confidence": 0.92},
                            {"action": "kept_as_body", "confidence": 0.42},
                            {"action": "promoted_to_heading", "confidence": "0.70"},
                        ],
                    }
                }
            ),
            encoding="utf-8",
        )
        structure_metrics = benchmark_module.structure_repair_metrics([{"report": str(structure_report)}])
        if structure_metrics != {
            "structure_repair_decisions": 3,
            "structure_repair_promoted": 2,
            "structure_repair_low_confidence": 1,
        }:
            raise RuntimeError(f"Expected structure repair metrics from report: {structure_metrics}")

        baseline_quality = root / "baseline-quality.json"
        candidate_quality = root / "candidate-quality.json"
        baseline_quality.write_text(
            json.dumps(
                {
                    "schema_version": "quality-regression-summary-v1",
                    "summary": {
                        "total": 2,
                        "scored": 2,
                        "status_counts": {"ok": 2},
                        "avg_headings": 1,
                        "avg_characters": 1000,
                        "avg_toc_match_ratio": 0.5,
                        "ocr_characters": 100,
                        "structure_repair_decisions": 2,
                        "structure_repair_promoted": 1,
                        "structure_repair_low_confidence": 1,
                        "page_heading_ratio": 0,
                        "repeated_noise_lines": 4,
                        "avg_duration_seconds": 2.0,
                        "max_duration_seconds": 3.0,
                        "fallback_count": 0,
                        "review_or_poor": 1,
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        candidate_quality.write_text(
            json.dumps(
                {
                    "schema_version": "quality-regression-summary-v1",
                    "summary": {
                        "total": 2,
                        "scored": 2,
                        "status_counts": {"ok": 2},
                        "avg_headings": 2,
                        "avg_characters": 1200,
                        "avg_toc_match_ratio": 0.75,
                        "ocr_characters": 120,
                        "structure_repair_decisions": 4,
                        "structure_repair_promoted": 3,
                        "structure_repair_low_confidence": 0,
                        "page_heading_ratio": 0,
                        "repeated_noise_lines": 0,
                        "avg_duration_seconds": 1.5,
                        "max_duration_seconds": 2.5,
                        "fallback_count": 0,
                        "review_or_poor": 0,
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        quality_compare_dir = root / "quality-compare"
        run_cmd(
            "compare_benchmark_quality.py",
            "--baseline",
            str(baseline_quality),
            "--candidate",
            str(candidate_quality),
            "--output",
            str(quality_compare_dir),
            "--fail-on-regression",
        )
        comparison_payload = json.loads((quality_compare_dir / "benchmark-quality-comparison.json").read_text(encoding="utf-8"))
        if comparison_payload.get("summary", {}).get("status") != "passed":
            raise RuntimeError(f"Expected passing quality comparison: {comparison_payload}")
        deltas = comparison_payload.get("summary", {}).get("deltas", {})
        for field in ["avg_toc_match_ratio", "ocr_characters", "structure_repair_decisions", "structure_repair_promoted", "avg_duration_seconds", "max_duration_seconds"]:
            if field not in deltas:
                raise RuntimeError(f"Expected quality comparison delta {field}: {comparison_payload}")

        bad_candidate = root / "bad-candidate-quality.json"
        bad_candidate.write_text(
            json.dumps(
                {
                    "schema_version": "quality-regression-summary-v1",
                    "summary": {
                        "total": 2,
                        "scored": 2,
                        "status_counts": {"ok": 1, "failed": 1},
                        "avg_headings": 0,
                        "avg_characters": 500,
                        "avg_toc_match_ratio": 0.0,
                        "ocr_characters": 50,
                        "structure_repair_decisions": 0,
                        "structure_repair_promoted": 0,
                        "structure_repair_low_confidence": 0,
                        "page_heading_ratio": 0,
                        "repeated_noise_lines": 8,
                        "avg_duration_seconds": 4.0,
                        "max_duration_seconds": 5.0,
                        "fallback_count": 0,
                        "review_or_poor": 2,
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        bad_compare_dir = root / "quality-compare-bad"
        bad = subprocess.run(
            [
                sys.executable,
                str(PROJECT_DIR / "scripts" / "compare_benchmark_quality.py"),
                "--baseline",
                str(baseline_quality),
                "--candidate",
                str(bad_candidate),
                "--output",
                str(bad_compare_dir),
                "--fail-on-regression",
            ],
            cwd=PROJECT_DIR,
            check=False,
        )
        if bad.returncode != 5:
            raise RuntimeError(f"Expected quality comparison regression exit 5, got {bad.returncode}")

        compare_dir = root / "compare"
        run_cmd("compare_pipelines.py", "--input", str(pdf), "--output", str(compare_dir), "--pipelines", "pymupdf4llm", "--overwrite", "--pipeline-timeout", "20")
        if (
            not (compare_dir / "pipeline-comparison.json").exists()
            or not (compare_dir / "pipeline-comparison.md").exists()
            or not (compare_dir / "pipeline-comparison.partial.json").exists()
            or not (compare_dir / "pipeline-comparison.partial.md").exists()
        ):
            raise RuntimeError("Pipeline comparison did not write expected reports.")
        compare_payload = json.loads((compare_dir / "pipeline-comparison.json").read_text(encoding="utf-8"))
        if compare_payload.get("pipeline_timeout_seconds") != 20.0:
            raise RuntimeError(f"Expected pipeline timeout in comparison report: {compare_payload}")

        stress_manifest = root / "stress-samples.json"
        stress_manifest.write_text(
            json.dumps({"schema_version": "benchmark-samples-v1", "samples": [{"id": "sample-pdf", "path": str(pdf), "category": "pdf"}]}, indent=2),
            encoding="utf-8",
        )
        server = start_http_server()
        try:
            stress_dir = root / "stress"
            run_cmd(
                "stress_agent_http.py",
                "--url",
                f"http://127.0.0.1:{server.server_port}",
                "--manifest",
                str(stress_manifest),
                "--output",
                str(stress_dir),
                "--iterations",
                "1",
                "--concurrency",
                "1",
                "--timeout",
                "60",
                "--ocr",
                "never",
                "--pdf-pipeline-mode",
                "pymupdf4llm",
            )
            if not (stress_dir / "agent-stress-results.json").exists():
                raise RuntimeError("Agent stress test did not write expected report.")
        finally:
            server.shutdown()

    print("Benchmark tools smoke test passed.")
    return 0


def run_cmd(script: str, *args: str) -> None:
    subprocess.run([sys.executable, str(PROJECT_DIR / "scripts" / script), *args], check=True, cwd=PROJECT_DIR)


def load_run_benchmarks():
    spec = importlib.util.spec_from_file_location("run_benchmarks", RUN_BENCHMARKS_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {RUN_BENCHMARKS_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def start_http_server():
    from http.server import ThreadingHTTPServer

    server = ThreadingHTTPServer(("127.0.0.1", 0), build_handler(""))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/health", timeout=30).read()
            return server
        except Exception:
            time.sleep(0.1)
    server.shutdown()
    raise RuntimeError("HTTP server did not start")


if __name__ == "__main__":
    raise SystemExit(main())
