from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ebook_markdown_pipeline.online_document_pipeline import (  # noqa: E402
    OnlinePipelineOptions,
    run_online_document_pipeline,
)
from ebook_markdown_pipeline.shared_vkp_gateway import (  # noqa: E402
    SharedVkpGateway,
    SharedVkpGatewayError,
    shared_vkp_gateway_fast_health,
)
from test_shared_vkp_loopback_integration import LoopbackGatewayHandler  # noqa: E402


def main() -> int:
    litellm_command = shutil.which("litellm")
    if not litellm_command:
        print("Shared VKP LiteLLM integration skipped: litellm command is unavailable.")
        return 0
    try:
        gateway = SharedVkpGateway()
        fast_health = shared_vkp_gateway_fast_health()
    except SharedVkpGatewayError as exc:
        print(f"Shared VKP LiteLLM integration skipped: {exc}")
        return 0
    if (fast_health.get("gateway") or {}).get("ready"):
        print("Shared VKP LiteLLM integration skipped: configured gateway is already running.")
        return 0

    gateway_config = gateway.modules.gateway.load_model_gateway_config(gateway.gateway_config_path)
    gateway_host = str(gateway_config["host"])
    gateway_port = int(gateway_config["port"])
    if gateway_host not in {"127.0.0.1", "localhost"}:
        print(f"Shared VKP LiteLLM integration skipped: unsupported test host {gateway_host!r}.")
        return 0

    master_key = gateway.modules.gateway._read_secret(
        gateway.modules.gateway.MASTER_KEY_ID,
        gateway.secrets_path,
    )
    if not master_key:
        raise AssertionError("VKP gateway master key is unavailable in the DPAPI secret store.")
    ocr_route = gateway._resolve_route("ocr")
    vision_route = gateway._resolve_route("semantic_frame")
    text_route = gateway._resolve_route("text_llm")

    fixture_root = PROJECT_DIR / ".tmp-shared-vkp-litellm-integration"
    shutil.rmtree(fixture_root, ignore_errors=True)
    source_root = fixture_root / "input"
    output_root = fixture_root / "output"
    source_root.mkdir(parents=True)
    shutil.copy2(
        PROJECT_DIR / "benchmarks" / "fixtures" / "generated" / "images" / "infographic.png",
        source_root / "infographic.png",
    )

    LoopbackGatewayHandler.requests_seen = []
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), LoopbackGatewayHandler)
    upstream_port = int(upstream.server_address[1])
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()

    config_path = fixture_root / "litellm-loopback.yaml"
    log_path = fixture_root / "litellm-loopback.log"
    config_path.write_text(
        render_litellm_config(
            ocr_virtual_model=str(ocr_route["virtual_model"]),
            vision_virtual_model=str(vision_route["virtual_model"]),
            text_virtual_model=str(text_route["virtual_model"]),
            upstream_port=upstream_port,
        ),
        encoding="utf-8",
        newline="\n",
    )
    env = secretless_subprocess_environment(master_key)
    creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0
    log_handle = log_path.open("w", encoding="utf-8", errors="replace")
    process = subprocess.Popen(
        [
            litellm_command,
            "--config",
            str(config_path),
            "--host",
            gateway_host,
            "--port",
            str(gateway_port),
            "--telemetry",
            "False",
        ],
        cwd=str(PROJECT_DIR),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log_handle,
        stderr=log_handle,
        creationflags=creationflags,
    )
    try:
        wait_for_health(gateway_host, gateway_port, process, log_path, master_key)
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
                f"VKP LiteLLM online pipeline failed: status={result.get('status')}, "
                f"results={failures}, upstream_requests={LoopbackGatewayHandler.requests_seen}"
            )
        image_result = next((item for item in result.get("results") or [] if isinstance(item, dict)), {})
        vlm_stage = next((item for item in image_result.get("stages") or [] if item.get("stage") == "vlm_layout"), {})
        if vlm_stage.get("status") != "ok" or vlm_stage.get("selected_count") != 1 or not vlm_stage.get("remote_requests_made"):
            raise AssertionError(f"LiteLLM did not execute the shared semantic-frame virtual model: {vlm_stage}")
        structure_stages = [
            stage for stage in image_result.get("stages") or [] if stage.get("stage") == "text_structure"
        ]
        if not structure_stages or any(
            stage.get("status") != "ok" or not stage.get("remote_requests_made")
            for stage in structure_stages
        ):
            raise AssertionError(f"LiteLLM did not expose remote structure evidence: {structure_stages}")
        request_rows = list(LoopbackGatewayHandler.requests_seen)
        paths = [row["path"] for row in request_rows]
        if not any(path.endswith("/ocr") for path in paths):
            raise AssertionError(f"LiteLLM did not forward OCR to the local upstream: {request_rows}")
        if not any(path.endswith("/chat/completions") for path in paths):
            raise AssertionError(f"LiteLLM did not forward text to the local upstream: {request_rows}")
        if not all(row["authorization_present"] for row in request_rows):
            raise AssertionError("LiteLLM did not authenticate every local upstream request.")
        serialized = json.dumps(result, ensure_ascii=False).lower()
        for forbidden in ('"api_key":', '"authorization":', '"token":', '"password":'):
            if forbidden in serialized:
                raise AssertionError(f"Credential-like field leaked into LiteLLM integration result: {forbidden}")
        log_handle.flush()
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        if master_key in log_text:
            raise AssertionError("VKP gateway master key leaked into the LiteLLM log.")
        print(
            "Shared VKP LiteLLM integration passed: "
            f"sources={len(result.get('results') or [])}, upstream_calls={len(request_rows)}"
        )
        return 0
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        log_handle.close()
        upstream.shutdown()
        upstream.server_close()
        upstream_thread.join(timeout=5)
        shutil.rmtree(fixture_root, ignore_errors=True)


def render_litellm_config(
    *,
    ocr_virtual_model: str,
    vision_virtual_model: str,
    text_virtual_model: str,
    upstream_port: int,
) -> str:
    upstream_url = f"http://127.0.0.1:{upstream_port}/v1"
    values = {
        "ocr_virtual": json.dumps(ocr_virtual_model),
        "vision_virtual": json.dumps(vision_virtual_model),
        "text_virtual": json.dumps(text_virtual_model),
        "upstream": json.dumps(upstream_url),
    }
    return f"""model_list:
  - model_name: {values['ocr_virtual']}
    litellm_params:
      model: mistral/mistral-ocr-latest
      api_base: {values['upstream']}
      api_key: local-loopback-not-secret
      timeout: 30
    model_info:
      id: local-loopback-ocr
      mode: ocr
  - model_name: {values['vision_virtual']}
    litellm_params:
      model: openai/loopback-vision
      api_base: {values['upstream']}
      api_key: local-loopback-not-secret
      timeout: 30
    model_info:
      id: local-loopback-vision
      mode: chat
  - model_name: {values['text_virtual']}
    litellm_params:
      model: openai/loopback-text
      api_base: {values['upstream']}
      api_key: local-loopback-not-secret
      timeout: 30
    model_info:
      id: local-loopback-text
      mode: chat
router_settings:
  num_retries: 0
  enable_pre_call_checks: true
general_settings:
  master_key: os.environ/VKP_LITELLM_MASTER_KEY
  disable_spend_logs: true
litellm_settings:
  telemetry: false
  turn_off_message_logging: true
  redact_user_api_key_info: true
"""


def secretless_subprocess_environment(master_key: str) -> dict[str, str]:
    env = dict(os.environ)
    for key in list(env):
        upper = key.upper()
        if (
            upper.endswith("_API_KEY")
            or upper.endswith("_ACCESS_TOKEN")
            or upper.endswith("_AUTH_TOKEN")
            or upper in {"GH_TOKEN", "GITHUB_TOKEN", "OPENAI_API_KEY"}
        ):
            env.pop(key, None)
    env["VKP_LITELLM_MASTER_KEY"] = master_key
    existing_no_proxy = str(env.get("NO_PROXY") or env.get("no_proxy") or "")
    no_proxy_parts = [item for item in existing_no_proxy.split(",") if item.strip()]
    no_proxy_parts.extend(["127.0.0.1", "localhost"])
    env["NO_PROXY"] = ",".join(dict.fromkeys(no_proxy_parts))
    return env


def wait_for_health(
    host: str,
    port: int,
    process: subprocess.Popen,
    log_path: Path,
    master_key: str,
) -> None:
    deadline = time.monotonic() + 30
    url = f"http://{host}:{port}/health/liveliness"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if 200 <= int(response.status) < 300:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.25)
    detail = log_path.read_text(encoding="utf-8", errors="replace")[-3000:]
    if master_key:
        detail = detail.replace(master_key, "[REDACTED]")
    raise AssertionError(
        f"Temporary LiteLLM gateway did not become ready; exit={process.poll()}; log_tail={detail}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
