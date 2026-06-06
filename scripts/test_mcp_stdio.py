from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import fitz


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
                "inspect_document",
                "process_material",
                "process_web_archive",
                "start_conversion",
                "get_job_status",
                "read_report",
                "read_pdf_tool_log",
                "read_artifact",
                "inspect_agent_batch_results",
                "list_agent_batch_results",
                "build_agent_handoff_bundle",
                "build_location_index",
                "start_location_index",
                "query_location_index",
                "export_location_review_pack",
                "rebuild_image_book",
                "start_image_book_rebuild",
                "rebuild_image_book_from_order",
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

            inspected_txt = call_tool(proc, 31, "inspect_document", {"input": str(input_file)})
            if inspected_txt["status"] != "ok" or inspected_txt["kind"] != "pandoc":
                raise RuntimeError(f"TXT inspection failed: {inspected_txt}")

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
                if not final.get("artifacts") or not final.get("next_actions"):
                    raise RuntimeError(f"Conversion job did not expose artifacts/next_actions: {final}")

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

            image_dir = tmpdir / "images"
            image_dir.mkdir()
            pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 80, 80), 0)
            pixmap.clear_with(255)
            pixmap.save(str(image_dir / "shot-001.png"))
            inspected_image_dir = call_tool(proc, 32, "inspect_document", {"input": str(image_dir), "recursive": False})
            if inspected_image_dir["kind"] != "directory" or inspected_image_dir["counts"]["images"] != 1:
                raise RuntimeError(f"Image directory inspection failed: {inspected_image_dir}")

            routed_location = call_tool(
                proc,
                34,
                "process_material",
                {
                    "input": str(image_dir),
                    "output": str(tmpdir / "routed-location"),
                    "recursive": False,
                    "ocr": "never",
                },
            )
            if routed_location["route"] != "start_location_index" or not routed_location.get("job_id"):
                raise RuntimeError(f"process_material did not route small image folder to location index: {routed_location}")
            routed_location_final = poll_job(proc, routed_location["job_id"])
            if routed_location_final["status"] != "done":
                raise RuntimeError(f"Routed location job failed: {routed_location_final}")

            routed_query = call_tool(
                proc,
                35,
                "process_material",
                {
                    "input": str(image_dir),
                    "output": str(tmpdir / "routed-query"),
                    "recursive": False,
                    "ocr": "never",
                    "query": "anything",
                },
            )
            if routed_query["route"] != "start_location_index" or not routed_query.get("next_actions"):
                raise RuntimeError(f"process_material query route missing next action: {routed_query}")

            pdf_path = tmpdir / "sample.pdf"
            pdf_doc = fitz.open()
            pdf_page = pdf_doc.new_page()
            pdf_page.insert_text((72, 72), "MCP inspect PDF text layer")
            pdf_doc.save(pdf_path)
            pdf_doc.close()
            inspected_pdf = call_tool(proc, 33, "inspect_document", {"input": str(pdf_path)})
            if inspected_pdf["kind"] != "pdf" or inspected_pdf["preflight"]["page_count"] != 1:
                raise RuntimeError(f"PDF inspection failed: {inspected_pdf}")

            async_location_dir = tmpdir / "async-locations"
            async_location = call_tool(
                proc,
                85,
                "start_location_index",
                {
                    "input": str(image_dir),
                    "output": str(async_location_dir),
                    "recursive": False,
                    "ocr": "never",
                },
            )
            async_location_final = poll_job(proc, async_location["job_id"])
            if async_location_final["status"] != "done" or not async_location_final.get("artifacts"):
                raise RuntimeError(f"Async location index failed: {async_location_final}")

            image_book_dir = tmpdir / "image-book"
            image_book = call_tool(
                proc,
                81,
                "rebuild_image_book",
                {
                    "input": str(image_dir),
                    "output": str(image_book_dir),
                    "recursive": False,
                    "ocr": "never",
                },
            )
            if image_book["source_count"] != 1 or not Path(image_book["book"]).exists():
                raise RuntimeError(f"Image book rebuild failed: {image_book}")

            async_image_book_dir = tmpdir / "async-image-book"
            async_image_book = call_tool(
                proc,
                86,
                "start_image_book_rebuild",
                {
                    "input": str(image_dir),
                    "output": str(async_image_book_dir),
                    "recursive": False,
                    "ocr": "never",
                },
            )
            async_image_book_final = poll_job(proc, async_image_book["job_id"])
            if async_image_book_final["status"] != "done" or not async_image_book_final.get("artifacts"):
                raise RuntimeError(f"Async image book rebuild failed: {async_image_book_final}")

            book_artifact = call_tool(
                proc,
                82,
                "read_artifact",
                {
                    "path": image_book["book"],
                    "artifact_type": "markdown",
                    "max_chars": 2000,
                    "max_lines": 50,
                },
            )
            if book_artifact["artifact_type"] != "markdown" or "text" not in book_artifact:
                raise RuntimeError(f"Markdown artifact read failed: {book_artifact}")

            clusters_artifact = call_tool(proc, 83, "read_artifact", {"path": image_book["clusters"]})
            if clusters_artifact["artifact_type"] != "clusters_json" or "json" not in clusters_artifact:
                raise RuntimeError(f"JSON artifact read failed: {clusters_artifact}")

            sqlite_artifact = call_tool(
                proc,
                84,
                "read_artifact",
                {"path": str(location_dir / "document_locations.sqlite")},
                allow_error=True,
            )
            if not sqlite_artifact.get("error"):
                raise RuntimeError(f"SQLite artifact should require a specific query tool: {sqlite_artifact}")

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


def call_tool(
    proc: subprocess.Popen[str],
    request_id: int,
    name: str,
    arguments: dict[str, Any],
    *,
    allow_error: bool = False,
) -> dict[str, Any]:
    response = call(proc, request_id, "tools/call", {"name": name, "arguments": arguments})
    content = response["result"]["content"][0]["text"]
    payload = json.loads(content)
    if payload.get("error") and not allow_error:
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
