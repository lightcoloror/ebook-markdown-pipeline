from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.online_providers import (  # noqa: E402
    OnlineProviderError,
    ProviderConfig,
    build_openai_compatible_chat_payload,
    fake_provider_for_type,
    load_provider_registry,
    openai_compatible_provider,
    provider_registry_health,
)


def main() -> int:
    assert_example_registry_loads()
    assert_fake_providers()
    assert_openai_payload()
    assert_openai_adapter_contract()
    assert_health_errors()
    print("Online provider contract test passed.")
    return 0


def assert_example_registry_loads() -> None:
    registry = load_provider_registry(PROJECT_DIR / "config" / "online_models.example.json")
    if registry.schema_version != "online-model-providers-v1":
        raise AssertionError(f"Unexpected registry schema: {registry}")
    if registry.default_mode != "hybrid":
        raise AssertionError(f"Unexpected default mode: {registry}")
    if not registry.provider_for_route("layout_heavy_images"):
        raise AssertionError(f"Expected layout route provider: {registry}")
    health = registry.health()
    if health["provider_count"] < 4 or "providers" not in health:
        raise AssertionError(f"Unexpected registry health: {health}")
    if health["missing_key_count"] < 1:
        raise AssertionError(f"Example config should report missing keys without secrets: {health}")


def assert_fake_providers() -> None:
    ocr = fake_provider_for_type("ocr_layout").recognize_layout(b"abc", prompt="read")
    if ocr["blocks"][0]["text"] != "Fake OCR block" or ocr["input_bytes"] != 3:
        raise AssertionError(f"Unexpected fake OCR output: {ocr}")

    vlm = fake_provider_for_type("vlm_layout").describe_layout(b"image")
    if "# Fake Layout" not in vlm["markdown"]:
        raise AssertionError(f"Unexpected fake VLM output: {vlm}")

    repaired = fake_provider_for_type("text_structure_llm").repair_structure("Title\n\nBody")
    if not repaired["markdown"].startswith("# Title"):
        raise AssertionError(f"Unexpected fake repair output: {repaired}")

    embedding = fake_provider_for_type("embedding").embed_texts(["a", "abc"])
    if embedding["dimension"] != 2 or len(embedding["vectors"]) != 2:
        raise AssertionError(f"Unexpected fake embedding output: {embedding}")

    table = fake_provider_for_type("table_repair").repair_table("| A | B |\n| --- | --- |\n| 1 | 2 |")
    if not table["tables"] or "A" not in table["markdown"]:
        raise AssertionError(f"Unexpected fake table output: {table}")


def assert_openai_payload() -> None:
    config = ProviderConfig(name="demo", type="vlm_layout", base_url="https://example.com/v1", model="demo-vlm", api_key_env="DEMO_KEY")
    payload = build_openai_compatible_chat_payload(config, prompt="Extract structure", image=b"png", mime_type="image/png")
    if payload["model"] != "demo-vlm":
        raise AssertionError(f"Payload model mismatch: {payload}")
    content = payload["messages"][0]["content"]
    if content[0]["type"] != "text" or content[1]["type"] != "image_url":
        raise AssertionError(f"Payload content mismatch: {payload}")
    if "base64,cG5n" not in content[1]["image_url"]["url"]:
        raise AssertionError(f"Image payload was not base64 encoded: {payload}")


def assert_openai_adapter_contract() -> None:
    calls: list[dict] = []

    def transport(url: str, headers: dict[str, str], payload: dict, timeout_seconds: int) -> dict:
        calls.append({"url": url, "headers": headers, "payload": payload, "timeout_seconds": timeout_seconds})
        if url.endswith("/embeddings"):
            return {"data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}]}
        if "image_url" in json.dumps(payload, ensure_ascii=False):
            content = {"markdown": "# Visual", "blocks": [{"text": "Visual"}], "tables": [], "warnings": []}
        elif "Repair only true tables" in json.dumps(payload, ensure_ascii=False):
            content = {"markdown": "| A | B |\n| --- | --- |\n| 1 | 2 |", "tables": [{"markdown": "table"}], "decisions": [], "confidence": 0.9}
        else:
            content = {"markdown": "# Title\n\nBody", "decisions": [{"action": "promoted_to_heading"}], "confidence": 0.8}
        return {"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]}

    config = ProviderConfig(
        name="openai_test",
        type="text_structure_llm",
        base_url="https://example.test/v1/",
        model="demo-model",
        api_key_env="ONLINE_PROVIDER_TEST_KEY",
        timeout_seconds=12,
    )
    provider = openai_compatible_provider(config, transport=transport)
    missing_key = None
    try:
        provider.repair_structure("Title\n\nBody")
    except OnlineProviderError as exc:
        missing_key = exc
    if not missing_key or missing_key.retryable:
        raise AssertionError("Missing API key should fail before transport and should not be retryable.")

    old_value = os.environ.get("ONLINE_PROVIDER_TEST_KEY")
    os.environ["ONLINE_PROVIDER_TEST_KEY"] = "test-key"
    try:
        repaired = provider.repair_structure("Title\n\nBody", context={"source": "unit"})
        if not repaired["markdown"].startswith("# Title") or repaired["confidence"] != 0.8:
            raise AssertionError(f"Unexpected structure repair response: {repaired}")
        visual = provider.describe_layout(b"png", mime_type="image/png")
        if visual["blocks"][0]["text"] != "Visual":
            raise AssertionError(f"Unexpected VLM response: {visual}")
        table = provider.repair_table("| A | B |\n| --- | --- |\n| 1 | 2 |")
        if not table["tables"] or table["confidence"] != 0.9:
            raise AssertionError(f"Unexpected table repair response: {table}")
        embedding = provider.embed_texts(["a", "b"])
        if len(embedding["vectors"]) != 2:
            raise AssertionError(f"Unexpected embedding response: {embedding}")
    finally:
        if old_value is None:
            os.environ.pop("ONLINE_PROVIDER_TEST_KEY", None)
        else:
            os.environ["ONLINE_PROVIDER_TEST_KEY"] = old_value

    if not calls or not calls[0]["url"].startswith("https://example.test/v1/chat/completions"):
        raise AssertionError(f"Expected chat completions endpoint call: {calls}")
    if calls[0]["headers"].get("Authorization") != "Bearer test-key":
        raise AssertionError(f"Expected bearer token header without exposing secret elsewhere: {calls[0]}")
    if calls[0]["timeout_seconds"] != 12:
        raise AssertionError(f"Expected configured timeout: {calls[0]}")


def assert_health_errors() -> None:
    with tempfile.TemporaryDirectory(prefix="online-provider-test-") as tmp:
        missing = provider_registry_health(Path(tmp) / "missing.json")
        if missing.get("ok") is not False or missing.get("error") != "config_not_found":
            raise AssertionError(f"Expected missing config health error: {missing}")

        bad_json = Path(tmp) / "bad.json"
        bad_json.write_text("{", encoding="utf-8")
        invalid = provider_registry_health(bad_json)
        if invalid.get("ok") is not False or invalid.get("error") != "invalid_json":
            raise AssertionError(f"Expected invalid JSON health error: {invalid}")

        custom = Path(tmp) / "custom.json"
        custom.write_text(
            json.dumps(
                {
                    "schema_version": "online-model-providers-v1",
                    "default_mode": "local",
                    "providers": {"fake_text": {"type": "text_structure_llm", "model": "fake"}},
                }
            ),
            encoding="utf-8",
        )
        health = provider_registry_health(custom)
        if health.get("ok") is not True or health.get("provider_count") != 1:
            raise AssertionError(f"Expected custom health success: {health}")


if __name__ == "__main__":
    raise SystemExit(main())
