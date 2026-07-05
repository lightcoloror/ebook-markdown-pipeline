from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("surya_image_to_md.py")
PROJECT_ROOT = SCRIPT.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ebook_converter_mcp import read_artifact

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
        layout_dry_run = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--input",
                str(image),
                "--output",
                str(output),
                "--output-dir",
                str(root / "surya_raw"),
                "--mode",
                "layout",
                "--dry-run",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if layout_dry_run.returncode != 0 or "surya_layout" not in layout_dry_run.stdout or "layout_candidates=" not in layout_dry_run.stdout:
            raise RuntimeError(f"Surya wrapper layout dry-run failed: {layout_dry_run.returncode}\n{layout_dry_run.stdout}")
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

        output.write_text("# Surya output\n", encoding="utf-8")
        layout_data = {
            "sample": [
                {
                    "page": 1,
                    "bboxes": [
                        {"label": "SectionHeader", "bbox": [0, 0, 100, 20], "confidence": 0.95, "position": 1},
                        {"label": "Text", "bbox": [0, 30, 100, 60], "score": "0.87", "reading_order": "2"},
                    ],
                }
            ]
        }
        layout_sidecar = surya_wrapper.write_surya_candidate_sidecars(root / "surya_raw", image, output, "layout", layout_data)[0]
        layout_payload = json.loads(layout_sidecar.read_text(encoding="utf-8"))
        if layout_payload.get("schema_version") != "layout-candidates-v1" or len(layout_payload["pages"][0]["blocks"]) != 2:
            raise RuntimeError(f"Unexpected Surya layout sidecar: {layout_payload}")
        layout_summary = read_artifact({"path": str(layout_sidecar), "artifact_type": "layout_candidates_json"}).get("summary") or {}
        if not layout_summary.get("schema_valid") or layout_summary.get("block_count") != 2:
            raise RuntimeError(f"Unexpected Surya layout artifact summary: {layout_summary}")

        table_data = {
            "sample": [
                {
                    "page": 1,
                    "tables": [
                        {
                            "html": "<table><tr><td>A</td></tr></table>",
                            "bbox": [0, 0, 100, 100],
                            "cells": [{"row": 0, "col": 0, "text": "A"}],
                        }
                    ],
                }
            ]
        }
        table_sidecar = surya_wrapper.write_surya_candidate_sidecars(root / "surya_raw", image, output, "table", table_data)[0]
        table_payload = json.loads(table_sidecar.read_text(encoding="utf-8"))
        if table_payload.get("schema_version") != "table-candidates-v1" or len(table_payload["pages"][0]["tables"]) != 1:
            raise RuntimeError(f"Unexpected Surya table sidecar: {table_payload}")
        table_summary = read_artifact({"path": str(table_sidecar), "artifact_type": "table_candidates_json"}).get("summary") or {}
        if not table_summary.get("schema_valid") or table_summary.get("table_count") != 1:
            raise RuntimeError(f"Unexpected Surya table artifact summary: {table_summary}")
    print("Surya wrapper contract test passed.")


if __name__ == "__main__":
    main()
