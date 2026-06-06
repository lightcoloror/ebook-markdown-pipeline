from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ebook_markdown_pipeline.http_config import default_http_url  # noqa: E402
from agent_call_helpers import print_json, run_material_flow  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Call process_material through the HTTP bridge.")
    parser.add_argument("--url", default=default_http_url())
    parser.add_argument("--token", default="")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--query", default="")
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()

    def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps({"name": name, "arguments": arguments}, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json; charset=utf-8", "Accept": "application/json"}
        if args.token:
            headers["Authorization"] = f"Bearer {args.token}"
        request = urllib.request.Request(args.url.rstrip("/") + "/call", data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8", errors="replace"))
            raise RuntimeError(body) from exc
        return body.get("result") if isinstance(body.get("result"), dict) else body

    material_args = {"input": args.input, "output": args.output, "recursive": True}
    if args.query:
        material_args["query"] = args.query
    print_json(run_material_flow(call_tool, material_args, timeout=args.timeout))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
