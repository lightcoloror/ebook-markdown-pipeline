from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the ebook converter MCP stdio server.")
    parser.add_argument("--convert", action="store_true", help="Run a tiny real TXT conversion after scan.")
    args = parser.parse_args()

    project_dir = Path(__file__).resolve().parents[1]
    workspace_root = project_dir.parent
    server_module = "ebook_markdown_pipeline.ebook_converter_mcp"

    with tempfile.TemporaryDirectory(prefix="ebook-mcp-smoke-") as tmp:
        tmpdir = Path(tmp)
        input_file = tmpdir / "sample.txt"
        output_dir = tmpdir / "out"
        input_file.write_text("# Sample\n\nThis is a tiny MCP smoke test.\n", encoding="utf-8")

        proc = subprocess.Popen(
            [sys.executable, "-m", server_module],
            cwd=workspace_root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        try:
            initialize = call(proc, 1, "initialize")
            assert initialize["result"]["serverInfo"]["name"] == "ebook-markdown-pipeline"

            tools = call(proc, 2, "tools/list")
            tool_names = {item["name"] for item in tools["result"]["tools"]}
            required_tools = {
                "scan_books",
                "health_check",
                "start_conversion",
                "get_job_status",
                "read_report",
                "read_pdf_tool_log",
                "build_location_index",
                "query_location_index",
            }
            missing = sorted(required_tools - tool_names)
            if missing:
                raise RuntimeError(f"Missing MCP tools: {missing}")

            scan = call_tool(
                proc,
                3,
                "scan_books",
                {
                    "input": str(input_file),
                    "output": str(output_dir),
                    "recursive": False,
                },
            )
            if scan["count"] != 1:
                raise RuntimeError(f"Expected one scanned file, got {scan['count']}")

            if args.convert:
                start = call_tool(
                    proc,
                    4,
                    "start_conversion",
                    {
                        "input": str(input_file),
                        "output": str(output_dir),
                        "overwrite": True,
                    },
                )
                job_id = start["job_id"]
                final = poll_job(proc, job_id)
                if final["status"] != "done":
                    raise RuntimeError(f"Conversion job did not finish: {final}")

            location_dir = tmpdir / "locations"
            location = call_tool(
                proc,
                80,
                "build_location_index",
                {
                    "input": str(input_file),
                    "output": str(location_dir),
                    "recursive": False,
                    "ocr": "never",
                },
            )
            if location["record_count"] != 0:
                raise RuntimeError(f"TXT should not be indexed by the location indexer: {location}")

            print("MCP stdio smoke test passed.")
            return 0
        finally:
            proc.kill()


def call(proc: subprocess.Popen[str], request_id: int, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    if proc.stdin is None or proc.stdout is None:
        raise RuntimeError("MCP subprocess pipes are not available.")
    request = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
    proc.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    if not line:
        stderr = proc.stderr.read() if proc.stderr is not None else ""
        raise RuntimeError(f"MCP server closed stdout. stderr={stderr}")
    response = json.loads(line)
    if "error" in response:
        raise RuntimeError(response["error"])
    return response


def call_tool(proc: subprocess.Popen[str], request_id: int, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    response = call(proc, request_id, "tools/call", {"name": name, "arguments": arguments})
    content = response["result"]["content"][0]["text"]
    payload = json.loads(content)
    if payload.get("error"):
        raise RuntimeError(payload)
    return payload


def poll_job(proc: subprocess.Popen[str], job_id: str) -> dict[str, Any]:
    for index in range(60):
        payload = call_tool(proc, 100 + index, "get_job_status", {"job_id": job_id})
        if payload["status"] != "running":
            return payload
        time.sleep(0.25)
    raise TimeoutError(f"Timed out waiting for job: {job_id}")


if __name__ == "__main__":
    raise SystemExit(main())
