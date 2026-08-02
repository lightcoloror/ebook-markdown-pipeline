from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.shared_vkp_gateway import (  # noqa: E402
    SharedVkpGateway,
    SharedVkpGatewayError,
    execution_remote_requests_made,
    redacted_json,
    shared_provider_catalog,
    shared_vkp_gateway_fast_health,
)


def main() -> int:
    try:
        health = SharedVkpGateway().health()
    except SharedVkpGatewayError as exc:
        print(f"Shared VKP gateway test skipped: {exc}")
        return 0
    if health.get("status") not in {"ready", "on_demand", "degraded"}:
        raise AssertionError(f"Unexpected shared gateway status: {health}")
    fast_health = shared_vkp_gateway_fast_health()
    if fast_health.get("status") not in {"ready", "on_demand", "degraded"}:
        raise AssertionError(f"Unexpected fast shared gateway status: {fast_health}")
    if fast_health.get("probe_mode") != "fast_config_and_tcp":
        raise AssertionError(f"Fast health must avoid dynamic VKP runtime imports: {fast_health}")
    if fast_health.get("api_keys_exposed") is not False or fast_health.get("remote_requests_made") is not False:
        raise AssertionError(f"Fast health must remain secretless and read-only: {fast_health}")
    if health.get("api_keys_exposed") is not False or health.get("api_keys_copied") is not False:
        raise AssertionError(f"Shared gateway must never expose or copy API keys: {health}")
    if health.get("remote_requests_made") is not False:
        raise AssertionError(f"Health must be read-only: {health}")
    catalog = health.get("shared_provider_catalog") or {}
    if catalog.get("provider_count", 0) < 1 or catalog.get("api_keys_copied") is not False:
        raise AssertionError(f"Shared provider catalog is missing or unsafe: {catalog}")
    synthetic_catalog = shared_provider_catalog(
        [
            {"provider": "mistral", "enabled": True, "location": "remote", "capabilities": ["ocr"]},
            {"provider": "gemini", "enabled": True, "location": "remote", "capabilities": ["text", "vision"]},
            {"provider": "groq_asr", "enabled": True, "location": "remote", "capabilities": ["asr"]},
            {"provider": "local", "enabled": True, "location": "local", "capabilities": ["vision"]},
        ],
        {
            "ocr_layout": {
                "route": {"deployments": [{"provider": "mistral"}]},
            }
        },
    )
    if synthetic_catalog.get("provider_count") != 3:
        raise AssertionError(f"All enabled remote providers must remain discoverable: {synthetic_catalog}")
    if synthetic_catalog.get("ebook_eligible_profile_count") != 2:
        raise AssertionError(f"Ebook-eligible provider classification drifted: {synthetic_catalog}")
    if synthetic_catalog.get("selected_route_providers") != ["mistral"]:
        raise AssertionError(f"Selected route providers were not distinguished: {synthetic_catalog}")
    nested_network = {
        "ok": True,
        "model_result": {
            "ok": True,
            "network_accounting": {"gateway_request_bytes": 128, "gateway_response_bytes": 64},
        },
    }
    if not execution_remote_requests_made(nested_network, route={"execution_location": "remote"}):
        raise AssertionError("Nested VKP runtime network evidence was not normalized.")
    if execution_remote_requests_made(
        {"ok": False, "remote_requests_made": False, "model_result": {"ok": False}},
        route={"execution_location": "remote"},
    ):
        raise AssertionError("A blocked remote task was incorrectly reported as exported.")
    serialized = json.dumps(health, ensure_ascii=False).lower()
    for forbidden in ('"api_key":', '"authorization":', '"token":', '"password":'):
        if forbidden in serialized:
            raise AssertionError(f"Credential-like field leaked from shared health: {forbidden}")
    document_example = {"text": 'A document may literally mention {"api_key": "example"}.'}
    if "api_key" not in redacted_json(document_example):
        raise AssertionError("Document text should not be mistaken for a structured credential field.")
    try:
        redacted_json({"api_key": "must-not-be-written"})
    except SharedVkpGatewayError:
        pass
    else:
        raise AssertionError("Structured credential fields must fail closed.")

    fast_fixture = PROJECT_DIR / ".tmp-shared-vkp-fast"
    shutil.rmtree(fast_fixture, ignore_errors=True)
    (fast_fixture / "src" / "video_knowledge_pipeline").mkdir(parents=True)
    (fast_fixture / "src" / "video_knowledge_pipeline" / "model_gateway.py").write_text("# fixture\n", encoding="utf-8")
    (fast_fixture / ".local").mkdir(parents=True)
    (fast_fixture / "config").mkdir(parents=True)
    settings_path = fast_fixture / ".local" / "model-api-settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "route_bindings": {
                    "ocr": {"remote_pool_id": "pool-ocr"},
                    "text_llm": {"remote_pool_id": "pool-text"},
                    "semantic_frame": {"remote_pool_id": ""},
                },
                "task_routes": {"ocr": "ocr-profile", "text_llm": "text-profile"},
                "profiles": [
                    {
                        "id": "ocr-profile",
                        "provider": "mistral",
                        "model": "ocr-model",
                        "enabled": True,
                        "location": "remote",
                        "capabilities": ["ocr"],
                    },
                    {
                        "id": "text-profile",
                        "provider": "gemini",
                        "model": "text-model",
                        "enabled": True,
                        "location": "remote",
                        "capabilities": ["text"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (fast_fixture / "config" / "model-gateway.json").write_text(
        json.dumps({"host": "127.0.0.1", "port": 65534}),
        encoding="utf-8",
    )
    try:
        partial_health = shared_vkp_gateway_fast_health(fast_fixture)
        assert partial_health["missing_required_stages"] == []
        assert partial_health["missing_optional_stages"] == ["vlm_layout"]
        assert partial_health["status"] in {"ready", "on_demand"}
        assert partial_health["shared_provider_catalog"]["selected_route_providers"] == ["gemini", "mistral"]
        settings_path.write_text(
            json.dumps({"route_bindings": {"ocr": "", "text_llm": "", "semantic_frame": ""}}),
            encoding="utf-8",
        )
        empty_health = shared_vkp_gateway_fast_health(fast_fixture)
        assert set(empty_health["missing_required_stages"]) == {"ocr_layout", "text_structure"}
        assert empty_health["status"] == "degraded"
    finally:
        shutil.rmtree(fast_fixture, ignore_errors=True)
    readiness_sequence = iter(
        [
            {"ready": False, "status": "gateway_unavailable"},
            {"ready": False, "status": "gateway_unavailable"},
            {"ready": True, "status": "ready"},
        ]
    )
    startup_fixture = SharedVkpGateway.__new__(SharedVkpGateway)
    startup_fixture.settings_path = PROJECT_DIR / ".tmp-startup-settings.json"
    startup_fixture.secrets_path = PROJECT_DIR / ".tmp-startup-secrets.json"
    startup_fixture.gateway_config_path = PROJECT_DIR / ".tmp-startup-gateway.json"
    startup_fixture.modules = SimpleNamespace(
        gateway=SimpleNamespace(
            model_gateway_runtime_readiness=lambda **_kwargs: next(readiness_sequence),
            start_model_gateway=lambda **_kwargs: {"status": "started", "pid": 123},
        )
    )
    startup = startup_fixture.ensure_gateway(
        start=True,
        startup_timeout_seconds=1.0,
        poll_interval_seconds=0.01,
    )
    if not startup.get("ready") or startup["startup_wait"]["poll_attempts"] != 2:
        raise AssertionError(f"Gateway startup readiness polling regressed: {startup}")
    if startup["startup_wait"]["timed_out"]:
        raise AssertionError(f"A delayed but ready gateway was reported as timed out: {startup}")
    fixture_root = PROJECT_DIR / ".tmp-shared-vkp-gateway"
    shutil.rmtree(fixture_root, ignore_errors=True)
    fixture_root.mkdir(parents=True)
    try:
        artifact = fixture_root / "page.png"
        artifact.write_bytes(b"fake image")
        execution = {
            "ok": True,
            "status": "completed",
            "remote_requests_made": True,
            "model_result": {
                "content": {
                    "pages": [
                        {
                            "index": 0,
                            "markdown": "# Remote heading\n\nRemote OCR text.",
                        }
                    ]
                }
            },
        }
        consent_arguments = {}

        def create_consent(*_args, **kwargs):
            consent_arguments.update(kwargs)
            consent_arguments["allowed_roots_env"] = os.environ.get(
                "VKP_MODEL_RUNTIME_ALLOWED_ROOTS"
            )
            return {"status": "created"}

        fake_gateway = SharedVkpGateway.__new__(SharedVkpGateway)
        fake_gateway.root = PROJECT_DIR
        fake_gateway.settings_path = fixture_root / "settings.json"
        fake_gateway.secrets_path = fixture_root / "secrets.json"
        fake_gateway.gateway_config_path = fixture_root / "gateway.json"
        fake_gateway.modules = SimpleNamespace(
            gateway=SimpleNamespace(
                model_gateway_runtime_readiness=lambda **_kwargs: {"ready": True}
            ),
            consent=SimpleNamespace(
                create_model_connector_consent=create_consent
            ),
            trusted_connector=SimpleNamespace(
                execute_consented_model_task=lambda *_args, **_kwargs: execution
            ),
        )
        fake_gateway._resolve_route = lambda capability: {
            "route_id": f"test-{capability}",
            "route_revision": "test-revision",
            "virtual_model": "test-model",
            "execution_location": "remote",
            "retry_policy": {"max_retries": 0},
            "deployments": [
                {
                    "id": "test",
                    "provider": "fake",
                    "model": "fake-model",
                    "adapter_backend": "proxy",
                    "location": "remote",
                }
            ],
        }
        previous_allowed_roots = os.environ.get("VKP_MODEL_RUNTIME_ALLOWED_ROOTS")
        result = fake_gateway.execute(
            "ocr_layout",
            [artifact],
            instructions="recognize",
            run_dir=fixture_root / "run",
            max_estimated_cost_usd=0.01,
            confirm_data_export=True,
        )
        assert result["markdown"].startswith("# Remote heading")
        assert result["pages"][0]["page_number"] == 1
        assert result["api_keys_exposed"] is False
        assert result["api_keys_copied"] is False
        assert consent_arguments["max_retries_per_call"] == 0
        assert consent_arguments["max_calls"] == 1
        assert consent_arguments["allowed_roots_env"] == str(artifact.resolve())
        assert os.environ.get("VKP_MODEL_RUNTIME_ALLOWED_ROOTS") == previous_allowed_roots
        assert result["runtime_artifact_scope"] == "exact_artifact_paths"
        assert result["retry_policy"] == {
            "requested_max_retries_per_call": 1,
            "route_max_retries": 0,
            "effective_max_retries_per_call": 0,
            "logical_calls": 1,
            "authorized_attempts": 1,
        }
    finally:
        shutil.rmtree(fixture_root, ignore_errors=True)
    print(f"Shared VKP gateway test passed: {health['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
