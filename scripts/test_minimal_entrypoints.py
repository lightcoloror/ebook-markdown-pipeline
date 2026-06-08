from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ebook-minimal-entrypoints-") as tmp:
        cwd = Path(tmp)
        assert_ui_script_imports_from_external_cwd(cwd)
        assert_cli_help_from_external_cwd(cwd)
        assert_cli_txt_conversion_from_external_cwd(cwd)
    print("Minimal entrypoints smoke test passed.")
    return 0


def assert_ui_script_imports_from_external_cwd(cwd: Path) -> None:
    script = PROJECT_DIR / "book_converter_ui.py"
    probe = (
        "import runpy; "
        f"ns = runpy.run_path({str(script)!r}); "
        "assert 'BookConverterUI' in ns; "
        "assert 'main' in ns"
    )
    completed = run_python(cwd, "-c", probe)
    if completed.returncode != 0:
        raise AssertionError(f"UI script should import from external cwd without ModuleNotFoundError:\n{completed.stderr}")


def assert_cli_help_from_external_cwd(cwd: Path) -> None:
    script = PROJECT_DIR / "batch_convert_books.py"
    completed = run_python(cwd, str(script), "--help")
    if completed.returncode != 0 or "Batch convert" not in completed.stdout:
        raise AssertionError(f"CLI --help should work from external cwd:\nstdout={completed.stdout}\nstderr={completed.stderr}")


def assert_cli_txt_conversion_from_external_cwd(cwd: Path) -> None:
    script = PROJECT_DIR / "batch_convert_books.py"
    source = PROJECT_DIR / "benchmarks" / "fixtures" / "generated" / "text" / "sample.txt"
    output = cwd / "out"
    completed = run_python(cwd, str(script), str(source), str(output), "--overwrite", "--output-format", "markdown")
    if completed.returncode != 0:
        raise AssertionError(f"Minimal TXT conversion should work from external cwd:\n{completed.stderr}")
    markdown = output / "sample.md"
    if not markdown.exists() or "Public Quality Fixture" not in markdown.read_text(encoding="utf-8", errors="replace"):
        raise AssertionError(f"Expected generated Markdown output: {markdown}")


def run_python(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", *args],
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


if __name__ == "__main__":
    raise SystemExit(main())
