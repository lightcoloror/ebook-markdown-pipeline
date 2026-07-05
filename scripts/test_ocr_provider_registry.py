from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.ocr_provider_registry import (  # noqa: E402
    OCR_PROVIDERS,
    OCR_PROVIDER_REGISTRY_SCHEMA_VERSION,
    executable_ocr_provider_keys,
    ocr_provider_for_display,
    ocr_provider_for_key,
    ocr_provider_registry_payload,
)


def main() -> int:
    payload = ocr_provider_registry_payload()
    if payload.get("schema_version") != OCR_PROVIDER_REGISTRY_SCHEMA_VERSION:
        raise AssertionError(f"Unexpected OCR provider registry schema: {payload}")
    if payload.get("remote_call_enabled") or payload.get("model_install_enabled"):
        raise AssertionError(f"Registry must not enable remote calls or model installs: {payload}")
    names = {item.get("display_name") for item in payload.get("providers") or []}
    expected = {"RapidOCR", "CnOCR", "Umi-OCR / PaddleOCR-json", "docTR", "Tesseract", "Surya OCR", "Pix2Text text-only"}
    if not expected.issubset(names):
        raise AssertionError(f"Missing OCR provider profiles: {payload}")
    executable = set(executable_ocr_provider_keys())
    if executable != {"rapidocr", "cnocr", "umi"}:
        raise AssertionError(f"Only current implemented providers should be executable: {executable}")
    for profile in OCR_PROVIDERS:
        if ocr_provider_for_key(profile.key) is not profile:
            raise AssertionError(f"Key lookup failed: {profile}")
        if ocr_provider_for_display(profile.display_name) is not profile:
            raise AssertionError(f"Display lookup failed: {profile}")
        if not profile.artifact_contract or "default" not in profile.default_policy:
            raise AssertionError(f"Incomplete OCR provider profile: {profile}")
    planned = {profile.key for profile in OCR_PROVIDERS if not profile.executable}
    if not {"doctr", "tesseract", "surya_ocr", "pix2text_text"}.issubset(planned):
        raise AssertionError(f"Expected planned-only OCR providers: {planned}")
    print("OCR provider registry contract test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
