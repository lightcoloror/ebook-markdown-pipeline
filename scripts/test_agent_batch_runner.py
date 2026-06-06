from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
RUNNER_PATH = PROJECT_DIR / "examples" / "agent-batch" / "agent_batch_http.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("agent_batch_http", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load runner: {RUNNER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    runner = load_runner()
    with tempfile.TemporaryDirectory(prefix="agent-batch-runner-") as tmp:
        root = Path(tmp)
        visual_check = root / "archive" / "visual_check"
        visual_check.mkdir(parents=True)
        result_path = visual_check / "visual_check_result.json"
        result_path.write_text(json.dumps({"schema_version": 1, "status": "pending_visual_engine"}), encoding="utf-8")
        layout_path = visual_check / "layout_ocr.md"
        layout_path.write_text("# Visual OCR Pending\n", encoding="utf-8")

        seen_material_args: list[dict[str, Any]] = []

        def fake_call_tool(args: argparse.Namespace, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            if name == "process_material":
                seen_material_args.append(dict(arguments))
                return {
                    "status": "routed",
                    "route": "process_web_archive",
                    "delegated": {
                        "status": "pending_visual_engine",
                        "artifacts": [
                            {"type": "visual_check_json", "path": str(result_path)},
                            {"type": "markdown", "path": str(layout_path)},
                        ],
                        "next_actions": [
                            {
                                "tool": "read_artifact",
                                "arguments": {"path": str(result_path), "artifact_type": "visual_check_json"},
                            }
                        ],
                    },
                }
            if name == "read_artifact":
                path = Path(arguments["path"])
                payload = {
                    "path": str(path),
                    "artifact_type": arguments.get("artifact_type"),
                    "text": path.read_text(encoding="utf-8"),
                }
                if arguments.get("artifact_type") == "visual_check_json":
                    payload["json"] = json.loads(path.read_text(encoding="utf-8"))
                return payload
            raise AssertionError(f"Unexpected fake tool call: {name}")

        runner.call_tool = fake_call_tool
        args = argparse.Namespace(artifact_max_chars=4000, artifact_max_lines=120, rerun_mode="as-manifest")
        result = runner.run_manifest_job(
            args,
            {},
            {"id": "archive", "input": str(root / "archive"), "output": str(root / "out")},
            1,
        )
        if result.get("status") != "review":
            raise AssertionError(f"Expected pending visual archive to become review status: {result}")
        artifacts = result.get("artifacts") or []
        if len(artifacts) != 2 or not all(item.get("status") == "ok" for item in artifacts):
            raise AssertionError(f"Expected readable synchronous artifacts: {result}")
        summary = runner.summarize([result])
        if summary.get("review") != 1 or summary.get("failed") != 0 or summary.get("hard_failed") != 0 or summary.get("artifact_reads") != 2:
            raise AssertionError(f"Expected review status to be non-failed but artifact-readable: {summary}")
        report_payload = runner.write_reports(root / "reports", root / "manifest.json", 0.0, [result], partial=False)
        if not (root / "reports" / "run_summary.md").exists():
            raise AssertionError(f"Expected run_summary.md to be written: {report_payload}")

        previous_payload = {
            "results": [
                {
                    "id": "archive",
                    "status": "review",
                    "job": {
                        "quality_summary": {
                            "review_items": [
                                {
                                    "next_actions": [
                                        {"action": "rerun", "pipeline": "pymupdf4llm"},
                                    ]
                                }
                            ]
                        }
                    },
                },
                {"id": "ok-job", "status": "ok"},
            ]
        }
        selected = runner.select_jobs(
            [{"id": "archive", "input": str(root / "archive"), "output": str(root / "out")}, {"id": "ok-job", "input": "x", "output": "y"}],
            previous_payload,
            "review",
        )
        if [item.get("id") for item in selected] != ["archive"]:
            raise AssertionError(f"Expected only review job to be selected: {selected}")

        args.rerun_mode = "recommended"
        runner.run_manifest_job(
            args,
            {},
            {"id": "archive", "input": str(root / "archive"), "output": str(root / "out")},
            1,
            previous_payload=previous_payload,
        )
        if seen_material_args[-1].get("pdf_pipeline_mode") != "pymupdf4llm":
            raise AssertionError(f"Expected recommended rerun pipeline to be applied: {seen_material_args[-1]}")

    print("Agent batch runner smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
