from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

import ebook_markdown_pipeline.batch_convert_books as pipeline  # noqa: E402
from ebook_markdown_pipeline.mineru_api_config import load_mineru_api_config  # noqa: E402
from ebook_markdown_pipeline.scripts import mineru_api_service  # noqa: E402


def main() -> int:
    config = load_mineru_api_config()
    assert config.host == "127.0.0.1"
    assert config.port == 8000
    assert config.client_temp_root.parent == config.state_root
    service_command = mineru_api_service.build_service_command(config)
    if sys.platform == "win32" and Path(config.command).name.lower() == "mineru-api.exe":
        assert service_command[0].lower().endswith("python.exe")
        assert service_command[1:3] == ["-m", "mineru.cli.fast_api"]
    assert service_command[-4:] == ["--host", "127.0.0.1", "--port", "8000"]

    parsed = pipeline.parse_args(["input.pdf", "output", "--pdf-pipeline-mode", "mineru"])
    assert parsed.mineru_api_url == config.url

    source = PROJECT_DIR / "synthetic-mineru-contract.pdf"
    output = PROJECT_DIR / "synthetic-mineru-contract.md"
    restricted_temp = Path("C:/tmp/ebook-mineru-contract")
    restricted_temp.mkdir(parents=True, exist_ok=True)
    dry_args = pipeline.SimpleNamespace(
        dry_run=True,
        mineru_command="mineru",
        mineru_api_url=config.url,
        mineru_client_temp_root=restricted_temp,
        mineru_extra_args=[],
        mineru_method="auto",
        mineru_backend="pipeline",
        mineru_lang="ch",
        mineru_keep_artifacts=True,
        output_format="markdown",
    )
    capture = io.StringIO()
    with contextlib.redirect_stdout(capture):
        pipeline.run_single_mineru_pdf_convert(source, output, dry_args)
    command_text = capture.getvalue()
    assert f"--api-url {config.url}" in command_text
    assert "mineru-api-client-" not in command_text

    try:
        pipeline.validate_mineru_extra_args(["--api-url", "http://127.0.0.1:9999"])
    except ValueError:
        pass
    else:
        raise AssertionError("Conflicting MinerU --api-url passthrough must be rejected")

    original_health = pipeline.mineru_api_health
    original_mineru = pipeline.run_mineru_pdf_convert
    original_pymupdf = pipeline.run_pymupdf4llm_pdf_convert
    original_available = pipeline.pymupdf4llm_available
    original_selected = pipeline.selected_pdf_pipeline
    original_label = pipeline.selected_pdf_pipeline_label
    try:
        pipeline.mineru_api_health = lambda unused_url: {"healthy": False, "error": "synthetic stopped API"}
        try:
            pipeline.require_mineru_api(config.url)
        except pipeline.MinerUAPIUnavailableError as exc:
            assert "will not start MinerU's temporary API" in str(exc)
        else:
            raise AssertionError("Stopped shared API must not be treated as healthy")

        def unavailable(*unused_args, **unused_kwargs):
            raise pipeline.MinerUAPIUnavailableError("synthetic stopped API")

        def local_fallback(unused_source, target, unused_args, *unused_positional, **unused_kwargs):
            target.write_text("# Local fallback\n", encoding="utf-8")

        pipeline.run_mineru_pdf_convert = unavailable
        pipeline.run_pymupdf4llm_pdf_convert = local_fallback
        pipeline.pymupdf4llm_available = lambda: True
        pipeline.selected_pdf_pipeline = lambda unused_source, unused_args: "mineru"
        pipeline.selected_pdf_pipeline_label = lambda unused_source, unused_args: "mineru"

        fallback_output = restricted_temp / "synthetic-fallback.md"
        fallback_args = pipeline.SimpleNamespace(
            pdf_fallback_to_pymupdf4llm=True,
            _pdf_fallback_diagnostics=[],
        )
        pipeline.run_pdf_convert(source, fallback_output, fallback_args)
        assert fallback_output.read_text(encoding="utf-8") == "# Local fallback\n"
        diagnostic = fallback_args._pdf_fallback_diagnostics[-1]
        assert diagnostic.get("reason_type") == "MinerUAPIUnavailableError"
        assert diagnostic.get("status") == "ok"
        fallback_output.unlink(missing_ok=True)

        no_fallback_args = pipeline.SimpleNamespace(pdf_fallback_to_pymupdf4llm=False)
        try:
            pipeline.run_pdf_convert(source, fallback_output, no_fallback_args)
        except pipeline.MinerUAPIUnavailableError:
            pass
        else:
            raise AssertionError("Disabled fallback must return a real MinerU API failure")
    finally:
        pipeline.mineru_api_health = original_health
        pipeline.run_mineru_pdf_convert = original_mineru
        pipeline.run_pymupdf4llm_pdf_convert = original_pymupdf
        pipeline.pymupdf4llm_available = original_available
        pipeline.selected_pdf_pipeline = original_selected
        pipeline.selected_pdf_pipeline_label = original_label

    print("MinerU fixed API contract test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
