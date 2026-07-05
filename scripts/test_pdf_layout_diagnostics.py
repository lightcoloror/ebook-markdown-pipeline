from __future__ import annotations

import json
import sys
import tempfile
import types
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

import ebook_markdown_pipeline.pdf_layout_diagnostics as diagnostics  # noqa: E402
from ebook_markdown_pipeline.ebook_converter_mcp import read_artifact  # noqa: E402
from ebook_markdown_pipeline.pdf_layout_diagnostics import analyze_pdf_layout_with_pdfplumber, build_pdf_layout_evidence, build_table_candidates, extract_tables_with_camelot, extract_tables_with_tabula, pdfplumber_available  # noqa: E402


def make_text_pdf(path: Path) -> None:
    import pymupdf

    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 72), "Header")
    page.insert_text((72, 140), "Name    Amount    Date")
    page.insert_text((72, 165), "Alpha   100       2026-01-01")
    page.insert_text((72, 190), "Beta    200       2026-01-02")
    page.insert_text((72, 780), "Footer")
    document.save(path)
    document.close()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ebook-pdf-layout-diagnostics-") as tmp:
        tmpdir = Path(tmp)
        pdf = tmpdir / "sample.pdf"
        out = tmpdir / "tables"
        make_text_pdf(pdf)

        result = analyze_pdf_layout_with_pdfplumber(pdf, sample_pages=1, output_dir=out)
        if not pdfplumber_available():
            if result.get("status") != "missing_dependency":
                raise AssertionError(f"Missing pdfplumber should be reported clearly: {result}")
            return 0

        if result.get("status") != "ok":
            raise AssertionError(f"pdfplumber diagnostics should succeed for a simple PDF: {result}")
        if not result.get("pages") or result["pages"][0].get("text_chars", 0) <= 0:
            raise AssertionError(f"Expected page text diagnostics: {result}")
        diagnostics_json = out / "table-diagnostics.json"
        if not diagnostics_json.exists():
            raise AssertionError("Expected table-diagnostics.json artifact.")
        evidence_json = out / "pdf-layout-evidence.json"
        if not evidence_json.exists():
            raise AssertionError("Expected pdf-layout-evidence.json artifact.")
        table_candidates_json = out / "table-candidates.json"
        if not table_candidates_json.exists():
            raise AssertionError("Expected table-candidates.json artifact.")
        persisted = json.loads(diagnostics_json.read_text(encoding="utf-8"))
        if persisted.get("status") != "ok" or "summary" not in persisted:
            raise AssertionError(f"Unexpected persisted diagnostics: {persisted}")
        if not persisted.get("pdf_layout_evidence_artifact") or persisted.get("pdf_layout_evidence", {}).get("schema_version") != "pdf-layout-evidence-v1":
            raise AssertionError(f"Expected diagnostics to reference layout evidence: {persisted}")
        if not persisted.get("table_candidates_artifact") or persisted.get("table_candidates", {}).get("schema_version") != "table-candidates-v1":
            raise AssertionError(f"Expected diagnostics to reference table candidates: {persisted}")
        evidence = json.loads(evidence_json.read_text(encoding="utf-8"))
        if evidence.get("schema_version") != "pdf-layout-evidence-v1" or evidence.get("backend") != "pdfplumber":
            raise AssertionError(f"Unexpected layout evidence payload: {evidence}")
        readable_evidence = read_artifact({"path": str(evidence_json)})
        evidence_summary = readable_evidence.get("summary") or {}
        if evidence_summary.get("kind") != "pdf_layout_evidence" or evidence_summary.get("backend") != "pdfplumber":
            raise AssertionError(f"Expected read_artifact layout evidence summary: {readable_evidence}")
        table_candidates = json.loads(table_candidates_json.read_text(encoding="utf-8"))
        if table_candidates.get("schema_version") != "table-candidates-v1" or table_candidates.get("backend") != "pdf_layout_diagnostics":
            raise AssertionError(f"Unexpected table candidates payload: {table_candidates}")
        readable_tables = read_artifact({"path": str(table_candidates_json)})
        table_summary = readable_tables.get("summary") or {}
        if table_summary.get("kind") != "table_candidates_json" or table_summary.get("candidate_schema_known") is not True:
            raise AssertionError(f"Expected read_artifact table candidates summary: {readable_tables}")
        synthetic_evidence = build_pdf_layout_evidence(
            source=pdf,
            status="ok",
            pages=[{"page": 1, "text_chars": 30, "line_count": 2, "table_count": 1, "image_count": 1, "two_column_likely": True}],
            summary={"table_pages": [1], "two_column_pages": [1], "image_heavy_pages": [1], "repeated_header_footer_candidates": [{"text": "Header", "count": 2}]},
        )
        flags = synthetic_evidence.get("flags") or {}
        if not flags.get("table_heavy_suspected") or not flags.get("layout_heavy_suspected") or not flags.get("repeated_header_footer_suspected"):
            raise AssertionError(f"Expected synthetic pdfplumber evidence flags: {synthetic_evidence}")

        camelot_out = tmpdir / "camelot"
        original_available = diagnostics.camelot_available
        original_module = sys.modules.get("camelot")
        diagnostics.camelot_available = lambda: True
        sys.modules["camelot"] = fake_camelot_module()
        try:
            camelot_result = extract_tables_with_camelot(pdf, output_dir=camelot_out, candidate_pages=[1], max_tables=5)
        finally:
            diagnostics.camelot_available = original_available
            if original_module is None:
                sys.modules.pop("camelot", None)
            else:
                sys.modules["camelot"] = original_module
        if camelot_result.get("status") != "ok" or not camelot_result.get("table_artifacts"):
            raise AssertionError(f"Expected fake Camelot table artifacts: {camelot_result}")
        artifact = camelot_result["table_artifacts"][0]
        if not Path(artifact["csv"]).exists() or not Path(artifact["markdown"]).exists():
            raise AssertionError(f"Expected Camelot CSV/Markdown artifacts: {artifact}")
        if "Revenue" not in Path(artifact["markdown"]).read_text(encoding="utf-8"):
            raise AssertionError(f"Expected Camelot Markdown table content: {artifact}")

        tabula_out = tmpdir / "tabula"
        original_tabula_available = diagnostics.tabula_available
        original_tabula_module = sys.modules.get("tabula")
        diagnostics.tabula_available = lambda: True
        sys.modules["tabula"] = fake_tabula_module()
        try:
            tabula_result = extract_tables_with_tabula(pdf, output_dir=tabula_out, candidate_pages=[1], max_tables=5)
        finally:
            diagnostics.tabula_available = original_tabula_available
            if original_tabula_module is None:
                sys.modules.pop("tabula", None)
            else:
                sys.modules["tabula"] = original_tabula_module
        if tabula_result.get("status") != "ok" or not tabula_result.get("table_artifacts"):
            raise AssertionError(f"Expected fake Tabula table artifacts: {tabula_result}")
        tabula_artifact = tabula_result["table_artifacts"][0]
        if not Path(tabula_artifact["csv"]).exists() or not Path(tabula_artifact["markdown"]).exists():
            raise AssertionError(f"Expected Tabula CSV/Markdown artifacts: {tabula_artifact}")
        if "Expenses" not in Path(tabula_artifact["markdown"]).read_text(encoding="utf-8"):
            raise AssertionError(f"Expected Tabula Markdown table content: {tabula_artifact}")
        combined_candidates = build_table_candidates(
            source=pdf,
            table_artifacts=[{"page": 1, "table_number": 1, "rows": 2, "csv": "pdfplumber.csv", "markdown": "pdfplumber.md"}],
            camelot_diagnostics=camelot_result,
            tabula_diagnostics=tabula_result,
        )
        combined_summary = read_artifact_payload_summary(combined_candidates)
        combined_backends = {table.get("backend") for page in combined_candidates.get("pages") or [] for table in page.get("tables") or []}
        if combined_summary.get("table_count") != 3 or combined_backends != {"camelot", "pdfplumber", "tabula"}:
            raise AssertionError(f"Expected combined table candidates from three backends: {combined_candidates}")

    print("PDF layout diagnostics test passed.")
    return 0



def read_artifact_payload_summary(payload: dict) -> dict:
    from ebook_markdown_pipeline.candidate_artifact_schema import summarize_candidate_artifact

    return summarize_candidate_artifact(payload, "table_candidates_json")

def fake_camelot_module():
    class FakeValues:
        def tolist(self):
            return [["Metric", "Q1"], ["Revenue", "120"]]

    class FakeDataFrame:
        values = FakeValues()

    class FakeTable:
        page = 1
        df = FakeDataFrame()
        accuracy = 99.2
        whitespace = 3.1

    def read_pdf(source: str, *, pages: str, flavor: str):
        if pages != "1" or flavor != "stream":
            raise AssertionError(f"Unexpected Camelot call: {source}, {pages}, {flavor}")
        return [FakeTable()]

    return types.SimpleNamespace(read_pdf=read_pdf)


def fake_tabula_module():
    class FakeValues:
        def tolist(self):
            return [["Metric", "Q2"], ["Expenses", "80"]]

    class FakeDataFrame:
        values = FakeValues()

    def read_pdf(source: str, *, pages: str, multiple_tables: bool, stream: bool, lattice: bool):
        if pages != "1" or not multiple_tables or not stream or lattice:
            raise AssertionError(f"Unexpected Tabula call: {source}, {pages}, {multiple_tables}, {stream}, {lattice}")
        return [FakeDataFrame()]

    return types.SimpleNamespace(read_pdf=read_pdf)


if __name__ == "__main__":
    raise SystemExit(main())
