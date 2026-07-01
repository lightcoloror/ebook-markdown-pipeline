from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
CLI_PATH = PROJECT_DIR / "examples" / "agent-calls" / "cli_agent_batch_handoff.py"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="agent-batch-handoff-cli-") as tmp:
        root = Path(tmp)
        batch_dir = root / "run-001"
        batch_dir.mkdir()
        comparison_md = batch_dir / "benchmark-quality-comparison.md"
        comparison_json = batch_dir / "benchmark-quality-comparison.json"
        comparison_md.write_text("# Quality Comparison\n\nfailed", encoding="utf-8")
        comparison_json.write_text(
            json.dumps({"schema_version": "benchmark-quality-comparison-v1", "summary": {"status": "failed"}}, ensure_ascii=False),
            encoding="utf-8",
        )
        results_path = batch_dir / "agent-batch-results.json"
        results_path.write_text(
            json.dumps(
                {
                    "schema_version": "agent-batch-v1",
                    "contract": agent_batch_contract(),
                    "manifest": str(root / "manifest.json"),
                    "created_at": "now",
                    "summary": {"total": 1, "ok": 0, "review": 1, "hard_failed": 0},
                    "selection": {"select": "all", "selected_count": 1, "manifest_job_count": 1},
                    "artifact_summary": {"total": 0, "ok": 0, "failed": 0, "type_counts": {}, "failed_artifacts": []},
                    "quality_comparison": {
                        "status": "failed",
                        "markdown": str(comparison_md),
                        "json": str(comparison_json),
                    },
                    "next_actions": [
                        {
                            "action": "rerun_failed_or_review",
                            "select": "failed-or-review",
                            "rerun_mode": "recommended",
                            "powershell_command": "python runner.py --select failed-or-review --rerun-mode recommended",
                        }
                    ],
                    "results": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        inspected = run_cli("inspect", str(results_path))
        if inspected.get("schema_version") != "agent-batch-inspection-v1" or inspected.get("recommended_rerun", {}).get("action") != "rerun_failed_or_review":
            raise AssertionError(f"Unexpected inspect output: {inspected}")

        listed = run_cli("list", str(root), "--max-depth", "2")
        if listed.get("schema_version") != "agent-batch-list-v1" or listed.get("count") != 1:
            raise AssertionError(f"Unexpected list output: {listed}")
        if listed.get("items", [{}])[0].get("summary", {}).get("review") != 1:
            raise AssertionError(f"Expected listed review summary: {listed}")

        bundled = run_cli("bundle", "--batch-results", str(results_path), "--output", str(root / "handoff"))
        if bundled.get("schema_version") != "agent-handoff-bundle-tool-v1" or bundled.get("bundle", {}).get("contract_validation", {}).get("ok") is not True:
            raise AssertionError(f"Unexpected bundle output: {bundled}")
        if not (root / "handoff" / "agent-handoff-bundle.json").exists() or not (root / "handoff" / "agent-handoff-bundle.md").exists():
            raise AssertionError(f"Expected bundle artifacts on disk: {bundled}")

    print("Agent batch handoff CLI smoke test passed.")
    return 0


def run_cli(*args: str) -> dict:
    completed = subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        cwd=PROJECT_DIR,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)


def agent_batch_contract() -> dict:
    return {
        "name": "ebook-markdown-pipeline-agent-batch",
        "schema_version": "agent-batch-contract-v1",
        "payload_schema_version": "agent-batch-v1",
        "runner": "test_agent_batch_handoff_cli.py",
        "capabilities": [
            "selection_summary",
            "artifact_summary",
            "handoff_next_actions",
            "attention_summary",
            "legacy_action_synthesis",
            "quality_comparison",
            "recommended_rerun",
        ],
        "required_fields": [
            "schema_version",
            "contract",
            "manifest",
            "created_at",
            "summary",
            "selection",
            "artifact_summary",
            "next_actions",
            "results",
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
