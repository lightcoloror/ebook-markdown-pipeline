from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.ebook_converter_mcp import call_tool  # noqa: E402
from ebook_markdown_pipeline.review_lifecycle import build_review_lifecycle  # noqa: E402


def main() -> int:
    quality_queue = {
        "schema_version": "quality-improvement-queue-v1",
        "summary": {"count": 1},
        "items": [
            {
                "id": "ocr-review",
                "recommended_focus": "ocr_cleanup",
                "quality_level": "review",
                "quality_score": 72,
                "safe_default_action": "Open report before changing OCR backend defaults.",
                "next_step": "Inspect OCR source pages.",
            }
        ],
        "next_actions": [{"action": "open_quality_queue", "tool": "read_artifact"}],
    }
    with tempfile.TemporaryDirectory(prefix="review-lifecycle-") as tmp:
        root = Path(tmp)
        source = root / "quality-improvement-queue.json"
        source.write_text(json.dumps(quality_queue, ensure_ascii=False), encoding="utf-8")
        payload = build_review_lifecycle(source)
        if payload["schema_version"] != "review-lifecycle-v1" or payload["lifecycle_state"] != "needs_manual_review":
            raise AssertionError(f"Expected manual-review lifecycle: {payload}")
        dumped = json.dumps(payload, ensure_ascii=False)
        if str(source) in dumped or "source_path" in payload:
            raise AssertionError(f"Default lifecycle should redact full local paths: {payload}")
        if "do_not_import_into_document_management_system" not in payload.get("blocked_actions", []):
            raise AssertionError(f"Expected DMS import to be blocked: {payload}")

        output = root / "lifecycle"
        completed = subprocess.run(
            [sys.executable, "-B", "scripts/build_review_lifecycle.py", "--source", str(source), "--output", str(output)],
            cwd=PROJECT_DIR,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=True,
        )
        cli_result = json.loads(completed.stdout)
        if cli_result.get("state") != "needs_manual_review" or not (output / "review-lifecycle.md").exists():
            raise AssertionError(f"Unexpected CLI lifecycle result: {cli_result}")

        agent_output = root / "agent-lifecycle"
        agent_result = call_tool(
            "build_review_lifecycle",
            {"source": str(source), "output": str(agent_output), "format": "markdown"},
        )
        if agent_result.get("status") != "ok" or agent_result.get("state") != "needs_manual_review":
            raise AssertionError(f"Unexpected agent lifecycle result: {agent_result}")
        read_result = call_tool(
            "read_artifact",
            {"path": str(agent_output / "review-lifecycle.json"), "artifact_type": "review_lifecycle_json"},
        )
        if (read_result.get("summary") or {}).get("kind") != "review_lifecycle":
            raise AssertionError(f"Expected read_artifact summary for review lifecycle: {read_result}")

    print("Review lifecycle artifact test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
