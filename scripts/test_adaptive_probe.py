from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

import fitz


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT.parent))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from ebook_markdown_pipeline.adaptive_probe import build_adaptive_pdf_probe_plan, execute_adaptive_pdf_probe_plan
from ebook_markdown_pipeline import ebook_converter_mcp as mcp
from compare_pipelines import render_comparison_markdown, select_comparison_winner


def comparison(pipeline: str, score: float, *, actual: str = "", headings: int = 3, page_noise: int = 0) -> dict:
    return {
        "pipeline": pipeline,
        "actual_pipeline": actual or pipeline,
        "status": "ok",
        "output": f"{pipeline}.md",
        "duration_seconds": 1.0,
        "metrics": {
            "score": score,
            "headings": headings,
            "characters": 1000,
            "table_like_lines": 0,
            "page_number_lines": page_noise,
        },
    }


def main() -> int:
    selected = select_comparison_winner(
        [comparison("pymupdf4llm", 72), comparison("mineru", 88)],
        minimum_score=80,
        selection_profile="best_quality",
    )
    assert selected["winner_pipeline"] == "mineru"
    assert selected["auto_accept"] is True
    assert selected["confidence"] == "high"

    close = select_comparison_winner(
        [comparison("pymupdf4llm", 82), comparison("mineru", 83)],
        minimum_score=80,
        selection_profile="best_quality",
    )
    assert close["status"] == "review_required"
    assert close["auto_accept"] is False

    fallback = select_comparison_winner(
        [comparison("docling", 90, actual="pymupdf4llm(fallback from docling)")],
        minimum_score=80,
        selection_profile="best_quality",
    )
    assert fallback["winner_pipeline"] == "pymupdf4llm"
    assert fallback["auto_accept"] is False

    markdown = render_comparison_markdown(
        {
            "source": "sample.pdf",
            "original_source": "sample.pdf",
            "created_at": "now",
            "page_ranges": "1,3",
            "pipeline_timeout_seconds": 30,
            "final": True,
            "preflight": {},
            "comparisons": [comparison("mineru", 88)],
            "selection": selected,
        }
    )
    assert markdown.index("| mineru |") < markdown.index("## Automatic Selection")

    with tempfile.TemporaryDirectory(prefix="adaptive-probe-", dir=PROJECT_ROOT) as temp_value:
        temp = Path(temp_value)
        source = temp / "sample.pdf"
        with fitz.open() as document:
            for index in range(6):
                page = document.new_page()
                page.insert_text((72, 72), f"Chapter {index + 1}", fontsize=18)
                page.insert_text((72, 110), "A public synthetic fixture with enough text for comparison. " * 8)
            document.save(source)

        plan = build_adaptive_pdf_probe_plan(
            source,
            temp / "out",
            pipelines=["pymupdf4llm"],
            pipeline_timeout=30,
        )
        assert plan["schema_version"] == "adaptive-pdf-probe-plan-v1"
        assert plan["status"] == "ready"
        assert plan["pipelines"] == ["pymupdf4llm"]
        assert plan["representative_pages"]
        assert "--page-ranges" in plan["command"]
        assert plan["safety"]["remote_calls_allowed"] is False

        tool_plan = mcp.call_tool(
            "prepare_adaptive_pdf_probe",
            {
                "input": str(source),
                "output": str(temp / "tool-out"),
                "pipelines": ["pymupdf4llm"],
                "pipeline_timeout": 30,
            },
        )
        assert tool_plan["status"] == "ready"
        assert tool_plan["pipelines"] == ["pymupdf4llm"]

        started = mcp.call_tool(
            "start_adaptive_pdf_probe",
            {
                "input": str(source),
                "output": str(temp / "mcp-out"),
                "pipelines": ["pymupdf4llm"],
                "pipeline_timeout": 30,
            },
        )
        deadline = time.monotonic() + 45
        mcp_job = started
        while mcp_job.get("status") == "running" and time.monotonic() < deadline:
            time.sleep(0.1)
            mcp_job = mcp.call_tool("get_job_status", {"job_id": started["job_id"]})
        assert mcp_job["status"] == "done", mcp_job
        assert mcp_job["quality_summary"]["winner_pipeline"] == "pymupdf4llm"

        result = execute_adaptive_pdf_probe_plan(plan)
        assert result["schema_version"] == "adaptive-pdf-probe-result-v1", result
        assert result["status"] == "ok", result
        comparison_path = Path(plan["expected_artifacts"]["comparison_json"])
        assert comparison_path.is_file()
        payload = json.loads(comparison_path.read_text(encoding="utf-8"))
        assert payload["page_ranges"] == plan["page_ranges"]
        assert payload["selection"]["winner_pipeline"] == "pymupdf4llm"
        assert any(item["type"] == "pdf_pipeline_comparison_json" for item in result["artifacts"])
        read_result = mcp.call_tool(
            "read_artifact",
            {"path": str(comparison_path), "artifact_type": "pdf_pipeline_comparison_json"},
        )
        assert read_result["summary"]["kind"] == "pdf_pipeline_comparison"
        assert read_result["summary"]["selection"]["winner_pipeline"] == "pymupdf4llm"

        original_start_probe = mcp.start_adaptive_pdf_probe
        try:
            mcp.start_adaptive_pdf_probe = lambda unused: {
                "job_id": "job-probe-test",
                "status": "running",
                "artifacts": [],
                "warnings": [],
                "errors": [],
            }
            routed = mcp.call_tool(
                "process_material",
                {
                    "input": str(source),
                    "output": str(temp / "routed-out"),
                    "routing_profile": "best_quality",
                    "adaptive_probe_max_pipelines": 1,
                },
            )
        finally:
            mcp.start_adaptive_pdf_probe = original_start_probe
        assert routed["route"] == "start_adaptive_pdf_probe"
        assert routed["job_id"] == "job-probe-test"

    print("adaptive probe tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
