from __future__ import annotations

from pathlib import Path
from typing import Any


SCHEMA_VERSION = "artifact-schema-v1"
JOB_SCHEMA_VERSION = "ebook-job-v1"


def job_payload(
    *,
    job_id: str,
    kind: str,
    status: str,
    started_at: str,
    input_path: str | Path,
    output_path: str | Path,
    total: int | None,
    completed: int = 0,
    finished_at: str | None = None,
    results: list[Any] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    next_actions: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    payload = {
        "schema_version": JOB_SCHEMA_VERSION,
        "artifact_schema_version": SCHEMA_VERSION,
        "job_id": job_id,
        "kind": kind,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "input": str(input_path),
        "output": str(output_path),
        "total": total,
        "completed": completed,
        "events": [],
        "results": list(results or []),
        "artifacts": list(artifacts or []),
        "warnings": list(warnings or []),
        "errors": list(errors or []),
        "next_actions": list(next_actions or []),
        "error": None,
    }
    payload.update(extra)
    return payload


def material_consumer_contract() -> dict[str, Any]:
    return {
        "schema_version": "material-consumer-handoff-v1",
        "supported_consumers": ["bookwiki", "video_knowledge_pipeline"],
        "preferred_artifact_types": ["markdown", "enhanced_markdown", "structure_json", "pages_jsonl"],
        "path_policy": "local_artifact_refs_only",
        "network_transfer_allowed": False,
    }

def artifact(
    artifact_type: str,
    path: str | Path,
    *,
    label: str | None = None,
    media_type: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    item = {
        "type": artifact_type,
        "path": str(path),
    }
    if label:
        item["label"] = label
    if media_type:
        item["media_type"] = media_type
    if description:
        item["description"] = description
    return item


def with_artifacts(payload: dict[str, Any], artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    payload["schema_version"] = SCHEMA_VERSION
    payload["artifacts"] = artifacts
    return payload
