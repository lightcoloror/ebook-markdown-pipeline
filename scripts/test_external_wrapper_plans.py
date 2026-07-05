from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.batch_convert_books import default_options, dependency_health_report, environment_capability_summary  # noqa: E402
from ebook_markdown_pipeline.ebook_converter_mcp import read_artifact  # noqa: E402
from ebook_markdown_pipeline.scripts.tesseract_ocr_worker import parse_tesseract_tsv  # noqa: E402


def run_script(script_name: str, output_dir: Path, extra_args: list[str] | None = None) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    input_file = output_dir / "sample.pdf"
    input_file.write_bytes(b"%PDF-1.4\n% fake input\n%%EOF\n")
    command = [
        sys.executable,
        str(PROJECT_DIR / "scripts" / script_name),
        "--input",
        str(input_file),
        "--output",
        str(output_dir / script_name.replace(".py", "")),
        *(extra_args or []),
    ]
    completed = subprocess.run(command, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
    if completed.returncode != 0:
        raise AssertionError(f"{script_name} failed:\nSTDOUT={completed.stdout}\nSTDERR={completed.stderr}")
    return json.loads(completed.stdout)


def assert_result(payload: dict, backend: str, mode: str, min_artifacts: int = 0) -> None:
    if payload.get("schema_version") != "external-wrapper-result-v1":
        raise AssertionError(f"Unexpected schema for {backend}: {payload}")
    if payload.get("backend") != backend:
        raise AssertionError(f"Unexpected backend for {backend}: {payload}")
    if payload.get("mode") != mode:
        raise AssertionError(f"Unexpected mode for {backend}: {payload}")
    if len(payload.get("artifacts") or []) < min_artifacts:
        raise AssertionError(f"Expected at least {min_artifacts} artifacts for {backend}: {payload}")
    result_path = Path(payload["output_dir"]) / "external-wrapper-result.json"
    if not result_path.exists():
        raise AssertionError(f"Expected persisted result for {backend}: {result_path}")



def assert_health_integration() -> None:
    checks = dependency_health_report([], default_options(), fast=True)
    names = {item.get("name") for item in checks}
    expected = {"pypdf diagnostics worker", "pdfminer.six text worker", "Tesseract OCR worker", "docTR OCR worker", "MonkeyOCR worker", "dots.mocr provider", "DocLayout-YOLO baseline", "pdf_table worker"}
    missing = expected - names
    if missing:
        raise AssertionError(f"Expected external wrapper checks in health report: missing={missing} checks={checks}")
    capabilities = environment_capability_summary(checks)
    capability_names = {item.get("name") for item in capabilities}
    expected_capabilities = {"pdf_lightweight_fallbacks", "ocr_candidate_workers", "external_document_vlm_wrappers", "layout_detector_baseline", "external_table_worker"}
    missing_capabilities = expected_capabilities - capability_names
    if missing_capabilities:
        raise AssertionError(f"Expected external wrapper capabilities: missing={missing_capabilities} capabilities={capabilities}")



def assert_table_candidates_artifact(payload: dict) -> None:
    artifacts = [item for item in payload.get("artifacts") or [] if isinstance(item, dict)]
    candidates = [item for item in artifacts if item.get("type") == "table_candidates_json"]
    if not candidates:
        raise AssertionError(f"Expected pdf_table table_candidates_json artifact: {payload}")
    readable = read_artifact({"path": str(candidates[0].get("path") or ""), "artifact_type": "table_candidates_json"})
    summary = readable.get("summary") or {}
    if summary.get("kind") != "table_candidates_json" or summary.get("table_count") != 1 or summary.get("candidate_schema_known") is not True:
        raise AssertionError(f"Expected readable pdf_table table candidates summary: {readable}")

def assert_tesseract_tsv_normalization() -> None:
    payload = parse_tesseract_tsv(
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        "5\t1\t2\t3\t4\t5\t10\t20\t120\t30\t90\tFake\n"
        "5\t1\t2\t3\t4\t6\t150\t20\t50\t30\t-1\tNoise\n",
        image="sample.png",
    )
    blocks = payload.get("blocks") or []
    if payload.get("schema_version") != "ocr-blocks-v1" or payload.get("provider") != "tesseract":
        raise AssertionError(f"Expected Tesseract ocr-blocks-v1 payload: {payload}")
    if len(blocks) != 2 or blocks[0].get("bbox") != [10, 20, 130, 50] or blocks[0].get("confidence") != 0.9:
        raise AssertionError(f"Expected TSV word block normalization: {payload}")
    if "confidence" in blocks[1]:
        raise AssertionError(f"Expected negative Tesseract confidence to be omitted: {payload}")
def main() -> int:
    assert_tesseract_tsv_normalization()

    root = PROJECT_DIR / ".tmp" / "external-wrapper-plan-tests"
    root.mkdir(parents=True, exist_ok=True)

    assert_result(
        run_script("pypdf_diagnostics_worker.py", root / "pypdf-fake", ["--mode", "fake"]),
        "pypdf",
        "fake",
        3,
    )
    assert_result(
        run_script("pdfminer_text_worker.py", root / "pdfminer-fake", ["--mode", "fake"]),
        "pdfminer_six",
        "fake",
        3,
    )
    assert_result(
        run_script("tesseract_ocr_worker.py", root / "tesseract-fake", ["--mode", "fake"]),
        "tesseract",
        "fake",
        5,
    )
    assert_result(
        run_script("doctr_ocr_worker.py", root / "doctr-fake", ["--mode", "fake"]),
        "doctr",
        "fake",
        2,
    )

    assert_result(
        run_script("monkeyocr_worker.py", root / "monkey-plan", ["--monkeyocr-root", str(root / "missing"), "--mode", "plan"]),
        "monkeyocr",
        "plan",
    )
    assert_result(
        run_script("monkeyocr_worker.py", root / "monkey-fake", ["--monkeyocr-root", str(root / "missing"), "--mode", "fake"]),
        "monkeyocr",
        "fake",
        6,
    )
    assert_result(
        run_script("dots_mocr_worker.py", root / "dots-fake", ["--mode", "fake"]),
        "dots_mocr",
        "fake",
        5,
    )
    assert_result(
        run_script("doclayout_yolo_worker.py", root / "layout-fake", ["--model", "fake-model.pt", "--mode", "fake"]),
        "doclayout_yolo",
        "fake",
        3,
    )
    table_result = run_script("pdf_table_worker.py", root / "table-fake", ["--pages", "1", "--mode", "fake"])
    assert_result(
        table_result,
        "pdf_table",
        "fake",
        6,
    )
    assert_table_candidates_artifact(table_result)

    print("External wrapper plan contract test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


