from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]

FAST_TESTS = [
    "scripts/test_agent_call_helpers.py",
    "scripts/test_agent_batch_runner.py",
    "scripts/test_agent_batch_handoff_cli.py",
    "scripts/test_agent_batch_handoff_http.py",
    "scripts/test_agent_fast_contract.py",
    "scripts/test_mcp_stdio.py",
    "scripts/test_http_api.py",
    "scripts/test_docs_contract.py",
]
FULL_TESTS = FAST_TESTS + ["scripts/test_agent_contract.py"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the agent-facing smoke test suite.")
    parser.add_argument("--full", action="store_true", help="Also run the slower full agent contract test.")
    args = parser.parse_args()

    tests = FULL_TESTS if args.full else FAST_TESTS
    results = []
    started = time.monotonic()
    for test in tests:
        results.append(run_test(test))
    failures = [item for item in results if item["returncode"] != 0]
    print_summary(results, elapsed=time.monotonic() - started)
    return 1 if failures else 0


def run_test(relative: str) -> dict:
    started = time.monotonic()
    completed = subprocess.run(
        [sys.executable, "-B", relative],
        cwd=PROJECT_DIR,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    elapsed = time.monotonic() - started
    status = "ok" if completed.returncode == 0 else "failed"
    print(f"[{status}] {relative} ({elapsed:.1f}s)")
    if completed.stdout.strip():
        print(completed.stdout.rstrip())
    if completed.stderr.strip():
        print(completed.stderr.rstrip())
    return {
        "test": relative,
        "returncode": completed.returncode,
        "elapsed_seconds": round(elapsed, 3),
    }


def print_summary(results: list[dict], *, elapsed: float) -> None:
    passed = sum(1 for item in results if item["returncode"] == 0)
    failed = len(results) - passed
    print(f"Agent smoke suite finished: passed={passed}, failed={failed}, elapsed={elapsed:.1f}s")
    if failed:
        failed_tests = ", ".join(item["test"] for item in results if item["returncode"] != 0)
        print(f"Failed tests: {failed_tests}")


if __name__ == "__main__":
    raise SystemExit(main())
