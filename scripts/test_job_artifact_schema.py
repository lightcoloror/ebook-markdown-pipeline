from __future__ import annotations

import sys
import tempfile
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.artifact_schema import JOB_SCHEMA_VERSION, SCHEMA_VERSION, artifact, job_payload, material_consumer_contract  # noqa: E402
from ebook_markdown_pipeline.ebook_converter_mcp import create_job, get_job_status  # noqa: E402


def assert_job_contract(payload: dict) -> None:
    if payload.get("schema_version") != JOB_SCHEMA_VERSION:
        raise AssertionError(f"Unexpected job schema: {payload}")
    if payload.get("artifact_schema_version") != SCHEMA_VERSION:
        raise AssertionError(f"Unexpected artifact schema: {payload}")
    required = {"job_id", "kind", "status", "input", "output", "total", "completed", "results", "artifacts", "warnings", "errors", "next_actions"}
    missing = required.difference(payload)
    if missing:
        raise AssertionError(f"Job payload missing fields {sorted(missing)}: {payload}")
    for item in payload.get("artifacts") or []:
        if not {"type", "path"}.issubset(item):
            raise AssertionError(f"Invalid artifact ref: {item}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="job-artifact-schema-") as tmp:
        root = Path(tmp)
        markdown = root / "output.md"
        markdown.write_text("# Synthetic\n", encoding="utf-8")
        direct = job_payload(
            job_id="cli-test",
            kind="conversion",
            status="done",
            started_at="2026-07-10 00:00:00",
            finished_at="2026-07-10 00:00:01",
            input_path=root / "input.txt",
            output_path=root,
            total=1,
            completed=1,
            artifacts=[artifact("markdown", markdown, media_type="text/markdown")],
        )
        assert_job_contract(direct)

        job_id = create_job("conversion", input_path=root / "input.txt", output_path=root, total=1)
        mcp_job = get_job_status({"job_id": job_id})
        assert_job_contract(mcp_job)

    consumer = material_consumer_contract()
    if consumer.get("schema_version") != "material-consumer-handoff-v1":
        raise AssertionError(f"Unexpected consumer contract: {consumer}")
    if consumer.get("network_transfer_allowed") is not False:
        raise AssertionError(f"Consumer contract must remain local-only: {consumer}")

    print("Job and artifact schema contract test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
