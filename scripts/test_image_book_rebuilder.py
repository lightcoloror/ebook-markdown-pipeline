from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ebook_markdown_pipeline.image_book_rebuilder import (  # noqa: E402
    ScreenshotPage,
    extract_page_number,
    infer_page_order,
    mark_duplicates,
    rebuild_image_book_from_order,
    render_book_markdown,
    text_to_markdown,
    write_pages_jsonl,
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
    if extract_page_number("03/08", filename_number=3) != 3:
        raise RuntimeError("Expected slash page number extraction.")
    if extract_page_number("03108", filename_number=3) != 3:
        raise RuntimeError("Expected OCR-noisy page number to trust filename sequence.")
    if extract_page_number("041 08", filename_number=4) != 4:
        raise RuntimeError("Expected spaced OCR-noisy page number to trust filename sequence.")

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
    artifact_types = {item["type"] for item in result.get("artifacts", [])}
    expected_artifacts = {"markdown", "pages_jsonl", "clusters_json", "order_report", "review_report"}
    if not expected_artifacts.issubset(artifact_types):
        raise RuntimeError(f"Expected image book artifacts: {result}")
    if not {"ocr", "dedupe", "order", "write"}.issubset({event["stage"] for event in events}):
        raise RuntimeError(f"Expected progress events, got: {events}")
    for path in output_dir.glob("*"):
        path.unlink()
    output_dir.rmdir()

    with tempfile.TemporaryDirectory(prefix="image-book-ocr-failure-") as tmp:
        root = Path(tmp)
        image_a = root / "001.png"
        image_b = root / "002.png"
        image_a.write_bytes(b"not-a-real-png-a")
        image_b.write_bytes(b"not-a-real-png-b")

        import ebook_markdown_pipeline.image_book_rebuilder as rebuilder  # noqa: PLC0415

        original_create = rebuilder.create_umi_paddle_engine
        original_close = rebuilder.close_umi_paddle_engine
        original_ocr = rebuilder.umi_ocr_image
        calls = {"ocr": 0}

        try:
            rebuilder.create_umi_paddle_engine = lambda options: object()
            rebuilder.close_umi_paddle_engine = lambda engine: None

            def flaky_ocr(source: Path, engine) -> str:
                calls["ocr"] += 1
                if source.name == "001.png":
                    raise RuntimeError("simulated Umi-OCR JSON failure")
                return "第二页 正文"

            rebuilder.umi_ocr_image = flaky_ocr
            robust_output = root / "robust"
            robust = rebuild_image_book_from_sources([image_a, image_b], robust_output, ocr_mode="auto")
            review = Path(robust["review"]).read_text(encoding="utf-8")
            pages_text = Path(robust["pages"]).read_text(encoding="utf-8")
            if "OCR 失败" not in review or "simulated Umi-OCR JSON failure" not in review:
                raise RuntimeError(f"Expected per-image OCR failure in review: {review}")
            if '"ocr_status": "failed"' not in pages_text:
                raise RuntimeError(f"Expected failed OCR status in pages.jsonl: {pages_text}")
            if calls["ocr"] < 3:
                raise RuntimeError("Expected OCR retry after first-image failure.")
        finally:
            rebuilder.create_umi_paddle_engine = original_create
            rebuilder.close_umi_paddle_engine = original_close
            rebuilder.umi_ocr_image = original_ocr

    with tempfile.TemporaryDirectory(prefix="image-book-manual-order-") as tmp:
        root = Path(tmp)
        pages_jsonl = root / "pages.jsonl"
        order_md = root / "order.md"
        manual_output = root / "manual"
        write_pages_jsonl(pages_jsonl, [first, second])
        order_md.write_text(
            "\n".join(
                [
                    "# 图片顺序推断 / Inferred Screenshot Order",
                    "",
                    "| # | Source | Page | Confidence | Reason | Overlap | Title candidates |",
                    "| --- | --- | --- | --- | --- | --- | --- |",
                    "| 1 | a.png |  | 0.65 | manual | 0 |  |",
                    "| 2 | b.png |  | 0.65 | manual | 0 |  |",
                ]
            ),
            encoding="utf-8",
        )
        manual = rebuild_image_book_from_order(pages_jsonl, order_md, manual_output, title="人工排序")
        manual_book = Path(manual["book"]).read_text(encoding="utf-8")
        if manual_book.find("<!-- source: a.png -->") > manual_book.find("<!-- source: b.png -->"):
            raise RuntimeError(f"Expected manual order to place a.png before b.png: {manual_book}")
        if manual["manual_order_count"] != 2 or manual["missing_source_count"] != 0:
            raise RuntimeError(f"Unexpected manual rebuild metadata: {manual}")
        manual_artifacts = {item["type"] for item in manual.get("artifacts", [])}
        if not {"markdown", "order_report", "review_report"}.issubset(manual_artifacts):
            raise RuntimeError(f"Expected manual rebuild artifacts: {manual}")

    print("Image book rebuilder smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
