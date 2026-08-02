from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import tempfile
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import fitz

from .batch_convert_books import (
    SUPPORTED_FORMATS,
    analyze_markdown_quality,
    clean_output_stem,
    convert_sources,
    default_options,
    inject_embedded_image_ocr_blocks,
    markdown_image_references,
    normalize_command_options,
)
from .chunk_map import chunk_by_title, parse_markdown_elements
from .online_providers import fake_provider_for_type
from .shared_vkp_gateway import SharedVkpGateway, redacted_json


SCHEMA_VERSION = "online-document-pipeline-v1"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
VISUAL_EXTENSIONS = IMAGE_EXTENSIONS | {".pdf"}
ProgressCallback = Callable[[str, Path, int, int, dict[str, Any]], None]


@dataclass
class OnlinePipelineOptions:
    provider_mode: str = "vkp_shared"
    execute: bool = False
    confirm_data_export: bool = False
    max_estimated_cost_usd: float = 0.0
    start_shared_gateway: bool = False
    vkp_root: str = ""
    recursive: bool = True
    include_hidden: bool = False
    overwrite: bool = False
    structure_pass: bool = True
    embedded_image_ocr: bool = True
    vlm_mode: str = "auto"
    vlm_max_pages: int = 12
    vlm_min_ocr_chars: int = 80
    max_chunk_chars: int = 12000
    render_dpi: int = 160
    request_interval_seconds: float = 0.25
    resume_manifest: str = ""


def run_online_document_pipeline(
    input_path: str | Path,
    output_root: str | Path,
    *,
    options: OnlinePipelineOptions | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    opts = options or OnlinePipelineOptions()
    source_input = Path(input_path).expanduser().resolve()
    destination = Path(output_root).expanduser().resolve()
    sources = collect_online_sources(
        source_input,
        recursive=opts.recursive,
        include_hidden=opts.include_hidden,
    )
    if not sources:
        return _error_payload("No supported files were found for online-only conversion.")
    if opts.provider_mode not in {"fake", "vkp_shared"}:
        return _error_payload(f"Unsupported provider_mode: {opts.provider_mode}")
    if opts.vlm_mode not in {"auto", "always", "never"}:
        return _error_payload(f"Unsupported vlm_mode: {opts.vlm_mode}")
    if opts.provider_mode == "vkp_shared" and opts.execute:
        if not opts.confirm_data_export:
            return _error_payload("Remote execution requires confirm_data_export=true.", code="data_export_confirmation_required")
        if float(opts.max_estimated_cost_usd) <= 0:
            return _error_payload("Remote execution requires a positive max_estimated_cost_usd.", code="cost_limit_required")

    destination.mkdir(parents=True, exist_ok=True)
    resume_payload, run_root, run_id = initialize_run(destination, opts)
    manifest_path = run_root / "manifest.json"
    source_root = source_input if source_input.is_dir() else source_input.parent
    output_disambiguators = build_output_disambiguators(sources, source_input, source_root)
    shared_gateway = SharedVkpGateway(opts.vkp_root or None) if opts.provider_mode == "vkp_shared" else None
    provider_health = shared_gateway.health() if shared_gateway else fake_provider_health()
    source_budget = float(opts.max_estimated_cost_usd) / max(len(sources), 1) if opts.max_estimated_cost_usd > 0 else 0.0
    previous_results = {
        str(item.get("source_sha256") or ""): item
        for item in resume_payload.get("results") or []
        if isinstance(item, dict)
    }
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "status": "running" if opts.execute else "planned",
        "mode": "online_only",
        "provider_mode": opts.provider_mode,
        "input": str(source_input),
        "output": str(destination),
        "run_root": str(run_root),
        "created_at": resume_payload.get("created_at") or timestamp(),
        "updated_at": timestamp(),
        "safety": safety_payload(opts),
        "provider_health": provider_health,
        "sources": [
            source_plan(source, output_disambiguator=output_disambiguators.get(source, ""))
            for source in sources
        ],
        "results": [],
    }
    write_json_artifact(manifest_path, manifest)
    if not opts.execute:
        artifacts = write_run_summary(run_root, manifest)
        return {
            **manifest,
            "status": "planned",
            "artifacts": artifacts,
            "next_actions": [
                {
                    "action": "execute_online_only_conversion",
                    "tool": "start_online_conversion",
                    "arguments": {
                        "input": str(source_input),
                        "output": str(destination),
                        "provider_mode": opts.provider_mode,
                        "execute": True,
                        "confirm_data_export": True,
                        "max_estimated_cost_usd": "REQUIRED_POSITIVE_NUMBER",
                    },
                    "safe_default": False,
                    "destructive": False,
                    "why": "execution sends exact source artifacts or rendered pages to configured remote providers",
                }
            ],
        }

    results: list[dict[str, Any]] = []
    total = len(sources)
    for index, source in enumerate(sources, start=1):
        source_hash = sha256_file(source)
        previous = previous_results.get(source_hash)
        if previous and previous.get("status") == "ok" and Path(str(previous.get("output") or "")).is_file():
            result = {**previous, "status": "skipped", "message": "Reused completed source from resume manifest."}
            results.append(result)
            emit_progress(progress_callback, "done", source, index, total, result)
            continue
        emit_progress(progress_callback, "start", source, index, total, {"mode": "online_only"})
        try:
            result = process_online_source(
                source,
                source_input=source_input,
                source_root=source_root,
                output_root=destination,
                run_root=run_root,
                run_id=run_id,
                options=opts,
                source_budget=source_budget,
                shared_gateway=shared_gateway,
                progress_callback=progress_callback,
                progress_index=index,
                progress_total=total,
                output_disambiguator=output_disambiguators.get(source, ""),
            )
        except Exception as exc:  # noqa: BLE001
            result = {
                "source": str(source),
                "source_sha256": source_hash,
                "status": "failed",
                "output": "",
                "message": f"{type(exc).__name__}: {exc}",
                "artifacts": [],
            }
        results.append(result)
        manifest["results"] = results
        manifest["updated_at"] = timestamp()
        write_json_artifact(manifest_path, manifest)
        emit_progress(progress_callback, "done", source, index, total, result)

    ok_count = sum(item.get("status") in {"ok", "skipped"} for item in results)
    failed_count = sum(item.get("status") == "failed" for item in results)
    status = "ok" if failed_count == 0 else ("partial" if ok_count else "failed")
    manifest.update(
        {
            "status": status,
            "finished_at": timestamp(),
            "updated_at": timestamp(),
            "results": results,
            "quality_summary": {
                "status": "review" if any((item.get("quality") or {}).get("level") in {"review", "poor"} for item in results) else status,
                "total": len(results),
                "ok": ok_count,
                "failed": failed_count,
                "review": sum((item.get("quality") or {}).get("level") == "review" for item in results),
                "poor": sum((item.get("quality") or {}).get("level") == "poor" for item in results),
            },
        }
    )
    artifacts = write_run_summary(run_root, manifest)
    manifest["artifacts"] = artifacts + [
        {"type": "markdown", "path": item["output"], "label": Path(item["output"]).name}
        for item in results
        if item.get("output") and Path(item["output"]).is_file()
    ]
    manifest["next_actions"] = online_next_actions(manifest)
    write_json_artifact(manifest_path, manifest)
    return manifest


def process_online_source(
    source: Path,
    *,
    source_input: Path,
    source_root: Path,
    output_root: Path,
    run_root: Path,
    run_id: str,
    options: OnlinePipelineOptions,
    source_budget: float,
    shared_gateway: SharedVkpGateway | None,
    progress_callback: ProgressCallback | None,
    progress_index: int,
    progress_total: int,
    output_disambiguator: str = "",
) -> dict[str, Any]:
    started = time.monotonic()
    source_hash = sha256_file(source)
    source_run = run_root / "sources" / source_hash[:16]
    source_run.mkdir(parents=True, exist_ok=True)
    output_path = online_output_path(
        source,
        source_input,
        source_root,
        output_root,
        run_id,
        options.overwrite,
        output_disambiguator=output_disambiguator,
    )
    visual = source.suffix.lower() in VISUAL_EXTENSIONS
    markdown = ""
    stage_reports: list[dict[str, Any]] = []
    warnings: list[str] = []

    if visual:
        emit_progress(progress_callback, "stage", source, progress_index, progress_total, {"stage": "render_pages"})
        images = render_visual_source(source, source_run / "pages", dpi=options.render_dpi)
        use_vlm = options.vlm_mode != "never"
        if use_vlm:
            ocr_budget = source_budget * (0.5 if options.structure_pass else 0.6)
            vlm_budget = source_budget * (0.3 if options.structure_pass else 0.4)
        else:
            ocr_budget = source_budget * (0.7 if options.structure_pass else 1.0)
            vlm_budget = 0.0
        ocr = run_ocr_stage(
            images,
            source=source,
            stage_dir=source_run / "ocr",
            options=options,
            budget=ocr_budget,
            shared_gateway=shared_gateway,
        )
        stage_reports.append(stage_summary(ocr, "ocr_layout"))
        page_payload = ocr
        if use_vlm:
            candidates = select_vlm_candidates(
                images,
                ocr.get("pages") or [],
                source=source,
                mode=options.vlm_mode,
                max_pages=options.vlm_max_pages,
                min_ocr_chars=options.vlm_min_ocr_chars,
            )
            if candidates:
                emit_progress(
                    progress_callback,
                    "stage",
                    source,
                    progress_index,
                    progress_total,
                    {"stage": "remote_vlm_layout", "selected_pages": len(candidates)},
                )
                vlm = run_vlm_stage(
                    candidates,
                    source=source,
                    stage_dir=source_run / "vlm",
                    options=options,
                    budget=vlm_budget,
                    shared_gateway=shared_gateway,
                )
                stage_reports.append(stage_summary(vlm, "vlm_layout"))
                warnings.extend(str(item) for item in vlm.get("warnings") or [])
                page_payload = {
                    **ocr,
                    "pages": fuse_ocr_vlm_pages(ocr.get("pages") or [], vlm.get("pages") or []),
                }
            else:
                stage_reports.append(
                    {
                        "stage": "vlm_layout",
                        "status": "not_needed",
                        "provider_mode": options.provider_mode,
                        "page_count": 0,
                        "selection_mode": options.vlm_mode,
                        "selection_reason": "no page met the deterministic VLM candidate rules",
                        "remote_requests_made": False,
                    }
                )
        markdown = render_ocr_pages(page_payload, source_kind="pdf" if source.suffix.lower() == ".pdf" else "image")
    else:
        emit_progress(progress_callback, "stage", source, progress_index, progress_total, {"stage": "deterministic_baseline"})
        baseline_path, baseline_result = build_deterministic_baseline(source, source_run / "baseline")
        stage_reports.append(baseline_result)
        markdown = baseline_path.read_text(encoding="utf-8", errors="replace")
        if options.embedded_image_ocr:
            markdown, embedded_report = enhance_embedded_images_online(
                markdown,
                baseline_path,
                source=source,
                stage_dir=source_run / "embedded-images",
                options=options,
                budget=source_budget * (0.35 if options.structure_pass else 1.0),
                shared_gateway=shared_gateway,
            )
            if embedded_report:
                stage_reports.append(embedded_report)

    if options.structure_pass:
        emit_progress(progress_callback, "stage", source, progress_index, progress_total, {"stage": "remote_structure"})
        structure_budget = source_budget * (0.2 if visual and options.vlm_mode != "never" else (0.3 if visual else 0.65))
        markdown, structure_reports, structure_warnings = run_structure_stage(
            markdown,
            source=source,
            stage_dir=source_run / "structure",
            options=options,
            budget=structure_budget,
            shared_gateway=shared_gateway,
        )
        stage_reports.extend(structure_reports)
        warnings.extend(structure_warnings)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown.rstrip() + "\n", encoding="utf-8", newline="\n")
    quality = analyze_markdown_quality(output_path)
    report = {
        "schema_version": SCHEMA_VERSION,
        "source": str(source),
        "source_sha256": source_hash,
        "status": "ok",
        "mode": "online_only",
        "provider_mode": options.provider_mode,
        "output_disambiguator": output_disambiguator,
        "output": str(output_path),
        "quality": asdict(quality) if quality else {},
        "duration_seconds": round(time.monotonic() - started, 3),
        "stages": stage_reports,
        "warnings": warnings,
        "safety": safety_payload(options),
    }
    report_path = source_run / "source-report.json"
    write_json_artifact(report_path, report)
    report["report"] = str(report_path)
    report["artifacts"] = [
        {"type": "markdown", "path": str(output_path), "label": "Online-only Markdown"},
        {"type": "conversion_report", "path": str(report_path), "label": "Online-only source report"},
    ]
    return report


def build_deterministic_baseline(source: Path, destination: Path) -> tuple[Path, dict[str, Any]]:
    destination.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() in {".md", ".txt"}:
        output = destination / f"{clean_output_stem(source.stem)}.md"
        output.write_text(source.read_text(encoding="utf-8", errors="replace"), encoding="utf-8", newline="\n")
        return output, {
            "stage": "deterministic_baseline",
            "status": "ok",
            "pipeline": "direct-text",
            "output": str(output),
            "local_model_inference": False,
            "reason": "plain-text normalization only; OCR/VLM/structure inference is remote",
        }
    reports = destination / ".reports"
    options = normalize_command_options(
        default_options(
            output_format="markdown",
            overwrite=True,
            resume=False,
            document_pipeline_mode="markitdown",
            embedded_image_ocr="never",
            report_dir=reports,
            summary=reports / "summary.md",
            no_reports=False,
        )
    )
    with isolated_temp_directory(destination / ".tmp"):
        results = convert_sources([source], source, destination, options)
    result = results[0]
    if result.status != "ok" or not result.output or not Path(result.output).is_file():
        raise RuntimeError(f"Deterministic baseline failed: {result.message or result.status}")
    if "docling" in str(result.pipeline).lower():
        raise RuntimeError("online_only refuses a Docling baseline because local model inference may be enabled")
    return Path(result.output), {
        "stage": "deterministic_baseline",
        "status": "ok",
        "pipeline": result.pipeline,
        "output": result.output,
        "local_model_inference": False,
        "reason": "format decoding only; OCR/VLM/structure inference is remote",
    }


def run_ocr_stage(
    images: list[Path],
    *,
    source: Path,
    stage_dir: Path,
    options: OnlinePipelineOptions,
    budget: float,
    shared_gateway: SharedVkpGateway | None,
) -> dict[str, Any]:
    stage_dir.mkdir(parents=True, exist_ok=True)
    result_path = stage_dir / "ocr-result.json"
    existing = load_json(result_path)
    if existing.get("status") == "ok" and existing.get("pages"):
        return {**existing, "resumed": True}
    instructions = (
        "Recognize every visible text block and reconstruct reading order. Return Markdown, preserving true headings, "
        "lists and true tables. Do not turn page numbers into headings. Do not omit small but meaningful labels."
    )
    if options.provider_mode == "fake":
        provider = fake_provider_for_type("ocr_layout")
        pages = []
        for index, image in enumerate(images, start=1):
            response = provider.recognize_layout(image.read_bytes(), mime_type=mime_type_for(image), prompt=instructions)
            markdown = str(response.get("markdown") or response.get("text") or "").strip()
            if not markdown:
                markdown = "\n\n".join(
                    str(block.get("text") or "").strip()
                    for block in response.get("blocks") or []
                    if isinstance(block, dict) and str(block.get("text") or "").strip()
                )
            pages.append({"page_number": index, "index": index - 1, "markdown": markdown})
        result = {
            "status": "ok" if any(str(page.get("markdown") or "").strip() for page in pages) else "failed",
            "provider_mode": "fake",
            "source": str(source),
            "pages": pages,
            "remote_requests_made": False,
        }
    else:
        if shared_gateway is None:
            raise RuntimeError("Shared VKP gateway is unavailable.")
        call = shared_gateway.execute(
            "ocr_layout",
            images,
            instructions=instructions,
            run_dir=stage_dir,
            max_estimated_cost_usd=positive_budget(budget),
            confirm_data_export=options.confirm_data_export,
            start_gateway=options.start_shared_gateway,
        )
        execution = call.get("execution") if isinstance(call.get("execution"), dict) else {}
        pages = [item for item in (call.get("pages") or []) if isinstance(item, dict)]
        if not pages and str(call.get("markdown") or "").strip():
            pages = [{"page_number": 1, "index": 0, "markdown": str(call["markdown"]).strip()}]
        has_text = any(str(item.get("markdown") or "").strip() for item in pages)
        result = {
            "status": "ok" if execution.get("ok") and has_text else "failed",
            "provider_mode": "vkp_shared",
            "source": str(source),
            "pages": pages,
            "consent_path": call.get("consent_path"),
            "route": call.get("route") or {},
            "execution_artifacts": execution.get("artifacts") or {},
            "remote_requests_made": bool(call.get("remote_requests_made")),
        }
        if result["status"] != "ok":
            reason = execution.get("status") or ("empty_remote_ocr" if execution.get("ok") else "unknown")
            raise RuntimeError(f"Remote OCR failed: {reason}")
    write_json_artifact(result_path, result)
    return result

def select_vlm_candidates(
    images: list[Path],
    ocr_pages: list[dict[str, Any]],
    *,
    source: Path,
    mode: str,
    max_pages: int,
    min_ocr_chars: int,
) -> list[dict[str, Any]]:
    page_map: dict[int, dict[str, Any]] = {}
    for position, page in enumerate(ocr_pages, start=1):
        if not isinstance(page, dict):
            continue
        page_number = int(page.get("page_number") or (int(page.get("index") or (position - 1)) + 1))
        page_map[page_number] = page
    selected: list[dict[str, Any]] = []
    limit = max(0, int(max_pages))
    if limit == 0 or mode == "never":
        return selected
    for page_number, image in enumerate(images, start=1):
        page = page_map.get(page_number) or {}
        markdown = str(page.get("markdown") or "").strip()
        reasons: list[str] = []
        if mode == "always":
            reasons.append("vlm_mode_always")
        elif source.suffix.lower() in IMAGE_EXTENSIONS:
            reasons.append("standalone_image")
        else:
            visible_chars = len(re.sub(r"\s+", "", markdown))
            if visible_chars < max(1, int(min_ocr_chars)):
                reasons.append("low_ocr_text")
            if looks_fragmented_layout(markdown):
                reasons.append("fragmented_short_blocks")
            if looks_tabular_layout(markdown):
                reasons.append("table_or_grid_candidate")
        if not reasons:
            continue
        selected.append(
            {
                "page_number": page_number,
                "index": page_number - 1,
                "image": image,
                "ocr_markdown": markdown,
                "selection_reasons": reasons,
            }
        )
        if len(selected) >= limit:
            break
    return selected


def looks_fragmented_layout(markdown: str) -> bool:
    lines = [
        re.sub(r"^\s*(?:#{1,6}|[-*+]\s+|\d+[.)]\s+)", "", line).strip()
        for line in markdown.splitlines()
        if line.strip() and not line.lstrip().startswith("<!--")
    ]
    if len(lines) < 6:
        return False
    short_lines = sum(1 for line in lines if len(line) <= 36)
    return short_lines / len(lines) >= 0.7


def looks_tabular_layout(markdown: str) -> bool:
    pipe_lines = [line for line in markdown.splitlines() if line.count("|") >= 2]
    return len(pipe_lines) >= 2


def run_vlm_stage(
    candidates: list[dict[str, Any]],
    *,
    source: Path,
    stage_dir: Path,
    options: OnlinePipelineOptions,
    budget: float,
    shared_gateway: SharedVkpGateway | None,
) -> dict[str, Any]:
    stage_dir.mkdir(parents=True, exist_ok=True)
    result_path = stage_dir / "vlm-result.json"
    existing = load_json(result_path)
    if existing.get("status") in {"ok", "partial"} and existing.get("pages"):
        return {**existing, "resumed": True}
    pages: list[dict[str, Any]] = []
    warnings: list[str] = []
    routes: list[dict[str, Any]] = []
    per_page_budget = positive_budget(budget / max(len(candidates), 1)) if options.provider_mode == "vkp_shared" else 0.0
    for position, candidate in enumerate(candidates, start=1):
        page_number = int(candidate["page_number"])
        image = Path(candidate["image"])
        page_result_path = stage_dir / f"page-{page_number:05d}.result.json"
        cached = load_json(page_result_path)
        if cached.get("status") == "ok" and str(cached.get("markdown") or "").strip():
            pages.append({**cached, "resumed": True})
            continue
        ocr_context = str(candidate.get("ocr_markdown") or "").strip()
        instructions = (
            "Reconstruct this document page as complete Markdown using both visual layout and the OCR transcript below. "
            "Preserve every visible label, heading relationship, list, true table, flow, comparison, arrow relation and "
            "diagram meaning. Do not invent facts. Do not turn cards into a table unless the image is a true table. "
            "Return only the complete page Markdown.\n\nOCR transcript for verification:\n"
            + ocr_context[:6000]
        )
        try:
            if options.provider_mode == "fake":
                provider = fake_provider_for_type("vlm_layout")
                response = provider.describe_layout(
                    image.read_bytes(),
                    mime_type=mime_type_for(image),
                    prompt=instructions,
                )
                markdown = str(response.get("markdown") or response.get("text") or "").strip()
                row = {
                    "status": "ok" if markdown else "failed",
                    "provider_mode": "fake",
                    "page_number": page_number,
                    "index": page_number - 1,
                    "markdown": markdown,
                    "selection_reasons": list(candidate.get("selection_reasons") or []),
                    "remote_requests_made": False,
                }
            else:
                if shared_gateway is None:
                    raise RuntimeError("Shared VKP gateway is unavailable.")
                call = shared_gateway.execute(
                    "vlm_layout",
                    [image],
                    instructions=instructions,
                    run_dir=stage_dir / f"page-{page_number:05d}-call",
                    max_estimated_cost_usd=per_page_budget,
                    confirm_data_export=options.confirm_data_export,
                    start_gateway=options.start_shared_gateway,
                )
                execution = call.get("execution") if isinstance(call.get("execution"), dict) else {}
                markdown = str(call.get("markdown") or "").strip()
                route = call.get("route") if isinstance(call.get("route"), dict) else {}
                if route:
                    routes.append(route)
                row = {
                    "status": "ok" if execution.get("ok") and markdown else "failed",
                    "provider_mode": "vkp_shared",
                    "page_number": page_number,
                    "index": page_number - 1,
                    "markdown": markdown,
                    "selection_reasons": list(candidate.get("selection_reasons") or []),
                    "consent_path": call.get("consent_path"),
                    "route": route,
                    "execution_artifacts": execution.get("artifacts") or {},
                    "remote_requests_made": bool(call.get("remote_requests_made")),
                    "error": "" if execution.get("ok") and markdown else str(execution.get("status") or "empty_remote_vlm"),
                }
        except Exception as exc:  # VLM is additive; preserve the successful remote OCR page.
            row = {
                "status": "failed",
                "provider_mode": options.provider_mode,
                "page_number": page_number,
                "index": page_number - 1,
                "markdown": "",
                "selection_reasons": list(candidate.get("selection_reasons") or []),
                # Once remote execution starts, an exception may occur after bytes were sent.
                # Conservatively report a possible request instead of understating export.
                "remote_requests_made": options.provider_mode == "vkp_shared",
                "remote_request_evidence": (
                    "conservative_after_execution_exception"
                    if options.provider_mode == "vkp_shared"
                    else "local_fake_provider"
                ),
                "error": f"{type(exc).__name__}: {exc}",
            }
        write_json_artifact(page_result_path, row)
        pages.append(row)
        if row["status"] != "ok":
            warnings.append(f"VLM page {page_number} failed; remote OCR content was preserved.")
        if options.request_interval_seconds > 0 and position < len(candidates) and options.provider_mode == "vkp_shared":
            time.sleep(options.request_interval_seconds)
    ok_count = sum(page.get("status") == "ok" for page in pages)
    result = {
        "status": "ok" if ok_count == len(pages) else ("partial" if ok_count else "failed"),
        "provider_mode": options.provider_mode,
        "source": str(source),
        "selection_mode": options.vlm_mode,
        "selected_count": len(candidates),
        "ok_count": ok_count,
        "failed_count": len(pages) - ok_count,
        "pages": pages,
        "warnings": warnings,
        "route": routes[0] if routes else {},
        "consent_paths": [str(page.get("consent_path")) for page in pages if page.get("consent_path")],
        "artifact": str(result_path),
        "remote_requests_made": any(bool(page.get("remote_requests_made")) for page in pages),
    }
    write_json_artifact(result_path, result)
    return result


def fuse_ocr_vlm_pages(
    ocr_pages: list[dict[str, Any]],
    vlm_pages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    vlm_map = {
        int(page.get("page_number") or (int(page.get("index") or 0) + 1)): page
        for page in vlm_pages
        if isinstance(page, dict)
    }
    fused: list[dict[str, Any]] = []
    for position, raw_page in enumerate(ocr_pages, start=1):
        page = dict(raw_page) if isinstance(raw_page, dict) else {}
        page_number = int(page.get("page_number") or (int(page.get("index") or (position - 1)) + 1))
        ocr_markdown = str(page.get("markdown") or "").strip()
        vlm = vlm_map.get(page_number) or {}
        vlm_markdown = str(vlm.get("markdown") or "").strip()
        if vlm.get("status") != "ok" or not vlm_markdown:
            page["fusion_decision"] = "ocr_preserved"
            fused.append(page)
            continue
        coverage = text_shingle_coverage(ocr_markdown, vlm_markdown)
        if not ocr_markdown or coverage >= 0.8:
            page["markdown"] = vlm_markdown
            page["fusion_decision"] = "vlm_complete_page"
        else:
            page["markdown"] = (
                ocr_markdown
                + "\n\n## Visual layout interpretation / 视觉版面补充\n\n"
                + vlm_markdown
            ).strip()
            page["fusion_decision"] = "ocr_plus_vlm"
        page["vlm_ocr_coverage"] = round(coverage, 4)
        page["vlm_selection_reasons"] = list(vlm.get("selection_reasons") or [])
        fused.append(page)
    return fused


def text_shingle_coverage(source: str, candidate: str) -> float:
    def shingles(value: str) -> set[str]:
        compact = re.sub(r"[^0-9A-Za-z\u3400-\u9fff]+", "", value).lower()
        if len(compact) < 2:
            return {compact} if compact else set()
        return {compact[index : index + 2] for index in range(len(compact) - 1)}

    source_shingles = shingles(source)
    if not source_shingles:
        return 1.0 if candidate.strip() else 0.0
    return len(source_shingles.intersection(shingles(candidate))) / len(source_shingles)

def run_structure_stage(
    markdown: str,
    *,
    source: Path,
    stage_dir: Path,
    options: OnlinePipelineOptions,
    budget: float,
    shared_gateway: SharedVkpGateway | None,
) -> tuple[str, list[dict[str, Any]], list[str]]:
    stage_dir.mkdir(parents=True, exist_ok=True)
    chunks = split_markdown_chunks(markdown, max_chars=max(1000, options.max_chunk_chars))
    per_chunk_budget = positive_budget(budget / max(len(chunks), 1)) if options.provider_mode == "vkp_shared" else 0.0
    outputs: list[str] = []
    reports: list[dict[str, Any]] = []
    warnings: list[str] = []
    instructions = (
        "Repair the Markdown hierarchy while preserving all factual content, source-page comments, lists, links, images, "
        "footnotes and true tables. Infer parent-child headings from numbering and semantics. Never use page numbers as "
        "headings. Return only the complete repaired Markdown for this chunk."
    )
    for index, chunk in enumerate(chunks, start=1):
        chunk_path = stage_dir / f"chunk-{index:04d}.md"
        result_path = stage_dir / f"chunk-{index:04d}.result.json"
        chunk_path.write_text(chunk, encoding="utf-8", newline="\n")
        existing = load_json(result_path)
        if existing.get("status") == "ok" and str(existing.get("markdown") or "").strip():
            raw_repaired = str(existing["markdown"])
            repaired = normalize_remote_markdown_response(raw_repaired)
            if repaired != raw_repaired.strip():
                existing["markdown"] = repaired
                existing["response_normalization"] = ["outer_markdown_fence_removed"]
                existing["content_changed"] = repaired != chunk
                write_json_artifact(result_path, existing)
            outputs.append(preserve_source_markers(chunk, repaired))
            reports.append(
                {
                    "stage": "text_structure",
                    "chunk": index,
                    "status": "ok",
                    "resumed": True,
                    "artifact": str(result_path),
                    "provider_mode": existing.get("provider_mode"),
                    "consent_path": existing.get("consent_path"),
                    "route": existing.get("route") or {},
                    "remote_requests_made": bool(existing.get("remote_requests_made")),
                    "content_changed": bool(existing.get("content_changed")),
                    "response_normalization": existing.get("response_normalization") or [],
                }
            )
            continue
        if options.provider_mode == "fake":
            provider = fake_provider_for_type("text_structure_llm")
            response = provider.repair_structure(chunk, context={"source": source.name, "chunk": index, "chunk_count": len(chunks)})
            raw_repaired = str(response.get("markdown") or chunk)
            repaired = normalize_remote_markdown_response(raw_repaired)
            response_normalization = ["outer_markdown_fence_removed"] if repaired != raw_repaired.strip() else []
            result = {"status": "ok", "provider_mode": "fake", "markdown": repaired, "remote_requests_made": False}
        else:
            if shared_gateway is None:
                raise RuntimeError("Shared VKP gateway is unavailable.")
            call = shared_gateway.execute(
                "text_structure",
                [chunk_path],
                instructions=instructions,
                run_dir=stage_dir / f"chunk-{index:04d}-call",
                max_estimated_cost_usd=per_chunk_budget,
                confirm_data_export=options.confirm_data_export,
                start_gateway=options.start_shared_gateway,
            )
            raw_repaired = str(call.get("markdown") or "")
            repaired = normalize_remote_markdown_response(raw_repaired)
            response_normalization = ["outer_markdown_fence_removed"] if repaired != raw_repaired.strip() else []
            execution_ok = bool((call.get("execution") or {}).get("ok"))
            remote_output_available = bool(repaired)
            if not execution_ok or not repaired:
                repaired = chunk
                warnings.append(f"Structure chunk {index} failed remotely; original chunk was preserved.")
            result = {
                "status": "ok" if execution_ok and remote_output_available else "fallback",
                "provider_mode": "vkp_shared",
                "markdown": repaired,
                "consent_path": call.get("consent_path"),
                "route": call.get("route") or {},
                "execution_artifacts": (call.get("execution") or {}).get("artifacts") or {},
                "remote_requests_made": bool(call.get("remote_requests_made")),
            }
        result["content_changed"] = repaired != chunk
        result["response_normalization"] = response_normalization
        repaired = preserve_source_markers(chunk, repaired)
        result["markdown"] = repaired
        write_json_artifact(result_path, result)
        outputs.append(repaired)
        reports.append(
            {
                "stage": "text_structure",
                "chunk": index,
                "status": result["status"],
                "artifact": str(result_path),
                "provider_mode": result.get("provider_mode"),
                "consent_path": result.get("consent_path"),
                "route": result.get("route") or {},
                "remote_requests_made": bool(result.get("remote_requests_made")),
                "content_changed": bool(result.get("content_changed")),
                "response_normalization": result.get("response_normalization") or [],
            }
        )
        if options.request_interval_seconds > 0 and index < len(chunks) and options.provider_mode == "vkp_shared":
            time.sleep(options.request_interval_seconds)
    return "\n\n".join(item.strip() for item in outputs if item.strip()).strip(), reports, warnings


def normalize_remote_markdown_response(value: str) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = text.split("\n")
    if len(lines) >= 2 and re.fullmatch(r"```(?:markdown|md)\s*", lines[0].strip(), flags=re.IGNORECASE):
        if lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()
    return text


def enhance_embedded_images_online(
    markdown: str,
    baseline_path: Path,
    *,
    source: Path,
    stage_dir: Path,
    options: OnlinePipelineOptions,
    budget: float,
    shared_gateway: SharedVkpGateway | None,
) -> tuple[str, dict[str, Any] | None]:
    refs = markdown_image_references(markdown)
    pairs = []
    for ref in refs:
        path = (baseline_path.parent / ref["normalized"]).resolve()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            pairs.append((ref, path))
    if not pairs:
        return markdown, None
    image_paths = [path for _, path in pairs]
    use_vlm = options.vlm_mode != "never"
    ocr = run_ocr_stage(
        image_paths,
        source=source,
        stage_dir=stage_dir / "ocr",
        options=options,
        budget=budget * (0.6 if use_vlm else 1.0),
        shared_gateway=shared_gateway,
    )
    pages = ocr.get("pages") or []
    vlm: dict[str, Any] = {}
    if use_vlm:
        candidates = select_vlm_candidates(
            image_paths,
            pages,
            source=image_paths[0],
            mode=options.vlm_mode,
            max_pages=options.vlm_max_pages,
            min_ocr_chars=options.vlm_min_ocr_chars,
        )
        if candidates:
            vlm = run_vlm_stage(
                candidates,
                source=source,
                stage_dir=stage_dir / "vlm",
                options=options,
                budget=budget * 0.4,
                shared_gateway=shared_gateway,
            )
            pages = fuse_ocr_vlm_pages(pages, vlm.get("pages") or [])
    ocr_map: dict[str, dict[str, object]] = {}
    for index, (ref, _path) in enumerate(pairs):
        page = pages[index] if index < len(pages) and isinstance(pages[index], dict) else {}
        text = str(page.get("markdown") or "").strip()
        if text:
            ocr_map[ref["normalized"]] = {
                "status": "ok",
                "provider": options.provider_mode,
                "text": text,
            }
    enhanced = inject_embedded_image_ocr_blocks(markdown, ocr_map)
    return enhanced, {
        # Keep the existing report stage name for downstream consumers; VLM is additive.
        "stage": "embedded_image_ocr",
        "analysis_mode": "online_ocr_plus_optional_vlm",
        "status": "ok" if ocr_map else "review",
        "image_count": len(pairs),
        "recognized_count": len(ocr_map),
        "ocr_status": ocr.get("status"),
        "vlm_status": vlm.get("status") if vlm else "not_needed",
        "vlm_selected_count": vlm.get("selected_count", 0) if vlm else 0,
        "remote_requests_made": bool(ocr.get("remote_requests_made")) or bool(vlm.get("remote_requests_made")),
        "ocr_artifact": str(stage_dir / "ocr" / "ocr-result.json"),
        "vlm_artifact": str(stage_dir / "vlm" / "vlm-result.json") if vlm else "",
    }


def render_visual_source(source: Path, destination: Path, *, dpi: int) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() in IMAGE_EXTENSIONS:
        target = destination / f"image-0001{source.suffix.lower()}"
        if not target.exists():
            shutil.copy2(source, target)
        return [target]
    images: list[Path] = []
    with fitz.open(source) as document:
        scale = max(int(dpi), 72) / 72.0
        matrix = fitz.Matrix(scale, scale)
        for index, page in enumerate(document, start=1):
            target = destination / f"page-{index:05d}.png"
            if not target.exists():
                page.get_pixmap(matrix=matrix, alpha=False).save(target)
            images.append(target)
    if not images:
        raise RuntimeError("PDF has no renderable pages.")
    return images


def render_ocr_pages(result: dict[str, Any], *, source_kind: str) -> str:
    parts: list[str] = []
    for index, page in enumerate(result.get("pages") or [], start=1):
        if not isinstance(page, dict):
            continue
        text = str(page.get("markdown") or "").strip()
        marker = f"<!-- source-page: {index} -->" if source_kind == "pdf" else f"<!-- source-image: {index} -->"
        parts.append(f"{marker}\n\n{text}".strip())
    return "\n\n".join(parts).strip()


def split_markdown_chunks(markdown: str, *, max_chars: int) -> list[str]:
    page_pattern = re.compile(r"(?=^<!--\s*source-page:\s*\d+\s*-->\s*$)", re.M)
    if page_pattern.search(markdown):
        sections = [item.strip() for item in page_pattern.split(markdown) if item.strip()]
        chunks: list[str] = []
        current: list[str] = []
        current_chars = 0
        for section in sections:
            if current and current_chars + len(section) > max_chars:
                chunks.append("\n\n".join(current))
                current = []
                current_chars = 0
            if len(section) > max_chars:
                chunks.extend(split_long_text(section, max_chars=max_chars))
            else:
                current.append(section)
                current_chars += len(section)
        if current:
            chunks.append("\n\n".join(current))
        return chunks or [markdown]
    elements = parse_markdown_elements(markdown, include_text_preview=False)
    mapped = chunk_by_title(elements, max_chunk_chars=max_chars)
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    chunks = [
        "\n".join(lines[max(0, int(item["line_start"]) - 1) : int(item["line_end"])]).strip()
        for item in mapped
    ]
    chunks = [item for item in chunks if item]
    return chunks or split_long_text(markdown, max_chars=max_chars)


def split_long_text(text: str, *, max_chars: int) -> list[str]:
    paragraphs = re.split(r"\n{2,}", text)
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph.strip()
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = paragraph.strip()
        elif len(candidate) > max_chars:
            chunks.extend(candidate[index : index + max_chars] for index in range(0, len(candidate), max_chars))
            current = ""
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [text]


def preserve_source_markers(source: str, repaired: str) -> str:
    markers = re.findall(r"^<!--\s*source-(?:page|image):\s*\d+\s*-->\s*$", source, re.M)
    missing = [marker for marker in markers if marker not in repaired]
    if not missing:
        return repaired
    return "\n".join(missing) + "\n\n" + repaired.lstrip()


def collect_online_sources(input_path: Path, *, recursive: bool, include_hidden: bool) -> list[Path]:
    supported = SUPPORTED_FORMATS | IMAGE_EXTENSIONS
    if input_path.is_file():
        return [input_path] if input_path.suffix.lower() in supported else []
    if not input_path.is_dir():
        return []
    iterator = input_path.rglob("*") if recursive else input_path.glob("*")
    return sorted(
        path
        for path in iterator
        if path.is_file()
        and path.suffix.lower() in supported
        and (include_hidden or not any(part.startswith(".") for part in path.relative_to(input_path).parts))
    )


def initialize_run(destination: Path, options: OnlinePipelineOptions) -> tuple[dict[str, Any], Path, str]:
    if options.resume_manifest:
        manifest = Path(options.resume_manifest).expanduser().resolve()
        payload = load_json(manifest)
        if not payload or payload.get("schema_version") != SCHEMA_VERSION:
            raise RuntimeError(f"Invalid online pipeline resume manifest: {manifest}")
        return payload, manifest.parent, str(payload["run_id"])
    run_id = f"online-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6]}"
    return {}, destination / ".online-runs" / run_id, run_id


def online_output_path(
    source: Path,
    source_input: Path,
    source_root: Path,
    output_root: Path,
    run_id: str,
    overwrite: bool,
    *,
    output_disambiguator: str = "",
) -> Path:
    relative_parent = online_relative_parent(source, source_input, source_root)
    stem = clean_output_stem(source.stem)
    token = re.sub(r"[^A-Za-z0-9_-]+", "-", output_disambiguator).strip("-_")
    if token:
        stem = f"{stem}.{token}"
    suffix = ".online.md" if overwrite else f".{run_id}.md"
    return output_root / relative_parent / f"{stem}{suffix}"


def online_relative_parent(source: Path, source_input: Path, source_root: Path) -> Path:
    try:
        return Path() if source_input.is_file() else source.parent.relative_to(source_root)
    except ValueError:
        return Path()


def build_output_disambiguators(
    sources: list[Path],
    source_input: Path,
    source_root: Path,
) -> dict[Path, str]:
    groups: dict[tuple[str, str], list[Path]] = {}
    for source in sources:
        relative_parent = online_relative_parent(source, source_input, source_root)
        key = (relative_parent.as_posix().casefold(), clean_output_stem(source.stem).casefold())
        groups.setdefault(key, []).append(source)

    disambiguators: dict[Path, str] = {}
    for grouped_sources in groups.values():
        if len(grouped_sources) < 2:
            continue
        format_counts: dict[str, int] = {}
        for source in grouped_sources:
            source_format = source.suffix.lower().lstrip(".") or "file"
            format_counts[source_format] = format_counts.get(source_format, 0) + 1
        for source in grouped_sources:
            source_format = source.suffix.lower().lstrip(".") or "file"
            if format_counts[source_format] > 1:
                source_format = f"{source_format}-{sha256_file(source)[:8]}"
            disambiguators[source] = source_format
    return disambiguators


def source_plan(source: Path, *, output_disambiguator: str = "") -> dict[str, Any]:
    calls = 1
    pages = None
    if source.suffix.lower() == ".pdf":
        try:
            with fitz.open(source) as document:
                pages = len(document)
                calls = max(1, pages)
        except Exception:
            pages = None
    return {
        "path": str(source),
        "name": source.name,
        "format": source.suffix.lower().lstrip("."),
        "bytes": source.stat().st_size,
        "sha256": sha256_file(source),
        "estimated_pages": pages,
        "estimated_remote_calls_before_structure": calls,
        "output_disambiguator": output_disambiguator,
        "route": "remote_ocr_then_structure" if source.suffix.lower() in VISUAL_EXTENSIONS else "deterministic_decode_then_remote_structure",
    }


def safety_payload(options: OnlinePipelineOptions) -> dict[str, Any]:
    return {
        "remote_execution_requested": bool(options.execute and options.provider_mode == "vkp_shared"),
        "confirmed_data_export": bool(options.confirm_data_export),
        "max_estimated_cost_usd": float(options.max_estimated_cost_usd),
        "credential_source": "vkp_windows_dpapi" if options.provider_mode == "vkp_shared" else "none_fake",
        "api_keys_copied": False,
        "api_keys_persisted_in_artifacts": False,
        "source_files_overwritten": False,
        "output_policy": "explicit overwrite uses .online.md; default uses versioned run suffix",
        "local_ai_inference": False,
        "local_deterministic_preprocessing": True,
    }


def fake_provider_health() -> dict[str, Any]:
    return {
        "schema_version": "fake-online-provider-v1",
        "status": "ready",
        "ready": True,
        "remote_requests_made": False,
        "api_keys_exposed": False,
        "routes": {name: {"status": "configured", "provider": "fake"} for name in ("ocr_layout", "vlm_layout", "text_structure")},
    }


def write_run_summary(run_root: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    run_root.mkdir(parents=True, exist_ok=True)
    manifest_path = run_root / "manifest.json"
    summary_path = run_root / "run-summary.md"
    write_json_artifact(manifest_path, manifest)
    lines = [
        "# Online-only conversion run",
        "",
        f"- Status: `{manifest.get('status', '')}`",
        f"- Run ID: `{manifest.get('run_id', '')}`",
        f"- Provider mode: `{manifest.get('provider_mode', '')}`",
        f"- Input count: `{len(manifest.get('sources') or [])}`",
        f"- API keys copied: `{bool((manifest.get('safety') or {}).get('api_keys_copied'))}`",
        f"- Data export confirmed: `{bool((manifest.get('safety') or {}).get('confirmed_data_export'))}`",
        f"- Cost ceiling: `${float((manifest.get('safety') or {}).get('max_estimated_cost_usd') or 0):.6f}`",
        "",
        "| Source | Status | Output |",
        "|---|---|---|",
    ]
    for item in manifest.get("results") or []:
        lines.append(f"| {Path(str(item.get('source') or '')).name} | `{item.get('status', '')}` | {item.get('output', '')} |")
    summary_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")
    return [
        {"type": "online_run_manifest", "path": str(manifest_path), "label": "Online-only run manifest"},
        {"type": "summary_report", "path": str(summary_path), "label": "Online-only run summary"},
    ]


def online_next_actions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    actions = [
        {
            "action": "read_online_run_summary",
            "tool": "read_artifact",
            "arguments": {"path": str(Path(payload["run_root"]) / "run-summary.md"), "artifact_type": "summary_report"},
            "safe_default": True,
            "destructive": False,
        }
    ]
    failed = [item for item in payload.get("results") or [] if item.get("status") == "failed"]
    if failed:
        actions.append(
            {
                "action": "resume_failed_online_sources",
                "tool": "start_online_conversion",
                "arguments": {
                    "input": payload["input"],
                    "output": payload["output"],
                    "provider_mode": payload["provider_mode"],
                    "resume_manifest": str(Path(payload["run_root"]) / "manifest.json"),
                    "execute": True,
                    "confirm_data_export": True,
                    "max_estimated_cost_usd": (payload.get("safety") or {}).get("max_estimated_cost_usd"),
                },
                "safe_default": False,
                "destructive": False,
            }
        )
    return actions


def stage_summary(result: dict[str, Any], stage: str) -> dict[str, Any]:
    return {
        "stage": stage,
        "status": result.get("status"),
        "provider_mode": result.get("provider_mode"),
        "page_count": len(result.get("pages") or []),
        "selected_count": result.get("selected_count"),
        "ok_count": result.get("ok_count"),
        "failed_count": result.get("failed_count"),
        "selection_mode": result.get("selection_mode"),
        "consent_path": result.get("consent_path"),
        "consent_paths": result.get("consent_paths") or [],
        "artifact": result.get("artifact"),
        "route": result.get("route") or {},
        "remote_requests_made": bool(result.get("remote_requests_made")),
    }


def emit_progress(
    callback: ProgressCallback | None,
    event: str,
    source: Path,
    index: int,
    total: int,
    payload: dict[str, Any],
) -> None:
    if callback:
        callback(event, source, index, total, payload)


def positive_budget(value: float) -> float:
    return max(round(float(value), 6), 0.000001)


class _RunTemporaryDirectory:
    def __init__(self, root: Path, *, prefix: str = "tmp", suffix: str = "") -> None:
        self.path = root / f"{prefix}{uuid4().hex[:10]}{suffix}"
        self.path.mkdir(parents=True, exist_ok=False)
        self.name = str(self.path)

    def __enter__(self) -> str:
        return self.name

    def __exit__(self, exc_type, exc, traceback) -> bool:
        shutil.rmtree(self.path, ignore_errors=True)
        return False

    def cleanup(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)


@contextmanager
def isolated_temp_directory(path: Path):
    """Keep third-party converter temp files inside the run artifact tree."""
    path.mkdir(parents=True, exist_ok=True)
    keys = ("TMP", "TEMP", "TMPDIR")
    previous_env = {key: os.environ.get(key) for key in keys}
    previous_tempdir = tempfile.tempdir
    previous_factory = tempfile.TemporaryDirectory

    def factory(suffix=None, prefix=None, dir=None, **_kwargs):
        root = Path(dir).resolve() if dir else path
        return _RunTemporaryDirectory(root, prefix=str(prefix or "tmp"), suffix=str(suffix or ""))

    for key in keys:
        os.environ[key] = str(path)
    tempfile.tempdir = str(path)
    tempfile.TemporaryDirectory = factory
    try:
        yield
    finally:
        tempfile.TemporaryDirectory = previous_factory
        tempfile.tempdir = previous_tempdir
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def mime_type_for(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "image/png"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json_artifact(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(redacted_json(payload), encoding="utf-8", newline="\n")


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _error_payload(message: str, *, code: str = "invalid_request") -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "failed",
        "error": True,
        "code": code,
        "message": message,
        "remote_requests_made": False,
    }
