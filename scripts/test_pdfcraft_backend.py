from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from ebook_markdown_pipeline.batch_convert_books import (  # noqa: E402
    PDF_PIPELINE_MODES,
    default_options,
    dependency_health_report,
    find_missing_dependencies,
    pipeline_name,
)
from ebook_markdown_pipeline.pdfcraft_backend import pdfcraft_available  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="ebook-pdfcraft-contract-") as tmp:
        root = Path(tmp)
        pdf = root / "scan.pdf"
        pdf.write_bytes(b"%PDF-1.4\n% fake contract input\n")
        output = root / "out.md"
        result_json = root / "result.json"

        options = default_options(
            input=pdf,
            output=root,
            pdf_pipeline_mode="pdfcraft",
            output_format="markdown",
        )
        if "pdfcraft" not in PDF_PIPELINE_MODES:
            raise AssertionError("PDF pipeline modes should include pdfcraft.")
        if pipeline_name(pdf, options) != "pdf-craft(scanned-book)":
            raise AssertionError(f"Unexpected pdfcraft pipeline label: {pipeline_name(pdf, options)}")

        missing = find_missing_dependencies([pdf], options)
        if pdfcraft_available():
            if any("pdf-craft" in item.lower() for item in missing):
                raise AssertionError(f"pdf-craft should not be missing when importable: {missing}")
        elif not any("pdf-craft" in item.lower() for item in missing):
            raise AssertionError(f"Expected missing pdf-craft dependency: {missing}")

        checks = dependency_health_report([pdf], options, fast=True)
        pdfcraft_check = next((item for item in checks if item.get("name") == "pdf-craft"), None)
        if not pdfcraft_check:
            raise AssertionError("Health report should include pdf-craft.")

        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "pdfcraft_backend.py"),
                str(pdf),
                "--output",
                str(output),
                "--output-json",
                str(result_json),
                "--dry-run",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"pdf-craft dry-run failed: {completed.returncode}\n{completed.stdout}")
        payload = json.loads(result_json.read_text(encoding="utf-8"))
        if not payload.get("dry_run") or payload.get("ocr_size") != "base":
            raise AssertionError(f"Unexpected pdf-craft dry-run payload: {payload}")
    print("pdf-craft backend contract test passed.")


if __name__ == "__main__":
    main()
