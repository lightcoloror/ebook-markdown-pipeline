from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from ebook_converter_mcp import read_artifact, run_online_enhancement


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="online-enhancement-artifacts-") as tmp:
        root = Path(tmp)
        image = root / "sample.png"
        image.write_bytes(b"fake image")
        vlm_out = root / "vlm"
        vlm = run_online_enhancement({"task": "vlm_layout", "input_path": str(image), "provider_mode": "fake", "output": str(vlm_out)})
        artifact_types = {item.get("type") for item in vlm.get("artifacts") or []}
        if vlm.get("status") != "ok" or "document_vlm_result_json" not in artifact_types:
            raise RuntimeError(f"Expected VLM document sidecar artifact: {vlm}")
        vlm_summary = read_artifact({"path": str(vlm_out / "document-vlm-result.json"), "artifact_type": "document_vlm_result_json"}).get("summary") or {}
        if not vlm_summary.get("schema_valid") or vlm_summary.get("block_count") != 1:
            raise RuntimeError(f"Unexpected VLM sidecar summary: {vlm_summary}")

        table_out = root / "table"
        table = run_online_enhancement(
            {
                "task": "table_repair",
                "input_text": "| A | B |\n| --- | --- |\n| 1 | 2 |",
                "provider_mode": "fake",
                "output": str(table_out),
            }
        )
        artifact_types = {item.get("type") for item in table.get("artifacts") or []}
        if table.get("status") != "ok" or "table_candidates_json" not in artifact_types:
            raise RuntimeError(f"Expected table candidate sidecar artifact: {table}")
        table_summary = read_artifact({"path": str(table_out / "table-candidates.json"), "artifact_type": "table_candidates_json"}).get("summary") or {}
        if not table_summary.get("schema_valid") or table_summary.get("table_count") != 1:
            raise RuntimeError(f"Unexpected table sidecar summary: {table_summary}")
    print("Online enhancement sidecar artifact test passed.")


if __name__ == "__main__":
    main()
