from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from ebook_markdown_pipeline.document_inspector import inspect_document


SCHEMA_VERSION = "adaptive-pdf-probe-plan-v1"
RESULT_SCHEMA_VERSION = "adaptive-pdf-probe-result-v1"
ALLOWED_PIPELINES = frozenset(
    {
        "marker",
        "mineru",
        "umi",
        "pymupdf4llm",
        "docling",
        "markitdown",
        "ocrmypdf",
        "pdfcraft",
        "olmocr",
    }
)


def build_adaptive_pdf_probe_plan(
    input_path: Path,
    output_root: Path,
    *,
    routing_profile: str = "best_quality",
    pipeline_timeout: float = 120.0,
    max_pipelines: int = 4,
    pipelines: list[str] | None = None,
) -> dict[str, Any]:
    inspection = inspect_document(
        input_path,
        sample_pages=8,
        routing_profile=routing_profile,
        output=output_root,
    )
    adaptive = inspection.get("adaptive_routing") if isinstance(inspection.get("adaptive_routing"), dict) else {}
    if inspection.get("status") != "ok" or inspection.get("kind") != "pdf":
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "unsupported",
            "input": str(input_path),
            "output": str(output_root),
            "inspection": inspection,
            "message": "Adaptive PDF probes require an existing supported PDF input.",
            "next_actions": [],
        }

    selected = normalize_pipelines(pipelines) if pipelines else pipelines_from_adaptive_plan(adaptive)
    selected = selected[: max(1, int(max_pipelines or 1))]
    if not selected:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "unsupported",
            "input": str(input_path),
            "output": str(output_root),
            "inspection": inspection,
            "message": "No local PDF candidate pipeline is available in the adaptive plan.",
            "next_actions": [],
        }

    pages = [int(value) for value in ((adaptive.get("sample_strategy") or {}).get("pages") or []) if int(value) > 0]
    if not pages:
        pages = [1]
    run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 1_000_000:06d}"
    run_dir = output_root / ".adaptive-probes" / f"{safe_name(input_path.stem)}-{run_id}"
    page_ranges = ",".join(str(page) for page in pages)
    compare_script = Path(__file__).resolve().parent / "scripts" / "compare_pipelines.py"
    command = [
        sys.executable,
        "-B",
        str(compare_script),
        "--input",
        str(input_path),
        "--output",
        str(run_dir),
        "--pipelines",
        *selected,
        "--page-ranges",
        page_ranges,
        "--pipeline-timeout",
        str(max(1.0, float(pipeline_timeout or 120.0))),
        "--minimum-score",
        str(int((adaptive.get("quality_gate") or {}).get("minimum_score") or 70)),
        "--selection-profile",
        str(adaptive.get("routing_profile") or routing_profile),
    ]
    expected_json = run_dir / "pipeline-comparison.json"
    expected_markdown = run_dir / "pipeline-comparison.md"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ready",
        "input": str(input_path),
        "output": str(output_root),
        "run_id": run_id,
        "run_dir": str(run_dir),
        "routing_profile": str(adaptive.get("routing_profile") or routing_profile),
        "representative_pages": pages,
        "page_ranges": page_ranges,
        "pipelines": selected,
        "pipeline_timeout_seconds": max(1.0, float(pipeline_timeout or 120.0)),
        "inspection": inspection,
        "adaptive_routing": adaptive,
        "command": command,
        "expected_artifacts": {
            "comparison_json": str(expected_json),
            "comparison_markdown": str(expected_markdown),
            "log": str(run_dir / "adaptive-probe.log"),
        },
        "safety": {
            "local_only": True,
            "remote_calls_allowed": False,
            "source_overwrite_allowed": False,
            "whole_document_conversion_started": False,
            "heavy_models_may_run_on_representative_pages": any(item in {"marker", "mineru", "docling", "pdfcraft", "olmocr"} for item in selected),
        },
        "next_actions": [
            {
                "action": "start_adaptive_pdf_probe",
                "tool": "start_adaptive_pdf_probe",
                "arguments": {
                    "input": str(input_path),
                    "output": str(output_root),
                    "routing_profile": str(adaptive.get("routing_profile") or routing_profile),
                    "pipeline_timeout": max(1.0, float(pipeline_timeout or 120.0)),
                    "max_pipelines": len(selected),
                    "pipelines": selected,
                },
                "safe_default": True,
                "destructive": False,
                "why": "Run isolated local candidates on representative pages before choosing a whole-document route.",
            }
        ],
    }


def execute_adaptive_pdf_probe_plan(plan: dict[str, Any]) -> dict[str, Any]:
    if plan.get("status") != "ready":
        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "status": "failed",
            "plan": plan,
            "message": str(plan.get("message") or "Adaptive probe plan is not executable."),
            "artifacts": [],
        }
    run_dir = Path(str(plan["run_dir"]))
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "adaptive-probe.log"
    started = time.monotonic()
    total_timeout = max(60.0, float(plan.get("pipeline_timeout_seconds") or 120.0) * len(plan.get("pipelines") or []) + 60.0)
    try:
        completed = subprocess.run(
            [str(value) for value in plan["command"]],
            cwd=str(Path(__file__).resolve().parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=total_timeout,
            check=False,
        )
        combined = "\n".join(value for value in (completed.stdout, completed.stderr) if value).strip()
        log_path.write_text(combined + ("\n" if combined else ""), encoding="utf-8")
    except subprocess.TimeoutExpired as exc:
        combined = "\n".join(str(value or "") for value in (exc.stdout, exc.stderr)).strip()
        log_path.write_text(combined + ("\n" if combined else ""), encoding="utf-8")
        return probe_result(
            plan,
            status="failed",
            duration_seconds=time.monotonic() - started,
            log_path=log_path,
            message=f"Adaptive probe exceeded total timeout: {total_timeout:.0f}s",
        )

    comparison_path = Path(str((plan.get("expected_artifacts") or {}).get("comparison_json") or ""))
    comparison: dict[str, Any] = {}
    if comparison_path.is_file():
        try:
            comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            comparison = {"error": str(exc)}
    status = "ok" if completed.returncode == 0 and comparison else "failed"
    message = "" if status == "ok" else f"Pipeline comparison exited with code {completed.returncode}."
    return probe_result(
        plan,
        status=status,
        duration_seconds=time.monotonic() - started,
        log_path=log_path,
        message=message,
        comparison=comparison,
    )


def probe_result(
    plan: dict[str, Any],
    *,
    status: str,
    duration_seconds: float,
    log_path: Path,
    message: str,
    comparison: dict[str, Any] | None = None,
) -> dict[str, Any]:
    comparison = comparison or {}
    expected = plan.get("expected_artifacts") or {}
    artifacts = []
    for artifact_type, key in (("pdf_pipeline_comparison_json", "comparison_json"), ("pdf_pipeline_comparison", "comparison_markdown"), ("tool_log", "log")):
        value = log_path if key == "log" else expected.get(key)
        path = Path(str(value or ""))
        if path.is_file():
            artifacts.append({"type": artifact_type, "path": str(path)})
    selection = comparison.get("selection") if isinstance(comparison.get("selection"), dict) else {}
    next_actions = []
    winner = str(selection.get("winner_pipeline") or "")
    if status == "ok" and winner:
        next_actions.append(
            {
                "action": "run_selected_pipeline_on_whole_document",
                "tool": "start_conversion",
                "arguments": {
                    "input": str(plan.get("input") or ""),
                    "output": str(plan.get("output") or ""),
                    "pdf_pipeline_mode": winner,
                    "output_format": "markdown",
                    "output_name_suffix": f".{winner}",
                    "overwrite": False,
                },
                "safe_default": bool(selection.get("auto_accept")),
                "destructive": False,
                "why": str(selection.get("reason") or "Use the representative-page winner on the full PDF with versioned output."),
            }
        )
    if not selection.get("auto_accept"):
        next_actions.append(
            {
                "action": "review_probe_comparison",
                "tool": "read_artifact",
                "arguments": {"path": str(expected.get("comparison_markdown") or ""), "artifact_type": "pdf_pipeline_comparison"},
                "safe_default": True,
                "destructive": False,
                "why": "The sampled winner is uncertain or below the quality gate; review evidence before a whole-document run.",
            }
        )
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "status": status,
        "duration_seconds": round(duration_seconds, 3),
        "message": message,
        "plan": plan,
        "comparison": comparison,
        "selection": selection,
        "artifacts": artifacts,
        "next_actions": next_actions,
    }


def pipelines_from_adaptive_plan(adaptive: dict[str, Any]) -> list[str]:
    values = []
    for item in adaptive.get("portfolio") or []:
        if not isinstance(item, dict) or item.get("remote"):
            continue
        arguments = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
        pipeline = str(arguments.get("pdf_pipeline_mode") or "")
        if pipeline in ALLOWED_PIPELINES and pipeline not in values:
            values.append(pipeline)
    return values


def normalize_pipelines(values: list[str] | None) -> list[str]:
    result = []
    for value in values or []:
        normalized = str(value or "").strip().lower()
        if normalized in ALLOWED_PIPELINES and normalized not in result:
            result.append(normalized)
    return result


def safe_name(value: str) -> str:
    cleaned = "".join(character if character.isalnum() or character in "-_." else "-" for character in value).strip("-._")
    return cleaned[:80] or "document"
