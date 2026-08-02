from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

from ebook_markdown_pipeline.online_document_pipeline import (  # noqa: E402
    OnlinePipelineOptions,
    run_online_document_pipeline,
)
from ebook_markdown_pipeline.shared_vkp_gateway import (  # noqa: E402
    redacted_json,
    shared_vkp_gateway_fast_health,
)
from generate_quality_fixtures import write_text_image  # noqa: E402


SCHEMA_VERSION = "ebook-online-supplier-smoke-v1"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Plan or execute a synthetic online-only supplier smoke through VKP shared routes. "
            "The default plan makes no supplier request."
        )
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--provider-mode", choices=("vkp_shared", "fake"), default="vkp_shared")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--confirm-data-export",
        action="store_true",
        help="Confirm export of the generated, non-sensitive smoke image to configured remote providers.",
    )
    parser.add_argument("--max-estimated-cost-usd", type=float, default=0.0)
    parser.add_argument("--start-shared-gateway", action="store_true")
    parser.add_argument("--vkp-root", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = run_supplier_smoke(
        args.output,
        provider_mode=args.provider_mode,
        execute=bool(args.execute),
        confirm_data_export=bool(args.confirm_data_export),
        max_estimated_cost_usd=float(args.max_estimated_cost_usd),
        start_shared_gateway=bool(args.start_shared_gateway),
        vkp_root=args.vkp_root,
    )
    print(redacted_json(payload))
    return 0 if payload.get("status") in {"planned", "passed"} else 2


def run_supplier_smoke(
    output: str | Path,
    *,
    provider_mode: str = "vkp_shared",
    execute: bool = False,
    confirm_data_export: bool = False,
    max_estimated_cost_usd: float = 0.0,
    start_shared_gateway: bool = False,
    vkp_root: str | Path | None = None,
) -> dict[str, Any]:
    output_root = Path(output).expanduser().resolve()
    run_id = f"supplier-smoke-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6]}"
    smoke_root = output_root / ".supplier-smoke-runs" / run_id
    fixture_root = smoke_root / "synthetic-input"
    pipeline_root = smoke_root / "pipeline-output"
    fixture_path = fixture_root / "online-supplier-smoke.png"
    smoke_root.mkdir(parents=True, exist_ok=False)
    write_text_image(
        fixture_path,
        [
            "Online Supplier Smoke",
            "Section 1: OCR and visual layout",
            "Section 2: Markdown structure",
            "Synthetic public fixture; no private data",
        ],
        size=(1100, 430),
        font_size=34,
    )

    preflight = shared_vkp_gateway_fast_health(vkp_root) if provider_mode == "vkp_shared" else fake_preflight()
    options = OnlinePipelineOptions(
        provider_mode=provider_mode,
        execute=execute,
        confirm_data_export=confirm_data_export,
        max_estimated_cost_usd=max_estimated_cost_usd,
        start_shared_gateway=start_shared_gateway,
        vkp_root=str(vkp_root or ""),
        recursive=False,
        overwrite=False,
        structure_pass=True,
        embedded_image_ocr=False,
        vlm_mode="always",
        vlm_max_pages=1,
        request_interval_seconds=0.0,
    )
    pipeline = run_online_document_pipeline(fixture_path, pipeline_root, options=options)
    stage_assertions = (
        evaluate_smoke_stages(pipeline, expect_remote=provider_mode == "vkp_shared")
        if execute
        else []
    )
    if not execute:
        status = "planned" if pipeline.get("status") == "planned" else "failed"
    else:
        status = "passed" if all(item["passed"] for item in stage_assertions) else "failed"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": status,
        "run_id": run_id,
        "run_root": str(smoke_root),
        "provider_mode": provider_mode,
        "execution_requested": execute,
        "synthetic_fixture": {
            "path": str(fixture_path),
            "contains_private_data": False,
            "purpose": "exercise online OCR, VLM layout, and text-structure routes",
        },
        "safety": {
            "confirmed_data_export": confirm_data_export,
            "max_estimated_cost_usd": max_estimated_cost_usd,
            "api_keys_copied": False,
            "api_keys_logged": False,
            "source_files_overwritten": False,
            "default_is_no_network_plan": True,
        },
        "preflight": preflight,
        "stage_assertions": stage_assertions,
        "pipeline": pipeline,
        "artifacts": [
            {"type": "supplier_smoke_json", "path": str(smoke_root / "online-supplier-smoke.json")},
            {"type": "supplier_smoke_report", "path": str(smoke_root / "online-supplier-smoke.md")},
        ],
    }
    write_smoke_artifacts(smoke_root, payload)
    return payload


def evaluate_smoke_stages(pipeline: dict[str, Any], *, expect_remote: bool) -> list[dict[str, Any]]:
    source_result = next(
        (item for item in pipeline.get("results") or [] if isinstance(item, dict)),
        {},
    )
    stages = [item for item in source_result.get("stages") or [] if isinstance(item, dict)]
    ocr = next((item for item in stages if item.get("stage") == "ocr_layout"), {})
    vlm = next((item for item in stages if item.get("stage") == "vlm_layout"), {})
    structure = [item for item in stages if item.get("stage") == "text_structure"]
    expected_request_value = expect_remote
    checks = [
        (
            "pipeline_completed",
            pipeline.get("status") == "ok",
            {"pipeline_status": pipeline.get("status")},
        ),
        (
            "ocr_layout_completed",
            ocr.get("status") == "ok" and bool(ocr.get("remote_requests_made")) == expected_request_value,
            compact_stage_evidence(ocr),
        ),
        (
            "vlm_layout_completed",
            vlm.get("status") == "ok"
            and int(vlm.get("selected_count") or 0) >= 1
            and bool(vlm.get("remote_requests_made")) == expected_request_value,
            compact_stage_evidence(vlm),
        ),
        (
            "text_structure_completed",
            bool(structure)
            and all(item.get("status") == "ok" for item in structure)
            and all(bool(item.get("remote_requests_made")) == expected_request_value for item in structure),
            {
                "chunk_count": len(structure),
                "statuses": [item.get("status") for item in structure],
                "remote_requests_made": [bool(item.get("remote_requests_made")) for item in structure],
                "providers": sorted(
                    {
                        str((item.get("route") or {}).get("provider") or "")
                        for item in structure
                        if (item.get("route") or {}).get("provider")
                    }
                ),
            },
        ),
    ]
    return [
        {"name": name, "passed": bool(passed), "evidence": evidence}
        for name, passed, evidence in checks
    ]


def compact_stage_evidence(stage: dict[str, Any]) -> dict[str, Any]:
    route = stage.get("route") if isinstance(stage.get("route"), dict) else {}
    return {
        "status": stage.get("status"),
        "selected_count": stage.get("selected_count"),
        "page_count": stage.get("page_count"),
        "remote_requests_made": bool(stage.get("remote_requests_made")),
        "provider": route.get("provider"),
        "virtual_model": route.get("virtual_model"),
    }


def fake_preflight() -> dict[str, Any]:
    return {
        "status": "ready",
        "provider_mode": "fake",
        "remote_requests_made": False,
        "api_keys_exposed": False,
    }


def write_smoke_artifacts(output_root: Path, payload: dict[str, Any]) -> None:
    json_path = output_root / "online-supplier-smoke.json"
    markdown_path = output_root / "online-supplier-smoke.md"
    json_path.write_text(redacted_json(payload) + "\n", encoding="utf-8", newline="\n")
    lines = [
        "# Online Supplier Smoke",
        "",
        f"- Status: `{payload.get('status')}`",
        f"- Provider mode: `{payload.get('provider_mode')}`",
        f"- Execution requested: `{str(bool(payload.get('execution_requested'))).lower()}`",
        f"- Confirmed data export: `{str(bool((payload.get('safety') or {}).get('confirmed_data_export'))).lower()}`",
        f"- Cost ceiling USD: `{float((payload.get('safety') or {}).get('max_estimated_cost_usd') or 0):.6f}`",
        "- Fixture: generated, non-sensitive, no private data",
        "",
        "## Stage Assertions",
        "",
        "| Stage | Passed | Evidence |",
        "| --- | --- | --- |",
    ]
    for item in payload.get("stage_assertions") or []:
        evidence = json.dumps(item.get("evidence") or {}, ensure_ascii=False, sort_keys=True).replace("|", "\\|")
        lines.append(f"| {item.get('name')} | {str(bool(item.get('passed'))).lower()} | `{evidence}` |")
    markdown_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    raise SystemExit(main())
