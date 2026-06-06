from __future__ import annotations

from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]


def main() -> int:
    required = {
        "docs/AGENT_INTEGRATION.md": [
            "--baseline-results",
            "benchmark-quality-comparison.json/md",
            "top-level `next_actions`",
            "copyable recommended rerun command",
            "`selection` block",
            "agent-batch-contract-v1",
            "validate_agent_batch_contract.py",
            "contract_validation",
            "Contract validation",
            "inspect_contract_validation",
            "build_agent_handoff_bundle.py",
            "artifact_summary",
            "inspect_failed_artifacts",
            "`attention`",
            "synthesizes missing",
            "inspect_agent_batch_results",
            "list_agent_batch_results",
            "--fail-on-regression",
            "test_agent_smoke_suite.py",
            "smoke summary fields",
            "agent-smoke-summary.json/md",
            "per-test rerun commands",
            "--fail-fast",
        ],
        "docs/TOOL_CONTRACT.md": [
            "Batch Quality Baselines",
            "--baseline-results",
            "`selection` block",
            "`contract` block",
            "validate_agent_batch_contract.py",
            "contract_validation",
            "Contract validation",
            "inspect_contract_validation",
            "agent-handoff-bundle.json/md",
            "artifact_summary",
            "read_run_summary",
            "`attention` triage block",
            "backward-compatible",
            "rerun_failed_or_review",
            "powershell_command",
            "inspect_agent_batch_results",
            "list_agent_batch_results",
            "completed-with-review",
        ],
        "examples/agent-batch/README.md": [
            "--baseline-results",
            "benchmark-quality-comparison.json/md",
            "machine-readable `selection` block",
            "artifact_summary",
            "inspect_review_items",
            "top-level `next_actions`",
            "copyable recommended rerun command",
            "--fail-on-regression",
        ],
        "examples/agent-batch/AGENT_PROMPT_TEMPLATE.md": [
            "--baseline-results",
            "benchmark-quality-comparison.md",
            "top-level `next_actions`",
            "powershell_command",
            "inspect_agent_batch_results",
            "list_agent_batch_results",
            "Quality comparison status",
        ],
        "README.md": [
            "test_agent_fast_contract.py",
            "test_agent_batch_contract_validator.py",
            "test_agent_handoff_bundle.py",
            "test_agent_smoke_suite.py",
            "summary 报告结构",
            "agent-smoke-summary.json/md",
            "逐条重跑命令",
            "--fail-fast",
            "test_agent_contract.py",
            "inspect_agent_batch_results",
            "list_agent_batch_results",
            "cli_agent_batch_handoff.py",
            "http_agent_batch_handoff.py",
            "完整 agent contract",
        ],
        "examples/agent-calls/README.md": [
            "Agent Batch Handoff",
            "cli_agent_batch_handoff.py list",
            "cli_agent_batch_handoff.py inspect",
            "http_agent_batch_handoff.py",
        ],
    }
    for relative, needles in required.items():
        text = (PROJECT_DIR / relative).read_text(encoding="utf-8")
        missing = [needle for needle in needles if needle not in text]
        if missing:
            raise AssertionError(f"{relative} missing required contract text: {missing}")
    print("Docs contract smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
