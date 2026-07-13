from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

import ebook_markdown_pipeline.batch_convert_books as pipeline  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="batch-control-flow-") as tmp:
        root = Path(tmp)
        source = root / "sample.txt"
        source.write_text("# Source\n\nSynthetic control-flow fixture.\n", encoding="utf-8")
        output_root = root / "output"
        output_root.mkdir()
        output = output_root / "sample.md"
        output.write_text("# Existing\n", encoding="utf-8")

        manifest = output_root / "manifest.json"
        manifest.write_text(
            json.dumps([{"source": str(source), "output": str(output), "status": "ok"}]),
            encoding="utf-8",
        )
        resume_args = pipeline.default_options(resume=True, manifest=manifest, no_reports=True)
        resumed = pipeline.convert_sources([source], source, output_root, resume_args)
        if len(resumed) != 1 or resumed[0].status != "skipped":
            raise AssertionError(f"Expected resume skip: {resumed}")
        if "Previously completed" not in resumed[0].message:
            raise AssertionError(f"Expected resume evidence: {resumed[0]}")

        skip_args = pipeline.default_options(overwrite=False)
        skipped = pipeline.convert_one(source, source, output_root, skip_args, output_path=output)
        if skipped.status != "skipped" or "--overwrite" not in skipped.message:
            raise AssertionError(f"Expected existing output protection: {skipped}")

        original_pandoc = pipeline.run_pandoc_direct_convert
        try:
            def fake_pandoc(source_path, output_path, args, *unused_args, **unused_kwargs):
                output_path.write_text("# Replaced\n", encoding="utf-8")
                args._last_ebook_pipeline = "pandoc(fake)"

            pipeline.run_pandoc_direct_convert = fake_pandoc
            overwrite_args = pipeline.default_options(overwrite=True)
            replaced = pipeline.convert_one(source, source, output_root, overwrite_args, output_path=output)
        finally:
            pipeline.run_pandoc_direct_convert = original_pandoc
        if replaced.status != "ok" or output.read_text(encoding="utf-8") != "# Replaced\n":
            raise AssertionError(f"Expected overwrite replacement: {replaced}")

    timeout_args = pipeline.default_options(pdf_tool_idle_timeout=3.0, pdf_tool_finalize_timeout=5.0)
    if "idle timeout" not in str(pipeline.pdf_tool_timeout_reason(timeout_args, 3.0, 0.0)):
        raise AssertionError("Expected deterministic idle timeout")
    if "finalize timeout" not in str(pipeline.pdf_tool_timeout_reason(timeout_args, 1.0, 5.0)):
        raise AssertionError("Expected deterministic finalize timeout")
    if pipeline.pdf_tool_timeout_reason(timeout_args, 2.9, 4.9) is not None:
        raise AssertionError("Timeout should not fire before threshold")

    original_available = pipeline.pymupdf4llm_available
    try:
        pipeline.pymupdf4llm_available = lambda: True
        fallback_args = pipeline.default_options(pdf_fallback_to_pymupdf4llm=True)
        timeout_error = pipeline.PdfToolTimeoutError("timeout", {"reason": "idle"})
        if not pipeline.should_fallback_from_pdf_tool(timeout_error, "mineru", fallback_args):
            raise AssertionError("MinerU timeout should fall back to local PyMuPDF4LLM")
        if pipeline.should_fallback_from_pdf_tool(timeout_error, "pymupdf4llm", fallback_args):
            raise AssertionError("PyMuPDF4LLM must not recursively fall back to itself")
        fallback_args.pdf_fallback_to_pymupdf4llm = False
        if pipeline.should_fallback_from_pdf_tool(timeout_error, "mineru", fallback_args):
            raise AssertionError("Explicit no-fallback setting must be honored")
    finally:
        pipeline.pymupdf4llm_available = original_available

    capabilities = pipeline.environment_capability_summary(
        [
            {"name": "pandoc", "kind": "command", "status": "ok", "detail": "synthetic"},
            {"name": "ebook-convert", "kind": "command", "status": "missing", "detail": "synthetic"},
            {"name": "PyMuPDF", "kind": "python", "status": "ok", "detail": "synthetic"},
            {"name": "pymupdf4llm", "kind": "python", "status": "ok", "detail": "synthetic"},
        ]
    )
    structured = next(item for item in capabilities if item["name"] == "structured_ebooks")
    if structured["status"] != "degraded" or "Calibre is missing" not in structured["detail"]:
        raise AssertionError(f"Expected explicit Pandoc coverage and Calibre gap: {structured}")

    print("Batch control-flow contract test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
