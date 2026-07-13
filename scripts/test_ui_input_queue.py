from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.book_converter_ui import collect_drop_files, common_input_root, merge_input_paths


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ui-input-queue-") as tmp:
        root = Path(tmp)
        first = root / "first.pdf"
        second = root / "second.epub"
        nested = root / "nested"
        hidden = root / ".hidden"
        nested.mkdir()
        hidden.mkdir()
        third = nested / "third.docx"
        hidden_file = hidden / "secret.pdf"
        unsupported = root / "ignore.exe"
        for path in (first, second, third, hidden_file, unsupported):
            path.write_bytes(b"fixture")

        merged = merge_input_paths(
            [first, second],
            [second, third, Path(str(first))],
        )
        if merged != [first, second, third]:
            raise AssertionError(f"Expected stable append and deduplication: {merged}")

        immediate = collect_drop_files([root], recursive=False, include_hidden=False)
        if immediate != [first, second]:
            raise AssertionError(f"Expected only immediate supported files: {immediate}")

        recursive = collect_drop_files([root], recursive=True, include_hidden=False)
        if set(recursive) != {first, second, third}:
            raise AssertionError(f"Expected recursive files without hidden input: {recursive}")

        with_hidden = collect_drop_files([root], recursive=True, include_hidden=True)
        if set(with_hidden) != {first, second, third, hidden_file}:
            raise AssertionError(f"Expected hidden files when enabled: {with_hidden}")

        cross_drive = common_input_root([Path("C:/batch-a/first.pdf"), Path("D:/batch-b/second.pdf")])
        if cross_drive != Path("C:/batch-a"):
            raise AssertionError(f"Cross-drive batches should fall back to the first parent: {cross_drive}")

        batches: list[Path] = []
        batches = merge_input_paths(batches, [first])
        batches = merge_input_paths(batches, [second, third])
        batches = merge_input_paths(batches, [first, third])
        if batches != [first, second, third]:
            raise AssertionError(f"Multiple drops must retain previous batches: {batches}")

    print("UI input queue append contract test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
