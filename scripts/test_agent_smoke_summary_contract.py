from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from ebook_converter_mcp import infer_artifact_type, read_artifact
from test_agent_smoke_suite import build_summary, render_markdown, tail_text, write_reports


REQUIRED_SUMMARY_FIELDS = {
    "schema_version",
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


def main() -> int:
    assert_passed_summary_contract()
    assert_fail_fast_summary_contract()
    assert_report_artifact_contract()
    assert_tail_contract()
    print("Agent smoke summary contract test passed.")
    return 0


def assert_passed_summary_contract() -> None:
    payload = build_summary(
        [
            {
                "test": "scripts/test_ok.py",
                "returncode": 0,
                "elapsed_seconds": 0.123,
                "stdout_tail": "ok",
                "stderr_tail": "",
            }
        ],
        elapsed=0.456,
        full=False,
        fail_fast=False,
        planned_total=1,
    )
    assert_required_fields(payload)
    expected = {
        "schema_version": "agent-smoke-suite-v1",
        "mode": "fast",
        "status": "passed",
        "fail_fast": False,
        "stopped_early": False,
        "passed": 1,
        "failed": 0,
        "total": 1,
        "planned_total": 1,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise AssertionError(f"Unexpected {key}: {payload}")
    if payload["next_actions"] != []:
        raise AssertionError(f"Passed smoke summary should not request follow-up actions: {payload}")
    markdown = render_markdown(payload)
    for needle in ["# Agent Smoke Suite", "- Status: passed", "- Planned total: 1", "| ok | `scripts/test_ok.py` | 0.123 |"]:
        if needle not in markdown:
            raise AssertionError(f"Markdown report missing {needle!r}: {markdown}")


def assert_fail_fast_summary_contract() -> None:
    payload = build_summary(
        [
            {
                "test": "scripts/test_failed.py",
                "returncode": 1,
                "elapsed_seconds": 1.5,
                "stdout_tail": "partial stdout",
                "stderr_tail": "boom",
            }
        ],
        elapsed=1.6,
        full=True,
        fail_fast=True,
        planned_total=3,
    )
    assert_required_fields(payload)
    if payload["mode"] != "full" or payload["status"] != "failed":
        raise AssertionError(f"Unexpected failed summary mode/status: {payload}")
    if not payload["fail_fast"] or not payload["stopped_early"]:
        raise AssertionError(f"Expected stopped fail-fast summary: {payload}")
    if payload["passed"] != 0 or payload["failed"] != 1 or payload["total"] != 1 or payload["planned_total"] != 3:
        raise AssertionError(f"Unexpected failed summary counts: {payload}")
    actions = {item.get("action"): item for item in payload.get("next_actions") or []}
    if actions.get("inspect_failed_smoke_tests", {}).get("failed_tests") != ["scripts/test_failed.py"]:
        raise AssertionError(f"Expected failed test inspection action: {payload}")
    rerun = actions.get("rerun_failed_smoke_tests", {})
    if rerun.get("commands") != [["python", "-B", "scripts/test_failed.py"]]:
        raise AssertionError(f"Expected per-test rerun command: {payload}")
    markdown = render_markdown(payload)
    for needle in ["- Fail fast: True", "- Stopped early: True", "## Failures", "boom"]:
        if needle not in markdown:
            raise AssertionError(f"Failed markdown report missing {needle!r}: {markdown}")


def assert_report_artifact_contract() -> None:
    payload = build_summary(
        [
            {
                "test": "scripts/test_ok.py",
                "returncode": 0,
                "elapsed_seconds": 0.1,
                "stdout_tail": "",
                "stderr_tail": "",
            }
        ],
        elapsed=0.2,
        full=False,
        fail_fast=False,
        planned_total=1,
    )
    with tempfile.TemporaryDirectory(prefix="ebook-agent-smoke-summary-") as tmp:
        output = Path(tmp)
        write_reports(output, payload)
        summary_json = output / "agent-smoke-summary.json"
        summary_md = output / "agent-smoke-summary.md"
        if not summary_json.exists() or not summary_md.exists():
            raise AssertionError("Expected JSON and Markdown smoke reports")
        persisted = json.loads(summary_json.read_text(encoding="utf-8"))
        artifact_types = {item.get("type") for item in persisted.get("artifacts") or []}
        if artifact_types != {"agent_smoke_summary_json", "agent_smoke_summary_markdown"}:
            raise AssertionError(f"Expected persisted smoke artifacts: {persisted}")
        action_names = [item.get("action") for item in persisted.get("next_actions") or []]
        if action_names[:2] != ["read_smoke_summary_markdown", "read_smoke_summary_json"]:
            raise AssertionError(f"Expected read-report actions first: {persisted}")
        if infer_artifact_type(summary_json) != "agent_smoke_summary_json":
            raise AssertionError("Expected agent-smoke-summary.json to infer agent_smoke_summary_json")
        if infer_artifact_type(summary_md) != "agent_smoke_summary_markdown":
            raise AssertionError("Expected agent-smoke-summary.md to infer agent_smoke_summary_markdown")
        readable_json = read_artifact({"path": str(summary_json), "artifact_type": "agent_smoke_summary_json"})
        if readable_json.get("artifact_type") != "agent_smoke_summary_json" or readable_json.get("json", {}).get("schema_version") != "agent-smoke-suite-v1":
            raise AssertionError(f"Expected readable smoke JSON artifact: {readable_json}")
        readable_md = read_artifact({"path": str(summary_md), "artifact_type": "agent_smoke_summary_markdown"})
        if readable_md.get("artifact_type") != "agent_smoke_summary_markdown" or "# Agent Smoke Suite" not in readable_md.get("text", ""):
            raise AssertionError(f"Expected readable smoke Markdown artifact: {readable_md}")


def assert_tail_contract() -> None:
    text = "x" * 4100
    tailed = tail_text(text, max_chars=4000)
    if len(tailed) != 4000 or tailed != text[-4000:]:
        raise AssertionError("tail_text must keep the rightmost max_chars characters")
    if tail_text("  short  ") != "short":
        raise AssertionError("tail_text must strip short text")


def assert_required_fields(payload: dict) -> None:
    missing = sorted(REQUIRED_SUMMARY_FIELDS - set(payload))
    if missing:
        raise AssertionError(f"Summary payload missing fields: {missing}")


if __name__ == "__main__":
    raise SystemExit(main())
