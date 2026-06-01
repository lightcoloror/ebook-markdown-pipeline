from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_call_helpers import print_json, run_material_flow  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Call process_material through MCP stdio.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--query", default="")
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()

    project_dir = Path(__file__).resolve().parents[2]
    workspace_root = project_dir.parent
    proc = subprocess.Popen(
        [sys.executable, "-m", "ebook_markdown_pipeline.ebook_converter_mcp"],
        cwd=workspace_root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    next_id = 1

    def rpc(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        nonlocal next_id
        if proc.stdin is None or proc.stdout is None:
            raise RuntimeError("MCP process pipes are not available")
        request = {"jsonrpc": "2.0", "id": next_id, "method": method}
        next_id += 1
        if params is not None:
            request["params"] = params
        proc.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
        proc.stdin.flush()
        response = json.loads(proc.stdout.readline())
        if "error" in response:
            raise RuntimeError(response["error"])
        return response["result"]

    def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = rpc("tools/call", {"name": name, "arguments": arguments})
        return json.loads(result["content"][0]["text"])

    try:
        rpc("initialize")
        material_args: dict[str, Any] = {"input": args.input, "output": args.output, "recursive": True}
        if args.query:
            material_args["query"] = args.query
        print_json(run_material_flow(call_tool, material_args, timeout=args.timeout))
    finally:
        proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
