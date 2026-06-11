from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.batch_convert_books import (  # noqa: E402
    build_review_checklist_entries,
    render_review_checklist_markdown,
)


def main() -> int:
    source = "sample.pdf"
    report = "sample.report.json"
    output = "sample.md"
    entries = [
        {
            "source": source,
            "output": output,
            "report": report,
            "status": "ok",
            "pipeline": "pymupdf4llm",
            "quality": {"level": "good", "score": 95, "reasons": []},
            "pdf_preflight": {"scanned_likely": False, "complex_layout_likely": False, "reasons": []},
            "pdf_outline": {},
            "pdf_outline_alignment": {},
            "pdf_layout_diagnostics": {
                "status": "ok",
                "summary": {
                    "table_pages": [2, 5],
                    "two_column_pages": [3],
                    "image_heavy_pages": [],
                    "repeated_header_footer_candidates": [{"text": "Header", "count": 3}],
                    "table_artifact_count": 1,
                    "camelot_available": False,
                },
            },
        }
    ]

    checklist = build_review_checklist_entries(entries)
    if len(checklist) != 1:
        raise AssertionError(f"Expected layout diagnostics to create one review item: {checklist}")
    item = checklist[0]
    reasons = " ".join(item.get("pdf_layout_reasons") or [])
    if "疑似表格页" not in reasons or "疑似双栏页" not in reasons or "疑似重复页眉页脚" not in reasons:
        raise AssertionError(f"Expected layout reasons in review item: {item}")
    action_names = {action.get("action") for action in item.get("next_actions") or []}
    expected_actions = {"inspect_table_diagnostics", "compare_pdf_pipelines", "inspect_noise"}
    if not expected_actions.issubset(action_names):
        raise AssertionError(f"Missing layout next_actions. Expected {expected_actions}, got {action_names}: {item}")
    if any(action.get("action") == "extract_pdf_tables" for action in item.get("next_actions") or []):
        raise AssertionError(f"Camelot action should not be suggested when camelot_available=false: {item}")
    if "表格" not in str(item.get("suggested_action") or ""):
        raise AssertionError(f"Expected table-oriented suggested action: {item}")

    with tempfile.TemporaryDirectory(prefix="ebook-layout-review-") as tmp:
        markdown = render_review_checklist_markdown(checklist, Path(tmp) / "checklist.json")
    if "疑似表格页" not in markdown or "inspect_table_diagnostics" not in markdown:
        raise AssertionError(f"Rendered checklist should include layout signals and actions: {markdown}")

    print("PDF layout review checklist test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
