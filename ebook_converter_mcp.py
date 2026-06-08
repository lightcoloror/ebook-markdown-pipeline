from __future__ import annotations

import argparse
import json
import os
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
    environment_capability_summary,
    find_missing_dependencies,
    normalize_command_options,
    write_batch_summary,
)
from ebook_markdown_pipeline.artifact_schema import artifact  # noqa: E402
from ebook_markdown_pipeline.batch_convert_books import suggest_review_next_actions  # noqa: E402
from ebook_markdown_pipeline.document_locator import build_location_index, export_location_review_pack, query_location_index  # noqa: E402
from ebook_markdown_pipeline.document_inspector import inspect_document  # noqa: E402
from ebook_markdown_pipeline.environment_report import compare_environment_lock, export_environment_report  # noqa: E402
from ebook_markdown_pipeline.image_book_rebuilder import rebuild_image_book, rebuild_image_book_from_order  # noqa: E402
from ebook_markdown_pipeline.process_web_archive import process_web_archive as process_web_archive_core  # noqa: E402


PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "ebook-markdown-pipeline"
SERVER_DISPLAY_NAME = "图文材料转换器"
SERVER_DISPLAY_NAME_EN = "Graphic-Text Material Converter"
SERVER_VERSION = "0.1.0"

for stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()
JSON_STDOUT = sys.stdout
AGENT_BATCH_CONTRACT_CAPABILITIES = {
    "selection_summary",
    "artifact_summary",
    "handoff_next_actions",
    "attention_summary",
    "legacy_action_synthesis",
    "quality_comparison",
    "recommended_rerun",
}
JSON_ARTIFACT_TYPES = {
    "json",
    "agent_batch_results",
    "agent_handoff_bundle_json",
    "agent_smoke_summary_json",
    "conversion_report",
    "summary_json",
    "review_json",
    "review_decisions_json",
    "clusters_json",
    "structure_json",
    "environment_json",
    "environment_lock",
    "environment_lock_compare",
    "environment_lock_compare_json",
    "quality_comparison_json",
    "visual_check_json",
    "visual_blocks_json",
    "table_candidates_json",
    "image_positions_json",
}
READABLE_ARTIFACT_TYPES = {
    "markdown",
    "agent_handoff_bundle_markdown",
    "agent_handoff_bundle_json",
    "agent_batch_run_summary",
    "agent_batch_summary",
    "agent_batch_results",
    "agent_smoke_summary_markdown",
    "agent_smoke_summary_json",
    "html",
    "text",
    "conversion_report",
    "summary_report",
    "summary_json",
    "review_report",
    "review_json",
    "review_decisions",
    "review_decisions_json",
    "location_index_jsonl",
    "pages_jsonl",
    "order_report",
    "structure_report",
    "structure_json",
    "environment_report",
    "environment_json",
    "environment_lock",
    "environment_lock_compare",
    "environment_lock_compare_json",
    "quality_comparison",
    "quality_comparison_json",
    "visual_check_json",
    "visual_blocks_json",
    "table_candidates_json",
    "image_positions_json",
    "requirements_lock",
    "tool_log",
}


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
                    "serverInfo": {
                        "name": SERVER_NAME,
                        "displayName": SERVER_DISPLAY_NAME,
                        "displayNameEn": SERVER_DISPLAY_NAME_EN,
                        "version": SERVER_VERSION,
                    },
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
            "name": "get_agent_contract",
            "description": "Return the stable agent calling contract, preferred entrypoints, tool schemas, artifact schema, and docs pointers.",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        },
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
            "name": "export_environment_report",
            "description": "Export environment diagnostics as Markdown/JSON artifacts for handoff or debugging.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "input": {"type": "string"},
                    "output": {"type": "string"},
                    "recursive": {"type": "boolean", "default": False},
                    "include_hidden": {"type": "boolean", "default": False},
                },
                "required": ["output"],
            },
        },
        {
            "name": "compare_environment_lock",
            "description": "Compare the current environment against a previously exported environment-lock.json.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "lock": {"type": "string"},
                    "output": {"type": "string"},
                },
                "required": ["lock"],
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
            "description": "High-level router for agents. Inspects input and starts the right recognition job. Conversion/image-book rebuilding is the default; location indexing requires intent=locate or query.",
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
                    "output_name_suffix": {"type": "string"},
                },
                "required": ["input", "output"],
            },
        },
        {
            "name": "process_web_archive",
            "description": "Prepare visual_check artifacts for a web-content-fetcher archive folder without replacing the source archive.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "input": {"type": "string"},
                    "output": {"type": "string"},
                    "format": {"type": "string", "enum": ["json", "summary"], "default": "json"},
                },
                "required": ["input"],
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
                    "output_name_suffix": {"type": "string"},
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
            "name": "inspect_agent_batch_results",
            "description": "Summarize an agent-batch-results.json handoff and expose quality comparison next actions.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_review_items": {"type": "integer", "default": 10},
                },
                "required": ["path"],
            },
        },
        {
            "name": "list_agent_batch_results",
            "description": "Find recent agent-batch-results.json files under a directory and summarize each handoff.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "max_results": {"type": "integer", "default": 10},
                    "max_depth": {"type": "integer", "default": 3},
                    "max_review_items": {"type": "integer", "default": 3},
                },
                "required": ["root"],
            },
        },
        {
            "name": "build_agent_handoff_bundle",
            "description": "Build a lightweight agent-handoff-bundle.json/md index for a prior agent batch result.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "batch_results": {"type": "string"},
                    "root": {"type": "string"},
                    "output": {"type": "string"},
                    "max_review_items": {"type": "integer", "default": 10},
                },
                "required": ["output"],
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
    if name == "get_agent_contract":
        return agent_contract_payload()
    if name == "scan_books":
        return scan_books(arguments)
    if name == "health_check":
        return health_check(arguments)
    if name == "export_environment_report":
        return export_environment_report_tool(arguments)
    if name == "compare_environment_lock":
        return compare_environment_lock_tool(arguments)
    if name == "inspect_document":
        return inspect_document_tool(arguments)
    if name == "process_material":
        return process_material(arguments)
    if name == "process_web_archive":
        return process_web_archive_tool(arguments)
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
    if name == "inspect_agent_batch_results":
        return inspect_agent_batch_results(arguments)
    if name == "list_agent_batch_results":
        return list_agent_batch_results(arguments)
    if name == "build_agent_handoff_bundle":
        return build_agent_handoff_bundle(arguments)
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


def agent_contract_payload(*, transport: str = "mcp-stdio") -> dict[str, Any]:
    tools = tool_schemas()
    project_dir = Path(__file__).resolve().parent
    operating_context = agent_operating_context()
    return {
        "schema_version": "ebook-agent-contract-v1",
        "server": SERVER_NAME,
        "display_name": SERVER_DISPLAY_NAME,
        "display_name_en": SERVER_DISPLAY_NAME_EN,
        "version": SERVER_VERSION,
        "transport": transport,
        "protocol_version": PROTOCOL_VERSION if transport == "mcp-stdio" else "",
        "artifact_schema_version": "artifact-schema-v1",
        "entrypoints": ["process_material", "get_job_status", "read_artifact"],
        "specialist_tools": [
            "health_check",
            "inspect_document",
            "scan_books",
            "inspect_agent_batch_results",
            "list_agent_batch_results",
            "build_agent_handoff_bundle",
        ],
        "supports_async_jobs": True,
        "supports_artifacts": True,
        "operating_context": operating_context,
        "pipeline_capabilities": operating_context["pipeline_capabilities"],
        "risk_status": operating_context["risk_status"],
        "long_task_guidance": operating_context["long_task_guidance"],
        "route_defaults": operating_context["route_defaults"],
        "tool_count": len(tools),
        "tools": tools,
        "docs": {
            "tool_contract": str(project_dir / "docs" / "TOOL_CONTRACT.md"),
            "agent_integration": str(project_dir / "docs" / "AGENT_INTEGRATION.md"),
            "agent_call_examples": str(project_dir / "examples" / "agent-calls" / "README.md"),
        },
        "error_contract": {
            "ok": False,
            "error": True,
            "code": "invalid_request",
            "retryable": False,
            "schema_version": "artifact-schema-v1",
        },
    }


def agent_operating_context() -> dict[str, Any]:
    capabilities = safe_pipeline_capabilities()
    return {
        "config_sources": {
            "http": str(Path(__file__).resolve().parent / "config" / "http.env"),
            "example_env": str(Path(__file__).resolve().parent / "config.example.env"),
        },
        "pipeline_capabilities": capabilities,
        "risk_status": agent_risk_status(capabilities),
        "route_defaults": {
            "process_material": "recognize_or_convert",
            "documents": "start_conversion",
            "pdf": "start_conversion",
            "images": "start_image_book_rebuild",
            "image_folders": "start_image_book_rebuild",
            "location_index": "requires intent=locate or query",
            "web_archives": "process_web_archive",
        },
        "long_task_guidance": {
            "prefer_async_tools": True,
            "poll_tool": "get_job_status",
            "heavy_routes": ["mineru", "marker", "umi", "docling", "paddleocr-vl", "qwen-vl"],
            "safe_pdf_default": "auto preflight, fallback diagnostics, versioned outputs",
            "large_pdf_advice": "Use page ranges or pipeline comparison before forcing whole-document heavy OCR/VLM.",
        },
        "recommended_agent_flow": [
            "call get_agent_contract once",
            "call process_material for unknown inputs",
            "poll get_job_status when job_id is returned",
            "read quality_summary before claiming output is final",
            "follow next_actions and read_artifact for reports/Markdown",
        ],
    }


def safe_pipeline_capabilities() -> dict[str, Any]:
    try:
        payload = health_check({"fast": True})
    except Exception as exc:  # noqa: BLE001
        return {
            "error": True,
            "message": str(exc),
            "ready": [],
            "degraded": [],
            "missing": ["health_check"],
            "capabilities": [],
        }
    return {
        "ready": payload.get("ready_capabilities", []),
        "degraded": payload.get("degraded_capabilities", []),
        "missing": payload.get("missing_capabilities", []),
        "capabilities": payload.get("capabilities", []),
    }


def agent_risk_status(capabilities: dict[str, Any]) -> str:
    if capabilities.get("error"):
        return "missing_dependencies"
    if capabilities.get("missing"):
        return "missing_dependencies"
    if capabilities.get("degraded"):
        return "degraded"
    return "ok"


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
    fast = bool(arguments.get("fast"))
    sources: list[Path] = []
    if getattr(options, "input", None):
        _, sources = resolve_sources_and_root(options)
    checks = dependency_health_report(sources, options, fast=fast)
    capability_checks = dependency_health_report([], options, fast=fast)
    capabilities = environment_capability_summary(capability_checks)
    return {
        "checks": checks,
        "capability_checks": capability_checks,
        "capabilities": capabilities,
        "ok": all(item["status"] != "missing" for item in checks),
        "ready_capabilities": [item["name"] for item in capabilities if item.get("status") == "ok"],
        "degraded_capabilities": [item["name"] for item in capabilities if item.get("status") == "degraded"],
        "missing_capabilities": [item["name"] for item in capabilities if item.get("status") == "missing"],
    }


def export_environment_report_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    input_value = arguments.get("input")
    output_dir = Path(arguments["output"])
    payload = export_environment_report(
        Path(input_value) if input_value else None,
        output_dir,
        recursive=bool(arguments.get("recursive", False)),
        include_hidden=bool(arguments.get("include_hidden", False)),
    )
    markdown_report = str(payload["markdown_report"])
    json_report = str(payload["json_report"])
    lock_report = str(payload["lock_report"])
    requirements_lock = str(payload["requirements_lock"])
    return {
        "status": "ok",
        "output": str(output_dir),
        "markdown_report": markdown_report,
        "json_report": json_report,
        "lock_report": lock_report,
        "requirements_lock": requirements_lock,
        "capabilities": payload.get("capabilities", []),
        "ready_capabilities": payload.get("ready_capabilities", []),
        "degraded_capabilities": payload.get("degraded_capabilities", []),
        "missing_capabilities": payload.get("missing_capabilities", []),
        "artifacts": [
            artifact(
                "environment_report",
                markdown_report,
                label="Environment report",
                media_type="text/markdown",
            ),
            artifact(
                "environment_json",
                json_report,
                label="Environment report JSON",
                media_type="application/json",
            ),
            artifact(
                "environment_lock",
                lock_report,
                label="Environment lock JSON",
                media_type="application/json",
            ),
            artifact(
                "requirements_lock",
                requirements_lock,
                label="Requirements lock snapshot",
                media_type="text/plain",
            ),
        ],
    }


def compare_environment_lock_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    output_value = arguments.get("output")
    payload = compare_environment_lock(
        Path(arguments["lock"]),
        Path(output_value) if output_value else None,
    )
    artifacts = []
    if payload.get("markdown_report"):
        artifacts.append(
            artifact(
                "environment_lock_compare",
                str(payload["markdown_report"]),
                label="Environment lock comparison",
                media_type="text/markdown",
            )
        )
    if payload.get("json_report"):
        artifacts.append(
            artifact(
                "environment_lock_compare_json",
                str(payload["json_report"]),
                label="Environment lock comparison JSON",
                media_type="application/json",
            )
        )
    return {
        "status": "ok",
        "severity": payload.get("severity"),
        "difference_count": payload.get("difference_count"),
        "differences": payload.get("differences", []),
        "markdown_report": payload.get("markdown_report", ""),
        "json_report": payload.get("json_report", ""),
        "artifacts": artifacts,
    }


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
            {"after_job_status": "done", "tool": "read_artifact", "artifact_type": "structure_report"},
            {"after_job_status": "done", "tool": "read_artifact", "artifact_type": "review_report"},
        ]
    elif route == "start_conversion":
        conversion_arguments = dict(delegated_arguments)
        conversion_arguments["pdf_pipeline_mode"] = choose_pdf_pipeline_mode(inspection, str(arguments.get("pdf_pipeline_mode") or "auto"))
        delegated = start_conversion(conversion_arguments)
        output_format = str(arguments.get("output_format") or "markdown")
        next_actions = [
            {"after_job_status": "done", "tool": "get_job_status", "purpose": "read quality_summary and concrete artifact paths"},
            {"after_job_status": "done", "tool": "read_artifact", "artifact_type": output_format},
            {"after_job_status": "done", "tool": "read_artifact", "artifact_type": "review_report"},
        ]
    elif route == "process_web_archive":
        delegated = process_web_archive_tool({"input": str(input_path)})
        next_actions = artifact_next_actions(delegated.get("artifacts", []))
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
    # Kept for API compatibility; auto mode now recognizes images by default.
    _ = image_book_threshold
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
        if images and not documents:
            return "start_image_book_rebuild"
        if documents:
            return "start_conversion"
    if kind == "web_archive":
        return "process_web_archive"
    if kind == "image":
        return "start_image_book_rebuild"
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
                quality_summary=conversion_quality_summary(results),
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
        (report_root / "review-decisions.md", "review_decisions", "Review decisions", "text/markdown"),
        (report_root / "review-decisions.json", "review_decisions_json", "Review decisions JSON", "application/json"),
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
    summary = report_root / "summary.md"
    if summary.exists():
        actions.append({"tool": "read_artifact", "arguments": {"path": str(summary), "artifact_type": "summary_report"}})
    summary_json = report_root / "summary.json"
    if summary_json.exists():
        actions.append({"tool": "read_artifact", "arguments": {"path": str(summary_json), "artifact_type": "summary_json"}})
    review = report_root / "review-checklist.md"
    if review.exists():
        actions.append({"tool": "read_artifact", "arguments": {"path": str(review), "artifact_type": "review_report"}})
    review_json = report_root / "review-checklist.json"
    if review_json.exists():
        actions.append({"tool": "read_artifact", "arguments": {"path": str(review_json), "artifact_type": "review_json"}})
    decisions = report_root / "review-decisions.md"
    if decisions.exists():
        actions.append({"tool": "read_artifact", "arguments": {"path": str(decisions), "artifact_type": "review_decisions"}})
    decisions_json = report_root / "review-decisions.json"
    if decisions_json.exists():
        actions.append({"tool": "read_artifact", "arguments": {"path": str(decisions_json), "artifact_type": "review_decisions_json"}})
    for item in conversion_artifacts(results, options):
        if item.get("type") in {"markdown", "html", "text", "summary_report"}:
            actions.append({"tool": "read_artifact", "arguments": {"path": item["path"], "artifact_type": item["type"]}})
            break
    actions.extend(conversion_review_next_actions(results, options))
    return unique_actions(actions)


def conversion_review_next_actions(results: list[Any], options: argparse.Namespace) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    output_root = Path(getattr(options, "output", ""))
    output_format = str(getattr(options, "output_format", "markdown") or "markdown")
    for result in results:
        report = getattr(result, "report", None)
        payload: dict[str, Any] = {}
        if report and Path(report).exists():
            try:
                payload = json.loads(Path(report).read_text(encoding="utf-8"))
            except Exception:
                payload = {}
        item = {**asdict(result), **payload}
        item.setdefault("source", getattr(result, "source", ""))
        item.setdefault("output", getattr(result, "output", ""))
        item.setdefault("report", report)
        item.setdefault("status", getattr(result, "status", ""))
        item.setdefault("pipeline", getattr(result, "pipeline", ""))
        quality = item.get("quality") or {}
        outline_alignment = item.get("pdf_outline_alignment") or {}
        needs_review = (
            str(getattr(result, "status", "")) == "failed"
            or quality.get("level") in {"review", "poor", "failed"}
            or outline_alignment.get("status") in {"low_alignment", "no_markdown_headings"}
        )
        has_fallback = "fallback" in str(item.get("pipeline") or "").lower() or bool(item.get("pdf_fallback_diagnostics"))
        if needs_review or has_fallback:
            actions.extend(executable_review_next_actions(item, output_root=output_root, output_format=output_format))
    return actions


def executable_review_next_actions(item: dict[str, Any], *, output_root: Path | None = None, output_format: str = "markdown") -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    source = str(item.get("source") or "")
    output = str(item.get("output") or "")
    report = str(item.get("report") or "")
    source_suffix = Path(source).suffix.lower()

    for raw_action in suggest_review_next_actions(item):
        action_name = str(raw_action.get("action") or "")
        why = raw_action.get("why")
        if action_name == "read_report" and raw_action.get("path"):
            actions.append(
                {
                    "action": "read_report",
                    "tool": "read_report",
                    "arguments": {"path": str(raw_action["path"])},
                    "why": why,
                }
            )
        elif action_name == "open_output" and raw_action.get("path"):
            path = str(raw_action["path"])
            actions.append(
                {
                    "action": "read_output",
                    "tool": "read_artifact",
                    "arguments": {"path": path, "artifact_type": infer_artifact_type(Path(path))},
                    "why": why,
                }
            )
        elif action_name == "rerun":
            pipeline = str(raw_action.get("pipeline") or "auto")
            rerun = rerun_action_for_pipeline(
                source,
                output,
                output_root=output_root,
                output_format=output_format,
                pipeline=pipeline,
                why=why,
            )
            if rerun:
                actions.append(rerun)
        elif action_name == "compare_pdf_pipelines" and source_suffix == ".pdf":
            pipelines = [part.strip() for part in str(raw_action.get("pipelines") or "mineru,docling,pymupdf4llm").split(",") if part.strip()]
            compare_args = [
                rerun_arguments_for_pipeline(
                    source,
                    output,
                    output_root=output_root,
                    output_format=output_format,
                    pipeline=pipeline,
                )
                for pipeline in pipelines
            ]
            compare_args = [args for args in compare_args if args]
            if compare_args:
                actions.append(
                    {
                        "action": "compare_pdf_pipelines",
                        "tool": "start_conversion",
                        "arguments_list": compare_args,
                        "why": why,
                    }
                )
        elif action_name == "inspect_pdf_outline" and report:
            actions.append(
                {
                    "action": "inspect_pdf_outline",
                    "tool": "read_report",
                    "arguments": {"path": report},
                    "why": why or "read pdf_outline and pdf_outline_alignment from the conversion report",
                }
            )
        elif action_name == "inspect_toc" and report:
            actions.append(
                {
                    "action": "inspect_toc",
                    "tool": "read_report",
                    "arguments": {"path": report},
                    "why": why or "read TOC alignment diagnostics from the conversion report",
                }
            )
        elif action_name == "export_location_review_pack" and source:
            review_output = str((output_root or Path(output).parent or Path(source).parent) / ".location-review")
            actions.append(
                {
                    "action": "build_location_index_for_review",
                    "tool": "start_location_index",
                    "arguments": {"input": source, "output": review_output, "recursive": False, "ocr": "auto"},
                    "why": why or "build a page/image-level index for OCR spot checks",
                }
            )
        elif action_name == "manual_accept_or_score":
            actions.append({"action": "manual_accept_or_score", "tool": None, "arguments": {}, "why": why})

    if item.get("pdf_fallback_diagnostics") and report:
        actions.append(
            {
                "action": "inspect_fallback_diagnostics",
                "tool": "read_report",
                "arguments": {"path": report},
                "why": "fallback diagnostics explain the original PDF tool failure and the fallback result",
            }
        )
    return unique_actions(actions)


def rerun_action_for_pipeline(
    source: str,
    output: str,
    *,
    output_root: Path | None,
    output_format: str,
    pipeline: str,
    why: str | None,
) -> dict[str, Any] | None:
    arguments = rerun_arguments_for_pipeline(source, output, output_root=output_root, output_format=output_format, pipeline=pipeline)
    if not arguments:
        return None
    return {
        "action": "rerun",
        "tool": "start_conversion",
        "arguments": arguments,
        "pipeline": pipeline,
        "why": why,
    }


def rerun_arguments_for_pipeline(
    source: str,
    output: str,
    *,
    output_root: Path | None,
    output_format: str,
    pipeline: str,
) -> dict[str, Any] | None:
    if not source:
        return None
    target_root = output_root if output_root and str(output_root) not in {"", "."} else None
    if target_root is None and output:
        target_root = Path(output).parent
    if target_root is None:
        target_root = Path(source).parent
    safe_pipeline = "".join(ch if ch.isalnum() else "-" for ch in pipeline.lower()).strip("-") or "auto"
    arguments: dict[str, Any] = {
        "input": source,
        "output": str(target_root),
        "recursive": False,
        "overwrite": False,
        "resume": False,
        "output_format": output_format,
        "output_name_suffix": f"-agent-rerun-{safe_pipeline}",
    }
    if Path(source).suffix.lower() == ".pdf" and pipeline not in {"auto", "calibre+pandoc"}:
        arguments["pdf_pipeline_mode"] = pipeline
    return arguments


def unique_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for action in actions:
        key = json.dumps(action, ensure_ascii=False, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        unique.append(action)
    return unique


def conversion_quality_summary(results: list[Any]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    review_items = []
    for result in results:
        report = getattr(result, "report", None)
        payload = {}
        if report and Path(report).exists():
            try:
                payload = json.loads(Path(report).read_text(encoding="utf-8"))
            except Exception:
                payload = {}
        quality = payload.get("quality") or {}
        outline_alignment = payload.get("pdf_outline_alignment") or {}
        outline_status = str(outline_alignment.get("status") or "")
        level = str(quality.get("level") or getattr(result, "status", "") or "unknown")
        counts[level] = counts.get(level, 0) + 1
        alignment_needs_review = outline_status in {"low_alignment", "no_markdown_headings"}
        if level in {"review", "poor", "failed"} or getattr(result, "status", "") == "failed" or alignment_needs_review:
            quality_reasons = list(quality.get("reasons") or [])
            if alignment_needs_review:
                quality_reasons.append(
                    f"PDF outline alignment requires review: {outline_status}, ratio={outline_alignment.get('match_ratio')}"
                )
            action_item = {**asdict(result), **payload}
            action_item.setdefault("report", report)
            review_items.append(
                {
                    "source": getattr(result, "source", ""),
                    "output": getattr(result, "output", ""),
                    "report": report,
                    "status": getattr(result, "status", ""),
                    "pipeline": getattr(result, "pipeline", ""),
                    "quality_level": quality.get("level"),
                    "quality_score": quality.get("score"),
                    "quality_reasons": quality_reasons,
                    "pdf_outline_alignment": outline_alignment,
                    "suggested_action": agent_suggested_quality_action(payload, result),
                    "next_actions": executable_review_next_actions(action_item),
                }
            )
    return {
        "counts": counts,
        "review_count": len(review_items),
        "review_items": review_items[:20],
    }


def agent_suggested_quality_action(payload: dict[str, Any], result: Any) -> str:
    quality = payload.get("quality") or {}
    reasons = " ".join(quality.get("reasons") or [])
    source = str(getattr(result, "source", "") or payload.get("source") or "")
    pipeline = str(getattr(result, "pipeline", "") or payload.get("pipeline") or "")
    if getattr(result, "status", "") == "failed":
        return "copy_failure_reason_or_retry"
    if source.lower().endswith(".pdf"):
        if any(token in reasons for token in ["标题", "页码", "重复短行", "OCR"]):
            return "run_compare_pipelines_or_rerun_recommended_pdf_backend"
        if "pymupdf" in pipeline.lower():
            return "review_output_then_compare_with_umi_or_mineru_if_structure_matters"
        return "open_review_checklist"
    if "标题" in reasons:
        return "inspect_original_toc_or_rerun_with_toc_alignment"
    return "read_report_and_review_output"


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
    if artifact_type in JSON_ARTIFACT_TYPES:
        try:
            payload["json"] = json.loads(text)
        except json.JSONDecodeError:
            payload["json_error"] = "Invalid JSON."
    if artifact_type in {"pages_jsonl", "location_index_jsonl"}:
        payload["records"] = parse_jsonl_preview(limited_lines)
    return payload


def inspect_agent_batch_results(arguments: dict[str, Any]) -> dict[str, Any]:
    path = Path(arguments["path"])
    max_review_items = clamp_int(arguments.get("max_review_items"), default=10, minimum=1, maximum=100)
    if not path.exists() or not path.is_file():
        return {"error": True, "message": f"Agent batch results file not found: {path}", "path": str(path)}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        return {"error": True, "message": f"Invalid agent batch JSON: {exc}", "path": str(path)}

    if payload.get("schema_version") != "agent-batch-v1":
        return {
            "error": True,
            "message": "Expected schema_version=agent-batch-v1.",
            "path": str(path),
            "schema_version": payload.get("schema_version"),
        }

    results = [item for item in payload.get("results") or [] if isinstance(item, dict)]
    review_items = agent_batch_review_items(results, max_review_items)
    next_actions = agent_batch_next_actions(path, payload)
    artifacts = agent_batch_artifacts(path, payload)
    attention = agent_batch_attention_summary(payload)
    return {
        "schema_version": "agent-batch-inspection-v1",
        "path": str(path),
        "contract": payload.get("contract") or {},
        "contract_validation": payload.get("contract_validation") or {},
        "manifest": payload.get("manifest"),
        "created_at": payload.get("created_at"),
        "duration_seconds": payload.get("duration_seconds"),
        "partial": bool(payload.get("partial")),
        "summary": payload.get("summary") or {},
        "selection": payload.get("selection") or {},
        "artifact_summary": payload.get("artifact_summary") or {},
        "attention": attention,
        "quality_comparison": payload.get("quality_comparison") or {},
        "next_actions": next_actions,
        "recommended_rerun": first_agent_batch_rerun_action(next_actions),
        "review_items": review_items,
        "artifacts": artifacts,
        "human_summary": agent_batch_human_summary(payload, next_actions),
    }


def list_agent_batch_results(arguments: dict[str, Any]) -> dict[str, Any]:
    root = Path(arguments["root"])
    max_results = clamp_int(arguments.get("max_results"), default=10, minimum=1, maximum=100)
    max_depth = clamp_int(arguments.get("max_depth"), default=3, minimum=0, maximum=10)
    max_review_items = clamp_int(arguments.get("max_review_items"), default=3, minimum=0, maximum=20)
    if not root.exists() or not root.is_dir():
        return {"error": True, "message": f"Agent batch root not found or not a directory: {root}", "root": str(root)}

    candidates = find_agent_batch_result_paths(root, max_depth=max_depth)
    candidates = sorted(candidates, key=lambda item: item.stat().st_mtime, reverse=True)[:max_results]
    items = []
    for path in candidates:
        inspected = inspect_agent_batch_results({"path": str(path), "max_review_items": max_review_items})
        items.append(
            {
                "path": str(path),
                "modified_at": timestamp_from_epoch(path.stat().st_mtime),
                "error": inspected.get("error", False),
                "contract": inspected.get("contract") or {},
                "contract_validation": inspected.get("contract_validation") or {},
                "summary": inspected.get("summary") or {},
                "selection": inspected.get("selection") or {},
                "artifact_summary": inspected.get("artifact_summary") or {},
                "attention": inspected.get("attention") or {},
                "quality_comparison": inspected.get("quality_comparison") or {},
                "recommended_rerun": inspected.get("recommended_rerun") or {},
                "human_summary": inspected.get("human_summary") or "",
                "review_items": inspected.get("review_items") or [],
                "artifacts": inspected.get("artifacts") or [],
            }
        )
    return {
        "schema_version": "agent-batch-list-v1",
        "root": str(root),
        "max_depth": max_depth,
        "count": len(items),
        "items": items,
        "next_actions": list_agent_batch_next_actions(items),
    }


def build_agent_handoff_bundle(arguments: dict[str, Any]) -> dict[str, Any]:
    output = Path(arguments["output"])
    max_review_items = clamp_int(arguments.get("max_review_items"), default=10, minimum=1, maximum=100)
    batch_results = Path(arguments["batch_results"]) if arguments.get("batch_results") else newest_agent_batch_results(arguments.get("root"))
    if not batch_results:
        return {"error": True, "message": "batch_results or root with an agent-batch-results.json is required"}
    if not batch_results.exists() or not batch_results.is_file():
        return {"error": True, "message": f"Agent batch results file not found: {batch_results}", "path": str(batch_results)}
    output.mkdir(parents=True, exist_ok=True)
    bundle = build_agent_handoff_bundle_payload(batch_results, max_review_items=max_review_items)
    json_path = output / "agent-handoff-bundle.json"
    md_path = output / "agent-handoff-bundle.md"
    json_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_agent_handoff_bundle_markdown(bundle), encoding="utf-8")
    artifacts = [
        artifact("agent_handoff_bundle_json", json_path, label="Agent handoff bundle JSON", media_type="application/json"),
        artifact("agent_handoff_bundle_markdown", md_path, label="Agent handoff bundle Markdown", media_type="text/markdown"),
    ]
    return {
        "schema_version": "agent-handoff-bundle-tool-v1",
        "status": "ok",
        "source": str(batch_results),
        "output": str(output),
        "bundle": bundle,
        "artifacts": artifacts,
        "next_actions": artifact_next_actions(artifacts),
    }


def newest_agent_batch_results(root: str | None) -> Path | None:
    if not root:
        return None
    listed = list_agent_batch_results({"root": root, "max_results": 1})
    items = listed.get("items") or []
    if not items:
        return None
    return Path(items[0]["path"])


def build_agent_handoff_bundle_payload(batch_results: Path, *, max_review_items: int = 10) -> dict[str, Any]:
    try:
        raw = json.loads(batch_results.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        return {
            "schema_version": "agent-handoff-bundle-v1",
            "source": str(batch_results),
            "handoff_ready": False,
            "handoff_status": "contract_failed",
            "recommended_next_action": {
                "action": "inspect_contract_validation",
                "reason": "The source agent-batch-results.json is invalid JSON; inspect or regenerate it before handoff.",
            },
            "contract_validation": {"ok": False, "errors": [f"invalid JSON: {exc}"]},
            "next_actions": [],
        }
    validation = validate_agent_batch_contract_payload(raw, batch_results)
    inspection = inspect_agent_batch_results({"path": str(batch_results), "max_review_items": max_review_items})
    attention = inspection.get("attention") or {}
    bundle = {
        "schema_version": "agent-handoff-bundle-v1",
        "source": str(batch_results),
        "contract_validation": validation,
        "inspection": inspection,
        "attention": attention,
        "summary": inspection.get("summary") or {},
        "selection": inspection.get("selection") or {},
        "artifact_summary": inspection.get("artifact_summary") or {},
        "next_actions": inspection.get("next_actions") or [],
        "artifacts": inspection.get("artifacts") or [],
        "review_items": inspection.get("review_items") or [],
    }
    bundle["handoff_ready"] = bool(validation.get("ok")) and not bool(attention.get("needs_attention"))
    status, recommendation = classify_agent_handoff_bundle(bundle)
    bundle["handoff_status"] = status
    bundle["recommended_next_action"] = recommendation
    return bundle


def classify_agent_handoff_bundle(bundle: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    validation = bundle.get("contract_validation") or {}
    if validation.get("ok") is not True:
        return (
            "contract_failed",
            recommended_bundle_action(
                bundle,
                "inspect_contract_validation",
                "The source batch contract did not validate; inspect errors before trusting handoff fields.",
            ),
        )
    attention = bundle.get("attention") or {}
    reasons = list(attention.get("reasons") or [])
    if "hard_failed_jobs" in reasons:
        return (
            "needs_recovery",
            recommended_bundle_action(
                bundle,
                "rerun_failed_or_review",
                "The batch has hard-failed jobs; rerun failed/review items before accepting the handoff.",
            ),
        )
    if "artifact_read_failures" in reasons:
        return (
            "needs_artifact_review",
            recommended_bundle_action(
                bundle,
                "inspect_failed_artifacts",
                "Some referenced artifacts were unreadable; inspect failed artifacts before accepting the handoff.",
            ),
        )
    if "quality_regression" in reasons:
        return (
            "needs_quality_compare",
            recommended_bundle_action(
                bundle,
                "read_quality_comparison",
                "Quality comparison reports a regression; inspect it before accepting the handoff.",
            ),
        )
    if "review_jobs" in reasons:
        return (
            "needs_review",
            recommended_bundle_action(
                bundle,
                "inspect_review_items",
                "Some jobs completed with review signals; inspect review items before accepting outputs.",
            ),
        )
    if attention.get("needs_attention"):
        return (
            "needs_attention",
            recommended_bundle_action(
                bundle,
                "inspect_agent_batch_results",
                "The batch needs attention; inspect the batch results before accepting the handoff.",
            ),
        )
    return (
        "ready",
        {
            "action": "accept_handoff",
            "reason": "Contract validation passed and no attention signals were detected.",
        },
    )


def recommended_bundle_action(bundle: dict[str, Any], action_name: str, reason: str) -> dict[str, Any]:
    for action in bundle.get("next_actions") or []:
        if not isinstance(action, dict):
            continue
        if action.get("action") == action_name:
            recommended = dict(action)
            recommended.setdefault("reason", reason)
            return recommended
    return {"action": action_name, "reason": reason}


def validate_agent_batch_contract_payload(payload: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    schema_version = payload.get("schema_version")
    errors: list[str] = []
    if schema_version == "agent-batch-v1":
        required = {"schema_version", "contract", "manifest", "created_at", "summary", "selection", "artifact_summary", "next_actions", "results"}
        payload_kind = "results"
    elif schema_version == "agent-batch-plan-v1":
        required = {"schema_version", "contract", "manifest", "created_at", "summary", "selection", "validation"}
        payload_kind = "plan"
    else:
        required = set()
        payload_kind = "unknown"
        errors.append(f"unsupported schema_version: {schema_version!r}")
    missing = sorted(field for field in required if field not in payload)
    if missing:
        errors.append(f"missing required fields: {', '.join(missing)}")
    contract = payload.get("contract") or {}
    if contract.get("schema_version") != "agent-batch-contract-v1":
        errors.append("contract.schema_version must be agent-batch-contract-v1")
    if contract.get("payload_schema_version") != schema_version:
        errors.append("contract.payload_schema_version must match payload schema_version")
    capabilities = set(contract.get("capabilities") or [])
    missing_capabilities = sorted(AGENT_BATCH_CONTRACT_CAPABILITIES - capabilities)
    if missing_capabilities:
        errors.append(f"missing capabilities: {', '.join(missing_capabilities)}")
    declared_required = set(contract.get("required_fields") or [])
    missing_declared = sorted(required - declared_required)
    if missing_declared:
        errors.append(f"contract.required_fields missing: {', '.join(missing_declared)}")
    return {
        "ok": not errors,
        "path": str(path) if path else "",
        "schema_version": schema_version,
        "payload_kind": payload_kind,
        "contract_schema_version": contract.get("schema_version"),
        "errors": errors,
    }


def render_agent_handoff_bundle_markdown(payload: dict[str, Any]) -> str:
    validation = payload.get("contract_validation") or {}
    attention = payload.get("attention") or {}
    summary = payload.get("summary") or {}
    selection = payload.get("selection") or {}
    artifact_summary = payload.get("artifact_summary") or {}
    lines = [
        "# Agent Handoff Bundle",
        "",
        f"- Source: `{payload.get('source', '')}`",
        f"- Handoff ready: {payload.get('handoff_ready')}",
        f"- Handoff status: {payload.get('handoff_status', '')}",
        f"- Contract validation: {'ok' if validation.get('ok') else 'failed'}",
        f"- Needs attention: {attention.get('needs_attention', False)}",
        f"- Attention reasons: {', '.join(attention.get('reasons') or []) or '(none)'}",
        f"- Recommended next action: {(payload.get('recommended_next_action') or {}).get('action', '')}",
        f"- Select: {selection.get('select', '')}",
        f"- Selected jobs: {selection.get('selected_count', 0)}/{selection.get('manifest_job_count', 0)}",
        f"- Total: {summary.get('total', 0)}",
        f"- OK: {summary.get('ok', 0)}",
        f"- Review: {summary.get('review', 0)}",
        f"- Hard failed: {summary.get('hard_failed', 0)}",
        f"- Artifact failures: {artifact_summary.get('failed', 0)}",
        "",
        "## Next Actions",
        "",
    ]
    actions = payload.get("next_actions") or []
    if actions:
        for action in actions:
            lines.append(f"- `{action.get('action') or action.get('tool')}`")
    else:
        lines.append("- (none)")
    review_items = payload.get("review_items") or []
    if review_items:
        lines.extend(["", "## Review Items", ""])
        for item in review_items[:10]:
            lines.append(f"- `{item.get('id')}` {item.get('quality_level', '')}: {item.get('suggested_action', '')}")
    return "\n".join(lines).rstrip() + "\n"


def find_agent_batch_result_paths(root: Path, *, max_depth: int) -> list[Path]:
    root = root.resolve()
    found: list[Path] = []
    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        try:
            relative = current_path.relative_to(root)
        except ValueError:
            dirs[:] = []
            continue
        depth = 0 if str(relative) == "." else len(relative.parts)
        if depth >= max_depth:
            dirs[:] = []
        if "agent-batch-results.json" in files:
            found.append(current_path / "agent-batch-results.json")
    return found


def list_agent_batch_next_actions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not items:
        return []
    newest = items[0]
    actions = [
        {
            "action": "inspect_latest_agent_batch",
            "tool": "inspect_agent_batch_results",
            "arguments": {"path": newest.get("path")},
        }
    ]
    if newest.get("recommended_rerun"):
        actions.append(newest["recommended_rerun"])
    return actions


def agent_batch_next_actions(path: Path, payload: dict[str, Any]) -> list[dict[str, Any]]:
    actions = [item for item in payload.get("next_actions") or [] if isinstance(item, dict)]
    names = {str(item.get("action") or item.get("tool") or "") for item in actions}

    def add_once(action: dict[str, Any]) -> None:
        name = str(action.get("action") or action.get("tool") or "")
        if name and name not in names:
            actions.append(action)
            names.add(name)

    run_summary = path.with_name("run_summary.partial.md" if payload.get("partial") else "run_summary.md")
    if run_summary.exists():
        add_once(
            {
                "action": "read_run_summary",
                "tool": "read_artifact",
                "arguments": {"path": str(run_summary), "artifact_type": "agent_batch_run_summary" if not payload.get("partial") else "markdown"},
                "reason": "Read the human-facing batch handoff summary before inspecting individual jobs.",
            }
        )
    add_once(
        {
            "action": "build_agent_handoff_bundle",
            "tool": "build_agent_handoff_bundle",
            "arguments": {"batch_results": str(path), "output": str(path.parent / ("handoff.partial" if payload.get("partial") else "handoff"))},
            "reason": "Create a compact agent-handoff-bundle.json/md package for another session or agent.",
        }
    )

    attention = agent_batch_attention_summary(payload)
    artifact_summary = payload.get("artifact_summary") or {}
    if int(artifact_summary.get("failed") or 0) > 0:
        add_once(
            {
                "action": "inspect_failed_artifacts",
                "failed_count": artifact_summary.get("failed"),
                "failed_artifacts": artifact_summary.get("failed_artifacts") or [],
                "reason": "One or more referenced artifacts could not be read during batch handoff.",
            }
        )
    if int(attention.get("review_jobs") or 0) > 0 or int(attention.get("review_items") or 0) > 0:
        add_once(
            {
                "action": "inspect_review_items",
                "review_jobs": attention.get("review_jobs", 0),
                "review_items": attention.get("review_items", 0),
                "reason": "Some jobs completed with review signals; inspect review items before accepting outputs.",
            }
        )
    contract_validation = payload.get("contract_validation") or {}
    if contract_validation.get("ok") is False:
        add_once(
            {
                "action": "inspect_contract_validation",
                "contract_validation": contract_validation,
                "reason": "The agent batch handoff contract did not validate; inspect errors before trusting handoff fields.",
            }
        )

    comparison = payload.get("quality_comparison") or {}
    if comparison.get("markdown"):
        add_once(
            {
                "action": "read_quality_comparison",
                "tool": "read_artifact",
                "arguments": {"path": comparison["markdown"], "artifact_type": "markdown"},
            }
        )
    if comparison.get("json"):
        add_once(
            {
                "action": "read_quality_comparison_json",
                "tool": "read_artifact",
                "arguments": {"path": comparison["json"], "artifact_type": "quality_comparison_json"},
            }
        )
    return actions


def timestamp_from_epoch(epoch: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(epoch))


def agent_batch_review_items(results: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    review_items: list[dict[str, Any]] = []
    for item in results:
        quality = ((item.get("job") or {}).get("quality_summary") or {})
        for review in quality.get("review_items") or []:
            if not isinstance(review, dict):
                continue
            review_items.append(
                {
                    "id": item.get("id"),
                    "status": item.get("status"),
                    "input": item.get("input"),
                    "output": item.get("output"),
                    "source": review.get("source"),
                    "report": review.get("report"),
                    "quality_level": review.get("quality_level"),
                    "quality_score": review.get("quality_score"),
                    "quality_reasons": review.get("quality_reasons") or [],
                    "suggested_action": review.get("suggested_action"),
                    "next_actions": review.get("next_actions") or [],
                }
            )
            if len(review_items) >= limit:
                return review_items
    return review_items


def agent_batch_artifacts(results_path: Path, payload: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = [
        artifact("agent_batch_results", results_path, label="Agent batch results", media_type="application/json"),
    ]
    base = results_path.parent
    for filename, artifact_type, label, media_type in [
        ("run_summary.md", "agent_batch_run_summary", "Agent batch run summary", "text/markdown"),
        ("agent-batch-summary.md", "agent_batch_summary", "Agent batch summary", "text/markdown"),
        ("benchmark-quality-comparison.md", "quality_comparison", "Quality comparison", "text/markdown"),
        ("benchmark-quality-comparison.json", "quality_comparison_json", "Quality comparison JSON", "application/json"),
    ]:
        candidate = base / filename
        if candidate.exists():
            artifacts.append(artifact(artifact_type, candidate, label=label, media_type=media_type))

    comparison = payload.get("quality_comparison") or {}
    for key, artifact_type, media_type in [
        ("markdown", "quality_comparison", "text/markdown"),
        ("json", "quality_comparison_json", "application/json"),
    ]:
        candidate = comparison.get(key)
        if candidate and Path(candidate).exists():
            item = artifact(artifact_type, Path(candidate), label=f"Quality comparison {key}", media_type=media_type)
            if not any(same_artifact(existing, item) for existing in artifacts):
                artifacts.append(item)
    return artifacts


def same_artifact(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left.get("type") != right.get("type"):
        return False
    try:
        return Path(str(left.get("path"))).resolve() == Path(str(right.get("path"))).resolve()
    except OSError:
        return str(left.get("path")) == str(right.get("path"))


def first_agent_batch_rerun_action(actions: list[dict[str, Any]]) -> dict[str, Any]:
    for action in actions:
        if action.get("action") == "rerun_failed_or_review":
            return action
    return {}


def agent_batch_attention_summary(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary") or {}
    artifact_summary = payload.get("artifact_summary") or {}
    comparison = payload.get("quality_comparison") or {}
    reasons: list[str] = []
    if payload.get("partial"):
        reasons.append("partial_run")
    if int(summary.get("hard_failed") or summary.get("failed") or 0) > 0:
        reasons.append("hard_failed_jobs")
    if int(summary.get("review") or 0) > 0:
        reasons.append("review_jobs")
    if int(summary.get("review_count") or 0) > 0:
        reasons.append("review_items")
    if int(artifact_summary.get("failed") or 0) > 0:
        reasons.append("artifact_read_failures")
    if comparison.get("status") == "failed":
        reasons.append("quality_regression")
    return {
        "needs_attention": bool(reasons),
        "reasons": reasons,
        "hard_failed": int(summary.get("hard_failed") or summary.get("failed") or 0),
        "review_jobs": int(summary.get("review") or 0),
        "review_items": int(summary.get("review_count") or 0),
        "artifact_failures": int(artifact_summary.get("failed") or 0),
        "quality_comparison": comparison.get("status") or "",
        "partial": bool(payload.get("partial")),
    }


def agent_batch_human_summary(payload: dict[str, Any], next_actions: list[dict[str, Any]]) -> str:
    summary = payload.get("summary") or {}
    comparison = payload.get("quality_comparison") or {}
    attention = agent_batch_attention_summary(payload)
    parts = [
        f"total={summary.get('total', 0)}",
        f"ok={summary.get('ok', 0)}",
        f"review={summary.get('review', 0)}",
        f"hard_failed={summary.get('hard_failed', 0)}",
    ]
    if comparison:
        parts.append(f"quality_comparison={comparison.get('status')}")
    rerun = first_agent_batch_rerun_action(next_actions)
    if rerun:
        parts.append("recommended_rerun=failed-or-review")
    if attention.get("needs_attention"):
        parts.append(f"attention={','.join(attention.get('reasons') or [])}")
    return "; ".join(parts)


def infer_artifact_type(path: Path) -> str:
    suffix = path.suffix.lower()
    name = path.name.lower()
    if suffix in {".md", ".markdown"}:
        if "agent-handoff-bundle" in name:
            return "agent_handoff_bundle_markdown"
        if "agent-smoke-summary" in name:
            return "agent_smoke_summary_markdown"
        return "markdown"
    if suffix == ".jsonl":
        if "location" in name:
            return "location_index_jsonl"
        return "pages_jsonl"
    if suffix == ".json":
        if "agent-handoff-bundle" in name:
            return "agent_handoff_bundle_json"
        if "agent-smoke-summary" in name:
            return "agent_smoke_summary_json"
        if "agent-batch-results" in name:
            return "agent_batch_results"
        if "review-decisions" in name:
            return "review_decisions_json"
        if "review-checklist" in name:
            return "review_json"
        if "summary" in name:
            return "summary_json"
        if "environment-report" in name:
            return "environment_json"
        if "environment-lock-compare" in name:
            return "environment_lock_compare_json"
        if "environment-lock" in name:
            return "environment_lock"
        if "benchmark-quality-comparison" in name:
            return "quality_comparison_json"
        if "visual_check_result" in name:
            return "visual_check_json"
        if "visual_blocks" in name:
            return "visual_blocks_json"
        if "table_candidates" in name:
            return "table_candidates_json"
        if "image_positions" in name:
            return "image_positions_json"
        if "report" in name:
            return "conversion_report"
        if "cluster" in name:
            return "clusters_json"
        if "structure" in name:
            return "structure_json"
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
        if artifact_type in READABLE_ARTIFACT_TYPES and path:
            actions.append({"tool": "read_artifact", "arguments": {"path": path, "artifact_type": artifact_type}})
    return actions[:4]


def process_web_archive_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    input_path = Path(arguments["input"])
    output_value = str(arguments.get("output") or "")
    result = process_web_archive_core(str(input_path), output_value)
    layout_ocr_path = result.get("layout_ocr_path") or ""
    visual_blocks_path = result.get("visual_blocks_path") or ""
    table_candidates_path = result.get("table_candidates_path") or ""
    image_positions_path = result.get("image_positions_path") or ""
    visual_check_result_path = str(Path(result["output_dir"]) / "visual_check_result.json")
    artifacts = [
        artifact("visual_check_json", visual_check_result_path, label="Visual check result", media_type="application/json"),
        artifact("markdown", layout_ocr_path, label="Visual OCR Markdown", media_type="text/markdown"),
        artifact("visual_blocks_json", visual_blocks_path, label="Visual blocks JSON", media_type="application/json"),
        artifact("table_candidates_json", table_candidates_path, label="Table candidates JSON", media_type="application/json"),
        artifact("image_positions_json", image_positions_path, label="Image positions JSON", media_type="application/json"),
    ]
    artifacts = [item for item in artifacts if item.get("path") and Path(str(item["path"])).exists()]
    return {
        **result,
        "artifacts": artifacts,
        "next_actions": artifact_next_actions(artifacts),
    }


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
