from __future__ import annotations

import tempfile
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

    print("Agent fast contract test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
