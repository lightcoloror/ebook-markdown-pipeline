from __future__ import annotations

from typing import Any


SCHEMA_VERSION = "adaptive-routing-plan-v1"
ROUTING_PROFILES = frozenset({"fast", "balanced", "best_quality"})


def build_adaptive_routing_plan(
    inspection: dict[str, Any],
    *,
    routing_profile: str = "balanced",
    output: str = "",
) -> dict[str, Any]:
    profile = normalize_routing_profile(routing_profile)
    kind = str(inspection.get("kind") or "unsupported")
    input_path = str(inspection.get("input") or "")
    output_path = str(output or "")
    candidates = build_candidates(
        inspection,
        profile=profile,
        input_path=input_path,
        output_path=output_path,
    )
    primary = next((item for item in candidates if item.get("role") == "primary"), candidates[0] if candidates else None)
    uncertainty = uncertainty_reasons(inspection, candidates, profile)
    sample_pages = representative_pages(inspection)
    decision_status = "ready"
    if not candidates:
        decision_status = "unsupported"
    elif profile == "best_quality" and len(candidates) > 1:
        decision_status = "probe_compare_required"
    elif uncertainty:
        decision_status = "review_recommended"

    primary_action = route_action(primary, output_bound=bool(output_path), comparison_required=decision_status == "probe_compare_required") if primary else None
    next_actions = [primary_action] if primary_action else []
    if kind == "pdf" and profile == "best_quality" and candidates:
        next_actions.insert(
            0,
            {
                "action": "prepare_representative_page_probe",
                "tool": "prepare_adaptive_pdf_probe",
                "arguments": {
                    "input": input_path,
                    "output": output_path or "REQUIRED_OUTPUT_PATH",
                    "routing_profile": profile,
                    "max_pipelines": min(4, len([item for item in candidates if not item.get("remote")])),
                },
                "safe_default": bool(output_path),
                "destructive": False,
                "why": "Prepare a bounded representative-page comparison before any whole-document heavy run.",
            },
        )
    if len(candidates) > 1:
        next_actions.extend(candidate_comparison_actions(candidates[1:4]))

    return {
        "schema_version": SCHEMA_VERSION,
        "routing_profile": profile,
        "selection_policy": "preflight_probe_compare_escalate",
        "decision_status": decision_status,
        "input": input_path,
        "output_bound": bool(output_path),
        "material_kind": kind,
        "objective": objective_for_profile(profile),
        "primary": primary,
        "winner_status": "provisional" if len(candidates) > 1 else ("single_candidate" if primary else "unavailable"),
        "selection_basis": "lightweight_preflight_rules",
        "portfolio": candidates,
        "sample_strategy": {
            "mode": "representative_pages" if sample_pages else "whole_small_input_or_native_structure",
            "pages": sample_pages,
            "max_candidate_routes": min(4, len(candidates)),
            "whole_document_heavy_run_before_compare": False,
            "executor_status": "available_via_prepare_adaptive_pdf_probe" if kind == "pdf" else "planned_only",
            "note": "PDF representative pages can be executed through the adaptive probe; other material types remain planning-only.",
        },
        "quality_gate": quality_gate(inspection, profile),
        "escalation_rules": escalation_rules(inspection, candidates),
        "stop_conditions": stop_conditions(inspection, profile),
        "uncertainty": {
            "needs_review": bool(uncertainty),
            "reasons": uncertainty,
        },
        "safety": {
            "inspection_only": True,
            "remote_calls_made": False,
            "models_installed": False,
            "services_started": False,
            "source_overwrite_allowed": False,
            "remote_candidates_require_explicit_confirmation": True,
        },
        "next_actions": next_actions,
    }


def normalize_routing_profile(value: str) -> str:
    normalized = str(value or "balanced").strip().lower().replace("-", "_")
    return normalized if normalized in ROUTING_PROFILES else "balanced"


def build_candidates(
    inspection: dict[str, Any],
    *,
    profile: str,
    input_path: str,
    output_path: str,
) -> list[dict[str, Any]]:
    kind = str(inspection.get("kind") or "")
    if kind == "pdf":
        return pdf_candidates(inspection, profile, input_path, output_path)
    if kind == "image":
        return image_candidates(inspection, profile, input_path, output_path)
    if kind == "directory":
        counts = inspection.get("counts") if isinstance(inspection.get("counts"), dict) else {}
        if int(counts.get("images") or 0) and not int(counts.get("documents") or 0):
            return image_candidates(inspection, profile, input_path, output_path)
        return directory_candidates(inspection, profile, input_path, output_path)
    if kind == "web_archive":
        return [
            candidate(
                "web_archive_visual_check",
                "primary",
                "process_web_archive",
                {"input": input_path, "output": required_output(output_path)},
                "Preserve source HTML/Markdown and add visual side evidence.",
                "low",
            )
        ]
    if kind in {"pandoc", "calibre", "docling", "markitdown"}:
        return document_candidates(inspection, profile, input_path, output_path)
    return []


def pdf_candidates(
    inspection: dict[str, Any],
    profile: str,
    input_path: str,
    output_path: str,
) -> list[dict[str, Any]]:
    preflight = inspection.get("preflight") if isinstance(inspection.get("preflight"), dict) else {}
    page_count = int(preflight.get("page_count") or 0)
    scanned = bool(preflight.get("scanned_likely"))
    complex_layout = bool(preflight.get("complex_layout_likely"))
    presentation = bool(preflight.get("presentation_like"))
    bookmarks = int(preflight.get("bookmark_count") or 0)
    table_pages = int(preflight.get("table_like_pages") or 0)

    if scanned:
        primary_pipeline = "umi" if profile == "fast" else "mineru"
    elif profile == "fast":
        primary_pipeline = "pymupdf4llm"
    elif complex_layout or presentation:
        primary_pipeline = "mineru"
    else:
        primary_pipeline = "marker" if 0 < page_count <= 12 else "mineru"

    candidates = [
        pdf_candidate(
            primary_pipeline,
            "primary",
            input_path,
            output_path,
            primary_reason(primary_pipeline, scanned=scanned, complex_layout=complex_layout, bookmarks=bookmarks),
        )
    ]
    if primary_pipeline != "pymupdf4llm":
        candidates.append(
            pdf_candidate(
                "pymupdf4llm",
                "text_baseline",
                input_path,
                output_path,
                "Fast text-layer baseline for coverage, heading, and noise comparison.",
            )
        )
    if primary_pipeline != "mineru":
        candidates.append(
            pdf_candidate(
                "mineru",
                "structure_candidate",
                input_path,
                output_path,
                "Structure-aware comparison for headings, reading order, tables, and mixed pages.",
            )
        )
    if scanned and primary_pipeline != "umi":
        candidates.append(
            pdf_candidate(
                "umi",
                "ocr_baseline",
                input_path,
                output_path,
                "OCR baseline for pages with a weak or missing text layer.",
            )
        )
    if 0 < page_count <= 12 and primary_pipeline != "marker":
        candidates.append(
            pdf_candidate(
                "marker",
                "short_layout_candidate",
                input_path,
                output_path,
                "Short-document layout comparison without committing a long document to Marker.",
            )
        )
    if presentation or table_pages:
        candidates.append(
            pdf_candidate(
                "docling",
                "layout_table_candidate",
                input_path,
                output_path,
                "Optional slide/table structure comparison when Docling is healthy.",
                cost="medium",
            )
        )
    if profile == "best_quality" and (scanned or complex_layout or presentation):
        candidates.append(
            candidate(
                "online_only_vlm",
                "remote_escalation",
                "start_online_conversion",
                {
                    "input": input_path,
                    "output": required_output(output_path),
                    "provider_mode": "vkp_shared",
                    "execute": False,
                    "confirm_data_export": False,
                    "max_estimated_cost_usd": 0,
                    "vlm_mode": "auto",
                },
                "Remote OCR/VLM/structure escalation for selected difficult pages only after explicit consent and a cost ceiling.",
                "remote",
                safe_default=False,
                remote=True,
            )
        )
    return deduplicate_candidates(candidates)


def image_candidates(
    inspection: dict[str, Any],
    profile: str,
    input_path: str,
    output_path: str,
) -> list[dict[str, Any]]:
    primary_provider = "rapidocr" if profile == "fast" else "auto"
    candidates = [
        candidate(
            f"image_book_{primary_provider}",
            "primary",
            "start_image_book_rebuild",
            {
                "input": input_path,
                "output": required_output(output_path),
                "ocr": "auto",
                "ocr_provider": primary_provider,
            },
            "Recognize, order, deduplicate, and rebuild images into Markdown with review artifacts.",
            "low" if primary_provider == "rapidocr" else "medium",
        ),
        candidate(
            "image_book_umi",
            "ocr_candidate",
            "start_image_book_rebuild",
            {
                "input": input_path,
                "output": required_output(output_path),
                "ocr": "always",
                "ocr_provider": "umi",
            },
            "Independent OCR comparison for weak, multilingual, or irregular screenshots.",
            "medium",
        ),
    ]
    if profile == "best_quality":
        candidates.append(
            candidate(
                "image_online_vlm",
                "remote_escalation",
                "run_online_enhancement",
                {
                    "task": "vlm_layout",
                    "input_path": input_path,
                    "output": required_output(output_path),
                    "provider_mode": "vkp_shared",
                    "allow_remote": False,
                },
                "Layout-heavy infographic or screenshot escalation after local OCR evidence is weak.",
                "remote",
                safe_default=False,
                remote=True,
            )
        )
    return candidates


def document_candidates(
    inspection: dict[str, Any],
    profile: str,
    input_path: str,
    output_path: str,
) -> list[dict[str, Any]]:
    extension = str(inspection.get("extension") or "")
    structure = inspection.get("structure_strategy") if isinstance(inspection.get("structure_strategy"), dict) else {}
    mode = str(structure.get("mode") or "")
    primary_mode = "auto"
    if mode == "docling_or_pandoc_structure" and profile == "best_quality":
        primary_mode = "docling"
    candidates = [
        candidate(
            f"document_{primary_mode}",
            "primary",
            "start_conversion",
            {
                "input": input_path,
                "output": required_output(output_path),
                "document_pipeline_mode": primary_mode,
                "output_format": "markdown",
            },
            "Use native ebook/Office structure first, including TOC/nav metadata when available.",
            "low" if primary_mode == "auto" else "medium",
        )
    ]
    if extension in {".docx", ".pptx", ".xlsx", ".html", ".htm", ".md"}:
        alternative = "markitdown" if primary_mode == "docling" else "docling"
        candidates.append(
            candidate(
                f"document_{alternative}",
                "structure_candidate",
                "start_conversion",
                {
                    "input": input_path,
                    "output": required_output(output_path),
                    "document_pipeline_mode": alternative,
                    "output_format": "markdown",
                },
                "Versioned structure comparison for Office/HTML material; use only when the optional backend is healthy.",
                "medium",
            )
        )
    return candidates


def directory_candidates(
    inspection: dict[str, Any],
    profile: str,
    input_path: str,
    output_path: str,
) -> list[dict[str, Any]]:
    return [
        candidate(
            "mixed_material_router",
            "primary",
            "process_material",
            {
                "input": input_path,
                "output": required_output(output_path),
                "routing_profile": profile,
                "recursive": bool(inspection.get("recursive", True)),
            },
            "Split mixed folders by material type, then apply each format-specific route.",
            "medium",
        )
    ]


def pdf_candidate(
    pipeline: str,
    role: str,
    input_path: str,
    output_path: str,
    why: str,
    *,
    cost: str | None = None,
) -> dict[str, Any]:
    costs = {
        "pymupdf4llm": "low",
        "umi": "medium",
        "ocrmypdf": "medium",
        "docling": "medium",
        "marker": "heavy",
        "mineru": "heavy",
    }
    return candidate(
        f"pdf_{pipeline}",
        role,
        "start_conversion",
        {
            "input": input_path,
            "output": required_output(output_path),
            "pdf_pipeline_mode": pipeline,
            "output_format": "markdown",
            "overwrite": False,
        },
        why,
        cost or costs.get(pipeline, "medium"),
    )


def candidate(
    candidate_id: str,
    role: str,
    tool: str,
    arguments: dict[str, Any],
    why: str,
    cost: str,
    *,
    safe_default: bool = True,
    remote: bool = False,
) -> dict[str, Any]:
    return {
        "id": candidate_id,
        "role": role,
        "tool": tool,
        "arguments": arguments,
        "why": why,
        "cost_class": cost,
        "remote": remote,
        "safe_default": bool(safe_default and not remote and arguments.get("output") != "REQUIRED_OUTPUT_PATH"),
        "destructive": False,
        "execution_status": "planned_only",
    }


def deduplicate_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in candidates:
        candidate_id = str(item.get("id") or "")
        if not candidate_id or candidate_id in seen:
            continue
        seen.add(candidate_id)
        result.append(item)
    return result


def required_output(output_path: str) -> str:
    return output_path or "REQUIRED_OUTPUT_PATH"


def route_action(primary: dict[str, Any], *, output_bound: bool, comparison_required: bool) -> dict[str, Any]:
    return {
        "action": "run_adaptive_primary_route",
        "tool": primary.get("tool"),
        "arguments": dict(primary.get("arguments") or {}),
        "safe_default": bool(primary.get("safe_default") and output_bound and not comparison_required),
        "destructive": False,
        "why": primary.get("why"),
    }


def candidate_comparison_actions(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for item in candidates:
        actions.append(
            {
                "action": "run_candidate_route_for_comparison",
                "candidate_id": item.get("id"),
                "tool": item.get("tool"),
                "arguments": dict(item.get("arguments") or {}),
                "safe_default": False,
                "destructive": False,
                "why": item.get("why"),
            }
        )
    return actions


def primary_reason(pipeline: str, *, scanned: bool, complex_layout: bool, bookmarks: int) -> str:
    if pipeline == "umi":
        return "Fast OCR-first route for scanned material; structure quality still requires review."
    if pipeline == "pymupdf4llm":
        return "Usable text layer and simple layout favor a fast deterministic baseline."
    if pipeline == "marker":
        return "Short PDF permits a layout-aware pass without long-document runtime risk."
    signals = []
    if scanned:
        signals.append("weak text layer")
    if complex_layout:
        signals.append("complex layout")
    if bookmarks:
        signals.append("bookmark-guided heading review")
    return "Structure-aware primary route for " + (", ".join(signals) if signals else "quality-first PDF conversion") + "."


def representative_pages(inspection: dict[str, Any], limit: int = 8) -> list[int]:
    preflight = inspection.get("preflight") if isinstance(inspection.get("preflight"), dict) else {}
    page_count = int(preflight.get("page_count") or 0)
    if page_count <= 0:
        return []
    if page_count <= limit:
        return list(range(1, page_count + 1))
    indexes = {1, 2, page_count, max(1, page_count // 4), max(1, page_count // 2), max(1, (page_count * 3) // 4)}
    step = max(1, page_count // max(limit - len(indexes), 1))
    cursor = step
    while len(indexes) < limit and cursor < page_count:
        indexes.add(cursor)
        cursor += step
    return sorted(indexes)[:limit]


def quality_gate(inspection: dict[str, Any], profile: str) -> dict[str, Any]:
    preflight = inspection.get("preflight") if isinstance(inspection.get("preflight"), dict) else {}
    strict = profile == "best_quality"
    dimensions = [
        {"name": "text_coverage", "weight": 0.22, "evidence": ["quality.characters", "ocr_character_count"]},
        {"name": "heading_structure", "weight": 0.22, "evidence": ["quality.headings", "structure_repair.promoted_heading_count"]},
        {"name": "reading_order", "weight": 0.14, "evidence": ["layout_candidates", "document_intelligence_blocks"]},
        {"name": "noise", "weight": 0.14, "evidence": ["quality.page_number_lines", "quality.repeated_noise_lines", "quality.replacement_chars"]},
        {"name": "toc_or_bookmark_alignment", "weight": 0.12, "evidence": ["pdf_outline_alignment.match_ratio", "ebook_toc_alignment"]},
        {"name": "table_formula_retention", "weight": 0.11, "evidence": ["table_retention_ratio", "formula_candidates"]},
        {"name": "duration", "weight": 0.05, "evidence": ["duration_seconds"]},
    ]
    return {
        "mode": "weighted_independent_evidence",
        "accept_level": "good",
        "minimum_score": 82 if strict else (70 if profile == "balanced" else 60),
        "minimum_toc_match_ratio": 0.75 if int(preflight.get("bookmark_count") or 0) else None,
        "maximum_replacement_chars": 0,
        "maximum_page_heading_ratio": 0.08,
        "dimensions": dimensions,
        "producer_self_score_is_sufficient": False,
    }


def escalation_rules(inspection: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidate_ids = {str(item.get("id")) for item in candidates}
    rules = [
        {
            "when": {"quality.level": ["review", "poor"]},
            "action": "compare_next_local_candidate",
            "candidate_priority": [item.get("id") for item in candidates if item.get("role") != "primary" and not item.get("remote")],
            "safe_default": True,
            "destructive": False,
        },
        {
            "when": {"quality.headings": 0, "structure_expected": True},
            "action": "run_local_structure_enhancement",
            "tool": "enhance_markdown_structure",
            "arguments": {"model_mode": "local", "overwrite": False},
            "safe_default": True,
            "destructive": False,
        },
        {
            "when": {"pdf_outline_alignment.match_ratio_lt": 0.75},
            "action": "review_and_repair_heading_alignment",
            "tool": "read_artifact",
            "arguments": {"artifact_type": "review_report"},
            "safe_default": True,
            "destructive": False,
        },
    ]
    if "pdf_umi" in candidate_ids or "pdf_mineru" in candidate_ids:
        rules.append(
            {
                "when": {"ocr_character_coverage": "low_or_empty"},
                "action": "switch_ocr_candidate",
                "candidate_priority": [item for item in ("pdf_umi", "pdf_mineru") if item in candidate_ids],
                "safe_default": True,
                "destructive": False,
            }
        )
    remote = [item.get("id") for item in candidates if item.get("remote")]
    if remote:
        rules.append(
            {
                "when": {"local_candidates_exhausted": True, "quality.level": ["review", "poor"]},
                "action": "request_explicit_remote_escalation",
                "candidate_priority": remote,
                "requires": ["allow_remote_or_execute", "confirm_data_export", "positive_cost_ceiling"],
                "safe_default": False,
                "destructive": False,
            }
        )
    return rules


def stop_conditions(inspection: dict[str, Any], profile: str) -> list[dict[str, Any]]:
    preflight = inspection.get("preflight") if isinstance(inspection.get("preflight"), dict) else {}
    conditions = [
        {"condition": "quality.level == good", "required": True},
        {"condition": "no critical OCR/encoding errors", "required": True},
        {"condition": "source is not overwritten", "required": True},
    ]
    if int(preflight.get("bookmark_count") or 0):
        conditions.append({"condition": "pdf_outline_alignment.match_ratio >= 0.75", "required": profile == "best_quality"})
    if bool(preflight.get("table_like_pages")):
        conditions.append({"condition": "table candidates reviewed or retained", "required": profile == "best_quality"})
    if profile == "best_quality":
        conditions.append({"condition": "representative-page winner selected with independent quality evidence", "required": True})
    return conditions


def uncertainty_reasons(inspection: dict[str, Any], candidates: list[dict[str, Any]], profile: str) -> list[str]:
    reasons: list[str] = []
    strategy = inspection.get("structure_strategy") if isinstance(inspection.get("structure_strategy"), dict) else {}
    if str(strategy.get("confidence") or "").lower() == "low":
        reasons.append("low_structure_strategy_confidence")
    preflight = inspection.get("preflight") if isinstance(inspection.get("preflight"), dict) else {}
    if preflight.get("scanned_likely"):
        reasons.append("scanned_or_weak_text_layer")
    if preflight.get("complex_layout_likely"):
        reasons.append("complex_layout")
    if preflight.get("table_like_pages"):
        reasons.append("table_retention_risk")
    if profile == "best_quality" and len(candidates) > 1:
        reasons.append("candidate_comparison_required")
    return sorted(set(reasons))


def objective_for_profile(profile: str) -> dict[str, Any]:
    if profile == "fast":
        return {"quality": 0.55, "duration": 0.35, "resource_cost": 0.10}
    if profile == "best_quality":
        return {"quality": 0.88, "duration": 0.07, "resource_cost": 0.05}
    return {"quality": 0.72, "duration": 0.20, "resource_cost": 0.08}
