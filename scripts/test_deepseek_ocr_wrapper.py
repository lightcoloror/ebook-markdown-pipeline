from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT / "scripts"))

from deepseek_ocr_image_to_md import build_deepseek_command, clean_stdout, prompt_from_args, stdout_to_markdown  # noqa: E402
from ebook_markdown_pipeline.batch_convert_books import default_options, dependency_health_report, environment_capability_summary  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="deepseek-ocr-wrapper-") as tmp:
        root = Path(tmp)
        image = root / "sample.png"
        image.write_bytes(b"fake image")
        output = root / "out.md"
        raw_dir = root / "raw"
        args = SimpleNamespace(
            python=sys.executable,
            model="deepseek-ai/DeepSeek-OCR",
            prompt_mode="markdown",
            prompt="",
            base_size=1024,
            image_size=640,
            device="auto",
            attention="auto",
            no_crop=False,
            no_test_compress=False,
        )

        command = build_deepseek_command(args, image, raw_dir)
        if "deepseek_ocr_transformers_runner.py" not in " ".join(command):
            raise AssertionError(f"Unexpected DeepSeek-OCR command: {command}")
        if "--model" not in command or "--prompt" not in command or "--image-size" not in command:
            raise AssertionError(f"DeepSeek-OCR command missing expected args: {command}")
        if "Convert the document to markdown" not in prompt_from_args(args):
            raise AssertionError("Expected default markdown prompt.")
        markdown = stdout_to_markdown("Loading model\n正文\n", source=image, raw_dir=raw_dir, mode="markdown")
        if "Loading model" in markdown or "正文" not in markdown:
            raise AssertionError(f"Unexpected DeepSeek-OCR markdown cleanup: {markdown}")
        if clean_stdout("CUDA ready\n正文") != "正文":
            raise AssertionError("Expected runtime noise to be removed from DeepSeek-OCR stdout.")

        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "deepseek_ocr_image_to_md.py"),
                "--input",
                str(image),
                "--output",
                str(output),
                "--model",
                "deepseek-ai/DeepSeek-OCR",
                "--dry-run",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0 or "deepseek_ocr_transformers_runner.py" not in completed.stdout:
            raise AssertionError(f"Expected DeepSeek-OCR dry-run command: {completed.returncode}\n{completed.stdout}")

    checks = dependency_health_report([], default_options(), fast=True)
    if not any(item.get("name") == "DeepSeek-OCR wrapper" for item in checks):
        raise AssertionError(f"DeepSeek-OCR wrapper should be listed in health checks: {checks}")
    capabilities = environment_capability_summary(checks)
    if not any(item.get("name") == "deepseek_ocr_experiment" for item in capabilities):
        raise AssertionError(f"DeepSeek-OCR capability should be listed: {capabilities}")

    print("DeepSeek-OCR wrapper contract test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
