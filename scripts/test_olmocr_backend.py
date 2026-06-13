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
from ebook_markdown_pipeline.olmocr_backend import build_olmocr_command, find_olmocr_markdown, olmocr_available, redact_command  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="ebook-olmocr-contract-") as tmp:
        root = Path(tmp)
        pdf = root / "sample.pdf"
        pdf.write_bytes(b"%PDF-1.4\n% fake contract input\n")
        output = root / "out.md"
        result_json = root / "result.json"

        options = default_options(
            input=pdf,
            output=root,
            pdf_pipeline_mode="olmocr",
            output_format="markdown",
        )
        if "olmocr" not in PDF_PIPELINE_MODES:
            raise AssertionError("PDF pipeline modes should include olmocr.")
        if pipeline_name(pdf, options) != "olmOCR(vlm)":
            raise AssertionError(f"Unexpected olmOCR pipeline label: {pipeline_name(pdf, options)}")

        missing = find_missing_dependencies([pdf], options)
        if olmocr_available(options.olmocr_command):
            if any("olmocr" in item.lower() for item in missing):
                raise AssertionError(f"olmOCR should not be missing when command/module is available: {missing}")
        elif not any("olmocr" in item.lower() for item in missing):
            raise AssertionError(f"Expected missing olmOCR dependency: {missing}")

        checks = dependency_health_report([pdf], options, fast=True)
        olmocr_check = next((item for item in checks if item.get("name") == "olmOCR"), None)
        if not olmocr_check:
            raise AssertionError("Health report should include olmOCR.")

        command = build_olmocr_command(
            pdf,
            root / "workspace",
            command="olmocr",
            server="http://remote-server:8000/v1",
            model="allenai/olmOCR-2-7B-1025-FP8",
            api_key_env="OLMOCR_TEST_KEY",
            workers=1,
            max_concurrent_requests=2,
            pages_per_group=4,
        )
        redacted = redact_command(command)
        if "--api_key" in command and "<redacted>" not in redacted:
            raise AssertionError(f"Expected API key redaction: {redacted}")
        if "--server" not in command or "--model" not in command or "--markdown" not in command:
            raise AssertionError(f"Unexpected olmOCR command: {command}")

        workspace = root / "workspace"
        markdown_dir = workspace / "markdown"
        markdown_dir.mkdir(parents=True)
        generated = markdown_dir / "sample.md"
        generated.write_text("# Sample\n", encoding="utf-8")
        if find_olmocr_markdown(workspace, pdf) != generated:
            raise AssertionError("Expected exact olmOCR Markdown match by source stem.")

        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "olmocr_backend.py"),
                str(pdf),
                "--output",
                str(output),
                "--output-json",
                str(result_json),
                "--workspace",
                str(root / "dry-workspace"),
                "--server",
                "http://remote-server:8000/v1",
                "--model",
                "allenai/olmOCR-2-7B-1025-FP8",
                "--api-key-env",
                "OLMOCR_TEST_KEY",
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
            raise RuntimeError(f"olmOCR dry-run failed: {completed.returncode}\n{completed.stdout}")
        payload = json.loads(result_json.read_text(encoding="utf-8"))
        if not payload.get("dry_run") or payload.get("api_key_env") != "OLMOCR_TEST_KEY":
            raise AssertionError(f"Unexpected olmOCR dry-run payload: {payload}")
        if any(str(item).startswith("sk-") for item in payload.get("command") or []):
            raise AssertionError(f"Dry-run command should not expose secrets: {payload}")
    print("olmOCR backend contract test passed.")


if __name__ == "__main__":
    main()
