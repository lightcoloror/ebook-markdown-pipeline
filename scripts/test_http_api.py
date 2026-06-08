from __future__ import annotations

import argparse
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))
from ebook_markdown_pipeline.ebook_converter_http import build_handler  # noqa: E402
from ebook_markdown_pipeline.http_config import default_http_url  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the graphic-text material converter HTTP bridge.")
    parser.add_argument("--url", default="", help=f"Existing bridge URL. If omitted, start an in-process server. Config default: {default_http_url()}")
    parser.add_argument("--token", default="")
    parser.add_argument("--input", default=str(Path(__file__).resolve().parents[1] / "requirements.txt"))
    parser.add_argument("--output", default=str(Path(__file__).resolve().parents[1] / "_http_api_test_output"))
    args = parser.parse_args()

    server: ThreadingHTTPServer | None = None
    url = args.url
    if not url:
        server = start_local_server(args.token)
        url = f"http://127.0.0.1:{server.server_port}"

    try:
        run_http_smoke(url, args)
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
    return 0


def run_http_smoke(url: str, args: argparse.Namespace) -> None:
    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
    health = request_json(f"{url.rstrip('/')}/health", headers=headers)
    if not health.get("ok"):
        raise RuntimeError(f"Health check failed: {health}")
    if health.get("display_name") != "图文材料转换器":
        raise RuntimeError(f"Health response has wrong display name: {health}")
    if not health.get("supports_async_jobs") or not health.get("supports_artifacts"):
        raise RuntimeError(f"Health response is missing capability flags: {health}")
    health_tool_names = set(health.get("tools", []))
    if not {"get_agent_contract", "read_artifact", "inspect_agent_batch_results", "list_agent_batch_results", "build_agent_handoff_bundle"}.issubset(health_tool_names):
        raise RuntimeError(f"Health response is missing tool names: {health}")
    http_config = health.get("http_config") or {}
    if not http_config.get("config_path") or not http_config.get("local_url") or not http_config.get("docker_url"):
        raise RuntimeError(f"Health response is missing HTTP config: {health}")
    if not isinstance(health.get("pipeline_capabilities"), dict) or health.get("risk_status") not in {"ok", "degraded", "missing_dependencies"}:
        raise RuntimeError(f"Health response is missing capability/risk summary: {health}")
    if not health.get("config_sources", {}).get("http") or not health.get("config_sources", {}).get("example_env"):
        raise RuntimeError(f"Health response is missing config sources: {health}")
    if not health.get("config_sources", {}).get("local_env") or "local_env_exists" not in health or "local_env_loaded_keys" not in health:
        raise RuntimeError(f"Health response is missing local env status: {health}")
    if health.get("route_defaults", {}).get("images") != "start_image_book_rebuild":
        raise RuntimeError(f"Health response should expose recognition-first route defaults: {health}")
    if not health.get("long_task_guidance", {}).get("prefer_async_tools"):
        raise RuntimeError(f"Health response is missing long task guidance: {health}")

    contract = request_json(f"{url.rstrip('/')}/contract", headers=headers)
    if contract.get("schema_version") != "ebook-http-contract-v1" or contract.get("transport") != "http":
        raise RuntimeError(f"HTTP contract response has wrong schema: {contract}")
    if contract.get("display_name") != "图文材料转换器":
        raise RuntimeError(f"HTTP contract has wrong display name: {contract}")
    if contract.get("entrypoints")[:3] != ["process_material", "get_job_status", "read_artifact"]:
        raise RuntimeError(f"HTTP contract entrypoints are wrong: {contract}")
    if not contract.get("supports_async_jobs") or not contract.get("supports_artifacts"):
        raise RuntimeError(f"HTTP contract missing capability flags: {contract}")
    if contract.get("tool_count", 0) < 10 or not isinstance(contract.get("tools"), list):
        raise RuntimeError(f"HTTP contract missing tool schemas: {contract}")
    if contract.get("route_defaults", {}).get("location_index") != "requires intent=locate or query":
        raise RuntimeError(f"HTTP contract missing route defaults: {contract}")
    if not contract.get("config_sources", {}).get("local_env") or "local_env_exists" not in contract:
        raise RuntimeError(f"HTTP contract missing local env status: {contract}")
    if not contract.get("pipeline_capabilities", {}).get("capabilities"):
        raise RuntimeError(f"HTTP contract missing pipeline capabilities: {contract}")
    if not contract.get("long_task_guidance", {}).get("poll_tool"):
        raise RuntimeError(f"HTTP contract missing long task guidance: {contract}")
    contract_tool_names = {item.get("name") for item in contract.get("tools") or []}
    if not {"get_agent_contract", "process_material", "read_artifact", "build_agent_handoff_bundle"}.issubset(contract_tool_names):
        raise RuntimeError(f"HTTP contract missing key tools: {contract}")
    docs = contract.get("docs") or {}
    if not docs.get("tool_contract") or not docs.get("agent_integration"):
        raise RuntimeError(f"HTTP contract missing docs pointers: {contract}")
    error_contract = contract.get("error_contract") or {}
    if error_contract.get("schema_version") != health.get("schema_version") or error_contract.get("transport") != "http":
        raise RuntimeError(f"HTTP contract missing error contract: {contract}")

    tools = request_json(f"{url.rstrip('/')}/tools", headers=headers)
    tool_names = {item["name"] for item in tools.get("tools", [])}
    required = {
        "get_agent_contract",
        "scan_books",
        "inspect_document",
        "process_material",
        "process_web_archive",
        "read_artifact",
        "inspect_agent_batch_results",
        "list_agent_batch_results",
        "build_agent_handoff_bundle",
        "start_location_index",
        "export_location_review_pack",
        "start_image_book_rebuild",
        "rebuild_image_book_from_order",
    }
    missing_tools = required - tool_names
    if missing_tools:
        raise RuntimeError(f"Missing tools: {sorted(missing_tools)}")

    scan = request_json(
        f"{url.rstrip('/')}/call",
        method="POST",
        headers=headers,
        payload={
            "name": "scan_books",
            "arguments": {
                "input": args.input,
                "output": args.output,
                "recursive": False,
            },
        },
    )
    if scan.get("error"):
        raise RuntimeError(scan)
    inspected = request_json(
        f"{url.rstrip('/')}/call",
        method="POST",
        headers=headers,
        payload={
            "name": "inspect_document",
            "arguments": {
                "input": args.input,
                "recursive": False,
            },
        },
    )
    if inspected.get("error"):
        raise RuntimeError(inspected)
    invalid = request_json(
        f"{url.rstrip('/')}/call",
        method="POST",
        headers=headers,
        payload={"name": "missing_tool_for_contract_test", "arguments": {}},
        allow_http_error=True,
    )
    if invalid.get("code") != "invalid_request" or invalid.get("retryable") is not False:
        raise RuntimeError(f"HTTP error contract failed: {invalid}")
    print(
        json.dumps(
            {
                "health": health,
                "scan_count": scan.get("count"),
                "inspect_status": inspected.get("status"),
                "tool_count": len(tool_names),
                "url": url,
            },
            ensure_ascii=False,
        )
    )


def start_local_server(token: str) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), build_handler(token))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/contract"
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            request_json(url, headers={"Authorization": f"Bearer {token}"} if token else {})
            return server
        except Exception:
            time.sleep(0.1)
    server.shutdown()
    server.server_close()
    raise RuntimeError("In-process HTTP server did not expose /contract in time.")


def request_json(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    allow_http_error: bool = False,
) -> dict[str, Any]:
    data = None
    request_headers = {"Accept": "application/json", **(headers or {})}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if allow_http_error:
            return json.loads(body)
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
