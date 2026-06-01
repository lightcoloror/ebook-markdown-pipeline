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
from ebook_markdown_pipeline.artifact_schema import artifact  # noqa: E402
from ebook_markdown_pipeline.document_locator import build_location_index, export_location_review_pack, query_location_index  # noqa: E402
from ebook_markdown_pipeline.document_inspector import inspect_document  # noqa: E402
from ebook_markdown_pipeline.image_book_rebuilder import rebuild_image_book, rebuild_image_book_from_order  # noqa: E402


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
            "name": "inspect_document",
            "description": "Lightweight preflight inspection for a document/image/folder. Returns type, risks, and recommended next tool.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "input": {"type": "string"},
                    "recursive": {"type": "boolean", "default": True},
                    "include_hidden": {"type": "boolean", "default": False},
                    "sample_pages": {"type": "integer", "default": 8},
                },
                "required": ["input"],
            },
        },
        {
            "name": "process_material",
            "description": "High-level router for agents. Inspects input and starts the right background job for conversion, location indexing, or image-book rebuilding.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "input": {"type": "string"},
                    "output": {"type": "string"},
                    "intent": {"type": "string", "enum": ["auto", "convert", "locate", "rebuild"], "default": "auto"},
                    "query": {"type": "string"},
                    "recursive": {"type": "boolean", "default": True},
                    "include_hidden": {"type": "boolean", "default": False},
                    "output_format": {"type": "string", "enum": ["markdown", "html", "text"], "default": "markdown"},
                    "pdf_pipeline_mode": {"type": "string", "enum": ["auto", "marker", "mineru", "pymupdf4llm", "umi", "docling"], "default": "auto"},
                    "image_book_threshold": {"type": "integer", "default": 8},
                    "sample_pages": {"type": "integer", "default": 8},
                    "ocr": {"type": "string", "enum": ["auto", "always", "never"], "default": "auto"},
                    "pdf_tool_idle_timeout": {"type": "number"},
                    "pdf_tool_finalize_timeout": {"type": "number"},
                    "docling_timeout": {"type": "number", "default": 45},
                    "docling_fallback_to_pandoc": {"type": "boolean", "default": True},
                    "mineru_segment_min_pages": {"type": "integer"},
                    "mineru_segment_pages": {"type": "integer"},
                },
                "required": ["input", "output"],
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
                    "docling_timeout": {"type": "number", "default": 45},
                    "docling_fallback_to_pandoc": {"type": "boolean", "default": True},
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
            "name": "read_artifact",
            "description": "Read a text/JSON/JSONL/Markdown artifact by path with size and line limits.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "artifact_type": {"type": "string"},
                    "max_chars": {"type": "integer", "default": 20000},
                    "max_lines": {"type": "integer", "default": 300},
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
            "name": "start_location_index",
            "description": "Start a background page/image-level location indexing job. Poll with get_job_status.",
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
            "name": "export_location_review_pack",
            "description": "Export a human review pack for location query matches, including review markdown, JSON, and rendered PDF pages or copied images when possible.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "index": {"type": "string"},
                    "query": {"type": "string"},
                    "output": {"type": "string"},
                    "limit": {"type": "integer", "default": 20},
                    "render_dpi": {"type": "integer", "default": 150},
                },
                "required": ["index", "query", "output"],
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
        {
            "name": "start_image_book_rebuild",
            "description": "Start a background screenshot/image-book rebuild job. Poll with get_job_status.",
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
        {
            "name": "rebuild_image_book_from_order",
            "description": "Rebuild book.md from pages.jsonl and a manually edited order.md without OCR.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "pages": {"type": "string"},
                    "order": {"type": "string"},
                    "output": {"type": "string"},
                    "title": {"type": "string"},
                },
                "required": ["pages", "order", "output"],
            },
        },
    ]


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "scan_books":
        return scan_books(arguments)
    if name == "health_check":
        return health_check(arguments)
    if name == "inspect_document":
        return inspect_document_tool(arguments)
    if name == "process_material":
        return process_material(arguments)
    if name == "start_conversion":
        return start_conversion(arguments)
    if name == "get_job_status":
        return get_job_status(arguments)
    if name == "read_report":
        return read_report(arguments)
    if name == "read_pdf_tool_log":
        return read_pdf_tool_log(arguments)
    if name == "read_artifact":
        return read_artifact(arguments)
    if name == "build_location_index":
        return build_location_index_tool(arguments)
    if name == "start_location_index":
        return start_location_index(arguments)
    if name == "query_location_index":
        return query_location_index_tool(arguments)
    if name == "export_location_review_pack":
        return export_location_review_pack_tool(arguments)
    if name == "rebuild_image_book":
        return rebuild_image_book_tool(arguments)
    if name == "start_image_book_rebuild":
        return start_image_book_rebuild(arguments)
    if name == "rebuild_image_book_from_order":
        return rebuild_image_book_from_order_tool(arguments)
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


def inspect_document_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    return inspect_document(
        Path(arguments["input"]),
        recursive=bool(arguments.get("recursive", True)),
        include_hidden=bool(arguments.get("include_hidden", False)),
        sample_pages=int(arguments.get("sample_pages") or 8),
    )


def process_material(arguments: dict[str, Any]) -> dict[str, Any]:
    input_path = Path(arguments["input"])
    output_path = Path(arguments["output"])
    intent = str(arguments.get("intent") or "auto")
    query = str(arguments.get("query") or "").strip()
    recursive = bool(arguments.get("recursive", True))
    include_hidden = bool(arguments.get("include_hidden", False))
    image_book_threshold = int(arguments.get("image_book_threshold") or 8)
    inspection = inspect_document(
        input_path,
        recursive=recursive,
        include_hidden=include_hidden,
        sample_pages=int(arguments.get("sample_pages") or 8),
    )

    route = choose_material_route(inspection, intent=intent, query=query, image_book_threshold=image_book_threshold)
    delegated_arguments = dict(arguments)
    delegated_arguments.pop("intent", None)
    delegated_arguments.pop("query", None)
    delegated_arguments.pop("image_book_threshold", None)

    if route == "start_location_index":
        delegated_arguments["ocr"] = str(arguments.get("ocr") or "auto")
        delegated = start_location_index(delegated_arguments)
        next_actions = []
        if query:
            next_actions.append(
                {
                    "after_job_status": "done",
                    "tool": "query_location_index",
                    "arguments": {
                        "index": str(output_path / "document_locations.sqlite"),
                        "query": query,
                    },
                }
            )
        else:
            next_actions.append({"after_job_status": "done", "tool": "read_artifact", "artifact_type": "location_index_jsonl"})
    elif route == "start_image_book_rebuild":
        delegated_arguments["ocr"] = "auto" if str(arguments.get("ocr") or "auto") == "always" else str(arguments.get("ocr") or "auto")
        delegated = start_image_book_rebuild(delegated_arguments)
        next_actions = [
            {"after_job_status": "done", "tool": "read_artifact", "artifact_type": "markdown"},
            {"after_job_status": "done", "tool": "read_artifact", "artifact_type": "review_report"},
        ]
    elif route == "start_conversion":
        conversion_arguments = dict(delegated_arguments)
        conversion_arguments["pdf_pipeline_mode"] = choose_pdf_pipeline_mode(inspection, str(arguments.get("pdf_pipeline_mode") or "auto"))
        delegated = start_conversion(conversion_arguments)
        output_format = str(arguments.get("output_format") or "markdown")
        next_actions = [
            {"after_job_status": "done", "tool": "read_artifact", "artifact_type": output_format},
            {"after_job_status": "done", "tool": "read_artifact", "artifact_type": "review_report"},
        ]
    else:
        return {
            "status": "unsupported",
            "route": route,
            "inspection": inspection,
            "warnings": inspection.get("warnings", []) + [f"No route available for intent={intent}."],
            "errors": [],
            "next_actions": [],
        }

    return {
        "status": "routed",
        "route": route,
        "inspection": inspection,
        "delegated": delegated,
        "job_id": delegated.get("job_id"),
        "warnings": inspection.get("warnings", []),
        "errors": [],
        "next_actions": next_actions,
    }


def choose_material_route(inspection: dict[str, Any], *, intent: str, query: str, image_book_threshold: int) -> str:
    if inspection.get("status") in {"missing", "unsupported"}:
        return "unsupported"
    if intent == "locate" or query:
        return "start_location_index"
    if intent == "rebuild":
        return "start_image_book_rebuild"
    if intent == "convert":
        return "start_conversion"

    kind = inspection.get("kind")
    if kind == "directory":
        counts = inspection.get("counts") or {}
        images = int(counts.get("images") or 0)
        documents = int(counts.get("documents") or 0)
        if images and not documents and images >= image_book_threshold:
            return "start_image_book_rebuild"
        if images and not documents:
            return "start_location_index"
        if documents:
            return "start_conversion"
    if kind == "image":
        return "start_location_index"
    if kind in {"pdf", "pandoc", "calibre", "docling"}:
        return "start_conversion"
    return "unsupported"


def choose_pdf_pipeline_mode(inspection: dict[str, Any], requested: str) -> str:
    if requested and requested != "auto":
        return requested
    if inspection.get("kind") != "pdf":
        return requested or "auto"
    preflight = inspection.get("preflight") or {}
    if preflight.get("scanned_likely"):
        return "mineru"
    recommended = str(preflight.get("recommended_pipeline") or "auto")
    return recommended if recommended in {"marker", "mineru", "umi", "pymupdf4llm", "docling"} else "auto"


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
        "kind": "conversion",
        "status": "running",
        "started_at": timestamp(),
        "input": str(input_root),
        "output": str(options.output),
        "total": len(sources),
        "completed": 0,
        "events": [],
        "results": [],
        "artifacts": [],
        "warnings": [],
        "errors": [],
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
            result_payloads = [asdict(item) for item in results]
            update_job(
                job_id,
                status="done",
                finished_at=timestamp(),
                results=result_payloads,
                artifacts=conversion_artifacts(results, options),
                warnings=conversion_warnings(results),
                errors=conversion_errors(results),
                next_actions=conversion_next_actions(results, options),
            )
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


def conversion_artifacts(results: list[Any], options: argparse.Namespace) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    output_format = str(getattr(options, "output_format", "markdown") or "markdown")
    for result in results:
        output = getattr(result, "output", None)
        if output and Path(output).exists():
            artifacts.append(
                artifact(
                    output_format if output_format in {"markdown", "html", "text"} else "document_output",
                    output,
                    label=f"Converted output: {Path(output).name}",
                    media_type=output_media_type(Path(output)),
                )
            )
        report = getattr(result, "report", None)
        if report and Path(report).exists():
            artifacts.append(artifact("conversion_report", report, label=f"Conversion report: {Path(report).name}", media_type="application/json"))

    report_root = conversion_report_root(options)
    for path, artifact_type, label, media_type in [
        (report_root / "summary.md", "summary_report", "Conversion summary", "text/markdown"),
        (report_root / "summary.json", "summary_json", "Conversion summary JSON", "application/json"),
        (report_root / "review-checklist.md", "review_report", "Review checklist", "text/markdown"),
        (report_root / "review-checklist.json", "review_json", "Review checklist JSON", "application/json"),
    ]:
        if path.exists():
            artifacts.append(artifact(artifact_type, path, label=label, media_type=media_type))
    return artifacts


def conversion_report_root(options: argparse.Namespace) -> Path:
    summary = getattr(options, "summary", None)
    if summary:
        return Path(summary).parent
    report_dir = getattr(options, "report_dir", None)
    if report_dir:
        return Path(report_dir)
    return Path(getattr(options, "output")) / ".reports"


def output_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        return "text/markdown"
    if suffix in {".html", ".htm"}:
        return "text/html"
    if suffix == ".txt":
        return "text/plain"
    return "application/octet-stream"


def conversion_warnings(results: list[Any]) -> list[str]:
    warnings = []
    for result in results:
        if getattr(result, "status", "") == "skipped":
            warnings.append(f"Skipped: {getattr(result, 'source', '')}")
    return warnings


def conversion_errors(results: list[Any]) -> list[str]:
    errors = []
    for result in results:
        if getattr(result, "status", "") == "failed":
            errors.append(f"{getattr(result, 'source', '')}: {getattr(result, 'message', '')}")
    return errors


def conversion_next_actions(results: list[Any], options: argparse.Namespace) -> list[dict[str, Any]]:
    actions = []
    report_root = conversion_report_root(options)
    review = report_root / "review-checklist.md"
    if review.exists():
        actions.append({"tool": "read_artifact", "arguments": {"path": str(review), "artifact_type": "review_report"}})
    for item in conversion_artifacts(results, options):
        if item.get("type") in {"markdown", "html", "text", "summary_report"}:
            actions.append({"tool": "read_artifact", "arguments": {"path": item["path"], "artifact_type": item["type"]}})
            break
    return actions


def update_job(job_id: str, **updates: Any) -> None:
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(updates)


def create_job(kind: str, *, input_path: Path, output_path: Path, total: int | None = None) -> str:
    job_id = f"job-{int(time.time())}-{len(JOBS) + 1}"
    job = {
        "job_id": job_id,
        "kind": kind,
        "status": "running",
        "started_at": timestamp(),
        "input": str(input_path),
        "output": str(output_path),
        "total": total,
        "completed": 0,
        "events": [],
        "results": [],
        "artifacts": [],
        "warnings": [],
        "errors": [],
        "next_actions": [],
        "error": None,
    }
    with JOBS_LOCK:
        JOBS[job_id] = job
    return job_id


def append_job_event(job_id: str, event: dict[str, Any]) -> None:
    with JOBS_LOCK:
        current = JOBS.get(job_id)
        if current is None:
            return
        current["events"].append({"time": timestamp(), **event})
        current["events"] = current["events"][-200:]
        index = event.get("index")
        total = event.get("total")
        if isinstance(index, int):
            current["completed"] = max(int(current.get("completed") or 0), index)
        if isinstance(total, int):
            current["total"] = total


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


def read_artifact(arguments: dict[str, Any]) -> dict[str, Any]:
    path = Path(arguments["path"])
    artifact_type = str(arguments.get("artifact_type") or infer_artifact_type(path))
    max_chars = clamp_int(arguments.get("max_chars"), default=20000, minimum=1000, maximum=200000)
    max_lines = clamp_int(arguments.get("max_lines"), default=300, minimum=20, maximum=5000)

    if not path.exists() or not path.is_file():
        return {"error": True, "message": f"Artifact file not found: {path}", "path": str(path)}
    if path.suffix.lower() in {".sqlite", ".db"} or artifact_type.endswith("_sqlite"):
        return {
            "error": True,
            "message": "SQLite artifacts are not read directly. Use query_location_index or a specific query tool.",
            "path": str(path),
            "artifact_type": artifact_type,
        }

    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    limited_lines = lines[:max_lines]
    limited_text = "\n".join(limited_lines)
    truncated_by_lines = len(lines) > len(limited_lines)
    truncated_by_chars = len(limited_text) > max_chars
    if truncated_by_chars:
        limited_text = limited_text[:max_chars]
    payload: dict[str, Any] = {
        "path": str(path),
        "artifact_type": artifact_type,
        "size_bytes": path.stat().st_size,
        "total_lines": len(lines),
        "returned_lines": min(len(lines), max_lines),
        "truncated": truncated_by_lines or truncated_by_chars,
        "text": limited_text,
    }
    if artifact_type in {"json", "clusters_json"} and not payload["truncated"]:
        try:
            payload["json"] = json.loads(text)
        except json.JSONDecodeError:
            payload["json_error"] = "Invalid JSON."
    if artifact_type in {"pages_jsonl", "location_index_jsonl"}:
        payload["records"] = parse_jsonl_preview(limited_lines)
    return payload


def infer_artifact_type(path: Path) -> str:
    suffix = path.suffix.lower()
    name = path.name.lower()
    if suffix in {".md", ".markdown"}:
        return "markdown"
    if suffix == ".jsonl":
        if "location" in name:
            return "location_index_jsonl"
        return "pages_jsonl"
    if suffix == ".json":
        if "cluster" in name:
            return "clusters_json"
        return "json"
    if suffix in {".log", ".txt"}:
        return "text"
    if suffix in {".html", ".htm"}:
        return "html"
    return suffix.lstrip(".") or "artifact"


def parse_jsonl_preview(lines: list[str]) -> list[dict[str, Any]]:
    records = []
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def clamp_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return min(max(parsed, minimum), maximum)


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


def start_location_index(arguments: dict[str, Any]) -> dict[str, Any]:
    input_path = Path(arguments["input"])
    output_path = Path(arguments["output"])
    job_id = create_job("location_index", input_path=input_path, output_path=output_path)

    def worker() -> None:
        try:
            append_job_event(job_id, {"event": "start", "message": "Build location index"})
            result = build_location_index_tool(arguments)
            update_job(
                job_id,
                status="done",
                finished_at=timestamp(),
                results=[result],
                artifacts=result.get("artifacts", []),
                warnings=result_warnings(result),
                errors=result_errors(result),
                next_actions=artifact_next_actions(result.get("artifacts", [])),
                completed=result.get("source_count", 0),
                total=result.get("source_count", 0),
            )
        except Exception as exc:  # noqa: BLE001
            update_job(job_id, status="failed", finished_at=timestamp(), error=str(exc), traceback=traceback.format_exc())

    threading.Thread(target=worker, daemon=True).start()
    return {"job_id": job_id, "status": "running", "kind": "location_index"}


def query_location_index_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    return query_location_index(
        Path(arguments["index"]),
        str(arguments["query"]),
        limit=int(arguments.get("limit") or 20),
    )


def export_location_review_pack_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    return export_location_review_pack(
        Path(arguments["index"]),
        str(arguments["query"]),
        Path(arguments["output"]),
        limit=int(arguments.get("limit") or 20),
        render_dpi=int(arguments.get("render_dpi") or 150),
    )


def result_warnings(result: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    status_counts = result.get("status_counts")
    if isinstance(status_counts, dict) and int(status_counts.get("failed") or 0):
        warnings.append(f"{status_counts.get('failed')} source(s) failed during processing.")
    if int(result.get("source_count") or 0) == 0:
        warnings.append("No supported source files were found.")
    return warnings


def result_errors(result: dict[str, Any]) -> list[str]:
    if result.get("error"):
        return [str(result.get("message") or result.get("error"))]
    return []


def artifact_next_actions(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions = []
    for item in artifacts:
        artifact_type = item.get("type")
        path = item.get("path")
        if artifact_type in {"markdown", "location_index_jsonl", "review_report", "order_report", "summary_report"} and path:
            actions.append({"tool": "read_artifact", "arguments": {"path": path, "artifact_type": artifact_type}})
    return actions[:4]


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


def rebuild_image_book_from_order_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    return rebuild_image_book_from_order(
        Path(arguments["pages"]),
        Path(arguments["order"]),
        Path(arguments["output"]),
        title=str(arguments.get("title") or ""),
    )


def start_image_book_rebuild(arguments: dict[str, Any]) -> dict[str, Any]:
    input_path = Path(arguments["input"])
    output_path = Path(arguments["output"])
    job_id = create_job("image_book_rebuild", input_path=input_path, output_path=output_path)

    def progress_callback(event: dict[str, Any]) -> None:
        append_job_event(
            job_id,
            {
                "event": event.get("stage") or "progress",
                "message": event.get("message", ""),
                "index": event.get("index"),
                "total": event.get("total"),
                "source": event.get("source", ""),
            },
        )

    def worker() -> None:
        try:
            result = rebuild_image_book(
                input_path=input_path,
                output_dir=output_path,
                recursive=bool(arguments.get("recursive", True)),
                include_hidden=bool(arguments.get("include_hidden", False)),
                ocr_mode=str(arguments.get("ocr") or "auto"),
                umi_paddle_exe=arguments.get("umi_paddle_exe"),
                umi_paddle_module=arguments.get("umi_paddle_module"),
                progress_callback=progress_callback,
            )
            update_job(
                job_id,
                status="done",
                finished_at=timestamp(),
                results=[result],
                artifacts=result.get("artifacts", []),
                warnings=result_warnings(result),
                errors=result_errors(result),
                next_actions=artifact_next_actions(result.get("artifacts", [])),
                completed=result.get("source_count", 0),
                total=result.get("source_count", 0),
            )
        except Exception as exc:  # noqa: BLE001
            update_job(job_id, status="failed", finished_at=timestamp(), error=str(exc), traceback=traceback.format_exc())

    threading.Thread(target=worker, daemon=True).start()
    return {"job_id": job_id, "status": "running", "kind": "image_book_rebuild"}


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
