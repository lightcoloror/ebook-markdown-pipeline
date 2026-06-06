from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import fitz

from test_agent_contract import (  # noqa: E402
    ARTIFACT_FIELDS,
    INSPECTION_FIELDS,
    JOB_FIELDS,
    PROCESS_MATERIAL_FIELDS,
    assert_fields,
    assert_quality_comparison_artifact_read,
    assert_quality_summary_next_actions,
    assert_tools,
    call_tool,
    poll_job,
)

from ebook_markdown_pipeline.artifact_schema import SCHEMA_VERSION  # noqa: E402


def main() -> int:
    assert_tools()
    with tempfile.TemporaryDirectory(prefix="ebook-agent-fast-contract-") as tmp:
        tmpdir = Path(tmp)
        image_dir = tmpdir / "images"
        output_dir = tmpdir / "out"
        image_dir.mkdir()
        pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 80, 80), 0)
        pixmap.clear_with(255)
        pixmap.save(str(image_dir / "shot-001.png"))

        routed = call_tool(
            "process_material",
            {
                "input": str(image_dir),
                "output": str(output_dir),
                "recursive": False,
                "ocr": "never",
            },
        )
        assert_fields("process_material", routed, PROCESS_MATERIAL_FIELDS)
        if routed["status"] != "routed" or routed["route"] != "start_location_index":
            raise AssertionError(f"Unexpected process_material route: {routed}")

        job = poll_job(str(routed["job_id"]))
        assert_fields("job", job, JOB_FIELDS)
        if job["status"] != "done":
            raise AssertionError(f"Job did not finish: {job}")
        if not job["artifacts"]:
            raise AssertionError(f"Job has no artifacts: {job}")
        for item in job["artifacts"]:
            assert_fields("artifact", item, ARTIFACT_FIELDS)
        if not job["results"] or job["results"][0].get("schema_version") != SCHEMA_VERSION:
            raise AssertionError(f"Artifact schema version mismatch: {job['results']}")
        if not isinstance(job.get("warnings"), list) or not isinstance(job.get("errors"), list):
            raise AssertionError(f"Job warnings/errors must be lists: {job}")
        if not isinstance(job.get("next_actions"), list):
            raise AssertionError(f"Job next_actions must be a list: {job}")

        inspection = call_tool("inspect_document", {"input": str(image_dir), "recursive": False})
        assert_fields("inspect_document", inspection, INSPECTION_FIELDS)
        if not isinstance(inspection.get("next_actions"), list) or "mode" not in inspection.get("structure_strategy", {}):
            raise AssertionError(f"inspect_document must expose structure strategy and next actions: {inspection}")

        readable = next(item for item in job["artifacts"] if item["type"] == "location_index_jsonl")
        artifact = call_tool("read_artifact", {"path": readable["path"], "artifact_type": readable["type"]})
        if artifact.get("artifact_type") != "location_index_jsonl" or "text" not in artifact:
            raise AssertionError(f"read_artifact contract failed: {artifact}")

        assert_quality_summary_next_actions(tmpdir)
        assert_quality_comparison_artifact_read(tmpdir)
        assert_agent_batch_results_inspection(tmpdir)
        assert_agent_batch_results_listing(tmpdir)

    print("Agent fast contract test passed.")
    return 0


def assert_agent_batch_results_inspection(tmpdir: Path) -> None:
    batch_dir = tmpdir / "agent-batch"
    batch_dir.mkdir()
    comparison_md = batch_dir / "benchmark-quality-comparison.md"
    comparison_json = batch_dir / "benchmark-quality-comparison.json"
    run_summary = batch_dir / "run_summary.md"
    comparison_md.write_text("# Quality Comparison\n\nfailed", encoding="utf-8")
    comparison_json.write_text(
        json.dumps({"schema_version": "benchmark-quality-comparison-v1", "summary": {"status": "failed"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    run_summary.write_text("# Run Summary\n\n## Recommended Rerun\n", encoding="utf-8")
    results_path = batch_dir / "agent-batch-results.json"
    results_path.write_text(
        json.dumps(
            {
                "schema_version": "agent-batch-v1",
                "manifest": str(tmpdir / "manifest.json"),
                "created_at": "now",
                "duration_seconds": 1.2,
                "partial": False,
                "summary": {"total": 2, "ok": 1, "review": 1, "hard_failed": 0},
                "quality_comparison": {
                    "status": "failed",
                    "markdown": str(comparison_md),
                    "json": str(comparison_json),
                    "summary": {"status": "failed"},
                },
                "next_actions": [
                    {
                        "action": "read_quality_comparison",
                        "tool": "read_artifact",
                        "arguments": {"path": str(comparison_md), "artifact_type": "markdown"},
                    },
                    {
                        "action": "rerun_failed_or_review",
                        "select": "failed-or-review",
                        "rerun_mode": "recommended",
                        "powershell_command": "python runner.py --select failed-or-review --rerun-mode recommended",
                    },
                ],
                "results": [
                    {
                        "id": "review",
                        "status": "review",
                        "input": "input.pdf",
                        "output": "output.md",
                        "job": {
                            "quality_summary": {
                                "review_items": [
                                    {
                                        "source": "input.pdf",
                                        "report": "report.json",
                                        "quality_level": "poor",
                                        "quality_score": 42,
                                        "quality_reasons": ["no headings"],
                                        "suggested_action": "compare pipelines",
                                        "next_actions": [{"action": "compare_pdf_pipelines"}],
                                    }
                                ]
                            }
                        },
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    inspected = call_tool("inspect_agent_batch_results", {"path": str(results_path)})
    if inspected.get("schema_version") != "agent-batch-inspection-v1" or inspected.get("summary", {}).get("review") != 1:
        raise AssertionError(f"Expected agent batch inspection summary: {inspected}")
    if inspected.get("quality_comparison", {}).get("status") != "failed":
        raise AssertionError(f"Expected quality comparison status: {inspected}")
    if inspected.get("recommended_rerun", {}).get("action") != "rerun_failed_or_review":
        raise AssertionError(f"Expected recommended rerun action: {inspected}")
    if not inspected.get("review_items") or inspected["review_items"][0].get("quality_level") != "poor":
        raise AssertionError(f"Expected review item extraction: {inspected}")
    artifact_types = {item.get("type") for item in inspected.get("artifacts") or []}
    if not {"agent_batch_results", "agent_batch_run_summary", "quality_comparison_json"}.issubset(artifact_types):
        raise AssertionError(f"Expected agent batch artifacts: {inspected}")
    readable = call_tool("read_artifact", {"path": str(results_path), "artifact_type": "agent_batch_results"})
    if (readable.get("json") or {}).get("schema_version") != "agent-batch-v1":
        raise AssertionError(f"Expected readable agent batch JSON artifact: {readable}")


def assert_agent_batch_results_listing(tmpdir: Path) -> None:
    first = write_agent_batch_result_fixture(tmpdir / "runs" / "run-001", status="passed", review=0)
    second = write_agent_batch_result_fixture(tmpdir / "runs" / "run-002", status="failed", review=1)
    now = time.time()
    os.utime(first, (now - 100, now - 100))
    os.utime(second, (now, now))
    listed = call_tool("list_agent_batch_results", {"root": str(tmpdir / "runs"), "max_results": 5, "max_depth": 2})
    if listed.get("schema_version") != "agent-batch-list-v1" or listed.get("count") != 2:
        raise AssertionError(f"Expected two listed agent batches: {listed}")
    if Path(listed["items"][0].get("path", "")).resolve() != second.resolve():
        raise AssertionError(f"Expected newest batch first: {listed}")
    action_names = {item.get("action") for item in listed.get("next_actions") or []}
    if "inspect_latest_agent_batch" not in action_names or "rerun_failed_or_review" not in action_names:
        raise AssertionError(f"Expected list next actions for latest failed batch: {listed}")


def write_agent_batch_result_fixture(batch_dir: Path, *, status: str, review: int) -> Path:
    batch_dir.mkdir(parents=True)
    comparison_md = batch_dir / "benchmark-quality-comparison.md"
    comparison_json = batch_dir / "benchmark-quality-comparison.json"
    run_summary = batch_dir / "run_summary.md"
    comparison_md.write_text(f"# Quality Comparison\n\n{status}", encoding="utf-8")
    comparison_json.write_text(
        json.dumps({"schema_version": "benchmark-quality-comparison-v1", "summary": {"status": status}}, ensure_ascii=False),
        encoding="utf-8",
    )
    run_summary.write_text("# Run Summary\n", encoding="utf-8")
    results_path = batch_dir / "agent-batch-results.json"
    next_actions = [
        {
            "action": "read_quality_comparison",
            "tool": "read_artifact",
            "arguments": {"path": str(comparison_md), "artifact_type": "markdown"},
        }
    ]
    if status == "failed":
        next_actions.append(
            {
                "action": "rerun_failed_or_review",
                "select": "failed-or-review",
                "rerun_mode": "recommended",
                "powershell_command": "python runner.py --select failed-or-review --rerun-mode recommended",
            }
        )
    results_path.write_text(
        json.dumps(
            {
                "schema_version": "agent-batch-v1",
                "manifest": str(batch_dir / "manifest.json"),
                "created_at": "now",
                "duration_seconds": 1.2,
                "partial": False,
                "summary": {"total": 2, "ok": 2 - review, "review": review, "hard_failed": 0},
                "quality_comparison": {
                    "status": status,
                    "markdown": str(comparison_md),
                    "json": str(comparison_json),
                    "summary": {"status": status},
                },
                "next_actions": next_actions,
                "results": [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return results_path


if __name__ == "__main__":
    raise SystemExit(main())
