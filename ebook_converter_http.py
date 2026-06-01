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
    SERVER_NAME,
    SERVER_VERSION,
    call_tool,
    tool_schemas,
)
from ebook_markdown_pipeline.artifact_schema import SCHEMA_VERSION  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="HTTP bridge for Docker/remote agent access.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host. Use 0.0.0.0 for Docker container access.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token", default=os.environ.get("EBOOK_CONVERTER_API_TOKEN", ""))
    args = parser.parse_args()

    if args.host not in {"127.0.0.1", "localhost", "::1"} and not args.token:
        print("Refusing non-local bind without --token or EBOOK_CONVERTER_API_TOKEN.", file=sys.stderr)
        return 2

    handler = build_handler(args.token)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"{SERVER_NAME} HTTP bridge listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


def build_handler(token: str):
    started_at = time.time()

    class Handler(BaseHTTPRequestHandler):
        server_version = f"{SERVER_NAME}/{SERVER_VERSION}"

        def do_GET(self) -> None:  # noqa: N802
            if not self.authorized():
                self.write_error("unauthorized", "Unauthorized", status=401, retryable=False)
                return
            if self.path == "/health":
                tools = tool_schemas()
                self.write_json(
                    {
                        "ok": True,
                        "server": SERVER_NAME,
                        "version": SERVER_VERSION,
                        "schema_version": SCHEMA_VERSION,
                        "transport": "http",
                        "tool_count": len(tools),
                        "tools": [tool["name"] for tool in tools],
                        "supports_async_jobs": True,
                        "supports_artifacts": True,
                        "uptime_seconds": round(time.time() - started_at, 3),
                    }
                )
                return
            if self.path == "/tools":
                self.write_json({"tools": tool_schemas()})
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


if __name__ == "__main__":
    raise SystemExit(main())
