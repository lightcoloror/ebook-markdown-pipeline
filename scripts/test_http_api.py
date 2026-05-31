from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the ebook converter HTTP bridge.")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--token", default="")
    parser.add_argument("--input", default=str(Path(__file__).resolve().parents[1] / "requirements.txt"))
    parser.add_argument("--output", default=str(Path(__file__).resolve().parents[1] / "_http_api_test_output"))
    args = parser.parse_args()

    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
    health = request_json(f"{args.url.rstrip('/')}/health", headers=headers)
    if not health.get("ok"):
        raise RuntimeError(f"Health check failed: {health}")

    tools = request_json(f"{args.url.rstrip('/')}/tools", headers=headers)
    tool_names = {item["name"] for item in tools.get("tools", [])}
    if "scan_books" not in tool_names:
        raise RuntimeError(f"scan_books is missing from tools: {tool_names}")

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
    print(json.dumps({"health": health, "scan_count": scan.get("count"), "tool_count": len(tool_names)}, ensure_ascii=False))
    return 0


def request_json(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
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
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
