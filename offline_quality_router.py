from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = "offline-stage-quality-v1"
STAGE_NAMES = ("parse", "layout", "image", "table", "ocr", "asset", "markdown")
STAGE_STATUSES = ("passed", "degraded", "blocked", "not_applicable", "not_evaluated")
ROUTE_STATUSES = ("minimal-deliverable", "degraded", "blocked", "fallback-proposed")


def quality_vocabulary() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "stages": list(STAGE_NAMES),
        "stage_statuses": list(STAGE_STATUSES),
        "route_statuses": list(ROUTE_STATUSES),
        "invariants": {
            "artifact_exists_is_quality_passed": False,
            "evaluation_is_read_only": True,
            "default_backend_selection_changes": False,
            "optional_missing_may_be_deliverable": True,
        },
    }


def evaluate_offline_quality(
    report: Mapping[str, Any],
    *,
    source_kind: str,
    capabilities: Mapping[str, str] | None = None,
    artifact_exists: bool | None = None,
) -> dict[str, Any]:
    snapshot = copy.deepcopy(dict(report))
    quality = _mapping(snapshot.get("quality"))
    risks = {str(item) for item in _mapping(snapshot.get("quality_risks")).get("risk_codes") or []}
    capabilities = {str(key): str(value) for key, value in dict(capabilities or {}).items()}
    output = str(snapshot.get("output") or "")
    exists = _artifact_exists(snapshot, output, artifact_exists)
    characters = _integer(quality.get("characters"))
    lines = _integer(quality.get("nonempty_lines"))
    empty = "empty_document" in risks or characters == 0 or lines == 0
    failed = str(snapshot.get("status") or "").lower() in {"failed", "error", "blocked"}
    kind = _normalize_kind(source_kind)
    stages: dict[str, dict[str, Any]] = {}

    if failed or not exists:
        stages["parse"] = _stage("blocked", True, ["conversion_failed" if failed else "artifact_missing"], "No parse artifact can be evaluated.", True)
    elif empty:
        stages["parse"] = _stage("blocked", True, ["empty_document"], "The artifact exists but contains no usable text.", True)
    else:
        stages["parse"] = _stage("passed", True, ["artifact_exists", f"characters={characters}"], "A non-empty parse artifact exists.", False)

    preflight = _mapping(snapshot.get("pdf_preflight"))
    layout_required = kind in {"text_pdf", "scanned_pdf", "mixed_image", "image_set"} or bool(preflight)
    layout_gap = "heading_hierarchy_missing" in risks or bool(preflight.get("complex_layout_likely"))
    layout_evidence = _mapping(snapshot.get("layout_evidence"))
    if not layout_required:
        stages["layout"] = _stage("not_applicable", False, [], "Layout recovery is not required.", False)
    elif layout_gap or (kind in {"mixed_image", "image_set"} and not layout_evidence):
        evidence = []
        if "heading_hierarchy_missing" in risks:
            evidence.append("heading_hierarchy_missing")
        if preflight.get("complex_layout_likely"):
            evidence.append("complex_layout_likely")
        if not layout_evidence:
            evidence.append("layout_evidence_missing")
        stages["layout"] = _stage("degraded", True, evidence, "Layout fidelity is not fully proven.", True)
    else:
        stages["layout"] = _stage("passed", True, ["layout_risk_not_detected"], "No deterministic layout gap was detected.", False)

    image_required = kind in {"scanned_pdf", "mixed_image", "image_set"} or _integer(preflight.get("image_pages")) > 0
    image_evidence = _mapping(snapshot.get("image_evidence"))
    if not image_required:
        stages["image"] = _stage("not_applicable", False, [], "Image recovery is not required.", False)
    elif image_evidence.get("status") == "passed":
        stages["image"] = _stage("passed", True, ["image_evidence_passed"], "Image recovery has local evidence.", False)
    else:
        stages["image"] = _stage("degraded", True, ["image_evidence_missing"], "Semantic image recovery is not proven.", True)

    table_evidence = _mapping(snapshot.get("table_validation"))
    if "table_structure_risk" not in risks:
        stages["table"] = _stage("not_applicable", False, [], "No deterministic table signal was detected.", False)
    elif table_evidence.get("status") == "passed":
        stages["table"] = _stage("passed", True, ["table_validation_passed"], "Row and column retention has evidence.", False)
    else:
        stages["table"] = _stage("degraded", True, ["table_structure_risk"], "Table structure needs comparison or review.", True)

    ocr_required = kind in {"scanned_pdf", "mixed_image", "image_set"}
    ocr_evidence = _mapping(snapshot.get("ocr_evidence"))
    if not ocr_required:
        stages["ocr"] = _stage("not_applicable", False, [], "OCR is not required.", False)
    elif "ocr_low_confidence" in risks:
        stages["ocr"] = _stage("degraded", True, ["ocr_low_confidence"], "OCR confidence is below threshold.", True)
    elif ocr_evidence.get("status") == "passed":
        stages["ocr"] = _stage("passed", True, ["ocr_evidence_passed"], "OCR has local quality evidence.", False)
    elif kind == "scanned_pdf" and (not exists or empty):
        stages["ocr"] = _stage("blocked", True, ["ocr_required", "usable_text_missing"], "The scan has no usable text artifact.", True)
    else:
        stages["ocr"] = _stage("degraded", True, ["ocr_evidence_missing"], "OCR was skipped or not measured.", True)

    asset_evidence = _mapping(snapshot.get("asset_evidence"))
    if kind not in {"mixed_image", "image_set"}:
        stages["asset"] = _stage("not_applicable", False, [], "No asset bundle is required.", False)
    elif asset_evidence.get("missing_count") in (0, "0") and _integer(asset_evidence.get("asset_count")) > 0:
        stages["asset"] = _stage("passed", True, ["local_assets_resolved"], "Referenced local assets are present.", False)
    else:
        stages["asset"] = _stage("degraded", True, ["asset_integrity_unproven"], "Local asset completeness is not proven.", True)

    level = str(quality.get("level") or "unknown")
    markdown_risks = risks.intersection({"heading_hierarchy_missing", "page_number_noise"})
    if not exists or empty:
        stages["markdown"] = _stage("blocked", True, ["artifact_missing" if not exists else "empty_document"], "Markdown is not usable.", True)
    elif level == "good" and not markdown_risks:
        stages["markdown"] = _stage("passed", True, ["quality_level=good"], "Markdown meets the deterministic minimum.", False)
    else:
        stages["markdown"] = _stage("degraded", True, [f"quality_level={level}", *sorted(markdown_risks)], "Markdown exists but needs review.", True)

    fallback = _fallback_proposal(kind, stages, capabilities)
    required = [item for item in stages.values() if item["required"]]
    blocked = any(item["status"] == "blocked" for item in required)
    degraded = any(item["status"] in {"degraded", "not_evaluated"} for item in required)
    quality_passed = bool(required) and not blocked and not degraded
    route_status = "fallback-proposed" if blocked and fallback["available"] else "blocked" if blocked else "degraded" if degraded else "minimal-deliverable"
    review_stages = [name for name, item in stages.items() if item["manual_review_required"]]
    return {
        "schema_version": SCHEMA_VERSION,
        "source_kind": kind,
        "artifact": {"exists": exists, "status": "exists" if exists else "missing", "path": output or None},
        "quality": {"passed": quality_passed, "status": "passed" if quality_passed else "blocked" if blocked else "needs_review"},
        "route": {"status": route_status, "deliverable": exists and not blocked, "reason": _route_reason(route_status)},
        "stages": stages,
        "manual_review_required": bool(review_stages),
        "manual_review_stages": review_stages,
        "fallback_proposal": fallback,
        "capability_snapshot": capabilities,
        "vocabulary": quality_vocabulary(),
    }


def explain_offline_route(evaluation: Mapping[str, Any]) -> str:
    route = _mapping(evaluation.get("route"))
    artifact = _mapping(evaluation.get("artifact"))
    quality = _mapping(evaluation.get("quality"))
    review = ",".join(str(item) for item in evaluation.get("manual_review_stages") or []) or "none"
    fallback = _mapping(evaluation.get("fallback_proposal"))
    backend = str(fallback.get("backend") or "none") if fallback.get("available") else "unavailable"
    return f"route={route.get('status')}; artifact={artifact.get('status')}; quality={quality.get('status')}; manual_review={review}; fallback={backend}"


def _stage(status: str, required: bool, evidence: list[str], explanation: str, review: bool) -> dict[str, Any]:
    return {"status": status, "required": required, "evidence": evidence, "explanation": explanation, "manual_review_required": review}


def _fallback_proposal(kind: str, stages: Mapping[str, Mapping[str, Any]], capabilities: Mapping[str, str]) -> dict[str, Any]:
    blocked = {name for name, item in stages.items() if item.get("status") == "blocked"}
    degraded = {name for name, item in stages.items() if item.get("status") == "degraded"}
    candidates: list[tuple[str, str, str]] = []
    if kind == "scanned_pdf" and {"parse", "ocr"}.intersection(blocked):
        candidates.append(("local_ocr", "rapidocr", "Run an explicit local OCR comparison on selected synthetic pages."))
    if "layout" in degraded:
        candidates.append(("pdf_structure_recovery", "mineru", "Compare a versioned local structure-recovery output."))
    if "table" in degraded:
        candidates.append(("pdf_table_extraction", "table_worker", "Compare detected table pages only."))
    if kind == "office" and "parse" in blocked:
        candidates.append(("markitdown_baseline", "markitdown", "Retry with the existing local Office baseline."))
    for capability, backend, action in candidates:
        status = capabilities.get(capability, "missing")
        if status in {"ok", "ready", "available"}:
            return {"available": True, "capability": capability, "capability_status": status, "backend": backend, "action": action, "automatic": False, "changes_default_backend": False}
    capability = candidates[0][0] if candidates else None
    return {"available": False, "capability": capability, "capability_status": capabilities.get(capability, "missing") if capability else "not_applicable", "backend": None, "action": "Keep the result blocked or degraded and request local review.", "automatic": False, "changes_default_backend": False}


def _artifact_exists(report: Mapping[str, Any], output: str, override: bool | None) -> bool:
    if override is not None:
        return bool(override)
    if "output_exists" in report:
        return bool(report.get("output_exists"))
    return bool(output and Path(output).is_file())


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _normalize_kind(value: str) -> str:
    normalized = str(value or "unknown").strip().lower().replace("-", "_")
    return {"pdf": "text_pdf", "complex_pdf": "text_pdf", "office_docx": "office", "images": "image_set"}.get(normalized, normalized)


def _route_reason(status: str) -> str:
    return {
        "minimal-deliverable": "Artifact and all required deterministic quality stages passed.",
        "degraded": "Artifact exists, but one or more required stages need review.",
        "blocked": "A required stage failed and no available local fallback is proven.",
        "fallback-proposed": "A required stage failed, and a non-automatic local fallback is available.",
    }[status]
