from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).with_name("qwen_vl_image_to_md.py")
PROJECT_ROOT = SCRIPT.parent.parent
if str(SCRIPT.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT.parent))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ebook_converter_mcp import read_artifact

SPEC = importlib.util.spec_from_file_location("qwen_vl_image_to_md", SCRIPT)
assert SPEC and SPEC.loader
qwen_wrapper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qwen_wrapper)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="qwen-vl-wrapper-test-") as tmp:
        root = Path(tmp)
        image = root / "sample.png"
        output = root / "sample.md"
        raw_dir = root / "qwen_raw"
        image.write_bytes(b"fake image")
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--input",
                str(image),
                "--output",
                str(output),
                "--output-dir",
                str(raw_dir),
                "--model",
                "test/qwen-vl",
                "--dry-run",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0 or "document-vlm-result.json" not in completed.stdout or "test/qwen-vl" not in completed.stdout:
            raise RuntimeError(f"Qwen-VL dry-run failed: {completed.returncode}\n{completed.stdout}")

        markdown = "# Fake Qwen Result\n\n- block"
        output.write_text(markdown + "\n", encoding="utf-8", newline="\n")
        sidecar = qwen_wrapper.write_qwen_vl_sidecar(raw_dir, image, output, markdown, model="test/qwen-vl", max_new_tokens=64)
        summary = read_artifact({"path": str(sidecar), "artifact_type": "document_vlm_result_json"}).get("summary") or {}
        if not summary.get("schema_valid") or summary.get("backend") != "qwen_vl" or summary.get("block_count") != 1:
            raise RuntimeError(f"Unexpected Qwen-VL sidecar summary: {summary}")
    print("Qwen-VL wrapper contract test passed.")


if __name__ == "__main__":
    main()
