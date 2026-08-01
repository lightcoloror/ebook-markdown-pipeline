from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ebook_markdown_pipeline.chat_screenshot_rebuilder import rebuild_chat_from_pages  # noqa: E402
from ebook_markdown_pipeline.image_book_rebuilder import ScreenshotPage  # noqa: E402


def make_page(name: str, order_index: int, blocks: list[dict], text: str = "") -> ScreenshotPage:
    page_text = text or "\n".join(str(block.get("text") or "") for block in blocks)
    return ScreenshotPage(
        source=str(Path(name).resolve()),
        file_name=name,
        width=1000,
        height=1600,
        mtime=float(order_index),
        filename_number=order_index,
        page_number=None,
        text=page_text,
        char_count=len(page_text),
        text_hash=name,
        image_hash=name,
        order_index=order_index,
        order_confidence=0.95,
        order_reason="test",
        title_candidates=[],
        ocr_blocks=blocks,
    )


def block(index: int, text: str, bbox: list[int], score: float = 0.95) -> dict:
    return {"index": index, "text": text, "bbox": bbox, "score": score}


def main() -> int:
    first = make_page(
        "chat-001.png",
        1,
        [
            block(1, "09:30", [440, 120, 560, 150]),
            block(2, "你好，最近怎么样？", [90, 220, 400, 252]),
            block(3, "项目进展顺利吗？", [92, 258, 410, 290]),
            block(4, "挺顺利的，今天刚交付。", [585, 350, 930, 385]),
            block(5, "张三撤回了一条消息", [375, 450, 625, 482]),
            block(6, "发送", [900, 1510, 980, 1550]),
        ],
    )
    second = make_page(
        "chat-002.png",
        2,
        [
            block(1, "挺顺利的，今天刚交付。", [585, 130, 930, 165]),
            block(2, "张三撤回了一条消息", [375, 220, 625, 252]),
            block(3, "那太好了。", [90, 330, 300, 365]),
            block(4, "这条横跨中线，无法可靠判断是谁发的", [260, 430, 740, 466]),
        ],
    )
    fallback = make_page("chat-003.png", 3, [], text="缺少坐标的一条消息")

    output = Path.cwd() / ".tmp_chat_rebuilder_test"
    if output.exists():
        shutil.rmtree(output)
    output.mkdir()
    try:
        result = rebuild_chat_from_pages(
            [second, fallback, first],
            output,
            title="测试聊天",
            my_label="我",
            other_label="客户",
        )

        if result["page_count"] != 3:
            raise RuntimeError(f"Expected three ordered pages: {result}")
        if result["duplicate_count"] != 2:
            raise RuntimeError(f"Expected two exact cross-page overlap messages: {result}")
        if result["fallback_page_count"] != 1:
            raise RuntimeError(f"Expected one text-only fallback page: {result}")
        if result["review_count"] < 2:
            raise RuntimeError(f"Expected ambiguous and fallback review items: {result}")

        markdown = Path(result["chat"]).read_text(encoding="utf-8")
        if "**客户**：你好，最近怎么样？\n项目进展顺利吗？" not in markdown:
            raise RuntimeError(f"Expected adjacent left OCR lines to merge: {markdown}")
        if markdown.count("挺顺利的，今天刚交付。") != 1:
            raise RuntimeError(f"Expected cross-page duplicate to be removed: {markdown}")
        if "**未知**：这条横跨中线" not in markdown or "**未知**：缺少坐标的一条消息" not in markdown:
            raise RuntimeError(f"Expected uncertain speakers to remain explicit: {markdown}")
        if "发送" in markdown:
            raise RuntimeError(f"Expected bottom input chrome to be skipped: {markdown}")

        rows = [
            json.loads(line)
            for line in Path(result["chat_jsonl"]).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if not any(not row["included"] and row["duplicate_of"] for row in rows):
            raise RuntimeError(f"Expected traceable removed duplicates: {rows}")
        if not any("unknown_speaker" in row["review_flags"] for row in rows):
            raise RuntimeError(f"Expected unknown-speaker review flags: {rows}")

        review = Path(result["review"]).read_text(encoding="utf-8")
        if "Removed cross-page duplicates: 2" not in review:
            raise RuntimeError(f"Expected duplicate summary: {review}")
        if "Text-only fallback pages: 1" not in review:
            raise RuntimeError(f"Expected fallback summary: {review}")

        artifact_types = {item["type"] for item in result["artifacts"]}
        expected = {"chat_markdown", "chat_jsonl", "review_report", "pages_jsonl"}
        if not expected.issubset(artifact_types):
            raise RuntimeError(f"Expected chat artifacts: {result}")
    finally:
        shutil.rmtree(output)

    print("Chat screenshot rebuilder smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())