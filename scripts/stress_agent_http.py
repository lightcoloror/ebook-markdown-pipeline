from __future__ import annotations

import argparse
import concurrent.futures
import json
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark_utils import AGENT_STRESS_SCHEMA_VERSION, load_samples, now, safe_id, write_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Stress-test agent HTTP /call workflow.")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--token", default="")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/runs/agent-stress"))
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--ocr", choices=["auto", "never"], default="never")
    parser.add_argument("--intent", choices=["auto", "convert", "locate", "rebuild"], default="auto")
    parser.add_argument("--query", default="")
    parser.add_argument("--pdf-pipeline-mode", default="auto")
    args = parser.parse_args()

    samples = [item for item in load_samples(args.manifest) if Path(item["path"]).exists()]
    if not samples:
        raise SystemExit("No existing samples found in manifest.")
    args.output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [
            executor.submit(run_iteration, args, random.choice(samples), index)
            for index in range(1, args.iterations + 1)
        ]
        results = [future.result() for future in concurrent.futures.as_completed(futures)]

    payload = {
        "schema_version": AGENT_STRESS_SCHEMA_VERSION,
        "created_at": now(),
        "url": args.url,
        "manifest": str(args.manifest),
        "iterations": args.iterations,
        "concurrency": args.concurrency,
        "duration_seconds": round(time.monotonic() - started, 3),
        "summary": summarize(results),
        "results": sorted(results, key=lambda item: item["iteration"]),
    }
    write_json(args.output / "agent-stress-results.json", payload)
    (args.output / "agent-stress-summary.md").write_text(render_summary(payload), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0 if payload["summary"].get("failed", 0) == 0 else 3


def run_iteration(args: argparse.Namespace, sample: dict, iteration: int) -> dict[str, Any]:
    output_dir = args.output / "outputs" / f"{iteration:04d}-{safe_id(str(sample.get('id') or 'sample'))}"
    started = time.monotonic()
    base = {
        "iteration": iteration,
        "sample_id": sample.get("id"),
        "source": sample.get("path"),
        "category": sample.get("category"),
        "status": "unknown",
    }
    try:
        material_args = {
            "input": sample["path"],
            "output": str(output_dir),
            "recursive": True,
            "ocr": args.ocr,
            "intent": args.intent,
            "pdf_pipeline_mode": args.pdf_pipeline_mode,
        }
        if args.query:
            material_args["query"] = args.query
        routed = call_tool(args, "process_material", material_args)
        job_id = routed.get("job_id")
        if not job_id:
            return finish(base, started, "no_job", routed=routed)
        job = poll_job(args, str(job_id))
        artifact_result = None
        artifact = first_readable_artifact(job)
        if artifact:
            artifact_result = call_tool(
                args,
                "read_artifact",
                {"path": artifact["path"], "artifact_type": artifact["type"], "max_chars": 1000, "max_lines": 40},
            )
        return finish(base, started, "ok" if job.get("status") == "done" else "failed", routed=routed, job=job, artifact=artifact_result)
    except Exception as exc:  # noqa: BLE001
        return finish(base, started, "failed", failure_reason=str(exc))


def call_tool(args: argparse.Namespace, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    payload = json.dumps({"name": name, "arguments": arguments}, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8", "Accept": "application/json"}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"
    request = urllib.request.Request(args.url.rstrip("/") + "/call", data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = json.loads(exc.read().decode("utf-8", errors="replace"))
        raise RuntimeError(body) from exc
    return body.get("result") if isinstance(body.get("result"), dict) else body


def poll_job(args: argparse.Namespace, job_id: str) -> dict[str, Any]:
    deadline = time.time() + args.timeout
    final = {}
    while time.time() < deadline:
        final = call_tool(args, "get_job_status", {"job_id": job_id})
        if final.get("status") != "running":
            return final
        time.sleep(0.25)
    raise TimeoutError(f"Job timed out: {job_id}; last={final}")


def first_readable_artifact(job: dict[str, Any]) -> dict[str, Any] | None:
    readable = {"markdown", "html", "text", "summary_report", "review_report", "location_index_jsonl", "order_report"}
    for item in job.get("artifacts", []):
        if item.get("type") in readable and item.get("path"):
            return item
    return None


def finish(base: dict, started: float, status: str, **updates) -> dict:
    payload = dict(base)
    payload.update(updates)
    payload["status"] = status
    payload["duration_seconds"] = round(time.monotonic() - started, 3)
    return payload


def summarize(results: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return counts


def render_summary(payload: dict[str, Any]) -> str:
    lines = [
        "# Agent HTTP Stress Summary",
        "",
        f"- Created: {payload['created_at']}",
        f"- Iterations: {payload['iterations']}",
        f"- Concurrency: {payload['concurrency']}",
        f"- Duration seconds: {payload['duration_seconds']}",
        f"- Summary: {payload['summary']}",
        "",
        "| Status | Seconds | Sample | Category | Failure |",
        "| --- | ---: | --- | --- | --- |",
    ]
    for item in payload["results"]:
        lines.append(
            f"| {item.get('status')} | {item.get('duration_seconds')} | "
            f"{Path(str(item.get('source') or '')).name} | {item.get('category', '')} | "
            f"{escape_table(str(item.get('failure_reason') or ''))[:180]} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").replace("\r", " ")


if __name__ == "__main__":
    raise SystemExit(main())
