from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import fitz

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.artifact_schema import SCHEMA_VERSION
from ebook_markdown_pipeline.batch_convert_books import ConversionResult, default_options, write_batch_summary, write_conversion_report
from ebook_markdown_pipeline.ebook_converter_http import build_handler
from ebook_markdown_pipeline.ebook_converter_mcp import call_tool, conversion_quality_summary, tool_schemas


REQUIRED_TOOLS = {
    "process_material",
    "process_web_archive",
    "get_job_status",
    "read_artifact",
    "inspect_agent_batch_results",
    "list_agent_batch_results",
    "build_agent_handoff_bundle",
    "inspect_document",
    "scan_books",
    "health_check",
    "export_environment_report",
    "compare_environment_lock",
    "start_conversion",
    "start_location_index",
    "query_location_index",
    "export_location_review_pack",
    "start_image_book_rebuild",
    "rebuild_image_book_from_order",
}

PROCESS_MATERIAL_FIELDS = {"status", "route", "inspection", "job_id", "warnings", "errors", "next_actions"}
HEALTH_FIELDS = {"checks", "capabilities", "ok", "ready_capabilities", "degraded_capabilities", "missing_capabilities"}
INSPECTION_FIELDS = {"status", "input", "kind", "recommendation", "structure_strategy", "next_actions", "warnings"}
JOB_FIELDS = {
    "job_id",
    "kind",
    "status",
    "started_at",
    "input",
    "output",
    "total",
    "completed",
    "events",
    "results",
    "artifacts",
    "warnings",
    "errors",
    "next_actions",
    "error",
}
ARTIFACT_FIELDS = {"type", "path", "label", "media_type"}
ERROR_FIELDS = {"ok", "error", "code", "message", "retryable", "transport", "schema_version"}


def main() -> int:
    assert_tools()
    with tempfile.TemporaryDirectory(prefix="ebook-agent-contract-") as tmp:
        tmpdir = Path(tmp)
        image_dir = tmpdir / "images"
        output_dir = tmpdir / "out"
        image_dir.mkdir()
        pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 80, 80), 0)
        pixmap.clear_with(255)
        pixmap.save(str(image_dir / "shot-001.png"))

        routed = call_tool(
            "process_material",
            {
                "input": str(image_dir),
                "output": str(output_dir),
                "recursive": False,
                "ocr": "never",
            },
        )
        assert_fields("process_material", routed, PROCESS_MATERIAL_FIELDS)
        if routed["status"] != "routed" or routed["route"] != "start_location_index":
            raise AssertionError(f"Unexpected process_material route: {routed}")

        job = poll_job(str(routed["job_id"]))
        assert_fields("job", job, JOB_FIELDS)
        if job["status"] != "done":
            raise AssertionError(f"Job did not finish: {job}")
        if not job["artifacts"]:
            raise AssertionError(f"Job has no artifacts: {job}")
        for item in job["artifacts"]:
            assert_fields("artifact", item, ARTIFACT_FIELDS)
        if not job["results"] or job["results"][0].get("schema_version") != SCHEMA_VERSION:
            raise AssertionError(f"Artifact schema version mismatch: {job['results']}")
        if not isinstance(job.get("warnings"), list) or not isinstance(job.get("errors"), list):
            raise AssertionError(f"Job warnings/errors must be lists: {job}")
        if not isinstance(job.get("next_actions"), list):
            raise AssertionError(f"Job next_actions must be a list: {job}")

        health = call_tool("health_check", {"input": str(image_dir), "output": str(output_dir)})
        assert_fields("health_check", health, HEALTH_FIELDS)
        if not isinstance(health.get("capabilities"), list) or not health["capabilities"]:
            raise AssertionError(f"health_check must expose capability matrix: {health}")
        assert_environment_report_tool(image_dir, tmpdir / "environment-report")

        inspection = call_tool("inspect_document", {"input": str(image_dir), "recursive": False})
        assert_fields("inspect_document", inspection, INSPECTION_FIELDS)
        if not isinstance(inspection.get("next_actions"), list) or "mode" not in inspection.get("structure_strategy", {}):
            raise AssertionError(f"inspect_document must expose structure strategy and next actions: {inspection}")
        assert_pdf_outline_inspection(tmpdir)
        assert_conversion_report_pdf_outline(tmpdir)
        assert_review_decisions_report(tmpdir)
        assert_web_archive_route(tmpdir)

        assert_quality_summary_next_actions(tmpdir)

        readable = next(item for item in job["artifacts"] if item["type"] == "location_index_jsonl")
        artifact = call_tool("read_artifact", {"path": readable["path"], "artifact_type": readable["type"]})
        if artifact.get("artifact_type") != "location_index_jsonl" or "text" not in artifact:
            raise AssertionError(f"read_artifact contract failed: {artifact}")
        assert_quality_comparison_artifact_read(tmpdir)

        assert_http_contract(image_dir, tmpdir / "http-out")

    print("Agent contract test passed.")
    return 0


def assert_tools() -> None:
    names = {tool["name"] for tool in tool_schemas()}
    missing = sorted(REQUIRED_TOOLS - names)
    if missing:
        raise AssertionError(f"Missing required tools: {missing}")


def poll_job(job_id: str, *, timeout: float = 20) -> dict[str, Any]:
    deadline = time.time() + timeout
    final: dict[str, Any] | None = None
    while time.time() < deadline:
        final = call_tool("get_job_status", {"job_id": job_id})
        if final.get("status") != "running":
            return final
        time.sleep(0.1)
    raise TimeoutError(f"Timed out waiting for job {job_id}: {final}")


def assert_fields(label: str, payload: dict[str, Any], fields: set[str]) -> None:
    missing = sorted(fields - set(payload))
    if missing:
        raise AssertionError(f"{label} missing fields {missing}: {payload}")


def assert_quality_summary_next_actions(tmpdir: Path) -> None:
    report = tmpdir / "poor-pdf.report.json"
    report.write_text(
        json.dumps(
            {
                "source": str(tmpdir / "poor.pdf"),
                "output": str(tmpdir / "poor.md"),
                "report": str(report),
                "status": "ok",
                "pipeline": "pymupdf4llm",
                "quality": {
                    "level": "poor",
                    "score": 40,
                    "reasons": ["没有 Markdown 标题，章节层级可能缺失"],
                },
                "pdf_preflight": {"complex_layout_likely": True, "reasons": ["complex"]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    result = ConversionResult(
        source=str(tmpdir / "poor.pdf"),
        output=str(tmpdir / "poor.md"),
        status="ok",
        pipeline="pymupdf4llm",
        message="",
        detected_format="PDF",
        duration_seconds=0,
        report=str(report),
    )
    summary = conversion_quality_summary([result])
    review_items = summary.get("review_items") or []
    if not review_items or not review_items[0].get("next_actions"):
        raise AssertionError(f"quality_summary review items must expose next_actions: {summary}")
    action_names = {item.get("action") for item in review_items[0]["next_actions"]}
    if "compare_pdf_pipelines" not in action_names and "rerun" not in action_names:
        raise AssertionError(f"Expected actionable PDF recovery actions: {summary}")


def assert_quality_comparison_artifact_read(tmpdir: Path) -> None:
    comparison = tmpdir / "benchmark-quality-comparison.json"
    comparison.write_text(
        json.dumps({"schema_version": "benchmark-quality-comparison-v1", "summary": {"status": "passed"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    artifact = call_tool("read_artifact", {"path": str(comparison)})
    if artifact.get("artifact_type") != "quality_comparison_json" or (artifact.get("json") or {}).get("schema_version") != "benchmark-quality-comparison-v1":
        raise AssertionError(f"Expected inferred quality comparison JSON artifact: {artifact}")


def assert_environment_report_tool(input_dir: Path, output_dir: Path) -> None:
    result = call_tool(
        "export_environment_report",
        {"input": str(input_dir), "output": str(output_dir), "recursive": False},
    )
    if result.get("status") != "ok":
        raise AssertionError(f"export_environment_report failed: {result}")
    markdown_report = Path(result.get("markdown_report") or "")
    json_report = Path(result.get("json_report") or "")
    lock_report = Path(result.get("lock_report") or "")
    requirements_lock = Path(result.get("requirements_lock") or "")
    if not markdown_report.exists() or not json_report.exists() or not lock_report.exists() or not requirements_lock.exists():
        raise AssertionError(f"export_environment_report must write reports and lock snapshots: {result}")
    artifact_types = {item.get("type") for item in result.get("artifacts", [])}
    if not {"environment_report", "environment_json", "environment_lock", "requirements_lock"}.issubset(artifact_types):
        raise AssertionError(f"Environment report must expose artifacts: {result}")
    readable = call_tool("read_artifact", {"path": str(json_report), "artifact_type": "environment_json"})
    payload = readable.get("json") or {}
    if payload.get("schema_version") != "environment-report-v1":
        raise AssertionError(f"Environment JSON artifact should be parsed: {readable}")
    snapshot = payload.get("version_snapshot") or {}
    package_names = {item.get("name") for item in snapshot.get("python_packages") or []}
    command_names = {item.get("name") for item in snapshot.get("commands") or []}
    if "PyMuPDF" not in package_names or "pandoc" not in command_names or "torch" not in snapshot:
        raise AssertionError(f"Environment report must include package, command, and torch version snapshots: {payload}")
    lock = call_tool("read_artifact", {"path": str(lock_report), "artifact_type": "environment_lock"})
    if (lock.get("json") or {}).get("schema_version") != "environment-lock-v1":
        raise AssertionError(f"Expected parsed environment lock artifact: {lock}")
    if "PyMuPDF" not in requirements_lock.read_text(encoding="utf-8"):
        raise AssertionError(f"Expected requirements lock snapshot to include package pins: {requirements_lock}")
    compare_dir = output_dir / "compare"
    comparison = call_tool("compare_environment_lock", {"lock": str(lock_report), "output": str(compare_dir)})
    if comparison.get("status") != "ok" or comparison.get("severity") not in {"ok", "info"}:
        raise AssertionError(f"Expected stable environment lock comparison: {comparison}")
    compare_json = Path(comparison.get("json_report") or "")
    compare_md = Path(comparison.get("markdown_report") or "")
    if not compare_json.exists() or not compare_md.exists():
        raise AssertionError(f"Expected persisted environment comparison artifacts: {comparison}")
    parsed_compare = call_tool("read_artifact", {"path": str(compare_json), "artifact_type": "environment_lock_compare_json"})
    if (parsed_compare.get("json") or {}).get("schema_version") != "environment-lock-compare-v1":
        raise AssertionError(f"Expected parsed environment comparison JSON: {parsed_compare}")


def assert_pdf_outline_inspection(tmpdir: Path) -> None:
    pdf_path = tmpdir / "outlined.pdf"
    document = fitz.open()
    first = document.new_page()
    first.insert_text((72, 72), "Chapter 1\nOpening text")
    second = document.new_page()
    second.insert_text((72, 72), "Section 1.1\nDetails")
    document.set_toc([[1, "Chapter 1", 1], [2, "Section 1.1", 2]])
    document.save(pdf_path)
    document.close()

    inspection = call_tool("inspect_document", {"input": str(pdf_path)})
    outline = inspection.get("outline") or {}
    if outline.get("count") != 2 or not outline.get("items"):
        raise AssertionError(f"Expected PDF outline preview: {inspection}")
    first_item = outline["items"][0]
    if first_item.get("title") != "Chapter 1" or first_item.get("level") != 1 or first_item.get("page") != 1:
        raise AssertionError(f"Unexpected first outline item: {inspection}")
    if (inspection.get("structure_strategy") or {}).get("mode") != "bookmark_guided_structure_recovery":
        raise AssertionError(f"Expected bookmark-guided structure strategy: {inspection}")


def assert_conversion_report_pdf_outline(tmpdir: Path) -> None:
    pdf_path = tmpdir / "report-outlined.pdf"
    output_path = tmpdir / "report-outlined.md"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Chapter 1\nOpening text")
    document.set_toc([[1, "Chapter 1", 1]])
    document.save(pdf_path)
    document.close()
    output_path.write_text("body without headings", encoding="utf-8")
    result = ConversionResult(
        source=str(pdf_path),
        output=str(output_path),
        status="ok",
        pipeline="pymupdf4llm",
        message="",
        detected_format="PDF",
        duration_seconds=0,
    )
    options = default_options(report_dir=tmpdir / ".reports")
    write_conversion_report(result, options, output_path)
    report = json.loads(Path(result.report).read_text(encoding="utf-8"))
    outline = report.get("pdf_outline") or {}
    if outline.get("count") != 1 or outline.get("items", [{}])[0].get("title") != "Chapter 1":
        raise AssertionError(f"Expected conversion report PDF outline: {report}")
    alignment = report.get("pdf_outline_alignment") or {}
    if alignment.get("status") != "no_markdown_headings" or alignment.get("outline_count") != 1:
        raise AssertionError(f"Expected PDF outline alignment warning: {report}")
    summary = conversion_quality_summary([result])
    actions = summary["review_items"][0].get("next_actions") or []
    if not any(item.get("action") == "inspect_pdf_outline" for item in actions):
        raise AssertionError(f"Expected outline inspection next action: {summary}")
    good_but_unaligned_report = tmpdir / "good-unmatched.report.json"
    good_but_unaligned_report.write_text(
        json.dumps(
            {
                "source": str(pdf_path),
                "output": str(tmpdir / "good-unmatched.md"),
                "status": "ok",
                "pipeline": "pymupdf4llm",
                "quality": {"level": "good", "score": 90, "reasons": []},
                "pdf_outline": {"count": 2, "items": [{"title": "Chapter 1"}, {"title": "Chapter 2"}]},
                "pdf_outline_alignment": {
                    "status": "low_alignment",
                    "outline_count": 2,
                    "markdown_heading_count": 2,
                    "matched_count": 0,
                    "match_ratio": 0.0,
                    "missing": ["Chapter 1", "Chapter 2"],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    good_but_unaligned = ConversionResult(
        source=str(pdf_path),
        output=str(tmpdir / "good-unmatched.md"),
        status="ok",
        pipeline="pymupdf4llm",
        message="",
        detected_format="PDF",
        duration_seconds=0,
        report=str(good_but_unaligned_report),
    )
    unaligned_summary = conversion_quality_summary([good_but_unaligned])
    if unaligned_summary.get("review_count") != 1:
        raise AssertionError(f"Expected low outline alignment to enter quality_summary review queue: {unaligned_summary}")
    unaligned_item = unaligned_summary["review_items"][0]
    if "pdf_outline_alignment" not in unaligned_item or not any(action.get("action") == "inspect_pdf_outline" for action in unaligned_item.get("next_actions") or []):
        raise AssertionError(f"Expected outline alignment next actions: {unaligned_summary}")

    aligned_output = tmpdir / "report-outlined-aligned.md"
    aligned_output.write_text("# Chapter 1\n\nOpening text", encoding="utf-8")
    aligned_result = ConversionResult(
        source=str(pdf_path),
        output=str(aligned_output),
        status="ok",
        pipeline="pymupdf4llm",
        message="",
        detected_format="PDF",
        duration_seconds=0,
    )
    write_conversion_report(aligned_result, options, aligned_output)
    aligned_report = json.loads(Path(aligned_result.report).read_text(encoding="utf-8"))
    aligned = aligned_report.get("pdf_outline_alignment") or {}
    if aligned.get("status") != "ok" or aligned.get("match_ratio") != 1.0:
        raise AssertionError(f"Expected aligned PDF outline headings: {aligned_report}")


def assert_review_decisions_report(tmpdir: Path) -> None:
    output_dir = tmpdir / "decision-out"
    output_dir.mkdir()
    good_md = output_dir / "good.md"
    poor_md = output_dir / "poor.md"
    good_md.write_text("# Good\n\nEnough body text for a simple accepted output.\n" * 30, encoding="utf-8")
    poor_md.write_text("tiny", encoding="utf-8")
    good = ConversionResult(
        source=str(tmpdir / "good.txt"),
        output=str(good_md),
        status="ok",
        pipeline="pandoc",
        message="",
        detected_format="TXT",
        duration_seconds=0,
    )
    poor = ConversionResult(
        source=str(tmpdir / "poor.pdf"),
        output=str(poor_md),
        status="ok",
        pipeline="pymupdf4llm",
        message="",
        detected_format="PDF",
        duration_seconds=0,
    )
    failed = ConversionResult(
        source=str(tmpdir / "failed.pdf"),
        output="",
        status="failed",
        pipeline="mineru",
        message="simulated failure",
        detected_format="PDF",
        duration_seconds=0,
    )
    options = default_options(output=output_dir)
    for result in (good, poor, failed):
        output_path = Path(result.output) if result.output else output_dir / f"{Path(result.source).stem}.md"
        write_conversion_report(result, options, output_path)
    manual_path = output_dir / ".reports" / "manual-review.json"
    manual_path.parent.mkdir(parents=True, exist_ok=True)
    manual_path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "source": good.source,
                        "output": good.output,
                        "human_status": "accepted",
                        "human_score": 95,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    write_batch_summary([good, poor, failed], options)
    decisions_path = output_dir / ".reports" / "review-decisions.json"
    decisions_md = output_dir / ".reports" / "review-decisions.md"
    if not decisions_path.exists() or not decisions_md.exists():
        raise AssertionError("Expected review decision reports to be generated.")
    decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
    decision_counts = decisions.get("counts") or {}
    if decision_counts.get("accept_manual") != 1 or decision_counts.get("failed_retry") != 1:
        raise AssertionError(f"Unexpected review decisions: {decisions}")
    manual_item = next((item for item in decisions.get("items") or [] if item.get("source") == good.source), {})
    if (manual_item.get("manual_review") or {}).get("human_score") != 95:
        raise AssertionError(f"Expected manual review to propagate into decisions: {decisions}")
    if not any(item.get("decision") == "rerun_or_manual_review" for item in decisions.get("items") or []):
        raise AssertionError(f"Expected poor output to require rerun/manual review: {decisions}")
    summary_artifact = call_tool("read_artifact", {"path": str(output_dir / ".reports" / "summary.json")})
    if summary_artifact.get("artifact_type") != "summary_json" or not isinstance(summary_artifact.get("json"), list):
        raise AssertionError(f"Expected parsed summary_json artifact: {summary_artifact}")
    summary_good = next((item for item in summary_artifact.get("json") or [] if item.get("source") == good.source), {})
    if (summary_good.get("manual_review") or {}).get("human_status") != "accepted":
        raise AssertionError(f"Expected manual review to propagate into summary.json: {summary_artifact}")
    decision_artifact = call_tool("read_artifact", {"path": str(decisions_path), "artifact_type": "review_decisions_json"})
    decision_payload = decision_artifact.get("json") or {}
    if decision_payload.get("schema_version") != "review-decisions-v1":
        raise AssertionError(f"Expected parsed review_decisions_json artifact: {decision_artifact}")
    report_artifact = call_tool("read_artifact", {"path": str(poor.report), "artifact_type": "conversion_report"})
    if (report_artifact.get("json") or {}).get("source") != poor.source:
        raise AssertionError(f"Expected parsed conversion_report artifact: {report_artifact}")


def assert_web_archive_route(tmpdir: Path) -> None:
    archive = tmpdir / "web-archive"
    rebuild_input = archive / "rebuild_input"
    rebuild_input.mkdir(parents=True)
    source_md = archive / "source.md"
    source_md.write_text(
        "# Source\n\n| Name | Value |\n|---|---|\n| A | 1 |\n",
        encoding="utf-8",
        newline="\n",
    )
    (rebuild_input / "manifest.json").write_text(
        json.dumps({"inputs": {"source_markdown": str(source_md)}, "image_assets": []}, ensure_ascii=False),
        encoding="utf-8",
        newline="\n",
    )

    inspection = call_tool("inspect_document", {"input": str(archive)})
    if inspection.get("kind") != "web_archive" or inspection.get("recommendation") != "process_web_archive_visual_check":
        raise AssertionError(f"Expected web archive inspection: {inspection}")

    routed = call_tool("process_material", {"input": str(archive), "output": str(tmpdir / "ignored-output")})
    if routed.get("route") != "process_web_archive" or routed.get("status") != "routed":
        raise AssertionError(f"Expected process_material to route web archive: {routed}")
    delegated = routed.get("delegated") or {}
    if delegated.get("status") != "pending_visual_engine":
        raise AssertionError(f"Expected pending visual-check contract without screenshot: {routed}")
    artifact_types = {item.get("type") for item in delegated.get("artifacts") or []}
    if not {"visual_check_json", "markdown", "table_candidates_json"}.issubset(artifact_types):
        raise AssertionError(f"Expected web archive visual artifacts: {delegated}")
    visual_check = archive / "visual_check" / "visual_check_result.json"
    if not visual_check.exists():
        raise AssertionError(f"Expected visual_check_result.json under archive: {routed}")
    readable = call_tool("read_artifact", {"path": str(visual_check), "artifact_type": "visual_check_json"})
    if (readable.get("json") or {}).get("schema_version") != 1:
        raise AssertionError(f"Expected parsed visual_check_json artifact: {readable}")


def assert_http_contract(input_path: Path, output_path: Path) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), build_handler(""))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        health = http_json(base + "/health")
        if not health.get("supports_async_jobs") or not health.get("supports_artifacts"):
            raise AssertionError(f"HTTP health missing capability flags: {health}")

        ok = http_json(
            base + "/call",
            payload={
                "name": "process_material",
                "arguments": {
                    "input": str(input_path),
                    "output": str(output_path),
                    "recursive": False,
                    "ocr": "never",
                },
            },
        )
        if ok.get("ok") is not True or not isinstance(ok.get("result"), dict) or ok.get("route") != "start_location_index":
            raise AssertionError(f"HTTP ok envelope failed: {ok}")
        http_job = http_poll_job(base, str(ok.get("job_id")))
        if http_job.get("status") != "done":
            raise AssertionError(f"HTTP async job did not finish: {http_job}")

        invalid = http_json(base + "/call", payload={"name": "missing_contract_tool", "arguments": {}}, allow_http_error=True)
        assert_fields("HTTP error", invalid, ERROR_FIELDS)
        if invalid["code"] != "invalid_request" or invalid["retryable"] is not False or invalid["schema_version"] != SCHEMA_VERSION:
            raise AssertionError(f"HTTP error contract failed: {invalid}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def http_poll_job(base: str, job_id: str, *, timeout: float = 20) -> dict[str, Any]:
    deadline = time.time() + timeout
    final: dict[str, Any] | None = None
    while time.time() < deadline:
        final = http_json(base + "/call", payload={"name": "get_job_status", "arguments": {"job_id": job_id}})
        if final.get("status") != "running":
            return final
        time.sleep(0.1)
    raise TimeoutError(f"Timed out waiting for HTTP job {job_id}: {final}")


def http_json(url: str, payload: dict[str, Any] | None = None, *, allow_http_error: bool = False) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json; charset=utf-8"} if payload is not None else {}
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if allow_http_error:
            return json.loads(exc.read().decode("utf-8", errors="replace"))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
