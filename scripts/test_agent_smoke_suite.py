from __future__ import annotations

import argparse
import json
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
    "scripts/test_agent_batch_contract_validator.py",
    "scripts/test_agent_handoff_bundle.py",
    "scripts/test_agent_fast_contract.py",
    "scripts/test_agent_smoke_summary_contract.py",
    "scripts/test_mcp_stdio.py",
    "scripts/test_http_api.py",
    "scripts/test_docs_contract.py",
]
FULL_TESTS = FAST_TESTS + ["scripts/test_agent_contract.py"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the agent-facing smoke test suite.")
    parser.add_argument("--full", action="store_true", help="Also run the slower full agent contract test.")
    parser.add_argument("--fail-fast", action="store_true", help="Stop after the first failing smoke test.")
    parser.add_argument("--output", type=Path, help="Optional directory for agent-smoke-summary.json/md.")
    args = parser.parse_args()

    tests = FULL_TESTS if args.full else FAST_TESTS
    results = []
    started = time.monotonic()
    for test in tests:
        result = run_test(test)
        results.append(result)
        if args.fail_fast and result["returncode"] != 0:
            break
    failures = [item for item in results if item["returncode"] != 0]
    payload = build_summary(
        results,
        elapsed=time.monotonic() - started,
        full=bool(args.full),
        fail_fast=bool(args.fail_fast),
        planned_total=len(tests),
    )
    print_summary(payload)
    if args.output:
        write_reports(args.output, payload)
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
        "stdout_tail": tail_text(completed.stdout),
        "stderr_tail": tail_text(completed.stderr),
    }


def build_summary(results: list[dict], *, elapsed: float, full: bool, fail_fast: bool, planned_total: int) -> dict:
    passed = sum(1 for item in results if item["returncode"] == 0)
    failed = len(results) - passed
    stopped_early = len(results) < planned_total
    return {
        "schema_version": "agent-smoke-suite-v1",
        "mode": "full" if full else "fast",
        "status": "passed" if failed == 0 else "failed",
        "fail_fast": fail_fast,
        "stopped_early": stopped_early,
        "passed": passed,
        "failed": failed,
        "total": len(results),
        "planned_total": planned_total,
        "elapsed_seconds": round(elapsed, 3),
        "results": results,
        "next_actions": smoke_next_actions(results),
    }


def print_summary(payload: dict) -> None:
    print(
        "Agent smoke suite finished: "
        f"passed={payload['passed']}, failed={payload['failed']}, elapsed={payload['elapsed_seconds']:.1f}s"
    )
    if payload["failed"]:
        failed_tests = ", ".join(item["test"] for item in payload["results"] if item["returncode"] != 0)
        print(f"Failed tests: {failed_tests}")


def write_reports(output: Path, payload: dict) -> None:
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "agent-smoke-summary.json"
    md_path = output / "agent-smoke-summary.md"
    payload = with_report_artifacts(payload, json_path=json_path, md_path=md_path)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")
    print(f"Wrote agent smoke reports: {json_path}; {md_path}")


def smoke_next_actions(results: list[dict]) -> list[dict]:
    failures = [item for item in results if item["returncode"] != 0]
    if not failures:
        return []
    failed_tests = [item["test"] for item in failures]
    return [
        {
            "action": "inspect_failed_smoke_tests",
            "failed_tests": failed_tests,
            "reason": "One or more agent smoke tests failed; inspect stdout_tail/stderr_tail before rerunning.",
        },
        {
            "action": "rerun_failed_smoke_tests",
            "commands": [["python", "-B", test] for test in failed_tests],
            "reason": "Rerun each failed smoke test directly after inspecting the failure tail.",
        },
    ]


def with_report_artifacts(payload: dict, *, json_path: Path, md_path: Path) -> dict:
    enriched = dict(payload)
    existing_actions = list(enriched.get("next_actions") or [])
    enriched["artifacts"] = [
        {"type": "agent_smoke_summary_json", "path": str(json_path)},
        {"type": "agent_smoke_summary_markdown", "path": str(md_path)},
    ]
    enriched["next_actions"] = [
        {
            "action": "read_smoke_summary_markdown",
            "path": str(md_path),
            "artifact_type": "markdown",
            "reason": "Use the Markdown report for a quick handoff-readable overview.",
        },
        {
            "action": "read_smoke_summary_json",
            "path": str(json_path),
            "artifact_type": "agent_smoke_summary_json",
            "reason": "Use the JSON report for machine-readable status and failure tails.",
        },
        *existing_actions,
    ]
    return enriched


def render_markdown(payload: dict) -> str:
    lines = [
        "# Agent Smoke Suite",
        "",
        f"- Mode: {payload['mode']}",
        f"- Status: {payload['status']}",
        f"- Fail fast: {payload['fail_fast']}",
        f"- Stopped early: {payload['stopped_early']}",
        f"- Passed: {payload['passed']}",
        f"- Failed: {payload['failed']}",
        f"- Total: {payload['total']}",
        f"- Planned total: {payload['planned_total']}",
        f"- Elapsed seconds: {payload['elapsed_seconds']}",
        "",
        "| Status | Test | Seconds |",
        "| --- | --- | ---: |",
    ]
    for item in payload["results"]:
        status = "ok" if item["returncode"] == 0 else "failed"
        lines.append(f"| {status} | `{item['test']}` | {item['elapsed_seconds']} |")
    failures = [item for item in payload["results"] if item["returncode"] != 0]
    if failures:
        lines.extend(["", "## Failures", ""])
        for item in failures:
            lines.append(f"### {item['test']}")
            if item.get("stdout_tail"):
                lines.extend(["", "```text", item["stdout_tail"], "```"])
            if item.get("stderr_tail"):
                lines.extend(["", "```text", item["stderr_tail"], "```"])
    return "\n".join(lines).rstrip() + "\n"


def tail_text(text: str, *, max_chars: int = 4000) -> str:
    stripped = text.strip()
    if len(stripped) <= max_chars:
        return stripped
    return stripped[-max_chars:]


if __name__ == "__main__":
    raise SystemExit(main())
