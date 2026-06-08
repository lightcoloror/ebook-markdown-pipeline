from __future__ import annotations

import sys
import tempfile
from types import SimpleNamespace
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.batch_convert_books import (  # noqa: E402
    ConversionResult,
    mineru_heading_candidates_from_artifacts,
    pdf_outline_heading_candidates,
    pymupdf_font_heading_candidates,
    write_conversion_report,
)
from ebook_markdown_pipeline.docling_backend import extract_docling_heading_candidates  # noqa: E402
from ebook_markdown_pipeline.structure_repair import HeadingCandidate, repair_markdown_structure  # noqa: E402


def main() -> int:
    source = (
        "第一章 总则\n\n"
        "第一节 保险责任\n\n"
        "第五条 在保险期间内，被保险人于旅游期间因遭受意外伤害（亦简称“意外”）而身故或者伤残的，保险人按下列约定承担保险责任：\n\n"
        "（一）旅游意外身故\n\n"
        "被保险人自遭受该意外之日起一百八十日内以该意外为直接、完全原因而身故。\n\n"
        "## （二）旅游意外伤残\n\n"
        "1. 伤残等级\n\n"
        "伤残等级依照相关标准确定。\n\n"
        "（1）一级伤残\n\n"
        "一级伤残按照约定比例给付。\n\n"
        "被保险人自遭受该意外之日起一百八十日内以该意外为直接、完全原因而致伤残。\n\n"
        "## 责任免除\n\n"
        "第六条 由于下列任何原因造成被保险人身故或者伤残的，保险人不承担给付保险金的责任：\n\n"
        "（一）投保人的故意行为；\n\n"
        "普通正文（不是标题）仍然保留。\n"
    )
    result = repair_markdown_structure(source, source_kind="pdf")
    markdown = result.markdown
    if "# 第一章 总则" not in markdown or "## 第一节 保险责任" not in markdown:
        raise AssertionError(f"Expected chapter/section hierarchy:\n{markdown}")
    if "### 第五条 在保险期间内" not in markdown:
        raise AssertionError(f"Expected 第五条 as article heading:\n{markdown}")
    if "#### （一）旅游意外身故" not in markdown or "#### （二）旅游意外伤残" not in markdown:
        raise AssertionError(f"Expected numbered clauses under 第五条:\n{markdown}")
    if "##### 1. 伤残等级" not in markdown or "###### （1）一级伤残" not in markdown:
        raise AssertionError(f"Expected item/sub-item hierarchy under clause:\n{markdown}")
    if "### 第六条 由于下列任何原因" not in markdown:
        raise AssertionError(f"Expected 第六条 as article heading:\n{markdown}")
    if "#### （一）投保人的故意行为；" in markdown:
        raise AssertionError(f"Expected semicolon-ended list item not to be promoted:\n{markdown}")
    report = result.report()
    if report.get("grammar") != "chapter_section_article_clause_item_subitem":
        raise AssertionError(f"Expected grammar name in report: {report}")
    candidate_sources = report.get("candidate_sources") or {}
    for expected_source in ("domain_grammar:chapter", "domain_grammar:section", "domain_grammar:article", "domain_grammar:parenthesized_clause"):
        if candidate_sources.get(expected_source, 0) < 1:
            raise AssertionError(f"Expected domain heading candidates in report: {report}")
    outline = report.get("inferred_outline") or []
    subitem = next((item for item in outline if item.get("title") == "（1）一级伤残"), None)
    if not subitem:
        raise AssertionError(f"Expected inferred outline to include subitem: {report}")
    expected_path = ["第一章 总则", "第一节 保险责任", "第五条 在保险期间内，被保险人于旅游期间因遭受意外伤害（亦简称“意外”）而身故或者伤残的，保险人按下列约定承担保险责任：", "（二）旅游意外伤残", "1. 伤残等级", "（1）一级伤残"]
    if subitem.get("path") != expected_path:
        raise AssertionError(f"Expected full hierarchy path, got {subitem}")
    decisions = report.get("decisions") or []
    if not all(item.get("action") and isinstance(item.get("confidence"), float) for item in decisions):
        raise AssertionError(f"Expected every structure decision to expose action and confidence: {report}")
    if report.get("action_counts", {}).get("promoted_to_heading", 0) < 1:
        raise AssertionError(f"Expected promoted heading count in report: {report}")
    fifth_children = [
        item
        for item in decisions
        if item.get("parent", "").startswith("第五条") and item.get("kind") == "parenthesized_clause"
    ]
    if len(fifth_children) != 2:
        raise AssertionError(f"Expected two child heading decisions under 第五条: {report}")
    reason_text = "\n".join(str(item.get("reason") or "") for item in fifth_children)
    if "nearest article parent" not in reason_text or "####" not in reason_text:
        raise AssertionError(f"Expected report reason to explain parent/level: {report}")
    with tempfile.TemporaryDirectory(prefix="structure-repair-report-") as tmp:
        root = Path(tmp)
        source_path = root / "source.txt"
        output_path = root / "source.md"
        report_dir = root / ".reports"
        source_path.write_text("source", encoding="utf-8")
        output_path.write_text(markdown, encoding="utf-8", newline="\n")
        args = SimpleNamespace(
            no_reports=False,
            report_dir=report_dir,
            _structure_repair_reports={str(output_path): report},
        )
        result_record = ConversionResult(
            source=str(source_path),
            output=str(output_path),
            status="ok",
            pipeline="test",
            message="",
            detected_format="TXT",
        )
        write_conversion_report(result_record, args, output_path)
        report_path = Path(result_record.report or "")
        if not report_path.exists():
            raise AssertionError("Expected conversion report to be written.")
        payload = __import__("json").loads(report_path.read_text(encoding="utf-8"))
    if not payload.get("structure_repair", {}).get("decisions"):
        raise AssertionError(f"Expected structure repair decisions in conversion report: {payload}")
    first_report_decision = payload["structure_repair"]["decisions"][0]
    if "confidence" not in first_report_decision or "action" not in first_report_decision:
        raise AssertionError(f"Expected persisted structure repair explanation fields: {payload}")
    candidate_source = (
        "正文开始\n\n"
        "特别约定\n\n"
        "这里是特别约定的正文内容，足够长，可以证明上一行不是孤立噪声。\n"
    )
    candidate_result = repair_markdown_structure(
        candidate_source,
        source_kind="pdf",
        heading_candidates=[
            HeadingCandidate(
                title="特别约定",
                level=2,
                source="pymupdf_font_jump",
                page=3,
                bbox=[10, 20, 200, 40],
                font_size=16,
                font="SimHei-Bold",
                score=0.88,
                reason="font size 16.0 vs body median 10.5",
            )
        ],
    )
    if "## 特别约定" not in candidate_result.markdown:
        raise AssertionError(f"Expected external font candidate to promote heading:\n{candidate_result.markdown}")
    candidate_report = candidate_result.report()
    if candidate_report.get("candidate_sources", {}).get("pymupdf_font_jump") != 1:
        raise AssertionError(f"Expected candidate source count in report: {candidate_report}")
    if "font_size:16" not in "\n".join(candidate_result.decisions[0].signals):
        raise AssertionError(f"Expected font signal in decision: {candidate_result.decisions[0]}")
    if candidate_result.report()["decisions"][0]["confidence"] < 0.85:
        raise AssertionError(f"Expected high confidence from font candidate score: {candidate_result.report()}")
    try:
        import pymupdf
    except Exception:
        pymupdf = None
    if pymupdf is not None:
        with tempfile.TemporaryDirectory(prefix="structure-repair-pdf-") as tmp:
            pdf_path = Path(tmp) / "font-outline.pdf"
            doc = pymupdf.open()
            page = doc.new_page()
            page.insert_text((72, 72), "Chapter One", fontsize=22, fontname="helv")
            page.insert_text(
                (72, 116),
                "This paragraph is deliberately long enough to establish the body font size baseline.",
                fontsize=10,
                fontname="helv",
            )
            doc.set_toc([[1, "Bookmarked Chapter", 1]])
            doc.save(str(pdf_path))
            doc.close()
            outline_candidates = pdf_outline_heading_candidates(pdf_path)
            if not any(item.title == "Bookmarked Chapter" and item.source == "pdf_outline" for item in outline_candidates):
                raise AssertionError(f"Expected PDF outline candidate: {outline_candidates}")
            font_candidates = pymupdf_font_heading_candidates(pdf_path, max_pages=1)
            if not any(item.title == "Chapter One" and item.source == "pymupdf_font_jump" for item in font_candidates):
                raise AssertionError(f"Expected PyMuPDF font heading candidate: {font_candidates}")
    with tempfile.TemporaryDirectory(prefix="structure-repair-mineru-") as tmp:
        artifact_root = Path(tmp)
        middle_json = artifact_root / "sample_middle.json"
        middle_json.write_text(
            __import__("json").dumps(
                {
                    "pdf_info": [
                        {
                            "page_size": [600, 800],
                            "para_blocks": [
                                {
                                    "type": "paragraph_title",
                                    "bbox": [40, 80, 300, 110],
                                    "lines": [{"spans": [{"content": "（一）旅游意外身故"}]}],
                                }
                            ],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        mineru_candidates = mineru_heading_candidates_from_artifacts(artifact_root)
        if not any(item.title == "（一）旅游意外身故" and item.source == "mineru_paragraph_title" for item in mineru_candidates):
            raise AssertionError(f"Expected MinerU paragraph title candidate: {mineru_candidates}")

    class FakeDoclingDocument:
        def model_dump(self):
            return {
                "texts": [
                    {
                        "label": "section_header",
                        "text": "特别约定",
                        "level": 2,
                        "prov": [{"page_no": 2, "bbox": {"l": 10, "t": 20, "r": 200, "b": 44}}],
                    }
                ]
            }

    docling_candidates = extract_docling_heading_candidates(FakeDoclingDocument())
    if not any(item.get("title") == "特别约定" and item.get("source") == "docling_heading" for item in docling_candidates):
        raise AssertionError(f"Expected Docling heading candidate: {docling_candidates}")
    print("Structure repair smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
