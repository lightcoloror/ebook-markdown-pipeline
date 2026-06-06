from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark_utils import now, write_json  # noqa: E402
from run_benchmarks import quality_regression_summary  # noqa: E402


SCHEMA_VERSION = "benchmark-quality-comparison-v1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two benchmark quality reports and flag regressions.")
    parser.add_argument("--baseline", type=Path, required=True, help="Baseline benchmark-results.json or quality-regression-summary.json.")
    parser.add_argument("--candidate", type=Path, required=True, help="Candidate benchmark-results.json or quality-regression-summary.json.")
    parser.add_argument("--output", type=Path, required=True, help="Output directory for comparison JSON/Markdown.")
    parser.add_argument("--min-success-rate-delta", type=float, default=-0.001, help="Allowed candidate-baseline success rate delta.")
    parser.add_argument("--min-good-rate-delta", type=float, default=-0.05, help="Allowed candidate-baseline good rate delta.")
    parser.add_argument("--max-review-poor-delta", type=float, default=0.05, help="Allowed candidate-baseline review/poor rate delta.")
    parser.add_argument("--max-timeout-rate-delta", type=float, default=0.001, help="Allowed candidate-baseline timeout rate delta.")
    parser.add_argument("--max-failed-rate-delta", type=float, default=0.001, help="Allowed candidate-baseline failed rate delta.")
    parser.add_argument("--fail-on-regression", action="store_true", help="Exit non-zero when regression status is failed.")
    args = parser.parse_args()

    payload = compare_reports(args)
    args.output.mkdir(parents=True, exist_ok=True)
    write_json(args.output / "benchmark-quality-comparison.json", payload)
    (args.output / "benchmark-quality-comparison.md").write_text(render_markdown(payload), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 5 if args.fail_on_regression and payload["summary"]["status"] == "failed" else 0


def compare_reports(args: argparse.Namespace) -> dict[str, Any]:
    baseline = load_quality_report(args.baseline)
    candidate = load_quality_report(args.candidate)
    baseline_metrics = comparison_metrics(baseline)
    candidate_metrics = comparison_metrics(candidate)
    deltas = {
        name: round(candidate_metrics.get(name, 0) - baseline_metrics.get(name, 0), 3)
        for name in sorted(set(baseline_metrics) | set(candidate_metrics))
    }
    checks = regression_checks(args, deltas)
    status = "passed" if all(item["passed"] for item in checks) else "failed"
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": now(),
        "baseline": {"path": str(args.baseline), **baseline},
        "candidate": {"path": str(args.candidate), **candidate},
        "summary": {
            "status": status,
            "baseline_metrics": baseline_metrics,
            "candidate_metrics": candidate_metrics,
            "deltas": deltas,
            "checks": checks,
        },
    }


def load_quality_report(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if payload.get("schema_version") == "quality-regression-summary-v1":
        return {
            "schema_version": payload.get("schema_version"),
            "created_at": payload.get("created_at"),
            "manifest": payload.get("manifest", ""),
            "summary": payload.get("summary") or {},
            "quality_gates": payload.get("quality_gates") or {},
        }
    if payload.get("schema_version") == "benchmark-run-v1" or payload.get("results"):
        report = quality_regression_summary(payload)
        return {
            "schema_version": report.get("schema_version"),
            "created_at": report.get("created_at"),
            "manifest": report.get("manifest", ""),
            "summary": report.get("summary") or {},
            "quality_gates": report.get("quality_gates") or {},
        }
    raise ValueError(f"Unsupported benchmark quality input: {path}")


def comparison_metrics(report: dict[str, Any]) -> dict[str, float]:
    summary = report.get("summary") or {}
    status_counts = summary.get("status_counts") or {}
    total = int(summary.get("total") or sum(int(value) for value in status_counts.values()) or 0)
    scored = int(summary.get("scored") or 0)
    review_or_poor = int(summary.get("review_or_poor") or 0)
    good = max(scored - review_or_poor, 0)
    headings = float(summary.get("avg_headings") or 0)
    characters = float(summary.get("avg_characters") or 0)
    return {
        "success_rate": ratio(int(status_counts.get("ok", 0)), total),
        "good_rate": ratio(good, scored),
        "review_poor_rate": ratio(review_or_poor, scored),
        "timeout_rate": ratio(int(status_counts.get("timeout", 0)), total),
        "failed_rate": ratio(int(status_counts.get("failed", 0)), total),
        "avg_headings": round(headings, 3),
        "avg_characters": round(characters, 3),
        "page_heading_ratio": float(summary.get("page_heading_ratio") or 0),
        "repeated_noise_lines": float(summary.get("repeated_noise_lines") or 0),
        "fallback_count": float(summary.get("fallback_count") or 0),
        "total": float(total),
        "scored": float(scored),
    }


def regression_checks(args: argparse.Namespace, deltas: dict[str, float]) -> list[dict[str, Any]]:
    specs = [
        ("success_rate", ">=", args.min_success_rate_delta),
        ("good_rate", ">=", args.min_good_rate_delta),
        ("review_poor_rate", "<=", args.max_review_poor_delta),
        ("timeout_rate", "<=", args.max_timeout_rate_delta),
        ("failed_rate", "<=", args.max_failed_rate_delta),
    ]
    checks = []
    for name, operator, threshold in specs:
        actual = deltas.get(name, 0.0)
        passed = actual >= threshold if operator == ">=" else actual <= threshold
        checks.append({"name": name, "operator": operator, "threshold": threshold, "actual_delta": actual, "passed": passed})
    return checks


def ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 3) if denominator else 0.0


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Benchmark Quality Comparison",
        "",
        f"- Created: {payload['created_at']}",
        f"- Status: {summary['status']}",
        f"- Baseline: `{payload['baseline']['path']}`",
        f"- Candidate: `{payload['candidate']['path']}`",
        "",
        "## Metrics",
        "",
        "| Metric | Baseline | Candidate | Delta |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name in sorted(summary["deltas"]):
        lines.append(
            f"| {name} | {summary['baseline_metrics'].get(name, '')} | "
            f"{summary['candidate_metrics'].get(name, '')} | {summary['deltas'].get(name, '')} |"
        )
    lines.extend(["", "## Regression Checks", "", "| Check | Rule | Threshold | Actual delta | Passed |", "| --- | --- | ---: | ---: | --- |"])
    for item in summary["checks"]:
        lines.append(
            f"| {item['name']} | delta {item['operator']} threshold | "
            f"{item['threshold']} | {item['actual_delta']} | {item['passed']} |"
        )
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
