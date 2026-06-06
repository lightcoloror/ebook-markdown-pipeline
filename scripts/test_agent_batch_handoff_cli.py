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
                    "manifest": str(root / "manifest.json"),
                    "summary": {"total": 1, "ok": 0, "review": 1, "hard_failed": 0},
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

    print("Agent batch handoff CLI smoke test passed.")
    return 0


def run_cli(*args: str) -> dict:
    completed = subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        cwd=PROJECT_DIR,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
