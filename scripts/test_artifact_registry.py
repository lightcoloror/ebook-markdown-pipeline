from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.artifact_registry import (  # noqa: E402
    JSON_ARTIFACT_TYPES,
    READABLE_ARTIFACT_TYPES,
    REGISTRY_SCHEMA_VERSION,
    artifact_profile_for_type,
    artifact_registry_payload,
    infer_artifact_type,
)
from ebook_markdown_pipeline.ebook_converter_mcp import infer_artifact_type as mcp_infer_artifact_type  # noqa: E402


def main() -> int:
    payload = artifact_registry_payload()
    if payload.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise AssertionError(f"Unexpected artifact registry schema: {payload}")
    if not JSON_ARTIFACT_TYPES.issubset(READABLE_ARTIFACT_TYPES):
        raise AssertionError("JSON artifacts must remain readable artifacts.")

    cases = {
        "agent-handoff-bundle.md": "agent_handoff_bundle_markdown",
        "agent-handoff-bundle.json": "agent_handoff_bundle_json",
        "agent-smoke-summary.json": "agent_smoke_summary_json",
        "ocr_blocks.jsonl": "ocr_blocks_jsonl",
        "location-index.jsonl": "location_index_jsonl",
        "backend-scorecard.json": "optional_backend_scorecard_json",
        "candidate-plan.json": "candidate_benchmark_plan_json",
        "environment-lock-compare.json": "environment_lock_compare_json",
        "table-candidates.json": "table_candidates_json",
        "pypdf-metadata.json": "pdf_metadata_json",
        "notes.txt": "text",
        "page.html": "html",
    }
    for name, expected in cases.items():
        path = Path(name)
        if infer_artifact_type(path) != expected:
            raise AssertionError(f"Expected {expected} for {name}, got {infer_artifact_type(path)}")
        if mcp_infer_artifact_type(path) != expected:
            raise AssertionError(f"MCP compatibility inference changed for {name}")

    profile = artifact_profile_for_type("table_candidates_json")
    if not profile or not profile.json_payload or not profile.readable:
        raise AssertionError(f"Expected table_candidates_json registry profile: {profile}")
    if artifact_profile_for_type("not-a-known-artifact") is not None:
        raise AssertionError("Unknown artifact type should not invent a registry profile.")

    print("Artifact registry contract test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
