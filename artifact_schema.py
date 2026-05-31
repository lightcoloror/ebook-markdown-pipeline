from __future__ import annotations

from pathlib import Path
from typing import Any


SCHEMA_VERSION = "artifact-schema-v1"


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
