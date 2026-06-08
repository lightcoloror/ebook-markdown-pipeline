from __future__ import annotations

import sys
import tempfile
from types import SimpleNamespace
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.batch_convert_books import ConversionResult, write_conversion_report  # noqa: E402
from ebook_markdown_pipeline.structure_repair import repair_markdown_structure  # noqa: E402


def main() -> int:
    source = (
        "## 保险责任\n\n"
        "第五条 在保险期间内，被保险人于旅游期间因遭受意外伤害（亦简称“意外”）而身故或者伤残的，保险人按下列约定承担保险责任：\n\n"
        "（一）旅游意外身故\n\n"
        "被保险人自遭受该意外之日起一百八十日内以该意外为直接、完全原因而身故。\n\n"
        "## （二）旅游意外伤残\n\n"
        "被保险人自遭受该意外之日起一百八十日内以该意外为直接、完全原因而致伤残。\n\n"
        "## 责任免除\n\n"
        "第六条 由于下列任何原因造成被保险人身故或者伤残的，保险人不承担给付保险金的责任：\n\n"
        "（一）投保人的故意行为；\n\n"
        "普通正文（不是标题）仍然保留。\n"
    )
    result = repair_markdown_structure(source, source_kind="pdf")
    markdown = result.markdown
    if "### 第五条 在保险期间内" not in markdown:
        raise AssertionError(f"Expected 第五条 as article heading:\n{markdown}")
    if "#### （一）旅游意外身故" not in markdown or "#### （二）旅游意外伤残" not in markdown:
        raise AssertionError(f"Expected numbered clauses under 第五条:\n{markdown}")
    if "### 第六条 由于下列任何原因" not in markdown:
        raise AssertionError(f"Expected 第六条 as article heading:\n{markdown}")
    if "#### （一）投保人的故意行为；" in markdown:
        raise AssertionError(f"Expected semicolon-ended list item not to be promoted:\n{markdown}")
    report = result.report()
    decisions = report.get("decisions") or []
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
    print("Structure repair smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
