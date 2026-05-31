from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import time
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ebook_markdown_pipeline import (  # noqa: E402
    analyze_sources,
    collect_sources,
    convert_sources,
    default_options,
    dependency_health_report,
    find_missing_dependencies,
    normalize_command_options,
    write_batch_summary,
)
from ebook_markdown_pipeline.document_locator import build_location_index, query_location_index  # noqa: E402
from ebook_markdown_pipeline.image_book_rebuilder import rebuild_image_book  # noqa: E402


PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "ebook-markdown-pipeline"
SERVER_VERSION = "0.1.0"

for stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()
JSON_STDOUT = sys.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description="MCP stdio server for ebook_markdown_pipeline.")
    parser.add_argument("--workspace-root", type=Path, default=Path.cwd())
    parser.parse_args()
    server = McpServer()
    server.serve()
    return 0


class McpServer:
    def serve(self) -> None:
        while True:
            line = sys.stdin.readline()
            if not line:
                return
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
                response = self.handle_request(request)
            except Exception as exc:  # noqa: BLE001
                response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32603,
                        "message": str(exc),
                        "data": traceback.format_exc(),
                    },
                }
            if response is not None:
                write_json(response)

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params") or {}

        try:
            if method == "initialize":
                result = {
                    "protocolVersion": PROTOCOL_VERSION,
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                    "capabilities": {"tools": {}},
                }
                return ok(request_id, result)
            if method == "notifications/initialized":
                return None
            if method == "tools/list":
                return ok(request_id, {"tools": tool_schemas()})
            if method == "tools/call":
                name = params.get("name")
                arguments = params.get("arguments") or {}
                return ok(request_id, tool_result(call_tool(str(name), arguments)))
            if method == "ping":
                return ok(request_id, {})
            return error(request_id, -32601, f"Unsupported method: {method}")
        except Exception as exc:  # noqa: BLE001
            return error(request_id, -32000, str(exc), traceback.format_exc())


def ok(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error(request_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        payload["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": payload}


def tool_result(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False, indent=2),
            }
        ],
        "isError": bool(payload.get("error")),
    }


def write_json(payload: dict[str, Any]) -> None:
    JSON_STDOUT.write(json.dumps(payload, ensure_ascii=False) + "\n")
    JSON_STDOUT.flush()


def tool_schemas() -> list[dict[str, Any]]:
    return [
        {
            "name": "scan_books",
            "description": "Scan ebook/PDF inputs and return planned conversion pipelines.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "input": {"type": "string"},
                    "output": {"type": "string"},
                    "recursive": {"type": "boolean", "default": True},
                    "include_hidden": {"type": "boolean", "default": False},
                    "output_format": {"type": "string", "enum": ["markdown", "html", "text"], "default": "markdown"},
                    "pdf_pipeline_mode": {
                        "type": "string",
                        "enum": ["auto", "marker", "mineru", "umi", "pymupdf4llm"],
                        "default": "auto",
                    },
                },
                "required": ["input", "output"],
            },
        },
        {
            "name": "health_check",
            "description": "Check required converter commands, Python packages, CUDA, and model cache.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "input": {"type": "string"},
                    "output": {"type": "string"},
                    "recursive": {"type": "boolean", "default": True},
                    "pdf_pipeline_mode": {"type": "string", "default": "auto"},
                },
            },
        },
        {
            "name": "start_conversion",
            "description": "Start a background conversion job. Poll with get_job_status.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "input": {"type": "string"},
                    "output": {"type": "string"},
                    "recursive": {"type": "boolean", "default": True},
                    "include_hidden": {"type": "boolean", "default": False},
                    "output_format": {"type": "string", "enum": ["markdown", "html", "text"], "default": "markdown"},
                    "pdf_pipeline_mode": {"type": "string", "default": "auto"},
                    "overwrite": {"type": "boolean", "default": False},
                    "resume": {"type": "boolean", "default": True},
                    "manifest": {"type": "string"},
                    "report_dir": {"type": "string"},
                    "pdf_tool_idle_timeout": {"type": "number"},
                    "pdf_tool_finalize_timeout": {"type": "number"},
                    "mineru_segment_min_pages": {"type": "integer"},
                    "mineru_segment_pages": {"type": "integer"},
                },
                "required": ["input", "output"],
            },
        },
        {
            "name": "get_job_status",
            "description": "Return status, progress, logs, and results for a conversion job.",
            "inputSchema": {
                "type": "object",
                "properties": {"job_id": {"type": "string"}},
                "required": ["job_id"],
            },
        },
        {
            "name": "read_report",
            "description": "Read a JSON report generated by the converter.",
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
        {
            "name": "read_pdf_tool_log",
            "description": "Read the tail of a persisted Marker/MinerU PDF tool log.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_lines": {"type": "integer", "default": 120},
                },
                "required": ["path"],
            },
        },
        {
            "name": "build_location_index",
            "description": "Build a page/image-level searchable index for PDFs and image files.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "input": {"type": "string"},
                    "output": {"type": "string"},
                    "recursive": {"type": "boolean", "default": True},
                    "include_hidden": {"type": "boolean", "default": False},
                    "ocr": {"type": "string", "enum": ["auto", "always", "never"], "default": "auto"},
                    "umi_render_dpi": {"type": "integer", "default": 200},
                    "umi_paddle_exe": {"type": "string"},
                    "umi_paddle_module": {"type": "string"},
                },
                "required": ["input", "output"],
            },
        },
        {
            "name": "query_location_index",
            "description": "Search a generated location SQLite index and return source file plus PDF page/image hit.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "index": {"type": "string"},
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": ["index", "query"],
            },
        },
        {
            "name": "rebuild_image_book",
            "description": "OCR a folder of screenshots/images, deduplicate near-repeats, infer order, and write a structured Markdown draft plus review files.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "input": {"type": "string"},
                    "output": {"type": "string"},
                    "recursive": {"type": "boolean", "default": True},
                    "include_hidden": {"type": "boolean", "default": False},
                    "ocr": {"type": "string", "enum": ["auto", "never"], "default": "auto"},
                    "umi_paddle_exe": {"type": "string"},
                    "umi_paddle_module": {"type": "string"},
                },
                "required": ["input", "output"],
            },
        },
    ]


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "scan_books":
        return scan_books(arguments)
    if name == "health_check":
        return health_check(arguments)
    if name == "start_conversion":
        return start_conversion(arguments)
    if name == "get_job_status":
        return get_job_status(arguments)
    if name == "read_report":
        return read_report(arguments)
    if name == "read_pdf_tool_log":
        return read_pdf_tool_log(arguments)
    if name == "build_location_index":
        return build_location_index_tool(arguments)
    if name == "query_location_index":
        return query_location_index_tool(arguments)
    if name == "rebuild_image_book":
        return rebuild_image_book_tool(arguments)
    raise ValueError(f"Unknown tool: {name}")


def options_from_arguments(arguments: dict[str, Any]) -> argparse.Namespace:
    path_fields = {"manifest", "report_dir", "input", "output"}
    converted = {
        key: Path(value) if key in path_fields and value not in {None, ""} else value
        for key, value in arguments.items()
    }
    options = default_options(**converted)
    if getattr(options, "resume", False) and getattr(options, "manifest", None) is None and getattr(options, "output", None):
        options.manifest = Path(options.output) / "manifest.json"
    return normalize_command_options(options)


def resolve_sources_and_root(options: argparse.Namespace) -> tuple[Path, list[Path]]:
    input_path = Path(options.input)
    sources = collect_sources(
        input_path,
        recursive=bool(getattr(options, "recursive", True)),
        include_hidden=bool(getattr(options, "include_hidden", False)),
    )
    return input_path, sources


def scan_books(arguments: dict[str, Any]) -> dict[str, Any]:
    options = options_from_arguments(arguments)
    input_root, sources = resolve_sources_and_root(options)
    plans = analyze_sources(sources, input_root, Path(options.output), options)
    missing = find_missing_dependencies(sources, options)
    return {
        "input": str(input_root),
        "output": str(options.output),
        "count": len(sources),
        "plans": [asdict(plan) for plan in plans],
        "missing_dependencies": missing,
    }


def health_check(arguments: dict[str, Any]) -> dict[str, Any]:
    options = options_from_arguments(arguments)
    sources: list[Path] = []
    if getattr(options, "input", None):
        _, sources = resolve_sources_and_root(options)
    checks = dependency_health_report(sources, options)
    return {"checks": checks, "ok": all(item["status"] != "missing" for item in checks)}


def start_conversion(arguments: dict[str, Any]) -> dict[str, Any]:
    arguments = {"resume": True, **arguments}
    options = options_from_arguments(arguments)
    input_root, sources = resolve_sources_and_root(options)
    if not sources:
        return {"error": True, "message": "No supported files found."}

    job_id = f"job-{int(time.time())}-{len(JOBS) + 1}"
    events: queue.Queue[dict[str, Any]] = queue.Queue()
    job = {
        "job_id": job_id,
        "status": "running",
        "started_at": timestamp(),
        "input": str(input_root),
        "output": str(options.output),
        "total": len(sources),
        "completed": 0,
        "events": [],
        "results": [],
        "error": None,
    }
    with JOBS_LOCK:
        JOBS[job_id] = job

    def progress_callback(event, source, index, total, result) -> None:
        events.put(
            {
                "time": timestamp(),
                "event": event,
                "source": str(source),
                "index": index,
                "total": total,
                "result": serialize_result(result),
            }
        )

    def worker() -> None:
        try:
            options.output.mkdir(parents=True, exist_ok=True)
            results = convert_sources(sources, input_root, options.output, options, progress_callback=progress_callback)
            if options.manifest:
                options.manifest.parent.mkdir(parents=True, exist_ok=True)
                options.manifest.write_text(
                    json.dumps([asdict(item) for item in results], ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            options.output = Path(options.output)
            write_batch_summary(results, options)
            update_job(job_id, status="done", finished_at=timestamp(), results=[asdict(item) for item in results])
        except Exception as exc:  # noqa: BLE001
            update_job(job_id, status="failed", finished_at=timestamp(), error=str(exc), traceback=traceback.format_exc())
        finally:
            events.put({"time": timestamp(), "event": "__stop__"})

    def event_drain() -> None:
        while True:
            item = events.get()
            if item.get("event") == "__stop__":
                return
            with JOBS_LOCK:
                current = JOBS.get(job_id)
                if current is None:
                    return
                current["events"].append(item)
                current["events"] = current["events"][-200:]
                if item["event"] == "done":
                    current["completed"] = max(int(current.get("completed", 0)), int(item.get("index") or 0))

    threading.Thread(target=event_drain, daemon=True).start()
    threading.Thread(target=worker, daemon=True).start()
    return {"job_id": job_id, "status": "running", "total": len(sources)}


def update_job(job_id: str, **updates: Any) -> None:
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(updates)


def get_job_status(arguments: dict[str, Any]) -> dict[str, Any]:
    job_id = str(arguments["job_id"])
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            return {"error": True, "message": f"Job not found: {job_id}"}
        return json.loads(json.dumps(job, ensure_ascii=False))


def read_report(arguments: dict[str, Any]) -> dict[str, Any]:
    path = Path(arguments["path"])
    return {"path": str(path), "report": json.loads(path.read_text(encoding="utf-8"))}


def read_pdf_tool_log(arguments: dict[str, Any]) -> dict[str, Any]:
    path = Path(arguments["path"])
    max_lines = int(arguments.get("max_lines") or 120)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    tail = lines[-max_lines:]
    return {"path": str(path), "lines": tail, "log": "\n".join(tail), "total_lines": len(lines)}


def build_location_index_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    return build_location_index(
        input_path=Path(arguments["input"]),
        output_dir=Path(arguments["output"]),
        recursive=bool(arguments.get("recursive", True)),
        include_hidden=bool(arguments.get("include_hidden", False)),
        ocr_mode=str(arguments.get("ocr") or "auto"),
        umi_render_dpi=int(arguments.get("umi_render_dpi") or 200),
        umi_paddle_exe=arguments.get("umi_paddle_exe"),
        umi_paddle_module=arguments.get("umi_paddle_module"),
    )


def query_location_index_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    return query_location_index(
        Path(arguments["index"]),
        str(arguments["query"]),
        limit=int(arguments.get("limit") or 20),
    )


def rebuild_image_book_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    return rebuild_image_book(
        input_path=Path(arguments["input"]),
        output_dir=Path(arguments["output"]),
        recursive=bool(arguments.get("recursive", True)),
        include_hidden=bool(arguments.get("include_hidden", False)),
        ocr_mode=str(arguments.get("ocr") or "auto"),
        umi_paddle_exe=arguments.get("umi_paddle_exe"),
        umi_paddle_module=arguments.get("umi_paddle_module"),
    )


def serialize_result(result: Any) -> Any:
    if hasattr(result, "__dataclass_fields__"):
        return asdict(result)
    if isinstance(result, dict):
        return result
    return str(result)


def timestamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    raise SystemExit(main())
