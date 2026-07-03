from __future__ import annotations

import sys
import shutil
from pathlib import Path
from types import SimpleNamespace

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.batch_convert_books import (  # noqa: E402
    DOCLING_TEXT_FALLBACK_FORMATS,
    build_output_path,
    markitdown_available,
    read_delimited_text_rows,
    render_delimited_text_markdown,
    required_dependencies,
    source_kind_for_conversion,
)


def assert_contains(text: str, needle: str) -> None:
    if needle not in text:
        raise AssertionError(f"Expected to find {needle!r} in output:\n{text}")


def main() -> int:
    root = PROJECT_DIR / ".tmp-tests" / "delimited-text-fallback"
    resolved_root = root.resolve()
    allowed_root = (PROJECT_DIR / ".tmp-tests").resolve()
    if root.exists():
        if allowed_root not in resolved_root.parents:
            raise AssertionError(f"Refusing to clean unexpected test directory: {resolved_root}")
        shutil.rmtree(root)
    root.mkdir(parents=True)
    try:
        csv_path = root / "policy-list.csv"
        bar = chr(124)
        csv_path.write_text(
            "姓名,说明,金额\n"
            "张三,包含逗号的说明,100\n"
            f"李四,含{bar}管道,200\n",
            encoding="utf-8-sig",
        )
        rows, encoding, delimiter_name = read_delimited_text_rows(csv_path)
        if rows[0] != ["姓名", "说明", "金额"]:
            raise AssertionError(f"Unexpected CSV header: {rows[0]!r}")
        if encoding != "utf-8-sig":
            raise AssertionError(f"Expected BOM-aware encoding, got {encoding}")
        if delimiter_name != ",":
            raise AssertionError(f"Unexpected delimiter: {delimiter_name!r}")
        markdown = render_delimited_text_markdown(csv_path, rows, encoding, delimiter_name)
        assert_contains(markdown, f"{bar} 姓名 {bar} 说明 {bar} 金额 {bar}")
        assert_contains(markdown, "含\\" + bar + "管道")

        tsv_path = root / "保单清单.tsv"
        tsv_path.write_bytes("产品\t保费\n医疗险\t1000\n".encode("gb18030"))
        rows, encoding, delimiter_name = read_delimited_text_rows(tsv_path)
        if rows[1] != ["医疗险", "1000"]:
            raise AssertionError(f"Unexpected TSV row: {rows[1]!r}")
        if encoding != "gb18030":
            raise AssertionError(f"Expected gb18030 fallback, got {encoding}")
        if delimiter_name != "tab":
            raise AssertionError(f"Expected tab delimiter, got {delimiter_name!r}")

        args = SimpleNamespace(output_format="markdown", document_pipeline_mode="auto", docling_fallback_to_pandoc=True, pandoc_command="pandoc")
        if source_kind_for_conversion(tsv_path, args) != "docling":
            raise AssertionError("TSV should be routed through the document fallback path.")
        if required_dependencies([csv_path, tsv_path], args):
            raise AssertionError("Default CSV/TSV conversion should not require Docling or other external tools.")
        if ".tsv" not in DOCLING_TEXT_FALLBACK_FORMATS:
            raise AssertionError("TSV should be supported as a lightweight delimited text format.")
        output_path = build_output_path(csv_path, root, root / "out", args)
        if output_path.name != "policy-list.md":
            raise AssertionError(f"Unexpected output name: {output_path}")

        docx_path = root / "fallback.docx"
        docx_path.write_bytes(b"not a real docx; dependency routing only")
        docx_required = required_dependencies([docx_path], args)
        if "docling" in docx_required:
            raise AssertionError(f"Auto DOCX fallback should not block on broken Docling: {docx_required}")
        if "pandoc" not in docx_required:
            raise AssertionError(f"Auto DOCX fallback should require Pandoc when Docling is unavailable: {docx_required}")

        pptx_path = root / "fallback.pptx"
        pptx_path.write_bytes(b"not a real pptx; dependency routing only")
        pptx_required = required_dependencies([pptx_path], args)
        if markitdown_available() and "docling" in pptx_required:
            raise AssertionError(f"Auto PPTX fallback should use MarkItDown instead of blocking on Docling: {pptx_required}")

        forced_docling_args = SimpleNamespace(
            output_format="markdown",
            document_pipeline_mode="docling",
            docling_fallback_to_pandoc=True,
            pandoc_command="pandoc",
        )
        forced_required = required_dependencies([csv_path], forced_docling_args)
        if "docling" not in forced_required:
            raise AssertionError("Explicit Docling mode should still require Docling for CSV.")
    finally:
        if root.exists():
            shutil.rmtree(root)

    print("Delimited text fallback smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())