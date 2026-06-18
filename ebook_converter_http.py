from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ebook_markdown_pipeline.ebook_converter_mcp import (  # noqa: E402
    SERVER_DISPLAY_NAME,
    SERVER_DISPLAY_NAME_EN,
    SERVER_NAME,
    SERVER_VERSION,
    agent_operating_context,
    agent_risk_status,
    call_tool,
    process_material_contract_payload,
    tool_schemas,
)
from ebook_markdown_pipeline.artifact_schema import SCHEMA_VERSION  # noqa: E402
from ebook_markdown_pipeline.http_config import HttpConfig, load_http_config  # noqa: E402


def main() -> int:
    config = load_http_config()
    parser = argparse.ArgumentParser(description="HTTP bridge for Docker/remote agent access.")
    parser.add_argument("--host", default=config.host, help=f"Bind host. Default from {config.source}. Use 0.0.0.0 for Docker container access.")
    parser.add_argument("--port", type=int, default=config.port, help=f"Bind port. Default from {config.source}.")
    parser.add_argument("--token", default=os.environ.get("EBOOK_CONVERTER_API_TOKEN", ""))
    args = parser.parse_args()

    if args.host not in {"127.0.0.1", "localhost", "::1"} and not args.token:
        print("Refusing non-local bind without --token or EBOOK_CONVERTER_API_TOKEN.", file=sys.stderr)
        return 2

    handler = build_handler(args.token, config=config, bind_host=args.host, bind_port=args.port)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"{SERVER_DISPLAY_NAME} ({SERVER_NAME}) HTTP bridge listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


def build_handler(token: str, *, config: HttpConfig | None = None, bind_host: str | None = None, bind_port: int | None = None):
    started_at = time.time()
    http_config = config or load_http_config()
    capability_cache: dict[str, Any] = {"time": 0.0, "payload": None}

    class Handler(BaseHTTPRequestHandler):
        server_version = f"{SERVER_NAME}/{SERVER_VERSION}"

        def do_GET(self) -> None:  # noqa: N802
            if not self.authorized():
                self.write_error("unauthorized", "Unauthorized", status=401, retryable=False)
                return
            if self.path == "/health":
                tools = tool_schemas()
                capabilities = cached_capability_summary(capability_cache)
                operating_context = agent_operating_context()
                minimal_status = minimal_capability_status(capabilities)
                self.write_json(
                    {
                        "ok": True,
                        "server": SERVER_NAME,
                        "display_name": SERVER_DISPLAY_NAME,
                        "display_name_en": SERVER_DISPLAY_NAME_EN,
                        "version": SERVER_VERSION,
                        "schema_version": SCHEMA_VERSION,
                        "transport": "http",
                        "tool_count": len(tools),
                        "tools": [tool["name"] for tool in tools],
                        "supports_async_jobs": True,
                        "supports_artifacts": True,
                        "http_config": {
                            "scheme": http_config.scheme,
                            "host": http_config.host,
                            "port": http_config.port,
                            "docker_host": http_config.docker_host,
                            "local_url": http_config.local_url,
                            "docker_url": http_config.docker_url,
                            "config_path": str(http_config.source),
                            "bind_host": bind_host or http_config.host,
                            "bind_port": bind_port or http_config.port,
                        },
                        "pipeline_capabilities": capabilities,
                        "risk_status": agent_risk_status(capabilities),
                        "provider_status": operating_context.get("online_provider_health", {}),
                        "backend_status": {
                            "ready": capabilities.get("ready", []),
                            "degraded": capabilities.get("degraded", []),
                            "missing": capabilities.get("missing", []),
                        },
                        "capability_status": {
                            "ready": capabilities.get("ready", []),
                            "degraded": capabilities.get("degraded", []),
                            "missing": capabilities.get("missing", []),
                        },
                        **minimal_status,
                        "operating_context": operating_context,
                        "config_sources": operating_context.get("config_sources", {}),
                        "local_env_exists": operating_context.get("local_env_exists", False),
                        "local_env_loaded_keys": operating_context.get("local_env_loaded_keys", []),
                        "route_defaults": operating_context.get("route_defaults", {}),
                        "long_task_guidance": operating_context.get("long_task_guidance", {}),
                        "uptime_seconds": round(time.time() - started_at, 3),
                    }
                )
                return
            if self.path == "/capabilities":
                capabilities = cached_capability_summary(capability_cache)
                operating_context = agent_operating_context()
                minimal_status = minimal_capability_status(capabilities)
                self.write_json(
                    {
                        "ok": True,
                        "server": SERVER_NAME,
                        "version": SERVER_VERSION,
                        "schema_version": "ebook-capabilities-v1",
                        "transport": "http",
                        "pipeline_capabilities": capabilities,
                        "risk_status": agent_risk_status(capabilities),
                        "provider_status": operating_context.get("online_provider_health", {}),
                        **minimal_status,
                        "route_defaults": operating_context.get("route_defaults", {}),
                        "long_task_guidance": operating_context.get("long_task_guidance", {}),
                    }
                )
                return
            if self.path == "/tools":
                self.write_json({"tools": tool_schemas()})
                return
            if self.path == "/contract":
                self.write_json(http_contract_payload(http_config, bind_host=bind_host, bind_port=bind_port))
                return
            self.write_error("not_found", f"Not found: {self.path}", status=404, retryable=False)

        def do_POST(self) -> None:  # noqa: N802
            if not self.authorized():
                self.write_error("unauthorized", "Unauthorized", status=401, retryable=False)
                return
            if self.path != "/call":
                self.write_error("not_found", f"Not found: {self.path}", status=404, retryable=False)
                return
            request_id = self.headers.get("X-Request-Id") or f"req-{uuid.uuid4().hex[:12]}"
            try:
                body = self.read_json()
                name = str(body.get("name") or "")
                arguments = body.get("arguments") or {}
                if not name:
                    raise ValueError("name is required")
                if not isinstance(arguments, dict):
                    raise ValueError("arguments must be an object")
                result = call_tool(name, arguments)
                envelope = {"request_id": request_id, "ok": True, "result": result}
                if isinstance(result, dict):
                    envelope.update(result)
                self.write_json(envelope)
            except json.JSONDecodeError as exc:
                self.write_error("invalid_json", f"Invalid JSON body: {exc}", status=400, retryable=False, request_id=request_id)
            except (KeyError, TypeError, ValueError) as exc:
                self.write_error("invalid_request", str(exc), status=400, retryable=False, request_id=request_id)
            except Exception as exc:  # noqa: BLE001
                self.write_error("tool_error", str(exc), status=500, retryable=True, request_id=request_id)

        def authorized(self) -> bool:
            if not token:
                return True
            header = self.headers.get("Authorization", "")
            return header == f"Bearer {token}" or self.headers.get("X-Api-Token", "") == token

        def read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length)
            if not raw:
                return {}
            payload = json.loads(raw.decode("utf-8-sig"))
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object")
            return payload

        def write_json(self, payload: dict[str, Any], status: int = 200) -> None:
            raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def write_error(
            self,
            code: str,
            message: str,
            *,
            status: int,
            retryable: bool,
            request_id: str | None = None,
        ) -> None:
            self.write_json(
                {
                    "request_id": request_id,
                    "ok": False,
                    "error": True,
                    "code": code,
                    "message": message,
                    "retryable": retryable,
                    "transport": "http",
                    "schema_version": SCHEMA_VERSION,
                },
                status=status,
            )

        def log_message(self, format: str, *args: Any) -> None:
            print(f"{self.address_string()} - {format % args}", file=sys.stderr)

    return Handler


def http_contract_payload(config: HttpConfig | None = None, *, bind_host: str | None = None, bind_port: int | None = None) -> dict[str, Any]:
    http_config = config or load_http_config()
    tools = tool_schemas()
    operating_context = agent_operating_context()
    return {
        "schema_version": "ebook-http-contract-v1",
        "server": SERVER_NAME,
        "display_name": SERVER_DISPLAY_NAME,
        "display_name_en": SERVER_DISPLAY_NAME_EN,
        "version": SERVER_VERSION,
        "transport": "http",
        "artifact_schema_version": SCHEMA_VERSION,
        "entrypoints": ["process_material", "get_job_status", "read_artifact"],
        "process_material_contract": process_material_contract_payload(),
        "specialist_tools": [
            "health_check",
            "show_latest_quality_gate",
            "inspect_document",
            "scan_books",
            "inspect_agent_batch_results",
            "list_agent_batch_results",
            "build_agent_handoff_bundle",
            "enhance_job_artifact",
        ],
        "supports_async_jobs": True,
        "supports_artifacts": True,
        "capability_endpoints": ["/health", "/capabilities", "/contract"],
        "operating_context": operating_context,
        "pipeline_capabilities": operating_context["pipeline_capabilities"],
        "risk_status": operating_context["risk_status"],
        "config_sources": operating_context["config_sources"],
        "local_env_exists": operating_context["local_env_exists"],
        "local_env_loaded_keys": operating_context["local_env_loaded_keys"],
        "long_task_guidance": operating_context["long_task_guidance"],
        "route_defaults": operating_context["route_defaults"],
        "http_config": {
            "scheme": http_config.scheme,
            "host": http_config.host,
            "port": http_config.port,
            "docker_host": http_config.docker_host,
            "local_url": http_config.local_url,
            "docker_url": http_config.docker_url,
            "config_path": str(http_config.source),
            "bind_host": bind_host or http_config.host,
            "bind_port": bind_port or http_config.port,
        },
        "tool_count": len(tools),
        "tools": tools,
        "docs": {
            "tool_contract": str(Path(__file__).resolve().parent / "docs" / "TOOL_CONTRACT.md"),
            "agent_integration": str(Path(__file__).resolve().parent / "docs" / "AGENT_INTEGRATION.md"),
            "agent_call_examples": str(Path(__file__).resolve().parent / "examples" / "agent-calls" / "README.md"),
        },
        "error_contract": {
            "ok": False,
            "error": True,
            "code": "invalid_request",
            "retryable": False,
            "transport": "http",
            "schema_version": SCHEMA_VERSION,
        },
    }


def safe_capability_summary() -> dict[str, Any]:
    try:
        payload = call_tool("health_check", {"fast": True})
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


def minimal_capability_status(capabilities: dict[str, Any]) -> dict[str, Any]:
    required = ["structured_ebooks", "pdf_fast_text"]
    missing = set(capabilities.get("missing") or [])
    missing_required = [name for name in required if name in missing]
    return {
        "minimal_ok": not missing_required,
        "minimal_required_capabilities": required,
        "missing_minimal_capabilities": missing_required,
        "optional_missing_is_ok": True,
    }


def cached_capability_summary(cache: dict[str, Any], *, ttl_seconds: float = 60.0) -> dict[str, Any]:
    now_time = time.time()
    cached = cache.get("payload")
    if isinstance(cached, dict) and now_time - float(cache.get("time") or 0) < ttl_seconds:
        return cached
    payload = safe_capability_summary()
    cache["time"] = now_time
    cache["payload"] = payload
    return payload


def health_risk_status(capabilities: dict[str, Any]) -> str:
    return agent_risk_status(capabilities)


if __name__ == "__main__":
    raise SystemExit(main())
