from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from statistics import median
from typing import Iterable

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ebook_markdown_pipeline.artifact_schema import artifact, with_artifacts  # noqa: E402
from ebook_markdown_pipeline.image_book_rebuilder import (  # noqa: E402
    ScreenshotPage,
    load_pages_jsonl,
    rebuild_image_book,
    write_pages_jsonl,
)


TIMESTAMP_PATTERNS = (
    re.compile(r"^\d{1,2}:\d{2}$"),
    re.compile(r"^(?:上午|下午|晚上|凌晨)?\s*\d{1,2}:\d{2}$"),
    re.compile(r"^(?:今天|昨天|前天)\s*(?:上午|下午|晚上|凌晨)?\s*\d{1,2}:\d{2}$"),
    re.compile(r"^\d{1,2}月\d{1,2}日(?:\s+\d{1,2}:\d{2})?$"),
    re.compile(r"^\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?(?:\s+\d{1,2}:\d{2})?$"),
    re.compile(r"^星期[一二三四五六日天](?:\s+\d{1,2}:\d{2})?$"),
)
SYSTEM_PATTERNS = (
    re.compile(r".+撤回了一条消息"),
    re.compile(r".+(?:加入|退出)了群聊"),
    re.compile(r".+拍了拍.+"),
    re.compile(r"^(?:以下|以上)是.+内容$"),
    re.compile(r"^你已添加了.+现在可以开始聊天了$"),
    re.compile(r"^消息已发出，但被对方拒收了$"),
)
MEDIA_PATTERN = re.compile(r"^\[(图片|语音|视频|文件|位置|链接|表情|红包|转账|小程序)\]$")
TOP_CHROME_PATTERN = re.compile(r"^(?:\d{1,2}:\d{2}|[45]G|Wi-?Fi|中国移动|中国联通|中国电信|\d{1,3}%?)$", re.I)
BOTTOM_CHROME_PATTERN = re.compile(r"^(?:发送|按住说话|说点什么|输入消息|更多|表情)$")


@dataclass
class ChatMessage:
    message_id: str
    sequence: int
    kind: str
    speaker: str
    speaker_label: str
    side: str
    text: str
    confidence: float
    source: str
    page_index: int
    block_indexes: list[int] = field(default_factory=list)
    bbox: list[float] | None = None
    reasons: list[str] = field(default_factory=list)
    review_flags: list[str] = field(default_factory=list)
    included: bool = True
    duplicate_of: str = ""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild a reviewable speaker-separated transcript from chat screenshots."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="OCR screenshots and build a chat transcript.")
    build_parser.add_argument("input", type=Path)
    build_parser.add_argument("output", type=Path)
    build_parser.add_argument("--recursive", action="store_true")
    build_parser.add_argument("--ocr-provider", choices=["auto", "umi", "rapidocr"], default="auto")
    add_transcript_arguments(build_parser)

    pages_parser = subparsers.add_parser(
        "from-pages",
        help="Build a chat transcript from an existing image-book pages.jsonl without rerunning OCR.",
    )
    pages_parser.add_argument("pages", type=Path)
    pages_parser.add_argument("output", type=Path)
    add_transcript_arguments(pages_parser)

    args = parser.parse_args()
    if args.command == "build":
        result = rebuild_chat_screenshots(
            args.input,
            args.output,
            recursive=args.recursive,
            ocr_provider=args.ocr_provider,
            title=args.title,
            my_label=args.my_label,
            other_label=args.other_label,
            speaker_mode=args.speaker_mode,
        )
    else:
        result = rebuild_chat_from_pages_jsonl(
            args.pages,
            args.output,
            title=args.title,
            my_label=args.my_label,
            other_label=args.other_label,
            speaker_mode=args.speaker_mode,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def add_transcript_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--title", default="聊天记录")
    parser.add_argument("--my-label", default="我")
    parser.add_argument("--other-label", default="对方")
    parser.add_argument("--speaker-mode", choices=["auto", "left-right"], default="auto")


def rebuild_chat_screenshots(
    input_path: Path,
    output_dir: Path,
    *,
    recursive: bool = True,
    ocr_provider: str = "auto",
    title: str = "聊天记录",
    my_label: str = "我",
    other_label: str = "对方",
    speaker_mode: str = "auto",
) -> dict:
    source_dir = output_dir / "_image_book_source"
    source_result = rebuild_image_book(
        input_path,
        source_dir,
        recursive=recursive,
        ocr_provider=ocr_provider,
        enhance_layout_heavy="never",
    )
    result = rebuild_chat_from_pages_jsonl(
        Path(source_result["pages"]),
        output_dir,
        title=title,
        my_label=my_label,
        other_label=other_label,
        speaker_mode=speaker_mode,
    )
    result["input"] = str(input_path)
    result["source_rebuild"] = source_result
    return result


def rebuild_chat_from_pages_jsonl(
    pages_jsonl: Path,
    output_dir: Path,
    *,
    title: str = "聊天记录",
    my_label: str = "我",
    other_label: str = "对方",
    speaker_mode: str = "auto",
) -> dict:
    pages = load_pages_jsonl(pages_jsonl)
    return rebuild_chat_from_pages(
        pages,
        output_dir,
        input_label=str(pages_jsonl),
        title=title,
        my_label=my_label,
        other_label=other_label,
        speaker_mode=speaker_mode,
    )


def rebuild_chat_from_pages(
    pages: Iterable[ScreenshotPage],
    output_dir: Path,
    *,
    input_label: str = "pages",
    title: str = "聊天记录",
    my_label: str = "我",
    other_label: str = "对方",
    speaker_mode: str = "auto",
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    page_list = ordered_representative_pages(list(pages))
    messages: list[ChatMessage] = []
    skipped_blocks: list[dict] = []
    fallback_pages: list[str] = []

    for page_index, page in enumerate(page_list, start=1):
        page_messages, page_skipped, used_fallback = messages_from_page(
            page,
            page_index=page_index,
            my_label=my_label,
            other_label=other_label,
            speaker_mode=speaker_mode,
        )
        messages.extend(page_messages)
        skipped_blocks.extend(page_skipped)
        if used_fallback:
            fallback_pages.append(page.source)

    renumber_messages(messages)
    duplicate_count, possible_duplicates = deduplicate_page_overlaps(messages)
    renumber_messages(messages)

    chat_md = output_dir / "chat.md"
    chat_jsonl = output_dir / "chat.jsonl"
    review_md = output_dir / "review.md"
    output_pages = output_dir / "pages.jsonl"
    write_pages_jsonl(output_pages, page_list)
    chat_md.write_text(render_chat_markdown(title, messages), encoding="utf-8", newline="\n")
    write_chat_jsonl(chat_jsonl, messages)
    review_md.write_text(
        render_review_markdown(
            messages,
            fallback_pages=fallback_pages,
            skipped_blocks=skipped_blocks,
            possible_duplicates=possible_duplicates,
        ),
        encoding="utf-8",
        newline="\n",
    )

    included = [message for message in messages if message.included]
    review_count = sum(1 for message in included if message.review_flags)
    return with_artifacts(
        {
            "input": input_label,
            "output": str(output_dir),
            "page_count": len(page_list),
            "message_count": len(included),
            "review_count": review_count,
            "duplicate_count": duplicate_count,
            "fallback_page_count": len(fallback_pages),
            "speaker_mode": speaker_mode,
            "chat": str(chat_md),
            "chat_jsonl": str(chat_jsonl),
            "review": str(review_md),
            "pages": str(output_pages),
            "warnings": transcript_warnings(page_list, included, review_count, fallback_pages),
        },
        [
            artifact("chat_markdown", chat_md, label="Speaker-separated chat transcript", media_type="text/markdown"),
            artifact("chat_jsonl", chat_jsonl, label="Message-level chat records", media_type="application/x-jsonlines"),
            artifact("review_report", review_md, label="Chat transcript review", media_type="text/markdown"),
            artifact("pages_jsonl", output_pages, label="Source OCR pages", media_type="application/x-jsonlines"),
        ],
    )


def ordered_representative_pages(pages: list[ScreenshotPage]) -> list[ScreenshotPage]:
    representatives = [page for page in pages if not page.duplicate_of]
    return sorted(
        representatives,
        key=lambda page: (
            page.order_index is None,
            page.order_index or 0,
            page.filename_number is None,
            page.filename_number or 0,
            page.mtime,
            page.file_name.lower(),
        ),
    )


def messages_from_page(
    page: ScreenshotPage,
    *,
    page_index: int,
    my_label: str,
    other_label: str,
    speaker_mode: str,
) -> tuple[list[ChatMessage], list[dict], bool]:
    blocks = normalized_page_blocks(page)
    if not blocks:
        messages = fallback_messages_from_text(
            page,
            page_index=page_index,
            my_label=my_label,
            other_label=other_label,
        )
        return messages, [], bool(page.text.strip())

    block_heights = [block["bbox"][3] - block["bbox"][1] for block in blocks]
    typical_height = max(8.0, median(block_heights))
    messages: list[ChatMessage] = []
    skipped: list[dict] = []
    for block in blocks:
        classification = classify_block(
            block,
            page=page,
            my_label=my_label,
            other_label=other_label,
            speaker_mode=speaker_mode,
        )
        if classification["kind"] == "chrome":
            skipped.append({"source": page.source, **block, "reason": classification["reasons"][0]})
            continue
        message = ChatMessage(
            message_id="",
            sequence=0,
            kind=classification["kind"],
            speaker=classification["speaker"],
            speaker_label=classification["speaker_label"],
            side=classification["side"],
            text=block["text"],
            confidence=classification["confidence"],
            source=page.source,
            page_index=page_index,
            block_indexes=[block["index"]],
            bbox=block["bbox"],
            reasons=classification["reasons"],
            review_flags=classification["review_flags"],
        )
        if messages and should_merge_messages(messages[-1], message, typical_height=typical_height, page_width=page.width):
            merge_message(messages[-1], message)
        else:
            messages.append(message)
    return messages, skipped, False


def normalized_page_blocks(page: ScreenshotPage) -> list[dict]:
    blocks = []
    for fallback_index, raw in enumerate(page.ocr_blocks or [], start=1):
        text = str(raw.get("text") or "").strip()
        bbox = normalize_bbox(raw.get("bbox"))
        if not text or bbox is None:
            continue
        blocks.append(
            {
                "index": int(raw.get("index") or fallback_index),
                "text": text,
                "bbox": bbox,
                "score": normalized_score(raw.get("score")),
            }
        )
    return sorted(blocks, key=lambda item: (item["bbox"][1], item["bbox"][0], item["index"]))


def classify_block(
    block: dict,
    *,
    page: ScreenshotPage,
    my_label: str,
    other_label: str,
    speaker_mode: str,
) -> dict:
    text = block["text"].strip()
    x1, y1, x2, y2 = block["bbox"]
    width = max(float(page.width), x2, 1.0)
    height = max(float(page.height), y2, 1.0)
    center = ((x1 + x2) / 2.0) / width
    score = block.get("score")

    if y2 <= height * 0.08 and TOP_CHROME_PATTERN.fullmatch(text):
        return block_classification("chrome", "system", "系统", "center", 0.98, ["top_ui_chrome"])
    if y1 >= height * 0.90 and BOTTOM_CHROME_PATTERN.fullmatch(text):
        return block_classification("chrome", "system", "系统", "center", 0.98, ["bottom_input_chrome"])
    if is_timestamp_text(text):
        confidence = 0.98 if 0.30 <= center <= 0.70 else 0.82
        return block_classification("timestamp", "system", "时间", "center", confidence, ["timestamp_pattern"])
    if is_system_text(text):
        return block_classification("system", "system", "系统", "center", 0.92, ["system_text_pattern"])

    media = bool(MEDIA_PATTERN.fullmatch(text))
    kind = "media" if media else "message"
    if center <= 0.46 or (x1 / width <= 0.18 and x2 / width < 0.72):
        confidence = side_confidence(center, "left", score)
        return block_classification(kind, "other", other_label, "left", confidence, ["left_aligned_ocr_block"])
    if center >= 0.54 or (x1 / width > 0.28 and x2 / width >= 0.82):
        confidence = side_confidence(center, "right", score)
        return block_classification(kind, "me", my_label, "right", confidence, ["right_aligned_ocr_block"])

    flags = ["unknown_speaker"]
    if speaker_mode == "auto":
        flags.append("ambiguous_horizontal_position")
    return block_classification(kind, "unknown", "未知", "unknown", 0.35, ["crosses_chat_centerline"], flags)


def block_classification(
    kind: str,
    speaker: str,
    speaker_label: str,
    side: str,
    confidence: float,
    reasons: list[str],
    review_flags: list[str] | None = None,
) -> dict:
    return {
        "kind": kind,
        "speaker": speaker,
        "speaker_label": speaker_label,
        "side": side,
        "confidence": round(max(0.0, min(1.0, confidence)), 3),
        "reasons": reasons,
        "review_flags": list(review_flags or []),
    }


def should_merge_messages(previous: ChatMessage, current: ChatMessage, *, typical_height: float, page_width: int) -> bool:
    if previous.source != current.source:
        return False
    if previous.kind not in {"message", "media"} or current.kind not in {"message", "media"}:
        return False
    if previous.speaker != current.speaker or previous.speaker == "unknown":
        return False
    if previous.bbox is None or current.bbox is None:
        return False
    gap = current.bbox[1] - previous.bbox[3]
    left_delta = abs(current.bbox[0] - previous.bbox[0])
    return -typical_height * 0.25 <= gap <= typical_height * 0.80 and left_delta <= max(24.0, page_width * 0.08)


def merge_message(target: ChatMessage, addition: ChatMessage) -> None:
    target.text = f"{target.text}\n{addition.text}"
    target.block_indexes.extend(addition.block_indexes)
    target.confidence = round(min(target.confidence, addition.confidence), 3)
    target.reasons = list(dict.fromkeys([*target.reasons, "merged_adjacent_ocr_lines", *addition.reasons]))
    target.review_flags = list(dict.fromkeys([*target.review_flags, *addition.review_flags]))
    if target.bbox and addition.bbox:
        target.bbox = [
            min(target.bbox[0], addition.bbox[0]),
            min(target.bbox[1], addition.bbox[1]),
            max(target.bbox[2], addition.bbox[2]),
            max(target.bbox[3], addition.bbox[3]),
        ]


def fallback_messages_from_text(
    page: ScreenshotPage,
    *,
    page_index: int,
    my_label: str,
    other_label: str,
) -> list[ChatMessage]:
    messages = []
    for line in (line.strip() for line in page.text.splitlines()):
        if not line:
            continue
        kind = "timestamp" if is_timestamp_text(line) else "system" if is_system_text(line) else "message"
        speaker = "system" if kind != "message" else "unknown"
        label = "时间" if kind == "timestamp" else "系统" if kind == "system" else "未知"
        flags = [] if kind != "message" else ["missing_ocr_coordinates", "unknown_speaker"]
        messages.append(
            ChatMessage(
                message_id="",
                sequence=0,
                kind=kind,
                speaker=speaker,
                speaker_label=label,
                side="center" if kind != "message" else "unknown",
                text=line,
                confidence=0.75 if kind != "message" else 0.20,
                source=page.source,
                page_index=page_index,
                reasons=["text_only_fallback"],
                review_flags=flags,
            )
        )
    return messages


def deduplicate_page_overlaps(messages: list[ChatMessage]) -> tuple[int, list[dict]]:
    duplicate_count = 0
    possible_duplicates: list[dict] = []
    page_indexes = sorted({message.page_index for message in messages})
    for previous_page, current_page in zip(page_indexes, page_indexes[1:]):
        previous = [message for message in messages if message.page_index == previous_page and message.included]
        current = [message for message in messages if message.page_index == current_page and message.included]
        overlap = exact_suffix_prefix_overlap(previous, current, limit=12)
        for index in range(overlap):
            current[index].included = False
            current[index].duplicate_of = previous[len(previous) - overlap + index].message_id
            current[index].review_flags = list(dict.fromkeys([*current[index].review_flags, "cross_page_duplicate"]))
            duplicate_count += 1
        if overlap == 0:
            possible = possible_single_overlap(previous[-5:], current[:5])
            if possible:
                possible_duplicates.append(possible)
                current[possible["current_index"]].review_flags = list(
                    dict.fromkeys([*current[possible["current_index"]].review_flags, "possible_duplicate"])
                )
    return duplicate_count, possible_duplicates


def exact_suffix_prefix_overlap(previous: list[ChatMessage], current: list[ChatMessage], *, limit: int) -> int:
    max_size = min(limit, len(previous), len(current))
    for size in range(max_size, 0, -1):
        left = [message_fingerprint(message) for message in previous[-size:]]
        right = [message_fingerprint(message) for message in current[:size]]
        if left != right:
            continue
        if size >= 2 or len(normalize_text(previous[-1].text)) >= 12:
            return size
    return 0


def possible_single_overlap(previous: list[ChatMessage], current: list[ChatMessage]) -> dict | None:
    for previous_index, left in enumerate(previous):
        left_text = normalize_text(left.text)
        if len(left_text) < 12:
            continue
        for current_index, right in enumerate(current):
            if left.speaker != right.speaker:
                continue
            ratio = SequenceMatcher(None, left_text, normalize_text(right.text)).ratio()
            if ratio >= 0.93:
                return {
                    "previous_id": left.message_id,
                    "current_id": right.message_id,
                    "current_index": current_index,
                    "similarity": round(ratio, 3),
                }
    return None


def renumber_messages(messages: list[ChatMessage]) -> None:
    for sequence, message in enumerate(messages, start=1):
        message.sequence = sequence
        message.message_id = f"msg-{sequence:06d}"


def render_chat_markdown(title: str, messages: list[ChatMessage]) -> str:
    lines = [
        f"# {title}",
        "",
        "> 由聊天截图坐标自动整理。说话人不确定的内容标为“未知”，请结合 `review.md` 复查。",
        "",
    ]
    for message in messages:
        if not message.included:
            continue
        text = message.text.replace("\r", "").strip()
        if message.kind == "timestamp":
            lines.extend([f"### {text}", ""])
        elif message.kind == "system":
            lines.extend([f"> [系统] {text}", ""])
        else:
            lines.extend([f"**{message.speaker_label}**：{text}", ""])
    return "\n".join(lines).rstrip() + "\n"


def render_review_markdown(
    messages: list[ChatMessage],
    *,
    fallback_pages: list[str],
    skipped_blocks: list[dict],
    possible_duplicates: list[dict],
) -> str:
    included = [message for message in messages if message.included]
    review_items = [message for message in included if message.review_flags]
    unknown = [message for message in included if message.speaker == "unknown"]
    duplicates = [message for message in messages if not message.included]
    lines = [
        "# 聊天截图复查清单 / Chat Screenshot Review",
        "",
        f"- Included messages: {len(included)}",
        f"- Review items: {len(review_items)}",
        f"- Unknown speaker: {len(unknown)}",
        f"- Removed cross-page duplicates: {len(duplicates)}",
        f"- Text-only fallback pages: {len(fallback_pages)}",
        f"- Skipped UI chrome blocks: {len(skipped_blocks)}",
        "",
        "## 当前假设 / Assumptions",
        "",
        "- 左侧聊天内容视为“对方”，右侧视为“我”。",
        "- 居中的时间和系统提示不归入任何说话人。",
        "- 只有跨相邻截图首尾完全重叠的消息会自动去重；模糊重复只提示复查。",
        "- 群聊昵称、引用回复、转发记录、表情/语音等复杂组件尚未可靠解析。",
        "",
    ]
    if review_items:
        lines.extend(["## 需要复查 / Needs Review", ""])
        for message in review_items:
            flags = ", ".join(message.review_flags)
            lines.append(
                f"- `{message.message_id}` `{Path(message.source).name}` "
                f"speaker={message.speaker_label} confidence={message.confidence:.2f} flags={flags}: "
                f"{markdown_inline(message.text)}"
            )
        lines.append("")
    if duplicates:
        lines.extend(["## 已去除的跨图重复 / Removed Overlap Duplicates", ""])
        for message in duplicates:
            lines.append(
                f"- `{message.message_id}` -> `{message.duplicate_of}` "
                f"`{Path(message.source).name}`: {markdown_inline(message.text)}"
            )
        lines.append("")
    if possible_duplicates:
        lines.extend(["## 疑似重复 / Possible Duplicates", ""])
        for item in possible_duplicates:
            lines.append(
                f"- `{item['current_id']}` may repeat `{item['previous_id']}` "
                f"(similarity={item['similarity']:.3f})"
            )
        lines.append("")
    if fallback_pages:
        lines.extend(["## 缺少坐标 / Missing OCR Coordinates", ""])
        for source in fallback_pages:
            lines.append(f"- `{source}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_chat_jsonl(path: Path, messages: Iterable[ChatMessage]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for message in messages:
            handle.write(json.dumps(asdict(message), ensure_ascii=False) + "\n")


def transcript_warnings(
    pages: list[ScreenshotPage],
    messages: list[ChatMessage],
    review_count: int,
    fallback_pages: list[str],
) -> list[str]:
    warnings = []
    if not pages:
        warnings.append("No screenshot pages were available.")
    if not messages:
        warnings.append("No chat messages were reconstructed.")
    if review_count:
        warnings.append(f"{review_count} message(s) require review.")
    if fallback_pages:
        warnings.append(f"{len(fallback_pages)} page(s) lacked OCR coordinates; speaker assignment was not attempted.")
    return warnings


def is_timestamp_text(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text.strip())
    return any(pattern.fullmatch(normalized) for pattern in TIMESTAMP_PATTERNS)


def is_system_text(text: str) -> bool:
    normalized = re.sub(r"\s+", "", text.strip())
    return any(pattern.fullmatch(normalized) for pattern in SYSTEM_PATTERNS)


def normalize_bbox(raw: object) -> list[float] | None:
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        x1, y1, x2, y2 = [float(value) for value in raw]
    except (TypeError, ValueError):
        return None
    return [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]


def normalized_score(value: object) -> float | None:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def side_confidence(center: float, side: str, score: float | None) -> float:
    geometric = min(0.98, 0.68 + abs(center - 0.5) * 1.1)
    if side == "left" and center > 0.5 or side == "right" and center < 0.5:
        geometric = 0.45
    return round(geometric if score is None else min(geometric, 0.55 + score * 0.45), 3)


def message_fingerprint(message: ChatMessage) -> tuple[str, str, str]:
    return message.kind, message.speaker, normalize_text(message.text)


def normalize_text(text: str) -> str:
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE).lower()


def markdown_inline(text: str) -> str:
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " / ").strip()


if __name__ == "__main__":
    raise SystemExit(main())
