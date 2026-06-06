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
    "tool_log",
}
ALLOWED_INTENTS = {"auto", "convert", "locate", "rebuild"}
ALLOWED_OUTPUT_FORMATS = {"markdown", "html", "text"}
ALLOWED_OCR = {"auto", "always", "never"}


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
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    args.output.mkdir(parents=True, exist_ok=True)

    validation = validate_manifest(manifest)
    if args.dry_run or args.validate_only or validation["errors"]:
        plan_payload = write_plan(args.output, args.manifest, manifest, validation)
        print(json.dumps(plan_payload["summary"], ensure_ascii=False, indent=2))
        return 2 if validation["errors"] else 0

    started = time.monotonic()
    results = []
    for index, job in enumerate(manifest.get("jobs", []), start=1):
        results.append(run_manifest_job(args, manifest.get("defaults", {}), job, index))
        write_reports(args.output, args.manifest, started, results, partial=True)

    payload = write_reports(args.output, args.manifest, started, results, partial=False)
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0 if payload["summary"]["failed"] == 0 else 3


def validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
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
    }


def run_manifest_job(args: argparse.Namespace, defaults: dict[str, Any], job: dict[str, Any], index: int) -> dict[str, Any]:
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
        routed = call_tool(args, "process_material", material_args)
        runtime_job_id = routed.get("job_id")
        if not runtime_job_id:
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
    artifact_refs = []
    for action in job.get("next_actions", []) or []:
        action_args = action.get("arguments") or {}
        if action.get("tool") == "read_artifact" and action_args.get("path"):
            artifact_refs.append({"path": action_args["path"], "type": action_args.get("artifact_type", "text")})
    for item in job.get("artifacts", []) or []:
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


def finish(base: dict[str, Any], started: float, status: str, **extra: Any) -> dict[str, Any]:
    result = {
        **base,
        "status": status,
        "duration_seconds": round(time.monotonic() - started, 3),
        "finished_at": timestamp(),
    }
    result.update(extra)
    return result


def write_reports(output: Path, manifest: Path, started: float, results: list[dict[str, Any]], *, partial: bool) -> dict[str, Any]:
    suffix = ".partial" if partial else ""
    payload = {
        "schema_version": "agent-batch-v1",
        "manifest": str(manifest),
        "created_at": timestamp(),
        "duration_seconds": round(time.monotonic() - started, 3),
        "partial": partial,
        "summary": summarize(results),
        "results": results,
    }
    (output / f"agent-batch-results{suffix}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / f"agent-batch-summary{suffix}.md").write_text(render_markdown(payload), encoding="utf-8")
    return payload


def write_plan(output: Path, manifest: Path, raw_manifest: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
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
        "defaults": raw_manifest.get("defaults", {}),
    }
    (output / "agent-batch-plan.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "agent-batch-plan.md").write_text(render_plan_markdown(payload), encoding="utf-8")
    return payload


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
    return {
        "total": total,
        "ok": counts.get("ok", 0),
        "failed": total - counts.get("ok", 0),
        "status_counts": counts,
        "review_count": review_count,
        "artifact_reads": artifact_reads,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Agent Batch Summary",
        "",
        f"- Created: {payload['created_at']}",
        f"- Manifest: `{payload['manifest']}`",
        f"- Status: {payload['summary']['status_counts']}",
        f"- Review items: {payload['summary']['review_count']}",
        f"- Artifact reads: {payload['summary']['artifact_reads']}",
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


def render_plan_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Agent Batch Plan",
        "",
        f"- Created: {payload['created_at']}",
        f"- Manifest: `{payload['manifest']}`",
        f"- Valid: {payload['summary']['valid']}",
        f"- Jobs: {payload['summary']['jobs']}",
        f"- Errors: {payload['summary']['errors']}",
        f"- Warnings: {payload['summary']['warnings']}",
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
