from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.recommendations import recommended_action_for_plan  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ebook-recommendations-") as tmp:
        root = Path(tmp)
        existing = root / "book.md"
        existing.write_text("# Existing\n", encoding="utf-8")
        if "Skip" not in recommended_action_for_plan(SimpleNamespace(output=str(existing), detected_format="EPUB", pipeline="pandoc")):
            raise AssertionError("Existing output should recommend skip/resume.")
        if "long task" not in recommended_action_for_plan(SimpleNamespace(output=str(root / "long.md"), detected_format="PDF", pipeline="mineru(structured)")):
            raise AssertionError("MinerU PDF should warn as long task.")
        if "Convert" not in recommended_action_for_plan(SimpleNamespace(output=str(root / "new.md"), detected_format="TXT", pipeline="pandoc")):
            raise AssertionError("New ordinary file should recommend conversion.")
    print("Recommendation smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
