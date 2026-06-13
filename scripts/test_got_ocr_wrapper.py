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

from ebook_markdown_pipeline.batch_convert_books import default_options, dependency_health_report, environment_capability_summary  # noqa: E402
from got_ocr_image_to_md import build_got_command, clean_stdout, stdout_to_markdown  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="got-ocr-wrapper-") as tmp:
        root = Path(tmp)
        image = root / "sample.png"
        image.write_bytes(b"fake image")
        script = root / "run_ocr_2.0.py"
        script.write_text("print('fake')\n", encoding="utf-8")
        output = root / "out.md"

        args = SimpleNamespace(
            python=sys.executable,
            script=str(script),
            crop_script="",
            model="stepfun-ai/GOT-OCR2_0",
            type="format",
            box="",
            color="",
            render=True,
            crop=False,
            multi_page=False,
        )

        cmd = build_got_command(args, image)
        if "--model-name" not in cmd or "--image-file" not in cmd or "--type" not in cmd or "--render" not in cmd:
            raise AssertionError(f"Unexpected GOT-OCR command: {cmd}")

        markdown = stdout_to_markdown("Loading model\n识别结果\n", source=image, mode="format")
        if "Loading model" in markdown or "识别结果" not in markdown:
            raise AssertionError(f"Unexpected GOT-OCR markdown cleanup: {markdown}")
        if clean_stdout("CUDA ready\n正文") != "正文":
            raise AssertionError("Expected runtime noise to be removed from GOT-OCR stdout.")

        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "got_ocr_image_to_md.py"),
                "--input",
                str(image),
                "--output",
                str(output),
                "--script",
                str(script),
                "--model",
                "stepfun-ai/GOT-OCR2_0",
                "--dry-run",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0 or "run_ocr_2.0.py" not in completed.stdout:
            raise AssertionError(f"Expected GOT-OCR dry-run command: {completed.returncode}\n{completed.stdout}")

    checks = dependency_health_report([], default_options(), fast=True)
    if not any(item.get("name") == "GOT-OCR wrapper" for item in checks):
        raise AssertionError(f"GOT-OCR wrapper should be listed in health checks: {checks}")
    capabilities = environment_capability_summary(checks)
    if not any(item.get("name") == "got_ocr_experiment" for item in capabilities):
        raise AssertionError(f"GOT-OCR capability should be listed: {capabilities}")

    print("GOT-OCR wrapper contract test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
