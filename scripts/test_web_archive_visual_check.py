from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

from ebook_markdown_pipeline.process_web_archive import process_web_archive


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="web-archive-visual-check-") as tmpdir:
        archive = Path(tmpdir)
        rebuild_input = archive / "rebuild_input"
        rebuild_input.mkdir(parents=True)
        source_md = archive / "source.md"
        source_md.write_text(
            "# Source\n\n| Name | Value |\n|---|---|\n| A | 1 |\n",
            encoding="utf-8",
            newline="\n",
        )
        (rebuild_input / "manifest.json").write_text(
            json.dumps({"inputs": {"source_markdown": str(source_md)}, "image_assets": []}, ensure_ascii=False),
            encoding="utf-8",
            newline="\n",
        )

        result = process_web_archive(str(archive))
        output_dir = Path(result["output_dir"])
        expected = [
            "layout_ocr.md",
            "visual_blocks.json",
            "table_candidates.json",
            "image_positions.json",
            "visual_check_result.json",
        ]
        missing = [name for name in expected if not (output_dir / name).exists()]
        if missing:
            raise AssertionError(f"Missing visual-check outputs: {missing}")
        if result["status"] != "pending_visual_engine":
            raise AssertionError(f"Expected pending status without screenshot: {result}")
        table_candidates = json.loads((output_dir / "table_candidates.json").read_text(encoding="utf-8"))
        if len(table_candidates) != 1:
            raise AssertionError(f"Expected one table candidate from source markdown: {table_candidates}")

    print("Web archive visual-check smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
