from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "review-lifecycle-v1"
CONSUME_POLICY = {
    "mode": "existing_outputs_only_no_dms_import",
    "source_files": "read_only",
    "outputs": "record_and_review_only",
    "archive": "manual_after_review",
}
BLOCKED_ACTIONS = [
    "do_not_delete_or_move_source_files",
    "do_not_import_into_document_management_system",
    "do_not_overwrite_existing_outputs",
    "do_not_publish_sync_or_upload",
    "do_not_mark_archived_without_human_acceptance",
]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_review_lifecycle_artifacts(output: Path, payload: dict[str, Any]) -> dict[str, str]:
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "review-lifecycle.json"
    markdown_path = output / "review-lifecycle.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    markdown_path.write_text(render_review_lifecycle_markdown(payload), encoding="utf-8", newline="\n")
    return {"json": str(json_path), "markdown": str(markdown_path)}


def build_review_lifecycle(source: Path, *, include_paths: bool = False) -> dict[str, Any]:
    payload = load_json(source)
    schema = str(payload.get("schema_version") or "")
    builder = {
        "quality-improvement-queue-v1": lifecycle_from_quality_queue,
        "agent-batch-v1": lifecycle_from_agent_batch,
        "agent-handoff-bundle-v1": lifecycle_from_agent_handoff,
        "layout-table-review-bundle-v1": lifecycle_from_layout_table_bundle,
        "optional-backend-scorecard-v1": lifecycle_from_scorecard,
    }.get(schema, lifecycle_from_generic_json)
    lifecycle = builder(payload)
    lifecycle.update(
        {
            "schema_version": SCHEMA_VERSION,
            "source_schema_version": schema,
            "source_name": source.name,
            "consume_policy": CONSUME_POLICY,
            "blocked_actions": BLOCKED_ACTIONS,
        }
    )
    if include_paths:
        lifecycle["source_path"] = str(source)
    lifecycle["summary"] = lifecycle_summary(lifecycle)
    lifecycle["recommended_followup"] = recommended_followup(lifecycle)
    return lifecycle


def lifecycle_from_quality_queue(payload: dict[str, Any]) -> dict[str, Any]:
    items = [item for item in payload.get("items") or [] if isinstance(item, dict)]
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return {
        "lifecycle_state": "needs_manual_review" if items else "ready_for_archive",
        "lifecycle_reasons": ["quality_queue_items"] if items else [],
        "review_targets": [
            {
                "id": item.get("id"),
                "state": "needs_manual_review",
                "focus": item.get("recommended_focus"),
                "quality_level": item.get("quality_level"),
                "quality_score": item.get("quality_score"),
                "safe_default_action": item.get("safe_default_action"),
                "next_step": item.get("next_step"),
            }
            for item in items
        ],
        "job_refs": [],
        "artifact_refs": [],
        "next_actions": safe_next_actions(payload.get("next_actions") or []),
        "source_summary": summary,
        "warning_count": 0,
    }


def lifecycle_from_agent_batch(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    artifact_summary = payload.get("artifact_summary") if isinstance(payload.get("artifact_summary"), dict) else {}
    comparison = payload.get("quality_comparison") if isinstance(payload.get("quality_comparison"), dict) else {}
    reasons: list[str] = []
    if payload.get("partial"):
        reasons.append("partial_run")
    if int(summary.get("hard_failed") or summary.get("failed") or 0) > 0:
        reasons.append("hard_failed_jobs")
    if int(artifact_summary.get("failed") or 0) > 0:
        reasons.append("artifact_read_failures")
    if comparison.get("status") == "failed":
        reasons.append("quality_regression")
    if int(summary.get("review") or 0) > 0 or int(summary.get("review_count") or 0) > 0:
        reasons.append("review_jobs")
    return {
        "lifecycle_state": state_from_reasons(reasons),
        "lifecycle_reasons": reasons,
        "review_targets": review_targets_from_agent_batch(payload),
        "job_refs": job_refs_from_agent_batch(payload),
        "artifact_refs": [],
        "next_actions": safe_next_actions(payload.get("next_actions") or []),
        "source_summary": summary,
        "warning_count": len(payload.get("warnings") or []),
        "failed_artifact_count": int(artifact_summary.get("failed") or 0),
    }


def lifecycle_from_agent_handoff(payload: dict[str, Any]) -> dict[str, Any]:
    status = str(payload.get("handoff_status") or "")
    status_to_state = {
        "ready": "ready_for_archive",
        "contract_failed": "failed",
        "needs_recovery": "failed",
        "needs_artifact_review": "needs_artifact_review",
        "needs_quality_compare": "needs_quality_compare",
        "needs_review": "needs_manual_review",
        "needs_attention": "needs_manual_review",
    }
    attention = payload.get("attention") if isinstance(payload.get("attention"), dict) else {}
    return {
        "lifecycle_state": status_to_state.get(status, "needs_manual_review"),
        "lifecycle_reasons": list(attention.get("reasons") or ([status] if status else [])),
        "review_targets": [
            {
                "id": item.get("id"),
                "state": "needs_manual_review",
                "quality_level": item.get("quality_level"),
                "quality_score": item.get("quality_score"),
                "suggested_action": item.get("suggested_action"),
                "next_actions": safe_next_actions(item.get("next_actions") or []),
            }
            for item in payload.get("review_items") or []
            if isinstance(item, dict)
        ],
        "job_refs": [],
        "artifact_refs": artifact_refs(payload.get("artifacts") or []),
        "next_actions": safe_next_actions(payload.get("next_actions") or []),
        "source_summary": payload.get("summary") or {},
        "warning_count": 0,
        "failed_artifact_count": int((payload.get("artifact_summary") or {}).get("failed") or 0),
    }


def lifecycle_from_layout_table_bundle(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    review_count = int(summary.get("table_review_matrix_count") or len(payload.get("table_review_matrix") or []))
    review_count += int(summary.get("formula_review_matrix_count") or len(payload.get("formula_review_matrix") or []))
    missing = int(summary.get("missing_expected_artifact_count") or 0)
    reasons = []
    if missing:
        reasons.append("missing_expected_artifacts")
    if review_count:
        reasons.append("layout_table_review")
    return {
        "lifecycle_state": "needs_artifact_review" if missing else "needs_manual_review" if review_count else "ready_for_archive",
        "lifecycle_reasons": reasons,
        "review_targets": [{"id": "layout_table_review_bundle", "state": "needs_manual_review", "count": review_count}],
        "job_refs": [],
        "artifact_refs": artifact_refs(payload.get("artifact_summaries") or []),
        "next_actions": safe_next_actions(payload.get("next_actions") or []),
        "source_summary": summary,
        "warning_count": 0,
        "failed_artifact_count": missing,
    }


def lifecycle_from_scorecard(payload: dict[str, Any]) -> dict[str, Any]:
    backends = [item for item in payload.get("backends") or [] if isinstance(item, dict)]
    review_targets = []
    for item in backends:
        gate = str(item.get("promotion_gate") or item.get("status") or "")
        if gate not in {"candidate_pass", "pass", "ready"}:
            review_targets.append(
                {
                    "id": item.get("backend"),
                    "state": "needs_manual_review",
                    "promotion_gate": gate,
                    "missing_artifacts": item.get("missing_artifacts") or [],
                }
            )
    return {
        "lifecycle_state": "needs_manual_review" if review_targets else "ready_for_archive",
        "lifecycle_reasons": ["backend_scorecard_review"] if review_targets else [],
        "review_targets": review_targets,
        "job_refs": [],
        "artifact_refs": [],
        "next_actions": safe_next_actions(payload.get("next_actions") or []),
        "source_summary": payload.get("summary") or {},
        "warning_count": 0,
    }


def lifecycle_from_generic_json(payload: dict[str, Any]) -> dict[str, Any]:
    status = str(payload.get("status") or "")
    warnings = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
    state = "failed" if status in {"failed", "error"} else "needs_manual_review" if warnings else "ready_for_archive"
    return {
        "lifecycle_state": state,
        "lifecycle_reasons": [status] if status in {"failed", "error"} else ["warnings"] if warnings else [],
        "review_targets": [],
        "job_refs": [],
        "artifact_refs": artifact_refs(payload.get("artifacts") or []),
        "next_actions": safe_next_actions(payload.get("next_actions") or []),
        "source_summary": {"status": status},
        "warning_count": len(warnings),
    }


def state_from_reasons(reasons: list[str]) -> str:
    if "partial_run" in reasons:
        return "processing"
    if "hard_failed_jobs" in reasons:
        return "failed"
    if "artifact_read_failures" in reasons:
        return "needs_artifact_review"
    if "quality_regression" in reasons:
        return "needs_quality_compare"
    if "review_jobs" in reasons:
        return "needs_manual_review"
    return "ready_for_archive"


def review_targets_from_agent_batch(payload: dict[str, Any]) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        quality = ((item.get("job") or {}).get("quality_summary") or {})
        if item.get("status") == "failed":
            targets.append({"id": item.get("id"), "state": "failed", "status": item.get("status")})
        for review in quality.get("review_items") or []:
            if not isinstance(review, dict):
                continue
            targets.append(
                {
                    "id": item.get("id"),
                    "state": "needs_manual_review",
                    "quality_level": review.get("quality_level"),
                    "quality_score": review.get("quality_score"),
                    "suggested_action": review.get("suggested_action"),
                }
            )
    return targets


def job_refs_from_agent_batch(payload: dict[str, Any]) -> list[dict[str, Any]]:
    refs = []
    for item in payload.get("results") or []:
        if isinstance(item, dict):
            refs.append({"id": item.get("id"), "status": item.get("status"), "job_id": (item.get("job") or {}).get("job_id")})
    return refs


def artifact_refs(values: list[Any]) -> list[dict[str, Any]]:
    refs = []
    for item in values:
        if not isinstance(item, dict):
            continue
        refs.append({"type": item.get("type"), "label": item.get("label"), "path_name": Path(str(item.get("path") or "")).name})
    return refs


def safe_next_actions(values: list[Any]) -> list[dict[str, Any]]:
    actions = []
    for item in values:
        if not isinstance(item, dict):
            continue
        action = dict(item)
        action.setdefault("safe_default", True)
        action.setdefault("destructive", False)
        actions.append(action)
    return actions


def lifecycle_summary(payload: dict[str, Any]) -> dict[str, Any]:
    artifacts = payload.get("artifact_refs") or []
    review_targets = payload.get("review_targets") or []
    failed_artifacts = int(payload.get("failed_artifact_count") or 0)
    return {
        "state": payload.get("lifecycle_state"),
        "reason_count": len(payload.get("lifecycle_reasons") or []),
        "artifact_count": len(artifacts),
        "failed_artifact_count": failed_artifacts,
        "warning_count": int(payload.get("warning_count") or 0),
        "review_item_count": len(review_targets),
        "next_action_count": len(payload.get("next_actions") or []),
    }


def recommended_followup(payload: dict[str, Any]) -> dict[str, Any]:
    state = str(payload.get("lifecycle_state") or "")
    action = {
        "processing": "poll_or_wait_for_current_job",
        "failed": "inspect_failure_and_rerun_safely",
        "needs_artifact_review": "inspect_missing_or_failed_artifacts",
        "needs_quality_compare": "read_quality_comparison_before_acceptance",
        "needs_manual_review": "inspect_review_targets",
        "ready_for_archive": "manual_accept_then_optionally_archive_outputs",
    }.get(state, "inspect_review_lifecycle")
    return {
        "action": action,
        "tool": "manual_review" if state == "ready_for_archive" else "read_artifact",
        "safe_default": True,
        "destructive": False,
        "why": "review lifecycle is metadata only; source files and outputs remain untouched",
    }


def render_review_lifecycle_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "# Review Lifecycle",
        "",
        f"- Schema: `{payload.get('schema_version')}`",
        f"- Source: `{payload.get('source_name', '')}`",
        f"- Source schema: `{payload.get('source_schema_version', '')}`",
        f"- State: `{payload.get('lifecycle_state', '')}`",
        f"- Reasons: {', '.join(payload.get('lifecycle_reasons') or []) or '(none)'}",
        f"- Review items: {summary.get('review_item_count', 0)}",
        f"- Artifacts: {summary.get('artifact_count', 0)}",
        f"- Failed artifacts: {summary.get('failed_artifact_count', 0)}",
        f"- Recommended follow-up: `{(payload.get('recommended_followup') or {}).get('action', '')}`",
        "",
        "## Blocked Actions",
        "",
    ]
    lines.extend(f"- `{item}`" for item in payload.get("blocked_actions") or [])
    targets = payload.get("review_targets") or []
    if targets:
        lines.extend(["", "## Review Targets", ""])
        for item in targets[:20]:
            lines.append(f"- `{item.get('id')}` {item.get('state', '')}: {item.get('suggested_action') or item.get('next_step') or item.get('focus') or ''}")
    actions = payload.get("next_actions") or []
    if actions:
        lines.extend(["", "## Next Actions", ""])
        for item in actions[:20]:
            lines.append(f"- `{item.get('action') or item.get('tool')}` safe={item.get('safe_default', True)} destructive={item.get('destructive', False)}")
    return "\n".join(lines).rstrip() + "\n"
