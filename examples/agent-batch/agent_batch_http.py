from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))
from ebook_markdown_pipeline.http_config import default_http_url  # noqa: E402
from ebook_markdown_pipeline.recommendations import normalize_pdf_pipeline, pipeline_from_suggestion_text  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
from compare_benchmark_quality import compare_reports, render_markdown as render_quality_comparison_markdown  # noqa: E402


READABLE_TYPES = {
    "markdown",
    "html",
    "text",
    "conversion_report",
    "summary_report",
    "summary_json",
    "review_report",
    "review_json",
    "matches_json",
    "location_index_jsonl",
    "pages_jsonl",
    "order_report",
    "visual_check_json",
    "visual_blocks_json",
    "table_candidates_json",
    "image_positions_json",
    "tool_log",
}
ALLOWED_INTENTS = {"auto", "convert", "locate", "rebuild"}
ALLOWED_OUTPUT_FORMATS = {"markdown", "html", "text"}
ALLOWED_OCR = {"auto", "always", "never"}
SELECT_MODES = {"all", "failed", "review", "failed-or-review"}
RERUN_MODES = {"as-manifest", "recommended"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a stable agent batch workflow through HTTP /call.")
    parser.add_argument("--url", default=default_http_url())
    parser.add_argument("--token", default="")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("agent-batch-run"))
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--http-timeout", type=float, default=60)
    parser.add_argument("--artifact-max-chars", type=int, default=4000)
    parser.add_argument("--artifact-max-lines", type=int, default=120)
    parser.add_argument("--dry-run", action="store_true", help="validate and render the batch plan without calling HTTP tools")
    parser.add_argument("--validate-only", action="store_true", help="alias for --dry-run")
    parser.add_argument("--select", choices=sorted(SELECT_MODES), default="all", help="Run all jobs or select jobs from --previous-results.")
    parser.add_argument("--rerun-mode", choices=sorted(RERUN_MODES), default="as-manifest", help="Use manifest arguments or recommended rerun arguments when available.")
    parser.add_argument("--previous-results", type=Path, help="Prior agent-batch-results.json used by --select failed/review/failed-or-review.")
    parser.add_argument("--baseline-results", type=Path, help="Prior agent-batch-results.json used for quality comparison after this run.")
    parser.add_argument("--fail-on-regression", action="store_true", help="Exit non-zero when --baseline-results comparison fails.")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    args.output.mkdir(parents=True, exist_ok=True)
    previous_results_path = resolve_previous_results_path(args.previous_results, args.manifest, args.output, args.select)
    previous_payload = load_previous_results(previous_results_path)

    validation = validate_manifest(manifest, previous_payload=previous_payload, select=args.select, previous_results_path=previous_results_path)
    if args.dry_run or args.validate_only or validation["errors"]:
        plan_payload = write_plan(args.output, args.manifest, manifest, validation, previous_results_path=previous_results_path)
        print(json.dumps(plan_payload["summary"], ensure_ascii=False, indent=2))
        return 2 if validation["errors"] else 0

    started = time.monotonic()
    results = []
    jobs_to_run = select_jobs(manifest.get("jobs", []), previous_payload, args.select)
    selection = build_selection_summary(
        select=args.select,
        rerun_mode=args.rerun_mode,
        previous_results_path=previous_results_path,
        selected_job_ids=validation.get("selected_job_ids") or [],
        selected_count=len(jobs_to_run),
        manifest_job_count=len([job for job in manifest.get("jobs", []) if isinstance(job, dict)]),
    )
    for index, job in enumerate(jobs_to_run, start=1):
        results.append(run_manifest_job(args, manifest.get("defaults", {}), job, index, previous_payload=previous_payload))
        write_reports(args.output, args.manifest, started, results, partial=True, selection=selection)

    payload = write_reports(args.output, args.manifest, started, results, partial=False, baseline_results=args.baseline_results, selection=selection)
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    regression_failed = (payload.get("quality_comparison") or {}).get("summary", {}).get("status") == "failed"
    if args.fail_on_regression and regression_failed:
        return 5
    return 0 if payload["summary"]["hard_failed"] == 0 else 3


def validate_manifest(
    manifest: dict[str, Any],
    *,
    previous_payload: dict[str, Any] | None = None,
    select: str = "all",
    previous_results_path: Path | None = None,
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    defaults = manifest.get("defaults", {})
    jobs = manifest.get("jobs", [])

    if not isinstance(defaults, dict):
        errors.append({"scope": "defaults", "message": "defaults must be an object"})
        defaults = {}
    if not isinstance(jobs, list) or not jobs:
        errors.append({"scope": "jobs", "message": "jobs must be a non-empty array"})
        jobs = []
    if select != "all" and not previous_payload:
        errors.append({"scope": "previous_results", "message": "--previous-results is required when --select is not all, and no prior agent-batch-results.json was auto-discovered"})

    seen_ids: set[str] = set()
    normalized_jobs = []
    for index, job in enumerate(jobs, start=1):
        if not isinstance(job, dict):
            errors.append({"scope": f"jobs[{index}]", "message": "job must be an object"})
            continue
        job_id = str(job.get("id") or f"job-{index}")
        if job_id in seen_ids:
            errors.append({"scope": job_id, "message": "duplicate job id"})
        seen_ids.add(job_id)

        merged = {**defaults, **job}
        input_path = merged.get("input")
        output_path = merged.get("output")
        intent = merged.get("intent", "auto")
        output_format = merged.get("output_format", "markdown")
        ocr = merged.get("ocr", "auto")

        if not input_path:
            errors.append({"scope": job_id, "message": "input is required"})
        elif not Path(str(input_path)).exists():
            warnings.append({"scope": job_id, "message": f"input path does not exist on this machine: {input_path}"})
        if not output_path:
            errors.append({"scope": job_id, "message": "output is required, either in defaults or the job"})
        elif not Path(str(output_path)).parent.exists():
            warnings.append({"scope": job_id, "message": f"output parent does not exist yet: {Path(str(output_path)).parent}"})
        if intent not in ALLOWED_INTENTS:
            errors.append({"scope": job_id, "message": f"intent must be one of {sorted(ALLOWED_INTENTS)}"})
        if output_format not in ALLOWED_OUTPUT_FORMATS:
            errors.append({"scope": job_id, "message": f"output_format must be one of {sorted(ALLOWED_OUTPUT_FORMATS)}"})
        if ocr not in ALLOWED_OCR:
            errors.append({"scope": job_id, "message": f"ocr must be one of {sorted(ALLOWED_OCR)}"})
        if intent == "locate" and not merged.get("query"):
            warnings.append({"scope": job_id, "message": "locate intent usually needs query"})

        normalized_jobs.append(
            {
                "id": job_id,
                "input": input_path,
                "output": output_path,
                "intent": intent,
                "output_format": output_format,
                "ocr": ocr,
                "query": merged.get("query"),
            }
        )

    return {
        "errors": errors,
        "warnings": warnings,
        "normalized_jobs": normalized_jobs,
        "select": select,
        "selected_job_ids": selected_job_ids(jobs, previous_payload, select),
        "previous_results": str(previous_results_path) if previous_results_path else "",
    }


def run_manifest_job(
    args: argparse.Namespace,
    defaults: dict[str, Any],
    job: dict[str, Any],
    index: int,
    *,
    previous_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    job_id = str(job.get("id") or f"job-{index}")
    material_args = {**defaults, **job}
    material_args.pop("id", None)
    base = {
        "id": job_id,
        "input": material_args.get("input"),
        "output": material_args.get("output"),
        "intent": material_args.get("intent", "auto"),
        "started_at": timestamp(),
    }
    try:
        material_args = apply_recommended_rerun(job_id, material_args, previous_payload, args.rerun_mode)
        routed = call_tool(args, "process_material", material_args)
        runtime_job_id = routed.get("job_id")
        if not runtime_job_id:
            delegated = routed.get("delegated") or {}
            if isinstance(delegated, dict) and delegated.get("artifacts"):
                artifacts = read_artifact_refs(args, delegated.get("artifacts", []), delegated.get("next_actions", []))
                status = synchronous_status(delegated)
                return finish(base, started, status, routed=routed, result=delegated, artifacts=artifacts)
            return finish(base, started, "unsupported" if routed.get("status") == "unsupported" else "no_job", routed=routed)

        final = poll_job(args, str(runtime_job_id))
        artifacts = read_followup_artifacts(args, final)
        status = "ok" if final.get("status") == "done" else "failed"
        return finish(base, started, status, routed=routed, job=final, artifacts=artifacts)
    except TimeoutError as exc:
        return finish(base, started, "timeout", failure_reason=str(exc))
    except Exception as exc:  # noqa: BLE001
        return finish(base, started, "failed", failure_reason=str(exc))


def call_tool(args: argparse.Namespace, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    payload = json.dumps({"name": name, "arguments": arguments}, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8", "Accept": "application/json"}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"
    request = urllib.request.Request(args.url.rstrip("/") + "/call", data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=args.http_timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"ok": False, "message": raw}
        raise RuntimeError(body) from exc
    if body.get("ok") is False:
        raise RuntimeError(body)
    return body.get("result") if isinstance(body.get("result"), dict) else body


def poll_job(args: argparse.Namespace, job_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + args.timeout
    last = {}
    while time.monotonic() < deadline:
        last = call_tool(args, "get_job_status", {"job_id": job_id})
        if last.get("status") != "running":
            return last
        time.sleep(args.poll_interval)
    raise TimeoutError(f"Timed out waiting for {job_id}; last={last}")


def read_followup_artifacts(args: argparse.Namespace, job: dict[str, Any]) -> list[dict[str, Any]]:
    return read_artifact_refs(args, job.get("artifacts", []), job.get("next_actions", []))


def read_artifact_refs(args: argparse.Namespace, artifacts_payload: list[dict[str, Any]], next_actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    artifact_refs = []
    for action in next_actions or []:
        action_args = action.get("arguments") or {}
        if action.get("tool") == "read_artifact" and action_args.get("path"):
            artifact_refs.append({"path": action_args["path"], "type": action_args.get("artifact_type", "text")})
    for item in artifacts_payload or []:
        if item.get("type") in READABLE_TYPES and item.get("path"):
            artifact_refs.append({"path": item["path"], "type": item.get("type")})

    seen = set()
    artifacts = []
    for item in artifact_refs:
        key = (item["path"], item.get("type"))
        if key in seen:
            continue
        seen.add(key)
        try:
            payload = call_tool(
                args,
                "read_artifact",
                {
                    "path": item["path"],
                    "artifact_type": item.get("type") or "text",
                    "max_chars": args.artifact_max_chars,
                    "max_lines": args.artifact_max_lines,
                },
            )
            artifacts.append({"status": "ok", "path": item["path"], "type": item.get("type"), "preview": payload})
        except Exception as exc:  # noqa: BLE001
            artifacts.append({"status": "failed", "path": item["path"], "type": item.get("type"), "message": str(exc)})
    return artifacts


def synchronous_status(result: dict[str, Any]) -> str:
    status = str(result.get("status") or "")
    if status in {"ok", "done"}:
        return "ok"
    if status in {"needs_review", "pending_visual_engine", "no_text"}:
        return "review"
    if status in {"failed", "error"}:
        return "failed"
    return "ok" if result.get("artifacts") else "failed"


def finish(base: dict[str, Any], started: float, status: str, **extra: Any) -> dict[str, Any]:
    result = {
        **base,
        "status": status,
        "duration_seconds": round(time.monotonic() - started, 3),
        "finished_at": timestamp(),
    }
    result.update(extra)
    return result


def write_reports(
    output: Path,
    manifest: Path,
    started: float,
    results: list[dict[str, Any]],
    *,
    partial: bool,
    baseline_results: Path | None = None,
    selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    suffix = ".partial" if partial else ""
    output.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "agent-batch-v1",
        "manifest": str(manifest),
        "created_at": timestamp(),
        "duration_seconds": round(time.monotonic() - started, 3),
        "partial": partial,
        "output": str(output),
        "selection": selection or build_selection_summary(
            select="all",
            rerun_mode="as-manifest",
            previous_results_path=None,
            selected_job_ids=job_ids(results),
            selected_count=len(results),
            manifest_job_count=len(results),
        ),
        "summary": summarize(results),
        "artifact_summary": summarize_artifacts(results),
        "results": results,
    }
    (output / f"agent-batch-results{suffix}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / f"agent-batch-summary{suffix}.md").write_text(render_markdown(payload), encoding="utf-8")
    (output / f"run_summary{suffix}.md").write_text(render_run_summary(payload), encoding="utf-8")
    if not partial and baseline_results:
        payload["quality_comparison"] = write_quality_comparison(output, baseline_results, output / "agent-batch-results.json")
        payload["next_actions"] = quality_comparison_next_actions(
            payload["quality_comparison"],
            manifest=manifest,
            current_results=output / "agent-batch-results.json",
            suggested_output=output.with_name(output.name + "-recommended-rerun"),
        )
        (output / "agent-batch-results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        (output / "run_summary.md").write_text(render_run_summary(payload), encoding="utf-8")
    return payload


def write_quality_comparison(output: Path, baseline_results: Path, candidate_results: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    args = argparse.Namespace(
        baseline=baseline_results,
        candidate=candidate_results,
        min_success_rate_delta=-0.001,
        min_good_rate_delta=-0.05,
        max_review_poor_delta=0.05,
        max_timeout_rate_delta=0.001,
        max_failed_rate_delta=0.001,
    )
    payload = compare_reports(args)
    write_path = output / "benchmark-quality-comparison.json"
    markdown_path = output / "benchmark-quality-comparison.md"
    write_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_quality_comparison_markdown(payload), encoding="utf-8")
    return {
        "status": payload.get("summary", {}).get("status"),
        "json": str(write_path),
        "markdown": str(markdown_path),
        "summary": payload.get("summary", {}),
    }


def quality_comparison_next_actions(
    comparison: dict[str, Any],
    *,
    manifest: Path | str | None = None,
    current_results: Path | str | None = None,
    suggested_output: Path | str | None = None,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if comparison.get("markdown"):
        actions.append(
            {
                "action": "read_quality_comparison",
                "tool": "read_artifact",
                "arguments": {"path": comparison["markdown"], "artifact_type": "markdown"},
            }
        )
    if comparison.get("json"):
        actions.append(
            {
                "action": "read_quality_comparison_json",
                "tool": "read_artifact",
                "arguments": {"path": comparison["json"], "artifact_type": "quality_comparison_json"},
            }
        )
    if comparison.get("status") == "failed":
        command_args = {
            "manifest": str(manifest or ""),
            "previous_results": str(current_results or ""),
            "select": "failed-or-review",
            "rerun_mode": "recommended",
            "output": str(suggested_output or ""),
        }
        actions.append(
            {
                "action": "rerun_failed_or_review",
                "runner": str(Path(__file__).resolve()),
                "select": "failed-or-review",
                "rerun_mode": "recommended",
                "previous_results": command_args["previous_results"],
                "baseline_results": command_args["previous_results"],
                "suggested_output": command_args["output"],
                "command_args": command_args,
                "powershell_command": render_recommended_rerun_command(command_args),
                "note": "Quality regression detected; rerun failed/review jobs with recommended safe pipeline settings before accepting the batch.",
            }
        )
    return actions


def render_recommended_rerun_command(command_args: dict[str, str]) -> str:
    runner = str(Path(__file__).resolve())
    return (
        f'python "{runner}" '
        f'--manifest "{command_args.get("manifest", "")}" '
        f'--previous-results "{command_args.get("previous_results", "")}" '
        f'--select {command_args.get("select", "failed-or-review")} '
        f'--rerun-mode {command_args.get("rerun_mode", "recommended")} '
        f'--output "{command_args.get("output", "")}"'
    )


def write_plan(
    output: Path,
    manifest: Path,
    raw_manifest: dict[str, Any],
    validation: dict[str, Any],
    *,
    previous_results_path: Path | None = None,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "agent-batch-plan-v1",
        "manifest": str(manifest),
        "created_at": timestamp(),
        "summary": {
            "jobs": len(validation["normalized_jobs"]),
            "errors": len(validation["errors"]),
            "warnings": len(validation["warnings"]),
            "valid": not validation["errors"],
        },
        "validation": validation,
        "selection": build_selection_summary(
            select=str(validation.get("select") or "all"),
            rerun_mode="as-manifest",
            previous_results_path=previous_results_path,
            selected_job_ids=validation.get("selected_job_ids") or [],
            selected_count=len(validation.get("selected_job_ids") or []),
            manifest_job_count=len(validation.get("normalized_jobs") or []),
        ),
        "defaults": raw_manifest.get("defaults", {}),
        "previous_results": str(previous_results_path) if previous_results_path else "",
    }
    (output / "agent-batch-plan.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "agent-batch-plan.md").write_text(render_plan_markdown(payload), encoding="utf-8")
    return payload


def load_previous_results(path: Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def resolve_previous_results_path(explicit: Path | None, manifest: Path, output: Path, select: str) -> Path | None:
    if explicit:
        return explicit
    if select == "all":
        return None
    return discover_previous_results(manifest, output)


def discover_previous_results(manifest: Path, output: Path) -> Path | None:
    candidates: list[Path] = []
    seen: set[str] = set()
    for root in previous_results_search_roots(manifest, output):
        for path in previous_results_candidates(root):
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            candidates.append(path)
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def previous_results_search_roots(manifest: Path, output: Path) -> list[Path]:
    roots = []
    for candidate in [output, output.parent, manifest.parent]:
        if candidate and candidate.exists() and candidate.is_dir():
            roots.append(candidate)
    deduped = []
    seen = set()
    for root in roots:
        key = str(root.resolve())
        if key not in seen:
            seen.add(key)
            deduped.append(root)
    return deduped


def previous_results_candidates(root: Path) -> list[Path]:
    direct = root / "agent-batch-results.json"
    candidates = [direct] if direct.exists() else []
    try:
        candidates.extend(path for path in root.glob("*/agent-batch-results.json") if path.exists())
    except OSError:
        pass
    return candidates


def select_jobs(jobs: list[Any], previous_payload: dict[str, Any] | None, select: str) -> list[dict[str, Any]]:
    normalized = [job for job in jobs if isinstance(job, dict)]
    if select == "all":
        return normalized
    previous_by_id = previous_results_by_id(previous_payload)
    selected = []
    for index, job in enumerate(normalized, start=1):
        job_id = str(job.get("id") or f"job-{index}")
        previous = previous_by_id.get(job_id)
        if not previous:
            continue
        status = str(previous.get("status") or "")
        if select == "failed" and is_hard_failed_status(status):
            selected.append(job)
        elif select == "review" and status == "review":
            selected.append(job)
        elif select == "failed-or-review" and (status == "review" or is_hard_failed_status(status)):
            selected.append(job)
    return selected


def selected_job_ids(jobs: list[Any], previous_payload: dict[str, Any] | None, select: str) -> list[str]:
    if select == "all":
        return [str(job.get("id") or f"job-{index}") for index, job in enumerate(jobs, start=1) if isinstance(job, dict)]
    previous_by_id = previous_results_by_id(previous_payload)
    selected = []
    for index, job in enumerate(jobs, start=1):
        if not isinstance(job, dict):
            continue
        job_id = str(job.get("id") or f"job-{index}")
        previous = previous_by_id.get(job_id)
        if not previous:
            continue
        status = str(previous.get("status") or "")
        if select == "failed" and is_hard_failed_status(status):
            selected.append(job_id)
        elif select == "review" and status == "review":
            selected.append(job_id)
        elif select == "failed-or-review" and (status == "review" or is_hard_failed_status(status)):
            selected.append(job_id)
    return selected


def build_selection_summary(
    *,
    select: str,
    rerun_mode: str,
    previous_results_path: Path | str | None,
    selected_job_ids: list[Any],
    selected_count: int,
    manifest_job_count: int,
) -> dict[str, Any]:
    ids = [str(job_id) for job_id in selected_job_ids]
    return {
        "select": select,
        "rerun_mode": rerun_mode,
        "previous_results": str(previous_results_path) if previous_results_path else "",
        "selected_job_ids": ids,
        "selected_count": selected_count,
        "manifest_job_count": manifest_job_count,
        "selection_ratio": round(selected_count / manifest_job_count, 4) if manifest_job_count else 0.0,
    }


def job_ids(items: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("id") or f"job-{index}") for index, item in enumerate(items, start=1)]


def previous_results_by_id(previous_payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not previous_payload:
        return {}
    return {str(item.get("id")): item for item in previous_payload.get("results") or [] if isinstance(item, dict) and item.get("id")}


def is_hard_failed_status(status: str) -> bool:
    return status in {"failed", "timeout", "unsupported", "no_job"}


def apply_recommended_rerun(job_id: str, material_args: dict[str, Any], previous_payload: dict[str, Any] | None, rerun_mode: str) -> dict[str, Any]:
    if rerun_mode != "recommended":
        return material_args
    previous = previous_results_by_id(previous_payload).get(job_id)
    if not previous:
        return material_args
    recommended = extract_recommended_arguments(previous)
    if not recommended:
        return material_args
    merged = dict(material_args)
    merged.update(recommended)
    return merged


def extract_recommended_arguments(previous: dict[str, Any]) -> dict[str, Any]:
    for action in iter_next_actions(previous):
        pipeline = action.get("pipeline") or action.get("pdf_pipeline_mode")
        if action.get("action") == "rerun" and pipeline:
            normalized = normalize_pdf_pipeline(str(pipeline))
            if normalized:
                return {"pdf_pipeline_mode": normalized}
        if action.get("action") == "compare_pdf_pipelines":
            return {"pdf_pipeline_mode": "auto"}
    for suggested in iter_suggested_actions(previous):
        pipeline = pipeline_from_suggestion_text(suggested)
        if pipeline:
            return {"pdf_pipeline_mode": pipeline}
    return {}


def iter_next_actions(payload: dict[str, Any]):
    for path in [
        ("result", "next_actions"),
        ("job", "next_actions"),
        ("routed", "next_actions"),
    ]:
        current: Any = payload
        for key in path:
            current = current.get(key) if isinstance(current, dict) else None
        if isinstance(current, list):
            for item in current:
                if isinstance(item, dict):
                    yield item
    quality_items = (((payload.get("job") or {}).get("quality_summary") or {}).get("review_items") or [])
    for item in quality_items:
        for action in item.get("next_actions") or []:
            if isinstance(action, dict):
                yield action


def iter_suggested_actions(payload: dict[str, Any]):
    if payload.get("suggested_action"):
        yield str(payload.get("suggested_action"))
    for path in [
        ("result", "suggested_action"),
        ("job", "suggested_action"),
        ("routed", "suggested_action"),
    ]:
        current: Any = payload
        for key in path:
            current = current.get(key) if isinstance(current, dict) else None
        if current:
            yield str(current)
    quality_items = (((payload.get("job") or {}).get("quality_summary") or {}).get("review_items") or [])
    for item in quality_items:
        if isinstance(item, dict) and item.get("suggested_action"):
            yield str(item.get("suggested_action"))


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    review_count = 0
    artifact_reads = 0
    for item in results:
        counts[item.get("status", "unknown")] = counts.get(item.get("status", "unknown"), 0) + 1
        quality = ((item.get("job") or {}).get("quality_summary") or {})
        review_count += int(quality.get("review_count") or 0)
        artifact_reads += sum(1 for artifact in item.get("artifacts", []) if artifact.get("status") == "ok")
    total = len(results)
    hard_failed_statuses = {"failed", "timeout", "unsupported", "no_job"}
    hard_failed = sum(count for status, count in counts.items() if status in hard_failed_statuses)
    review_jobs = counts.get("review", 0)
    return {
        "total": total,
        "ok": counts.get("ok", 0),
        "review": review_jobs,
        "failed": hard_failed,
        "hard_failed": hard_failed,
        "completed_with_review": review_jobs,
        "other": total - counts.get("ok", 0) - review_jobs - hard_failed,
        "status_counts": counts,
        "review_count": review_count,
        "artifact_reads": artifact_reads,
    }


def summarize_artifacts(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = 0
    ok = 0
    failed = 0
    type_counts: dict[str, int] = {}
    failed_artifacts = []
    for item in results:
        job_id = str(item.get("id") or "")
        for artifact_item in item.get("artifacts") or []:
            if not isinstance(artifact_item, dict):
                continue
            total += 1
            artifact_type = str(artifact_item.get("type") or "unknown")
            type_counts[artifact_type] = type_counts.get(artifact_type, 0) + 1
            if artifact_item.get("status") == "ok":
                ok += 1
            else:
                failed += 1
                failed_artifacts.append(
                    {
                        "job_id": job_id,
                        "path": artifact_item.get("path"),
                        "type": artifact_item.get("type"),
                        "status": artifact_item.get("status"),
                        "message": artifact_item.get("message") or ((artifact_item.get("preview") or {}).get("message") if isinstance(artifact_item.get("preview"), dict) else ""),
                    }
                )
    return {
        "total": total,
        "ok": ok,
        "failed": failed,
        "type_counts": type_counts,
        "failed_artifacts": failed_artifacts[:20],
    }


def render_markdown(payload: dict[str, Any]) -> str:
    selection = payload.get("selection") or {}
    artifact_summary = payload.get("artifact_summary") or {}
    lines = [
        "# Agent Batch Summary",
        "",
        f"- Created: {payload['created_at']}",
        f"- Manifest: `{payload['manifest']}`",
        f"- Select: {selection.get('select', 'all')}",
        f"- Selected jobs: {selection.get('selected_count', len(payload.get('results') or []))}/{selection.get('manifest_job_count', len(payload.get('results') or []))}",
        f"- Status: {payload['summary']['status_counts']}",
        f"- Review items: {payload['summary']['review_count']}",
        f"- Artifact reads: {payload['summary']['artifact_reads']}",
        f"- Artifact read failures: {artifact_summary.get('failed', 0)}",
        "",
        "| Status | ID | Input | Output | Review | Failure |",
        "| --- | --- | --- | --- | ---: | --- |",
    ]
    for item in payload["results"]:
        quality = ((item.get("job") or {}).get("quality_summary") or {})
        failure = item.get("failure_reason") or (item.get("job") or {}).get("error") or ""
        lines.append(
            f"| {cell(item.get('status'))} | {cell(item.get('id'))} | {cell(item.get('input'))} | "
            f"{cell(item.get('output'))} | {quality.get('review_count', '')} | {cell(str(failure)[:220])} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def render_run_summary(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    selection = payload.get("selection") or {}
    artifact_summary = payload.get("artifact_summary") or {}
    lines = [
        "# Run Summary",
        "",
        f"- Created: {payload['created_at']}",
        f"- Manifest: `{payload['manifest']}`",
        f"- Select: {selection.get('select', 'all')}",
        f"- Rerun mode: {selection.get('rerun_mode', 'as-manifest')}",
        f"- Previous results: `{selection.get('previous_results', '')}`",
        f"- Selected jobs: {selection.get('selected_count', len(payload.get('results') or []))}/{selection.get('manifest_job_count', len(payload.get('results') or []))}",
        f"- Total: {summary.get('total', 0)}",
        f"- OK: {summary.get('ok', 0)}",
        f"- Review: {summary.get('review', 0)}",
        f"- Hard failed: {summary.get('hard_failed', 0)}",
        f"- Artifact reads: {summary.get('artifact_reads', 0)}",
        f"- Artifact read failures: {artifact_summary.get('failed', 0)}",
    ]
    comparison = payload.get("quality_comparison") or {}
    if comparison:
        lines.extend(
            [
                f"- Quality comparison: {comparison.get('status', '')}",
                f"- Quality comparison report: `{comparison.get('markdown', '')}`",
            ]
        )
    next_actions = payload.get("next_actions") or []
    if next_actions:
        lines.append(f"- Next actions: {summarize_batch_next_actions(next_actions)}")
        rerun_command = first_rerun_command(next_actions)
        if rerun_command:
            lines.extend(["", "## Recommended Rerun", "", "```powershell", rerun_command, "```"])
    lines.extend([
        "",
        "| Status | ID | Route | Input | Output | Artifacts | Next |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ])
    for item in payload["results"]:
        routed = item.get("routed") or {}
        route = routed.get("route") or ""
        artifact_paths = [str(artifact.get("path") or "") for artifact in item.get("artifacts") or [] if artifact.get("path")]
        next_action = summarize_next_action(item)
        lines.append(
            f"| {cell(item.get('status'))} | {cell(item.get('id'))} | {cell(route)} | "
            f"{cell(item.get('input'))} | {cell(item.get('output'))} | {cell('; '.join(artifact_paths[:3]))} | {cell(next_action)} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def summarize_batch_next_actions(actions: list[dict[str, Any]]) -> str:
    names = []
    for action in actions:
        name = str(action.get("action") or action.get("tool") or "").strip()
        if name:
            names.append(name)
    return ", ".join(names[:4])


def first_rerun_command(actions: list[dict[str, Any]]) -> str:
    for action in actions:
        if action.get("action") == "rerun_failed_or_review" and action.get("powershell_command"):
            return str(action["powershell_command"])
    return ""


def summarize_next_action(item: dict[str, Any]) -> str:
    if item.get("failure_reason"):
        return str(item["failure_reason"])
    quality = ((item.get("job") or {}).get("quality_summary") or {})
    review_items = quality.get("review_items") or []
    if review_items:
        first = review_items[0]
        reasons = "; ".join(str(reason) for reason in first.get("quality_reasons") or [])
        suggested = str(first.get("suggested_action") or "")
        return f"{suggested}: {reasons}".strip(": ")
    result = item.get("result") or {}
    warnings = result.get("warnings") or []
    if warnings:
        return "; ".join(str(warning) for warning in warnings[:2])
    if item.get("status") == "review":
        return "Review generated artifacts before accepting."
    return ""


def render_plan_markdown(payload: dict[str, Any]) -> str:
    selection = payload.get("selection") or {}
    lines = [
        "# Agent Batch Plan",
        "",
        f"- Created: {payload['created_at']}",
        f"- Manifest: `{payload['manifest']}`",
        f"- Valid: {payload['summary']['valid']}",
        f"- Jobs: {payload['summary']['jobs']}",
        f"- Errors: {payload['summary']['errors']}",
        f"- Warnings: {payload['summary']['warnings']}",
        f"- Select: {selection.get('select', payload['validation'].get('select', 'all'))}",
        f"- Rerun mode: {selection.get('rerun_mode', 'as-manifest')}",
        f"- Previous results: `{payload.get('previous_results') or payload['validation'].get('previous_results') or ''}`",
        f"- Selected jobs: {selection.get('selected_count', len(payload['validation'].get('selected_job_ids') or []))}/{selection.get('manifest_job_count', len(payload['validation'].get('normalized_jobs') or []))}: {', '.join(payload['validation'].get('selected_job_ids') or []) or '(none)'}",
        "",
    ]
    if payload["validation"]["errors"]:
        lines.extend(["## Errors", ""])
        for item in payload["validation"]["errors"]:
            lines.append(f"- `{cell(item.get('scope'))}`: {cell(item.get('message'))}")
        lines.append("")
    if payload["validation"]["warnings"]:
        lines.extend(["## Warnings", ""])
        for item in payload["validation"]["warnings"]:
            lines.append(f"- `{cell(item.get('scope'))}`: {cell(item.get('message'))}")
        lines.append("")

    lines.extend(
        [
            "## Jobs",
            "",
            "| ID | Intent | Input | Output | Query |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for job in payload["validation"]["normalized_jobs"]:
        lines.append(
            f"| {cell(job.get('id'))} | {cell(job.get('intent'))} | {cell(job.get('input'))} | "
            f"{cell(job.get('output'))} | {cell(job.get('query'))} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def timestamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    raise SystemExit(main())
