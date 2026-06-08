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
    parser.add_argument("--profile", choices=["minimal", "full"], default="minimal")
    parser.add_argument("--fixtures-dir", type=Path, default=GENERATED_FIXTURES)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--reuse-fixtures", action="store_true", help="Do not regenerate public fixtures before running.")
    parser.add_argument("--sample-timeout", type=float, default=90.0)
    parser.add_argument("--pdf-mode-for-benchmark", default="fast", choices=["auto", "fast", "pymupdf4llm", "mineru", "marker", "umi", "docling"])
    parser.add_argument("--min-success-rate", type=float, default=0.95)
    parser.add_argument("--min-good-rate", type=float, default=0.30)
    parser.add_argument("--max-review-poor-rate", type=float, default=0.70)
    parser.add_argument("--max-timeout-rate", type=float, default=0.0)
    parser.add_argument("--max-failed-rate", type=float, default=0.0)
    parser.add_argument("--no-fail-on-quality-gate", action="store_true")
    args = parser.parse_args()

    fixtures_dir = args.fixtures_dir.resolve()
    if not args.reuse_fixtures:
        run([sys.executable, str(PROJECT_DIR / "scripts" / "generate_quality_fixtures.py"), "--output", str(fixtures_dir)])

    manifest = fixtures_dir / f"quality-{args.profile}.json"
    if not manifest.exists():
        raise FileNotFoundError(f"quality fixture manifest not found: {manifest}")

    output = (args.output or DEFAULT_OUTPUT / time.strftime("%Y%m%d-%H%M%S")).resolve()
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
        args.pdf_mode_for_benchmark,
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
                "summary": str(output / "benchmark-summary.md"),
                "quality_summary": str(output / "quality-regression-summary.md"),
                "exit_code": result.returncode,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return result.returncode


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print(subprocess.list2cmdline(command))
    return subprocess.run(command, cwd=PROJECT_DIR, text=True, check=check)


if __name__ == "__main__":
    raise SystemExit(main())
