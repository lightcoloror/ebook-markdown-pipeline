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
    "get_job_status",
    "read_artifact",
    "inspect_document",
    "scan_books",
    "health_check",
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

        inspection = call_tool("inspect_document", {"input": str(image_dir), "recursive": False})
        assert_fields("inspect_document", inspection, INSPECTION_FIELDS)
        if not isinstance(inspection.get("next_actions"), list) or "mode" not in inspection.get("structure_strategy", {}):
            raise AssertionError(f"inspect_document must expose structure strategy and next actions: {inspection}")
        assert_pdf_outline_inspection(tmpdir)
        assert_conversion_report_pdf_outline(tmpdir)
        assert_review_decisions_report(tmpdir)

        assert_quality_summary_next_actions(tmpdir)

        readable = next(item for item in job["artifacts"] if item["type"] == "location_index_jsonl")
        artifact = call_tool("read_artifact", {"path": readable["path"], "artifact_type": readable["type"]})
        if artifact.get("artifact_type") != "location_index_jsonl" or "text" not in artifact:
            raise AssertionError(f"read_artifact contract failed: {artifact}")

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
    summary = conversion_quality_summary([result])
    actions = summary["review_items"][0].get("next_actions") or []
    if not any(item.get("action") == "inspect_pdf_outline" for item in actions):
        raise AssertionError(f"Expected outline inspection next action: {summary}")


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
    write_batch_summary([good, poor, failed], options)
    decisions_path = output_dir / ".reports" / "review-decisions.json"
    decisions_md = output_dir / ".reports" / "review-decisions.md"
    if not decisions_path.exists() or not decisions_md.exists():
        raise AssertionError("Expected review decision reports to be generated.")
    decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
    decision_counts = decisions.get("counts") or {}
    if decision_counts.get("accept") != 1 or decision_counts.get("failed_retry") != 1:
        raise AssertionError(f"Unexpected review decisions: {decisions}")
    if not any(item.get("decision") == "rerun_or_manual_review" for item in decisions.get("items") or []):
        raise AssertionError(f"Expected poor output to require rerun/manual review: {decisions}")


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

        invalid = http_json(base + "/call", payload={"name": "missing_contract_tool", "arguments": {}}, allow_http_error=True)
        assert_fields("HTTP error", invalid, ERROR_FIELDS)
        if invalid["code"] != "invalid_request" or invalid["retryable"] is not False or invalid["schema_version"] != SCHEMA_VERSION:
            raise AssertionError(f"HTTP error contract failed: {invalid}")
    finally:
        server.shutdown()


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
