from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.candidate_backend_registry import (  # noqa: E402
    CANDIDATE_BACKENDS,
    REGISTRY_SCHEMA_VERSION,
    RUN_PREVIEW_SCHEMA_VERSION,
    READINESS_CONTRACT_SCHEMA_VERSION,
    candidate_backend_for_display,
    candidate_backend_for_key,
    candidate_backend_registry_payload,
    candidate_backends_for_sample_class,
)


def main() -> int:
    payload = candidate_backend_registry_payload()
    if payload.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise AssertionError(f"Unexpected registry schema: {payload}")
    if payload.get("remote_call_enabled") or payload.get("model_install_enabled"):
        raise AssertionError(f"Registry must stay non-executing: {payload}")
    if payload.get("run_preview_schema_version") != RUN_PREVIEW_SCHEMA_VERSION:
        raise AssertionError(f"Expected run preview schema in registry: {payload}")
    if payload.get("readiness_contract_schema_version") != READINESS_CONTRACT_SCHEMA_VERSION:
        raise AssertionError(f"Expected readiness contract schema in registry: {payload}")
    if len(payload.get("backends") or []) != len(CANDIDATE_BACKENDS):
        raise AssertionError(f"Expected all candidate backends in payload: {payload}")

    for profile in CANDIDATE_BACKENDS:
        if candidate_backend_for_key(profile.key) is not profile:
            raise AssertionError(f"Key lookup failed for {profile}")
        if candidate_backend_for_display(profile.display_name) is not profile:
            raise AssertionError(f"Display lookup failed for {profile}")
        for health_name in profile.health_names:
            if candidate_backend_for_display(health_name) is not profile:
                raise AssertionError(f"Health alias lookup failed for {health_name}")
        if not profile.module or not profile.command_hint or not profile.artifact_contract:
            raise AssertionError(f"Incomplete candidate profile: {profile}")
        as_payload = profile.to_dict()
        readiness = as_payload.get("readiness_contract") or {}
        if readiness.get("schema_version") != READINESS_CONTRACT_SCHEMA_VERSION:
            raise AssertionError(f"Expected readiness contract on profile payload: {as_payload}")
        if readiness.get("model_install_enabled") or readiness.get("service_start_enabled") or readiness.get("remote_call_enabled"):
            raise AssertionError(f"Readiness contract must stay non-executing: {readiness}")
        if list(readiness.get("supported_artifacts") or []) != list(profile.artifact_contract):
            raise AssertionError(f"Readiness contract should mirror artifacts: {readiness}")
        preview = profile.run_preview(capability="contract_test", trigger="fixture")
        if preview.get("schema_version") != RUN_PREVIEW_SCHEMA_VERSION or preview.get("default_mode") != "plan":
            raise AssertionError(f"Expected candidate run preview: {preview}")
        if preview.get("model_install_enabled") or preview.get("service_start_enabled") or preview.get("remote_call_enabled"):
            raise AssertionError(f"Preview must remain non-executing: {preview}")
        if (preview.get("readiness_contract") or {}).get("schema_version") != READINESS_CONTRACT_SCHEMA_VERSION:
            raise AssertionError(f"Preview should expose readiness contract: {preview}")
        if "external_wrapper_result_json" not in [item.get("artifact_type") for item in preview.get("next_actions") or [] if isinstance(item, dict)]:
            raise AssertionError(f"Expected read_artifact action for wrapper result: {preview}")
        if "candidate" not in profile.default_policy or "default" not in profile.default_policy:
            raise AssertionError(f"Candidate policy should name default behavior: {profile}")

    scanned = {item.display_name for item in candidate_backends_for_sample_class("scanned_pdf")}
    if not {"MonkeyOCR", "dots.mocr", "Tesseract OCR", "docTR"}.issubset(scanned):
        raise AssertionError(f"Expected scanned PDF VLM candidates: {scanned}")
    text_layer = {item.display_name for item in candidate_backends_for_sample_class("pdf_text_layer")}
    if not {"pypdf", "pdfminer.six"}.issubset(text_layer):
        raise AssertionError(f"Expected lightweight PDF fallback sample mapping: {text_layer}")
    table = {item.display_name for item in candidate_backends_for_sample_class("pdf_table")}
    if "pdf_table" not in table:
        raise AssertionError(f"Expected pdf_table sample mapping: {table}")
    layout = {item.display_name for item in candidate_backends_for_sample_class("pdf_two_column")}
    if not {"DocLayout-YOLO", "dots.mocr"}.issubset(layout):
        raise AssertionError(f"Expected layout sample mapping: {layout}")
    dots = candidate_backend_for_key("dots_mocr")
    dots_readiness = dots.readiness_contract() if dots else {}
    if not dots_readiness.get("manual_start_required") or "needs_server" not in dots_readiness.get("missing_states", []):
        raise AssertionError(f"Expected dots.mocr manual service readiness contract: {dots_readiness}")

    print("Candidate backend registry contract test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
