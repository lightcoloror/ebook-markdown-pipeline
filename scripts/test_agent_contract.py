from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import fitz

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.artifact_schema import SCHEMA_VERSION
from ebook_markdown_pipeline.ebook_converter_http import build_handler
from ebook_markdown_pipeline.ebook_converter_mcp import call_tool, tool_schemas


REQUIRED_TOOLS = {
    "process_material",
    "get_job_status",
    "read_artifact",
    "inspect_document",
    "scan_books",
    "health_check",
    "start_conversion",
    "start_location_index",
    "query_location_index",
    "export_location_review_pack",
    "start_image_book_rebuild",
}

PROCESS_MATERIAL_FIELDS = {"status", "route", "inspection", "job_id", "warnings", "errors", "next_actions"}
JOB_FIELDS = {
    "job_id",
    "kind",
    "status",
    "started_at",
    "input",
    "output",
    "total",
    "completed",
    "events",
    "results",
    "artifacts",
    "warnings",
    "errors",
    "next_actions",
    "error",
}
ARTIFACT_FIELDS = {"type", "path", "label", "media_type"}
ERROR_FIELDS = {"ok", "error", "code", "message", "retryable", "transport", "schema_version"}


def main() -> int:
    assert_tools()
    with tempfile.TemporaryDirectory(prefix="ebook-agent-contract-") as tmp:
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

        readable = next(item for item in job["artifacts"] if item["type"] == "location_index_jsonl")
        artifact = call_tool("read_artifact", {"path": readable["path"], "artifact_type": readable["type"]})
        if artifact.get("artifact_type") != "location_index_jsonl" or "text" not in artifact:
            raise AssertionError(f"read_artifact contract failed: {artifact}")

        assert_http_contract(image_dir, tmpdir / "http-out")

    print("Agent contract test passed.")
    return 0


def assert_tools() -> None:
    names = {tool["name"] for tool in tool_schemas()}
    missing = sorted(REQUIRED_TOOLS - names)
    if missing:
        raise AssertionError(f"Missing required tools: {missing}")


def poll_job(job_id: str, *, timeout: float = 20) -> dict[str, Any]:
    deadline = time.time() + timeout
    final: dict[str, Any] | None = None
    while time.time() < deadline:
        final = call_tool("get_job_status", {"job_id": job_id})
        if final.get("status") != "running":
            return final
        time.sleep(0.1)
    raise TimeoutError(f"Timed out waiting for job {job_id}: {final}")


def assert_fields(label: str, payload: dict[str, Any], fields: set[str]) -> None:
    missing = sorted(fields - set(payload))
    if missing:
        raise AssertionError(f"{label} missing fields {missing}: {payload}")


def assert_http_contract(input_path: Path, output_path: Path) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), build_handler(""))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        health = http_json(base + "/health")
        if not health.get("supports_async_jobs") or not health.get("supports_artifacts"):
            raise AssertionError(f"HTTP health missing capability flags: {health}")

        ok = http_json(
            base + "/call",
            payload={
                "name": "process_material",
                "arguments": {
                    "input": str(input_path),
                    "output": str(output_path),
                    "recursive": False,
                    "ocr": "never",
                },
            },
        )
        if ok.get("ok") is not True or not isinstance(ok.get("result"), dict) or ok.get("route") != "start_location_index":
            raise AssertionError(f"HTTP ok envelope failed: {ok}")

        invalid = http_json(base + "/call", payload={"name": "missing_contract_tool", "arguments": {}}, allow_http_error=True)
        assert_fields("HTTP error", invalid, ERROR_FIELDS)
        if invalid["code"] != "invalid_request" or invalid["retryable"] is not False or invalid["schema_version"] != SCHEMA_VERSION:
            raise AssertionError(f"HTTP error contract failed: {invalid}")
    finally:
        server.shutdown()


def http_json(url: str, payload: dict[str, Any] | None = None, *, allow_http_error: bool = False) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json; charset=utf-8"} if payload is not None else {}
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if allow_http_error:
            return json.loads(exc.read().decode("utf-8", errors="replace"))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
