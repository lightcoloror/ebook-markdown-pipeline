from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ebook_markdown_pipeline.image_book_rebuilder import (  # noqa: E402
    ScreenshotPage,
    infer_page_order,
    mark_duplicates,
    render_book_markdown,
    text_to_markdown,
)


def make_page(source: str, text: str, filename_number: int | None = None) -> ScreenshotPage:
    return ScreenshotPage(
        source=source,
        file_name=Path(source).name,
        width=100,
        height=100,
        mtime=0.0,
        filename_number=filename_number,
        page_number=None,
        text=text,
        char_count=len(text),
        text_hash=source,
        image_hash=source,
        title_candidates=[],
    )


def main() -> int:
    first = make_page("b.png", "第一章 开始\n这是第一段内容，最后一句发生在苹果树下", 20)
    second = make_page("a.png", "后一句发生在苹果树下，然后继续讲第二段内容。", 10)
    duplicate = make_page("dup.png", "第一章 开始\n这是第一段内容，最后一句发生在苹果树下", 30)
    duplicate.text_hash = first.text_hash

    pages = [second, duplicate, first]
    groups = mark_duplicates(pages)
    if len(groups) != 1:
        raise RuntimeError(f"Expected one duplicate group: {groups}")

    representatives = [page for page in pages if not page.duplicate_of]
    ordered = infer_page_order(representatives)
    if [Path(page.source).name for page in ordered] != ["b.png", "a.png"]:
        raise RuntimeError(f"Expected overlap-aware order, got {[page.source for page in ordered]}")
    if ordered[1].previous_overlap_chars < 6:
        raise RuntimeError("Expected duplicated overlap to be recorded as ordering evidence.")
    if not ordered[1].order_reason.startswith("text_overlap_"):
        raise RuntimeError(f"Expected text-overlap ordering reason: {ordered[1].order_reason}")

    markdown = text_to_markdown("第一章 开始\n\n1.1 小节\n正文")
    if "## 第一章 开始" not in markdown or "### 1.1 小节" not in markdown:
        raise RuntimeError(f"Expected heading promotion: {markdown}")

    book = render_book_markdown(Path("截图集"), ordered)
    if "<!-- source: b.png -->" not in book or "## 第一章 开始" not in book:
        raise RuntimeError(f"Expected traceable rebuilt Markdown: {book}")

    events = []
    from ebook_markdown_pipeline.image_book_rebuilder import rebuild_image_book_from_sources  # noqa: PLC0415

    output_dir = Path.cwd().joinpath(".tmp_image_book_progress").resolve()
    result = rebuild_image_book_from_sources(
        [],
        output_dir,
        ocr_mode="never",
        progress_callback=events.append,
    )
    if not Path(result["book"]).exists():
        raise RuntimeError(f"Expected output files from empty rebuild: {result}")
    if not {"ocr", "dedupe", "order", "write"}.issubset({event["stage"] for event in events}):
        raise RuntimeError(f"Expected progress events, got: {events}")
    for path in output_dir.glob("*"):
        path.unlink()
    output_dir.rmdir()

    print("Image book rebuilder smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
