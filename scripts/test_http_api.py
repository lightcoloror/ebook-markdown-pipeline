from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))
from ebook_markdown_pipeline.http_config import default_http_url  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the ebook converter HTTP bridge.")
    parser.add_argument("--url", default=default_http_url())
    parser.add_argument("--token", default="")
    parser.add_argument("--input", default=str(Path(__file__).resolve().parents[1] / "requirements.txt"))
    parser.add_argument("--output", default=str(Path(__file__).resolve().parents[1] / "_http_api_test_output"))
    args = parser.parse_args()

    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
    health = request_json(f"{args.url.rstrip('/')}/health", headers=headers)
    if not health.get("ok"):
        raise RuntimeError(f"Health check failed: {health}")
    if not health.get("supports_async_jobs") or not health.get("supports_artifacts"):
        raise RuntimeError(f"Health response is missing capability flags: {health}")
    if "read_artifact" not in set(health.get("tools", [])):
        raise RuntimeError(f"Health response is missing tool names: {health}")

    tools = request_json(f"{args.url.rstrip('/')}/tools", headers=headers)
    tool_names = {item["name"] for item in tools.get("tools", [])}
    required = {
        "scan_books",
        "inspect_document",
        "process_material",
        "process_web_archive",
        "read_artifact",
        "start_location_index",
        "export_location_review_pack",
        "start_image_book_rebuild",
        "rebuild_image_book_from_order",
    }
    missing_tools = required - tool_names
    if missing_tools:
        raise RuntimeError(f"Missing tools: {sorted(missing_tools)}")

    scan = request_json(
        f"{args.url.rstrip('/')}/call",
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
        f"{args.url.rstrip('/')}/call",
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
        f"{args.url.rstrip('/')}/call",
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
            },
            ensure_ascii=False,
        )
    )
    return 0


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
