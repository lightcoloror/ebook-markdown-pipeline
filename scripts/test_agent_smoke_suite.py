from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]

FAST_TESTS = [
    "scripts/test_local_env.py",
    "scripts/test_agent_call_helpers.py",
    "scripts/test_minimal_entrypoints.py",
    "scripts/test_agent_batch_runner.py",
    "scripts/test_agent_batch_handoff_cli.py",
    "scripts/test_agent_batch_handoff_http.py",
    "scripts/test_agent_batch_contract_validator.py",
    "scripts/test_agent_handoff_bundle.py",
    "scripts/test_online_providers.py",
    "scripts/test_run_online_enhancement_cli.py",
    "scripts/test_show_latest_quality_gate.py",
    "scripts/test_prepare_github_release_notes.py",
    "scripts/test_enhance_markdown_structure_cli.py",
    "scripts/test_agent_fast_contract.py",
    "scripts/test_agent_smoke_summary_contract.py",
    "scripts/test_mcp_stdio.py",
    "scripts/test_http_api.py",
    "scripts/test_docs_contract.py",
    "scripts/check_project_readiness.py",
]
FULL_TESTS = FAST_TESTS + ["scripts/test_agent_contract.py"]
AGENT_SMOKE_SCHEMA_VERSION = "agent-smoke-suite-v1"
AGENT_SMOKE_CONTRACT_VERSION = "agent-smoke-suite-contract-v1"
AGENT_SMOKE_CONTRACT_CAPABILITIES = [
    "mode_summary",
    "fail_fast_summary",
    "per_test_results",
    "failure_tails",
    "readable_artifacts",
    "rerun_failed_tests",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the agent-facing smoke test suite.")
    parser.add_argument("--full", action="store_true", help="Also run the slower full agent contract test.")
    parser.add_argument("--fail-fast", action="store_true", help="Stop after the first failing smoke test.")
    parser.add_argument("--list", action="store_true", help="List planned smoke tests as JSON without running them.")
    parser.add_argument("--output", type=Path, help="Optional directory for agent-smoke-summary.json/md.")
    args = parser.parse_args()

    tests = FULL_TESTS if args.full else FAST_TESTS
    if args.list:
        print_test_list(tests, full=bool(args.full))
        return 0
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


def print_test_list(tests: list[str], *, full: bool) -> None:
    payload = {
        "schema_version": "agent-smoke-suite-list-v1",
        "mode": "full" if full else "fast",
        "count": len(tests),
        "tests": tests,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def run_test(relative: str) -> dict:
    started = time.monotonic()
    completed = subprocess.run(
        [sys.executable, "-B", relative],
        cwd=PROJECT_DIR,
        text=True,
        encoding="utf-8",
        errors="replace",
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
    payload = {
        "schema_version": AGENT_SMOKE_SCHEMA_VERSION,
        "contract": agent_smoke_contract(),
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
    payload["contract_validation"] = validate_agent_smoke_contract(payload)
    return payload


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


def agent_smoke_contract() -> dict:
    return {
        "name": "ebook-markdown-pipeline-agent-smoke-suite",
        "schema_version": AGENT_SMOKE_CONTRACT_VERSION,
        "payload_schema_version": AGENT_SMOKE_SCHEMA_VERSION,
        "runner": str(Path(__file__).resolve()),
        "capabilities": AGENT_SMOKE_CONTRACT_CAPABILITIES,
        "required_fields": [
            "schema_version",
            "contract",
            "mode",
            "status",
            "fail_fast",
            "stopped_early",
            "passed",
            "failed",
            "total",
            "planned_total",
            "elapsed_seconds",
            "results",
            "next_actions",
        ],
    }


def validate_agent_smoke_contract(payload: dict) -> dict:
    errors: list[str] = []
    required = {
        "schema_version",
        "contract",
        "mode",
        "status",
        "fail_fast",
        "stopped_early",
        "passed",
        "failed",
        "total",
        "planned_total",
        "elapsed_seconds",
        "results",
        "next_actions",
    }
    missing = sorted(field for field in required if field not in payload)
    if missing:
        errors.append(f"missing required fields: {', '.join(missing)}")
    if payload.get("schema_version") != AGENT_SMOKE_SCHEMA_VERSION:
        errors.append(f"schema_version must be {AGENT_SMOKE_SCHEMA_VERSION}")
    contract = payload.get("contract") or {}
    if contract.get("schema_version") != AGENT_SMOKE_CONTRACT_VERSION:
        errors.append(f"contract.schema_version must be {AGENT_SMOKE_CONTRACT_VERSION}")
    if contract.get("payload_schema_version") != payload.get("schema_version"):
        errors.append("contract.payload_schema_version must match payload schema_version")
    missing_capabilities = sorted(set(AGENT_SMOKE_CONTRACT_CAPABILITIES) - set(contract.get("capabilities") or []))
    if missing_capabilities:
        errors.append(f"missing capabilities: {', '.join(missing_capabilities)}")
    missing_declared = sorted(required - set(contract.get("required_fields") or []))
    if missing_declared:
        errors.append(f"contract.required_fields missing: {', '.join(missing_declared)}")
    return {
        "ok": not errors,
        "schema_version": payload.get("schema_version"),
        "contract_schema_version": contract.get("schema_version"),
        "errors": errors,
    }


def with_report_artifacts(payload: dict, *, json_path: Path, md_path: Path) -> dict:
    enriched = dict(payload)
    existing_actions = list(enriched.get("next_actions") or [])
    enriched["contract_validation"] = validate_agent_smoke_contract(enriched)
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
    contract_validation = payload.get("contract_validation") or validate_agent_smoke_contract(payload)
    lines = [
        "# Agent Smoke Suite",
        "",
        f"- Mode: {payload['mode']}",
        f"- Status: {payload['status']}",
        f"- Contract validation: {'ok' if contract_validation.get('ok') else 'failed'}",
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
