from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("surya_image_to_md.py")
SPEC = importlib.util.spec_from_file_location("surya_image_to_md", SCRIPT)
assert SPEC and SPEC.loader
surya_wrapper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(surya_wrapper)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="surya-wrapper-test-") as tmp:
        root = Path(tmp)
        image = root / "sample.png"
        output = root / "sample.md"
        image.write_bytes(b"fake image")
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--input",
                str(image),
                "--output",
                str(output),
                "--mode",
                "ocr",
                "--dry-run",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0 or "surya_ocr" not in completed.stdout:
            raise RuntimeError(f"Surya wrapper dry-run failed: {completed.returncode}\n{completed.stdout}")
        fake = {
            "sample": [
                {
                    "page": 1,
                    "blocks": [
                        {"label": "SectionHeader", "reading_order": 0, "html": "<p>标题</p>"},
                        {"label": "Text", "reading_order": 1, "html": "<p>正文<br>第二行</p>"},
                    ],
                }
            ]
        }
        markdown = surya_wrapper.results_to_markdown(fake, "ocr")
        if "#### 标题" not in markdown or "正文\n第二行" not in markdown:
            raise RuntimeError(f"Unexpected Surya Markdown normalization: {markdown}")
        table_markdown = surya_wrapper.results_to_markdown({"sample": [[{"html": "<table><tr><td>A</td></tr></table>"}]]}, "table")
        if "<table><tr><td>A</td></tr></table>" not in table_markdown:
            raise RuntimeError(f"Unexpected Surya table normalization: {table_markdown}")
    print("Surya wrapper contract test passed.")


if __name__ == "__main__":
    main()
