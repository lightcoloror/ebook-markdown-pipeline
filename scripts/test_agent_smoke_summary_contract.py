from __future__ import annotations

from test_agent_smoke_suite import build_summary, render_markdown, tail_text


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
}


def main() -> int:
    assert_passed_summary_contract()
    assert_fail_fast_summary_contract()
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
    markdown = render_markdown(payload)
    for needle in ["- Fail fast: True", "- Stopped early: True", "## Failures", "boom"]:
        if needle not in markdown:
            raise AssertionError(f"Failed markdown report missing {needle!r}: {markdown}")


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
