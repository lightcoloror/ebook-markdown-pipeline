from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.online_providers import (  # noqa: E402
    ProviderConfig,
    build_openai_compatible_chat_payload,
    fake_provider_for_type,
    load_provider_registry,
    provider_registry_health,
)


def main() -> int:
    assert_example_registry_loads()
    assert_fake_providers()
    assert_openai_payload()
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
    if health["provider_count"] < 3 or "providers" not in health:
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
