from __future__ import annotations

import json
import time
from typing import Any, Callable


def print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def poll_job(call_tool: Callable[[str, dict[str, Any]], dict[str, Any]], job_id: str, *, interval: float = 0.5, timeout: float = 300) -> dict[str, Any]:
    deadline = time.time() + timeout
    final: dict[str, Any] | None = None
    while time.time() < deadline:
        final = call_tool("get_job_status", {"job_id": job_id})
        status = final.get("status")
        if status != "running":
            return final
        time.sleep(interval)
    raise TimeoutError(f"Job did not finish within {timeout} seconds: {job_id}. Last status: {final}")


def first_readable_artifact(job: dict[str, Any]) -> dict[str, Any] | None:
    preferred = {"markdown", "html", "text", "summary_report", "review_report", "location_index_jsonl", "order_report"}
    for item in job.get("artifacts", []):
        if item.get("type") in preferred and item.get("path"):
            return item
    return None


def run_material_flow(call_tool: Callable[[str, dict[str, Any]], dict[str, Any]], arguments: dict[str, Any], *, timeout: float = 300) -> dict[str, Any]:
    routed = call_tool("process_material", arguments)
    if routed.get("status") == "unsupported":
        return {"routed": routed, "job": None, "artifact": None}
    job_id = routed.get("job_id")
    if not job_id:
        return {"routed": routed, "job": None, "artifact": None}
    job = poll_job(call_tool, str(job_id), timeout=timeout)
    artifact = first_readable_artifact(job)
    artifact_payload = None
    if artifact:
        artifact_payload = call_tool("read_artifact", {"path": artifact["path"], "artifact_type": artifact["type"], "max_chars": 4000, "max_lines": 120})
    return {"routed": routed, "job": job, "artifact": artifact_payload}
