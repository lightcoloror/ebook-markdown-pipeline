from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
GENERATED_FIXTURES = PROJECT_DIR / "benchmarks" / "fixtures" / "generated"
DEFAULT_OUTPUT = PROJECT_DIR / "benchmarks" / "runs" / "quality-gate"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the public quality regression gate.")
    parser.add_argument("--profile", choices=["minimal", "full", "backend-compare", "release"], default="minimal")
    parser.add_argument("--fixtures-dir", type=Path, default=GENERATED_FIXTURES)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--reuse-fixtures", action="store_true", help="Compatibility flag; existing fixture manifests are reused by default.")
    parser.add_argument("--regenerate-fixtures", action="store_true", help="Force regeneration of public fixtures before running.")
    parser.add_argument("--sample-timeout", type=float, default=90.0)
    parser.add_argument("--pdf-mode-for-benchmark", default="fast", choices=["auto", "fast", "pymupdf4llm", "mineru", "marker", "umi", "docling", "markitdown", "ocrmypdf", "pdfcraft"])
    parser.add_argument("--document-mode-for-benchmark", default="auto", choices=["auto", "docling", "markitdown"])
    parser.add_argument("--min-success-rate", type=float, default=0.95)
    parser.add_argument("--min-good-rate", type=float, default=0.30)
    parser.add_argument("--max-review-poor-rate", type=float, default=0.70)
    parser.add_argument("--max-timeout-rate", type=float, default=0.0)
    parser.add_argument("--max-failed-rate", type=float, default=0.0)
    parser.add_argument("--no-fail-on-quality-gate", action="store_true")
    parser.add_argument("--no-update-latest", action="store_true", help="Do not update benchmarks/runs/latest when running the release profile.")
    args = parser.parse_args()

    fixtures_dir = args.fixtures_dir.resolve()
    manifest_profile = "minimal" if args.profile in {"backend-compare", "release"} else args.profile
    manifest = fixtures_dir / f"quality-{manifest_profile}.json"
    if should_generate_fixtures(args, manifest):
        run([sys.executable, str(PROJECT_DIR / "scripts" / "generate_quality_fixtures.py"), "--output", str(fixtures_dir)])
    if not manifest.exists():
        raise FileNotFoundError(f"quality fixture manifest not found: {manifest}")

    output = (args.output or DEFAULT_OUTPUT / time.strftime("%Y%m%d-%H%M%S")).resolve()
    if args.profile == "release":
        return run_release_profile(args, fixtures_dir, output)
    if args.profile == "backend-compare":
        return run_backend_compare(args, manifest, output)

    document_mode = args.document_mode_for_benchmark
    pdf_mode = args.pdf_mode_for_benchmark
    command = [
        sys.executable,
        str(PROJECT_DIR / "scripts" / "run_benchmarks.py"),
        "--manifest",
        str(manifest),
        "--output",
        str(output),
        "--sample-timeout",
        str(args.sample_timeout),
        "--pdf-mode-for-benchmark",
        pdf_mode,
        "--document-mode-for-benchmark",
        document_mode,
        "--min-success-rate",
        str(args.min_success_rate),
        "--min-good-rate",
        str(args.min_good_rate),
        "--max-review-poor-rate",
        str(args.max_review_poor_rate),
        "--max-timeout-rate",
        str(args.max_timeout_rate),
        "--max-failed-rate",
        str(args.max_failed_rate),
    ]
    if not args.no_fail_on_quality_gate:
        command.append("--fail-on-quality-gate")
    result = run(command, check=False)
    print(
        json.dumps(
            {
                "profile": args.profile,
                "manifest": str(manifest),
                "output": str(output),
                "pdf_mode_for_benchmark": pdf_mode,
                "document_mode_for_benchmark": document_mode,
                "summary": str(output / "benchmark-summary.md"),
                "quality_summary": str(output / "quality-regression-summary.md"),
                "exit_code": result.returncode,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return result.returncode


def should_generate_fixtures(args: argparse.Namespace, manifest: Path) -> bool:
    if bool(getattr(args, "regenerate_fixtures", False)):
        return True
    if bool(getattr(args, "reuse_fixtures", False)):
        return False
    return not manifest.exists()


def run_release_profile(args: argparse.Namespace, fixtures_dir: Path, output: Path) -> int:
    output.mkdir(parents=True, exist_ok=True)
    minimal_manifest = fixtures_dir / "quality-minimal.json"
    minimal_output = output / "minimal"
    backend_output = output / "backend-compare"
    ocr_output = output / "ocr-provider-comparison"
    backend_scorecard_output = output / "backend-scorecard"
    docs_output = output / "docs-contract"
    public_output = output / "public-release"

    minimal = run_benchmark_command(
        manifest=minimal_manifest,
        output=minimal_output,
        sample_timeout=args.sample_timeout,
        pdf_mode=args.pdf_mode_for_benchmark,
        document_mode=args.document_mode_for_benchmark,
        args=args,
        fail_on_quality_gate=not args.no_fail_on_quality_gate,
    )
    backend_args = argparse.Namespace(**vars(args))
    backend_args.no_fail_on_quality_gate = True
    backend = run_backend_compare(backend_args, minimal_manifest, backend_output)
    ocr = run(
        [
            sys.executable,
            str(PROJECT_DIR / "scripts" / "compare_ocr_providers.py"),
            str(fixtures_dir / "images"),
            "--recursive",
            "--providers",
            "rapidocr",
            "umi",
            "--output",
            str(ocr_output),
        ],
        check=False,
    )
    backend_scorecard = run(
        [
            sys.executable,
            str(PROJECT_DIR / "scripts" / "generate_backend_scorecard.py"),
            "--output",
            str(backend_scorecard_output),
        ],
        check=False,
    )
    docs = run(
        [sys.executable, str(PROJECT_DIR / "scripts" / "test_docs_contract.py")],
        check=False,
    )
    docs_output.mkdir(parents=True, exist_ok=True)
    (docs_output / "docs-contract.txt").write_text((docs.stdout or "") + (docs.stderr or ""), encoding="utf-8")
    public = run(
        [
            sys.executable,
            str(PROJECT_DIR / "scripts" / "check_public_release.py"),
            "--output",
            str(public_output),
            "--run-smoke",
        ],
        check=False,
    )
    backend_comparison_summary = load_quality_comparison_summary(backend_output / "backend-comparison" / "benchmark-quality-comparison.json")
    regression_tags = sorted(set(backend_comparison_summary.get("regression_tags") or []))
    payload = {
        "schema_version": "quality-gate-release-v1",
        "profile": "release",
        "output": str(output),
        "regression_tags": regression_tags,
        "quality_comparison": {
            "backend_compare": backend_comparison_summary,
        },
        "steps": [
            release_step("minimal", minimal.returncode, minimal_output / "quality-regression-summary.md"),
            release_step(
                "backend_compare",
                backend,
                backend_output / "backend-comparison" / "benchmark-quality-comparison.md",
                extra={"regression_tags": regression_tags},
            ),
            release_step("ocr_provider_comparison", ocr.returncode, ocr_output / "ocr-provider-comparison.md"),
            release_step("optional_backend_scorecard", backend_scorecard.returncode, backend_scorecard_output / "backend-scorecard.md"),
            release_step("docs_contract", docs.returncode, docs_output / "docs-contract.txt"),
            release_step("public_release", public.returncode, public_output / "public-release-check.md"),
        ],
    }
    payload["summary"] = {
        "status": "passed" if all(int(step["exit_code"]) == 0 for step in payload["steps"]) else "failed",
        "failed_steps": [step["name"] for step in payload["steps"] if int(step["exit_code"]) != 0],
    }
    write_release_reports(output, payload)
    if not bool(getattr(args, "no_update_latest", False)):
        write_latest_release_index(payload)
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return first_nonzero([int(step["exit_code"]) for step in payload["steps"]])


def load_quality_comparison_summary(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"status": "missing", "regression_tags": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"status": "unreadable", "regression_tags": [], "message": str(exc)}
    summary = payload.get("summary") if isinstance(payload, dict) else {}
    if not isinstance(summary, dict):
        return {"status": "invalid", "regression_tags": []}
    return {
        "status": summary.get("status", "unknown"),
        "regression_tags": list(summary.get("regression_tags") or []),
        "deltas": summary.get("deltas") or {},
    }


def release_step(name: str, exit_code: int, report: Path, *, extra: dict[str, object] | None = None) -> dict[str, object]:
    payload = {
        "name": name,
        "exit_code": exit_code,
        "status": "passed" if exit_code == 0 else "failed",
        "report": str(report),
    }
    if extra:
        payload.update(extra)
    return payload


def write_release_reports(output: Path, payload: dict) -> None:
    (output / "release-summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Release Quality Gate",
        "",
        f"- Status: {payload['summary']['status']}",
        f"- Output: `{payload['output']}`",
        f"- Regression tags: {', '.join(payload.get('regression_tags') or []) or 'none'}",
        "",
        "| Step | Status | Exit | Report |",
        "| --- | --- | ---: | --- |",
    ]
    for step in payload["steps"]:
        lines.append(f"| {step['name']} | {step['status']} | {step['exit_code']} | `{step['report']}` |")
    (output / "release-summary.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_latest_release_index(payload: dict) -> None:
    latest = PROJECT_DIR / "benchmarks" / "runs" / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    (latest / "release-index.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Latest Release Quality Gate",
        "",
        f"- Status: {payload['summary']['status']}",
        f"- Output: `{payload['output']}`",
        f"- Failed steps: {', '.join(payload['summary'].get('failed_steps') or []) or 'none'}",
        f"- Regression tags: {', '.join(payload.get('regression_tags') or []) or 'none'}",
    ]
    (latest / "release-index.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def run_backend_compare(args: argparse.Namespace, manifest: Path, output: Path) -> int:
    baseline_output = output / "baseline"
    candidate_output = output / "markitdown"
    comparison_output = output / "backend-comparison"
    fail_on_quality_gate = not args.no_fail_on_quality_gate

    baseline = run_benchmark_command(
        manifest=manifest,
        output=baseline_output,
        sample_timeout=args.sample_timeout,
        pdf_mode=args.pdf_mode_for_benchmark,
        document_mode=args.document_mode_for_benchmark,
        args=args,
        fail_on_quality_gate=fail_on_quality_gate,
    )
    candidate = run_benchmark_command(
        manifest=manifest,
        output=candidate_output,
        sample_timeout=args.sample_timeout,
        pdf_mode="markitdown",
        document_mode="markitdown",
        args=args,
        fail_on_quality_gate=fail_on_quality_gate,
    )
    comparison = run(
        [
            sys.executable,
            str(PROJECT_DIR / "scripts" / "compare_benchmark_quality.py"),
            "--baseline",
            str(baseline_output / "quality-regression-summary.json"),
            "--candidate",
            str(candidate_output / "quality-regression-summary.json"),
            "--output",
            str(comparison_output),
        ],
        check=False,
    )
    exit_code = first_nonzero([baseline.returncode, candidate.returncode, comparison.returncode])
    print(
        json.dumps(
            {
                "profile": args.profile,
                "manifest": str(manifest),
                "output": str(output),
                "baseline": {
                    "output": str(baseline_output),
                    "pdf_mode_for_benchmark": args.pdf_mode_for_benchmark,
                    "document_mode_for_benchmark": args.document_mode_for_benchmark,
                    "quality_summary": str(baseline_output / "quality-regression-summary.md"),
                    "exit_code": baseline.returncode,
                },
                "candidate": {
                    "output": str(candidate_output),
                    "pdf_mode_for_benchmark": "markitdown",
                    "document_mode_for_benchmark": "markitdown",
                    "quality_summary": str(candidate_output / "quality-regression-summary.md"),
                    "exit_code": candidate.returncode,
                },
                "comparison": {
                    "output": str(comparison_output),
                    "summary": str(comparison_output / "benchmark-quality-comparison.md"),
                    "exit_code": comparison.returncode,
                },
                "exit_code": exit_code,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return exit_code


def run_benchmark_command(
    *,
    manifest: Path,
    output: Path,
    sample_timeout: float,
    pdf_mode: str,
    document_mode: str,
    args: argparse.Namespace,
    fail_on_quality_gate: bool,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(PROJECT_DIR / "scripts" / "run_benchmarks.py"),
        "--manifest",
        str(manifest),
        "--output",
        str(output),
        "--sample-timeout",
        str(sample_timeout),
        "--pdf-mode-for-benchmark",
        pdf_mode,
        "--document-mode-for-benchmark",
        document_mode,
        "--min-success-rate",
        str(args.min_success_rate),
        "--min-good-rate",
        str(args.min_good_rate),
        "--max-review-poor-rate",
        str(args.max_review_poor_rate),
        "--max-timeout-rate",
        str(args.max_timeout_rate),
        "--max-failed-rate",
        str(args.max_failed_rate),
    ]
    if fail_on_quality_gate:
        command.append("--fail-on-quality-gate")
    return run(command, check=False)


def first_nonzero(codes: list[int]) -> int:
    for code in codes:
        if code:
            return code
    return 0


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print(subprocess.list2cmdline(command))
    return subprocess.run(command, cwd=PROJECT_DIR, text=True, check=check)


if __name__ == "__main__":
    raise SystemExit(main())
