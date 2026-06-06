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
            "--fail-on-regression",
        ],
        "docs/TOOL_CONTRACT.md": [
            "Batch Quality Baselines",
            "--baseline-results",
            "rerun_failed_or_review",
            "powershell_command",
            "completed-with-review",
        ],
        "examples/agent-batch/README.md": [
            "--baseline-results",
            "benchmark-quality-comparison.json/md",
            "top-level `next_actions`",
            "copyable recommended rerun command",
            "--fail-on-regression",
        ],
        "examples/agent-batch/AGENT_PROMPT_TEMPLATE.md": [
            "--baseline-results",
            "benchmark-quality-comparison.md",
            "top-level `next_actions`",
            "powershell_command",
            "Quality comparison status",
        ],
        "README.md": [
            "test_agent_fast_contract.py",
            "test_agent_contract.py",
            "完整 agent contract",
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
