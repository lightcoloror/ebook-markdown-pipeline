from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_call_helpers import print_json  # noqa: E402
from ebook_markdown_pipeline.http_config import default_http_url  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect or list agent batch handoff results through the HTTP bridge.")
    parser.add_argument("--url", default=default_http_url())
    parser.add_argument("--token", default="")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Summarize one agent-batch-results.json file.")
    inspect_parser.add_argument("path")
    inspect_parser.add_argument("--max-review-items", type=int, default=10)

    list_parser = subparsers.add_parser("list", help="Find recent agent-batch-results.json files below a root directory.")
    list_parser.add_argument("root")
    list_parser.add_argument("--max-results", type=int, default=10)
    list_parser.add_argument("--max-depth", type=int, default=3)
    list_parser.add_argument("--max-review-items", type=int, default=3)

    args = parser.parse_args()
    if args.command == "inspect":
        print_json(
            call_tool(
                args,
                "inspect_agent_batch_results",
                {"path": args.path, "max_review_items": args.max_review_items},
            )
        )
        return 0
    if args.command == "list":
        print_json(
            call_tool(
                args,
                "list_agent_batch_results",
                {
                    "root": args.root,
                    "max_results": args.max_results,
                    "max_depth": args.max_depth,
                    "max_review_items": args.max_review_items,
                },
            )
        )
        return 0
    raise AssertionError(f"Unhandled command: {args.command}")


def call_tool(args: argparse.Namespace, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    payload = json.dumps({"name": name, "arguments": arguments}, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8", "Accept": "application/json"}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"
    url = args.url.rstrip("/") + "/call"
    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urlopen_local_aware(request, url, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = json.loads(exc.read().decode("utf-8", errors="replace"))
        raise RuntimeError(body) from exc
    if body.get("ok") is False:
        raise RuntimeError(body)
    return body.get("result") if isinstance(body.get("result"), dict) else body


def urlopen_local_aware(request: urllib.request.Request, url: str, *, timeout: float):
    hostname = urllib.parse.urlparse(url).hostname or ""
    if hostname in {"127.0.0.1", "localhost", "::1"}:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open(request, timeout=timeout)
    return urllib.request.urlopen(request, timeout=timeout)


if __name__ == "__main__":
    raise SystemExit(main())
