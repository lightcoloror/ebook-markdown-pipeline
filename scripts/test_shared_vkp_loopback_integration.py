from __future__ import annotations

import json
import shutil
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.online_document_pipeline import (  # noqa: E402
    OnlinePipelineOptions,
    run_online_document_pipeline,
)
from ebook_markdown_pipeline.shared_vkp_gateway import (  # noqa: E402
    SharedVkpGateway,
    SharedVkpGatewayError,
    shared_vkp_gateway_fast_health,
)


class LoopbackGatewayHandler(BaseHTTPRequestHandler):
    requests_seen: list[dict[str, Any]] = []

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path in {"/health", "/health/liveliness"}:
            self._write_json({"status": "ok"})
            return
        self._write_json({"error": "not_found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        size = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(size)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
        self.requests_seen.append(
            {
                "path": self.path,
                "model": str(payload.get("model") or ""),
                "authorization_present": bool(self.headers.get("Authorization")),
                "request_bytes": len(body),
            }
        )
        if self.path == "/v1/ocr":
            self._write_json(
                {
                    "model": str(payload.get("model") or "loopback-ocr"),
                    "pages": [
                        {
                            "index": 0,
                            "markdown": "# Loopback Remote OCR\n\nRecognized through the VKP runtime contract.",
                        }
                    ],
                    "usage_info": {"total_tokens": 1},
                    "response_cost": 0.0,
                }
            )
            return
        if self.path == "/v1/chat/completions":
            self._write_json(
                {
                    "id": "loopback-chat-completion",
                    "object": "chat.completion",
                    "model": str(payload.get("model") or "loopback-text"),
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "# Loopback Remote Structure\n\nStructured through the VKP runtime contract.",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"total_tokens": 1},
                    "response_cost": 0.0,
                }
            )
            return
        self._write_json({"error": "not_found"}, status=404)

    def _write_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("x-litellm-response-cost", "0")
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    try:
        gateway = SharedVkpGateway()
        fast_health = shared_vkp_gateway_fast_health()
    except SharedVkpGatewayError as exc:
        print(f"Shared VKP loopback integration skipped: {exc}")
        return 0
    gateway_plan = gateway.modules.gateway.start_model_gateway(
        gateway_config_path=gateway.gateway_config_path,
        settings_path=gateway.settings_path,
        secrets_path=gateway.secrets_path,
        execute=False,
    )
    render = gateway_plan.get("render") or {}
    if (
        gateway_plan.get("status") != "planned"
        or not render.get("ready_for_start")
        or int(render.get("model_count") or 0) < 2
        or render.get("credential_blockers")
        or gateway_plan.get("secrets_in_command") is not False
        or gateway_plan.get("remote_requests_made") is not False
    ):
        raise AssertionError(
            "VKP LiteLLM gateway plan is not ready or secretless: "
            f"status={gateway_plan.get('status')}, model_count={render.get('model_count')}, "
            f"ready={render.get('ready_for_start')}, "
            f"credential_blockers={len(render.get('credential_blockers') or [])}"
        )

    if (fast_health.get("gateway") or {}).get("ready"):
        print("Shared VKP loopback integration skipped: configured gateway is already running.")
        return 0
    gateway_config = gateway.modules.gateway.load_model_gateway_config(gateway.gateway_config_path)
    host = str(gateway_config["host"])
    port = int(gateway_config["port"])
    if host not in {"127.0.0.1", "localhost"}:
        print(f"Shared VKP loopback integration skipped: unsupported test host {host!r}.")
        return 0

    fixture_root = PROJECT_DIR / ".tmp-shared-vkp-loopback-integration"
    shutil.rmtree(fixture_root, ignore_errors=True)
    source_root = fixture_root / "input"
    output_root = fixture_root / "output"
    source_root.mkdir(parents=True)
    (source_root / "sample.txt").write_text(
        "Fifth Article\n\n(1) Remote structure integration fixture.",
        encoding="utf-8",
    )
    shutil.copy2(
        PROJECT_DIR / "benchmarks" / "fixtures" / "generated" / "images" / "infographic.png",
        source_root / "infographic.png",
    )

    LoopbackGatewayHandler.requests_seen = []
    server = ThreadingHTTPServer((host, port), LoopbackGatewayHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        options = OnlinePipelineOptions(
            provider_mode="vkp_shared",
            execute=True,
            confirm_data_export=True,
            max_estimated_cost_usd=10.0,
            start_shared_gateway=False,
            recursive=True,
            overwrite=False,
            structure_pass=True,
            embedded_image_ocr=True,
            request_interval_seconds=0,
        )
        result = run_online_document_pipeline(source_root, output_root, options=options)
        if result.get("status") != "ok":
            failures = [
                {
                    "source": Path(str(item.get("source") or "")).name,
                    "status": item.get("status"),
                    "message": item.get("message"),
                    "warnings": item.get("warnings") or [],
                }
                for item in result.get("results") or []
                if isinstance(item, dict)
            ]
            raise AssertionError(
                f"Loopback online pipeline failed: status={result.get('status')}, "
                f"results={failures}, requests={LoopbackGatewayHandler.requests_seen}"
            )
        results = [item for item in result.get("results") or [] if isinstance(item, dict)]
        if len(results) != 2 or any(item.get("status") != "ok" for item in results):
            raise AssertionError(f"Loopback source results failed: {results}")
        image_result = next((item for item in results if Path(str(item.get("source") or "")).suffix.lower() == ".png"), {})
        vlm_stage = next((item for item in image_result.get("stages") or [] if item.get("stage") == "vlm_layout"), {})
        if vlm_stage.get("status") != "ok" or vlm_stage.get("selected_count") != 1 or not vlm_stage.get("remote_requests_made"):
            raise AssertionError(f"Real VKP connector did not execute the shared VLM route: {vlm_stage}")
        structure_stages = [
            stage
            for item in results
            for stage in item.get("stages") or []
            if stage.get("stage") == "text_structure"
        ]
        if not structure_stages or any(
            stage.get("status") != "ok" or not stage.get("remote_requests_made")
            for stage in structure_stages
        ):
            raise AssertionError(f"Real VKP connector did not expose remote structure evidence: {structure_stages}")
        request_rows = list(LoopbackGatewayHandler.requests_seen)
        paths = [row["path"] for row in request_rows]
        if paths.count("/v1/ocr") != 1 or paths.count("/v1/chat/completions") < 2:
            raise AssertionError(f"Unexpected VKP runtime calls: {request_rows}")
        if not all(row["authorization_present"] for row in request_rows):
            raise AssertionError("VKP runtime did not authenticate every loopback gateway request.")
        if not all(row["model"] and row["request_bytes"] > 0 for row in request_rows):
            raise AssertionError(f"VKP runtime request contract was incomplete: {request_rows}")
        serialized = json.dumps(result, ensure_ascii=False).lower()
        for forbidden in ('"api_key":', '"authorization":', '"token":', '"password":'):
            if forbidden in serialized:
                raise AssertionError(f"Credential-like field leaked into online pipeline result: {forbidden}")
        print(
            "Shared VKP loopback integration passed: "
            f"sources={len(results)}, ocr_calls={paths.count('/v1/ocr')}, "
            f"text_calls={paths.count('/v1/chat/completions')}, "
            f"proxy_models={int(render.get('model_count') or 0)}"
        )
        return 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        shutil.rmtree(fixture_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
