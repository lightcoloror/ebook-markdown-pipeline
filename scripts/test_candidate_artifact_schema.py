from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.candidate_artifact_schema import (  # noqa: E402
    CANDIDATE_ARTIFACT_SCHEMA_VERSION,
    candidate_artifact_schema_payload,
    summarize_candidate_artifact,
    validate_candidate_artifact,
)


def main() -> int:
    registry = candidate_artifact_schema_payload()
    if registry.get("schema_version") != CANDIDATE_ARTIFACT_SCHEMA_VERSION:
        raise AssertionError(f"Unexpected schema registry: {registry}")
    if registry.get("remote_call_enabled") or registry.get("model_install_enabled"):
        raise AssertionError(f"Candidate artifact schemas must be non-executing: {registry}")
    artifact_types = {item.get("artifact_type") for item in registry.get("schemas") or []}
    expected = {"layout_candidates_json", "table_candidates_json", "formula_candidates_json", "document_vlm_result_json"}
    if not expected.issubset(artifact_types):
        raise AssertionError(f"Missing candidate artifact schemas: {registry}")

    layout = {
        "schema_version": "layout-candidates-v1",
        "backend": "doclayout_yolo",
        "status": "review",
        "pages": [{"page": 1, "blocks": [{"label": "title"}, {"label": "table"}]}],
    }
    validation = validate_candidate_artifact(layout, "layout_candidates_json")
    if validation.get("ok") is not True or validation.get("summary", {}).get("block_count") != 2:
        raise AssertionError(f"Expected valid layout artifact: {validation}")
    summary = summarize_candidate_artifact(layout, "layout_candidates_json")
    if summary.get("promotion_use", "").find("silently mutate") < 0:
        raise AssertionError(f"Expected promotion guidance in summary: {summary}")

    invalid = {"schema_version": "table-candidates-v1", "backend": "pdf_table", "pages": [{"tables": "bad"}]}
    invalid_result = validate_candidate_artifact(invalid, "table_candidates_json")
    if invalid_result.get("ok") is not False or not invalid_result.get("errors"):
        raise AssertionError(f"Expected invalid table artifact errors: {invalid_result}")

    unknown = validate_candidate_artifact({"schema_version": "mystery"}, "")
    if unknown.get("ok") is not False or "unknown" not in " ".join(unknown.get("errors") or []):
        raise AssertionError(f"Expected unknown schema failure: {unknown}")
    print("Candidate artifact schema contract test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
