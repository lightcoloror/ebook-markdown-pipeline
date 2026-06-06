from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

import stress_agent_http as stress


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="agent-stress-runner-") as tmp:
        root = Path(tmp)
        archive = root / "archive"
        visual_check = archive / "visual_check"
        visual_check.mkdir(parents=True)
        result_path = visual_check / "visual_check_result.json"
        result_path.write_text(json.dumps({"schema_version": 1, "status": "pending_visual_engine"}), encoding="utf-8")

        def fake_call_tool(args: argparse.Namespace, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            if name == "process_material":
                return {
                    "status": "routed",
                    "route": "process_web_archive",
                    "delegated": {
                        "status": "pending_visual_engine",
                        "artifacts": [{"type": "visual_check_json", "path": str(result_path)}],
                    },
                }
            if name == "read_artifact":
                return {
                    "path": arguments["path"],
                    "artifact_type": arguments.get("artifact_type"),
                    "json": json.loads(Path(arguments["path"]).read_text(encoding="utf-8")),
                }
            raise AssertionError(f"Unexpected tool call: {name}")

        stress.call_tool = fake_call_tool
        args = argparse.Namespace(
            output=root / "out",
            ocr="never",
            intent="auto",
            pdf_pipeline_mode="auto",
            docling_timeout=None,
            pdf_tool_idle_timeout=None,
            pdf_tool_finalize_timeout=None,
            query="",
        )
        result = stress.run_iteration(args, {"id": "archive", "path": str(archive), "category": "web_archive"}, 1)
        if result.get("status") != "review" or not result.get("artifact_read"):
            raise AssertionError(f"Expected synchronous web archive stress iteration to read artifact: {result}")
        summary = stress.summarize([result])
        if summary.get("counts", {}).get("review") != 1 or summary.get("counts", {}).get("artifact_reads") != 1:
            raise AssertionError(f"Expected review status and artifact read in summary: {summary}")

    print("Agent stress runner smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
