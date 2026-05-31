from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Iterable

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ebook_markdown_pipeline.batch_convert_books import (  # noqa: E402
    close_umi_paddle_engine,
    create_umi_paddle_engine,
    default_options,
    normalize_command_options,
    suggested_umi_paddle_exe,
    suggested_umi_paddle_module,
    umi_ocr_image,
)
from ebook_markdown_pipeline.document_locator import IMAGE_EXTENSIONS  # noqa: E402


@dataclass
class ScreenshotPage:
    source: str
    file_name: str
    width: int
    height: int
    mtime: float
    filename_number: int | None
    page_number: int | None
    text: str
    char_count: int
    text_hash: str
    image_hash: str
    duplicate_group: int | None = None
    duplicate_of: str = ""
    order_index: int | None = None
    order_confidence: float = 0.0
    previous_overlap_chars: int = 0
    order_reason: str = ""
    title_candidates: list[str] | None = None


ProgressCallback = Callable[[dict], None]


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild an ordered Markdown document from screenshots.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="OCR screenshots, deduplicate them, infer order, and write Markdown.")
    build_parser.add_argument("input", type=Path)
    build_parser.add_argument("output", type=Path)
    build_parser.add_argument("--recursive", action="store_true")
    build_parser.add_argument("--ocr", choices=["auto", "never"], default="auto")
    build_parser.add_argument("--include-hidden", action="store_true")
    build_parser.add_argument("--umi-paddle-exe", default=suggested_umi_paddle_exe())
    build_parser.add_argument("--umi-paddle-module", default=suggested_umi_paddle_module())

    args = parser.parse_args()
    if args.command == "build":
        result = rebuild_image_book(
            args.input,
            args.output,
            recursive=args.recursive,
            include_hidden=args.include_hidden,
            ocr_mode=args.ocr,
            umi_paddle_exe=args.umi_paddle_exe,
            umi_paddle_module=args.umi_paddle_module,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    return 2


def rebuild_image_book(
    input_path: Path,
    output_dir: Path,
    *,
    recursive: bool = True,
    include_hidden: bool = False,
    ocr_mode: str = "auto",
    umi_paddle_exe: str | None = None,
    umi_paddle_module: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    emit_progress(progress_callback, "collect", f"Collected image sources from {input_path}")
    sources = collect_image_sources(input_path, recursive=recursive, include_hidden=include_hidden)
    return rebuild_image_book_from_sources(
        sources,
        output_dir,
        input_label=str(input_path),
        title=input_path.stem if input_path.is_file() else input_path.name,
        ocr_mode=ocr_mode,
        umi_paddle_exe=umi_paddle_exe,
        umi_paddle_module=umi_paddle_module,
        progress_callback=progress_callback,
    )


def rebuild_image_book_from_sources(
    sources: Iterable[Path],
    output_dir: Path,
    *,
    input_label: str = "selected images",
    title: str = "Rebuilt Image Book",
    ocr_mode: str = "auto",
    umi_paddle_exe: str | None = None,
    umi_paddle_module: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    source_list = [
        source.resolve()
        for source in sources
        if source.exists() and source.is_file() and source.suffix.lower() in IMAGE_EXTENSIONS
    ]
    emit_progress(progress_callback, "ocr", f"OCR {len(source_list)} image(s)", index=0, total=len(source_list))
    pages = ocr_screenshot_pages(
        source_list,
        ocr_mode=ocr_mode,
        umi_paddle_exe=umi_paddle_exe,
        umi_paddle_module=umi_paddle_module,
        progress_callback=progress_callback,
    )
    emit_progress(progress_callback, "dedupe", "Detect duplicate screenshots")
    duplicate_groups = mark_duplicates(pages)
    representatives = choose_representatives(pages)
    emit_progress(progress_callback, "order", "Infer screenshot order")
    ordered_pages = infer_page_order(representatives)

    pages_jsonl = output_dir / "pages.jsonl"
    clusters_json = output_dir / "clusters.json"
    order_md = output_dir / "order.md"
    review_md = output_dir / "review.md"
    book_md = output_dir / "book.md"

    emit_progress(progress_callback, "write", f"Write outputs to {output_dir}")
    write_pages_jsonl(pages_jsonl, pages)
    clusters_json.write_text(json.dumps(duplicate_groups, ensure_ascii=False, indent=2), encoding="utf-8")
    order_md.write_text(render_order_markdown(ordered_pages), encoding="utf-8")
    review_md.write_text(render_review_markdown(pages, ordered_pages, duplicate_groups), encoding="utf-8")
    book_md.write_text(render_book_markdown(title, ordered_pages), encoding="utf-8")

    return {
        "input": input_label,
        "output": str(output_dir),
        "source_count": len(source_list),
        "page_count": len(pages),
        "representative_count": len(ordered_pages),
        "duplicate_group_count": len(duplicate_groups),
        "book": str(book_md),
        "pages": str(pages_jsonl),
        "clusters": str(clusters_json),
        "order": str(order_md),
        "review": str(review_md),
    }


def collect_image_sources(input_path: Path, *, recursive: bool, include_hidden: bool) -> list[Path]:
    if input_path.is_file():
        return [input_path.resolve()] if input_path.suffix.lower() in IMAGE_EXTENSIONS else []
    if not input_path.exists():
        return []
    root = input_path.resolve()
    pattern = "**/*" if recursive else "*"
    sources = []
    for path in root.glob(pattern):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        relative_parts = path.relative_to(root).parts
        if not include_hidden and any(part.startswith(".") for part in relative_parts):
            continue
        sources.append(path.resolve())
    return sorted(sources, key=natural_sort_key)


def ocr_screenshot_pages(
    sources: Iterable[Path],
    *,
    ocr_mode: str,
    umi_paddle_exe: str | None,
    umi_paddle_module: str | None,
    progress_callback: ProgressCallback | None = None,
) -> list[ScreenshotPage]:
    options = normalize_command_options(
        default_options(
            umi_paddle_exe=umi_paddle_exe or suggested_umi_paddle_exe(),
            umi_paddle_module=umi_paddle_module or suggested_umi_paddle_module(),
        )
    )
    ocr_engine = None
    pages: list[ScreenshotPage] = []
    try:
        if ocr_mode != "never":
            ocr_engine = create_umi_paddle_engine(options)
        source_list = list(sources)
        for index, source in enumerate(source_list, start=1):
            emit_progress(progress_callback, "ocr_page", f"OCR image {index}/{len(source_list)}: {source.name}", index=index, total=len(source_list), source=source)
            text = umi_ocr_image(source, ocr_engine).strip() if ocr_engine is not None else ""
            width, height, image_hash = image_metadata(source)
            normalized_text = normalize_text_for_hash(text)
            titles = detect_title_candidates(text)
            pages.append(
                ScreenshotPage(
                    source=str(source),
                    file_name=source.name,
                    width=width,
                    height=height,
                    mtime=source.stat().st_mtime,
                    filename_number=extract_filename_number(source),
                    page_number=extract_page_number(text),
                    text=text,
                    char_count=len(text),
                    text_hash=short_hash(normalized_text),
                    image_hash=image_hash,
                    title_candidates=titles,
                )
            )
    finally:
        if ocr_engine is not None:
            close_umi_paddle_engine(ocr_engine)
    return pages


def image_metadata(path: Path) -> tuple[int, int, str]:
    import fitz

    try:
        pixmap = fitz.Pixmap(str(path))
        digest = hashlib.sha1(pixmap.samples[: min(len(pixmap.samples), 65536)]).hexdigest()[:16]
        return pixmap.width, pixmap.height, digest
    except Exception:
        stat = path.stat()
        return 0, 0, short_hash(f"{path.name}:{stat.st_size}:{stat.st_mtime}")


def mark_duplicates(pages: list[ScreenshotPage]) -> list[dict]:
    groups: list[list[ScreenshotPage]] = []
    for page in pages:
        matched_group = None
        for group in groups:
            if is_duplicate(page, group[0]):
                matched_group = group
                break
        if matched_group is None:
            groups.append([page])
        else:
            matched_group.append(page)

    duplicate_groups = []
    for group_index, group in enumerate(groups, start=1):
        if len(group) < 2:
            continue
        representative = max(group, key=lambda item: (item.char_count, -len(item.file_name)))
        for page in group:
            page.duplicate_group = group_index
            if page.source != representative.source:
                page.duplicate_of = representative.source
        duplicate_groups.append(
            {
                "group": group_index,
                "representative": representative.source,
                "items": [page.source for page in group],
                "reason": duplicate_reason(group),
            }
        )
    return duplicate_groups


def is_duplicate(left: ScreenshotPage, right: ScreenshotPage) -> bool:
    if left.image_hash == right.image_hash:
        return True
    if left.text_hash == right.text_hash and left.char_count > 20:
        return True
    if left.char_count > 40 and right.char_count > 40:
        return SequenceMatcher(None, normalize_text_for_hash(left.text), normalize_text_for_hash(right.text)).ratio() >= 0.92
    return False


def duplicate_reason(group: list[ScreenshotPage]) -> str:
    image_hashes = {page.image_hash for page in group}
    text_hashes = {page.text_hash for page in group}
    if len(image_hashes) == 1:
        return "same_image_hash"
    if len(text_hashes) == 1:
        return "same_text_hash"
    return "near_duplicate_text"


def choose_representatives(pages: list[ScreenshotPage]) -> list[ScreenshotPage]:
    representatives = []
    skipped = {page.source for page in pages if page.duplicate_of}
    for page in pages:
        if page.source not in skipped:
            representatives.append(page)
    return representatives


def infer_page_order(pages: list[ScreenshotPage]) -> list[ScreenshotPage]:
    if not pages:
        return []
    remaining = sorted(pages, key=base_order_key)
    start_index = choose_start_page_index(remaining)
    ordered = [remaining.pop(start_index)]
    ordered[0].order_confidence = base_order_confidence(ordered[0])
    ordered[0].order_reason = "start"

    while remaining:
        previous = ordered[-1]
        best_index = 0
        best_score = -1.0
        best_overlap = 0
        for index, candidate in enumerate(remaining):
            score, overlap = continuity_score(previous, candidate)
            score += base_order_tie_breaker(candidate, index)
            if score > best_score:
                best_index = index
                best_score = score
                best_overlap = overlap
        next_page = remaining.pop(best_index)
        next_page.previous_overlap_chars = best_overlap
        next_page.order_confidence = min(max(best_score, 0.0), 1.0)
        next_page.order_reason = order_reason(previous, next_page, best_overlap)
        ordered.append(next_page)

    for index, page in enumerate(ordered, start=1):
        page.order_index = index
    return ordered


def choose_start_page_index(pages: list[ScreenshotPage]) -> int:
    if len(pages) == 1:
        return 0
    if all(page.page_number is not None for page in pages):
        return 0

    best_index = 0
    best_score = None
    for index, page in enumerate(pages):
        incoming_overlap = max(
            (suffix_prefix_overlap(other.text, page.text) for other in pages if other.source != page.source),
            default=0,
        )
        outgoing_overlap = max(
            (suffix_prefix_overlap(page.text, other.text) for other in pages if other.source != page.source),
            default=0,
        )
        # A likely first screenshot has little incoming overlap but may have
        # strong outgoing overlap to the next screenshot.
        score = (incoming_overlap, -outgoing_overlap, base_order_key(page))
        if best_score is None or score < best_score:
            best_index = index
            best_score = score
    return best_index


def continuity_score(previous: ScreenshotPage, candidate: ScreenshotPage) -> tuple[float, int]:
    if previous.page_number is not None and candidate.page_number is not None:
        distance = candidate.page_number - previous.page_number
        if distance == 1:
            return 0.95, 0
        if distance > 1:
            return max(0.15, 0.75 - min(distance, 20) * 0.03), 0
        return 0.02, 0

    overlap = suffix_prefix_overlap(previous.text, candidate.text)
    if overlap >= 80:
        return 0.9, overlap
    if overlap >= 30:
        return 0.75, overlap
    if starts_new_section(candidate.text):
        return 0.48, overlap
    return 0.35, overlap


def order_reason(previous: ScreenshotPage, candidate: ScreenshotPage, overlap: int) -> str:
    if previous.page_number is not None and candidate.page_number is not None:
        distance = candidate.page_number - previous.page_number
        if distance == 1:
            return "page_number_continuity"
        if distance > 1:
            return f"page_number_gap_{distance}"
        return "page_number_conflict"
    if overlap:
        return f"text_overlap_{overlap}"
    if starts_new_section(candidate.text):
        return "starts_new_section"
    if candidate.filename_number is not None:
        return "filename_number"
    return "fallback_order"


def suffix_prefix_overlap(left: str, right: str, *, max_chars: int = 500) -> int:
    left_text = compact_text(left)[-max_chars:]
    right_text = compact_text(right)[:max_chars]
    max_len = min(len(left_text), len(right_text), max_chars)
    for length in range(max_len, 7, -1):
        if left_text[-length:] == right_text[:length]:
            return length
        if length >= 12 and SequenceMatcher(None, left_text[-length:], right_text[:length]).ratio() >= 0.82:
            return length
    return 0


def base_order_key(page: ScreenshotPage) -> tuple[int, float, int, str]:
    if page.page_number is not None:
        return (0, float(page.page_number), page.filename_number or 0, page.file_name.lower())
    if page.filename_number is not None:
        return (1, float(page.filename_number), 0, page.file_name.lower())
    return (2, page.mtime, 0, page.file_name.lower())


def base_order_confidence(page: ScreenshotPage) -> float:
    if page.page_number is not None:
        return 0.9
    if page.filename_number is not None:
        return 0.65
    return 0.45


def base_order_tie_breaker(page: ScreenshotPage, index: int) -> float:
    confidence = base_order_confidence(page) * 0.08
    return confidence + max(0.0, 0.04 - index * 0.001)


def render_book_markdown(title: str | Path, pages: list[ScreenshotPage]) -> str:
    title = str(title)
    lines = [f"# {title or 'Rebuilt Image Book'}", ""]
    for page in pages:
        lines.append(f"<!-- source: {page.source} -->")
        if page.order_confidence < 0.45:
            lines.append(f"<!-- low-confidence-order: {page.order_confidence:.2f} -->")
        lines.extend(text_to_markdown(page.text).splitlines())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def text_to_markdown(text: str) -> str:
    output = []
    previous_blank = True
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            if output and output[-1] != "":
                output.append("")
            previous_blank = True
            continue
        heading_level = infer_heading_level(line, previous_blank=previous_blank)
        if heading_level:
            output.append(f"{'#' * heading_level} {line}")
        else:
            output.append(line)
        previous_blank = False
    return "\n".join(output).strip()


def infer_heading_level(line: str, *, previous_blank: bool) -> int | None:
    normalized = line.strip()
    if re.match(r"^(第[一二三四五六七八九十百千万\d]+[章节篇部卷]|Chapter\s+\d+|Part\s+\w+)\b", normalized, re.IGNORECASE):
        return 2
    dotted = re.match(r"^(\d+(?:\.\d+){0,3})[\s、.．]+", normalized)
    if dotted:
        return min(2 + dotted.group(1).count("."), 5)
    if previous_blank and 2 <= len(normalized) <= 28 and not re.search(r"[。！？.!?，,；;：:]$", normalized):
        return 3
    return None


def render_order_markdown(pages: list[ScreenshotPage]) -> str:
    lines = ["# 图片顺序推断 / Inferred Screenshot Order", ""]
    lines.append("| # | Source | Page | Confidence | Reason | Overlap | Title candidates |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for page in pages:
        titles = "; ".join(page.title_candidates or [])
        lines.append(
            f"| {page.order_index} | {markdown_cell(page.source)} | {page.page_number or ''} | "
            f"{page.order_confidence:.2f} | {markdown_cell(page.order_reason)} | {page.previous_overlap_chars} | {markdown_cell(titles)} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def render_review_markdown(
    pages: list[ScreenshotPage],
    ordered_pages: list[ScreenshotPage],
    duplicate_groups: list[dict],
) -> str:
    low_confidence = [page for page in ordered_pages if page.order_confidence < 0.45]
    no_text = [page for page in pages if page.char_count == 0]
    lines = ["# 截图成书复查清单 / Image Book Review", ""]
    lines.append(f"- Total images: {len(pages)}")
    lines.append(f"- Ordered representatives: {len(ordered_pages)}")
    lines.append(f"- Duplicate groups: {len(duplicate_groups)}")
    lines.append(f"- Low-confidence order items: {len(low_confidence)}")
    lines.append(f"- Empty OCR items: {len(no_text)}")
    lines.append("")

    if duplicate_groups:
        lines.extend(["## 重复/近重复截图 / Duplicate Groups", ""])
        for group in duplicate_groups:
            lines.append(f"- Group {group['group']} ({group['reason']}): representative `{group['representative']}`")
            for item in group["items"]:
                lines.append(f"  - `{item}`")
        lines.append("")

    if low_confidence:
        lines.extend(["## 低置信度顺序 / Low Confidence Order", ""])
        for page in low_confidence:
            lines.append(f"- #{page.order_index}: `{page.source}` confidence={page.order_confidence:.2f}")
        lines.append("")

    if no_text:
        lines.extend(["## OCR 为空 / Empty OCR", ""])
        for page in no_text:
            lines.append(f"- `{page.source}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_pages_jsonl(path: Path, pages: Iterable[ScreenshotPage]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for page in pages:
            handle.write(json.dumps(asdict(page), ensure_ascii=False) + "\n")


def detect_title_candidates(text: str) -> list[str]:
    candidates = []
    for line in text.splitlines():
        stripped = line.strip()
        if infer_heading_level(stripped, previous_blank=True):
            candidates.append(stripped)
        if len(candidates) >= 5:
            break
    return candidates


def extract_page_number(text: str) -> int | None:
    candidates = []
    for line in text.splitlines()[:8] + text.splitlines()[-8:]:
        stripped = line.strip()
        match = re.search(r"(?:第\s*)?(\d{1,5})(?:\s*页)?$", stripped)
        if match:
            candidates.append(int(match.group(1)))
    return candidates[-1] if candidates else None


def extract_filename_number(path: Path) -> int | None:
    matches = re.findall(r"\d+", path.stem)
    return int(matches[-1]) if matches else None


def natural_sort_key(path: Path) -> tuple:
    parts = re.split(r"(\d+)", path.name.lower())
    return tuple(int(part) if part.isdigit() else part for part in parts)


def normalize_text_for_hash(text: str) -> str:
    return compact_text(text).lower()


def compact_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def starts_new_section(text: str) -> bool:
    for line in text.splitlines()[:5]:
        if infer_heading_level(line.strip(), previous_blank=True):
            return True
    return False


def short_hash(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8", errors="ignore")
    return hashlib.sha1(value).hexdigest()[:16]


def markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def emit_progress(
    callback: ProgressCallback | None,
    stage: str,
    message: str,
    *,
    index: int | None = None,
    total: int | None = None,
    source: Path | None = None,
) -> None:
    if callback is None:
        return
    callback(
        {
            "stage": stage,
            "message": message,
            "index": index,
            "total": total,
            "source": str(source) if source else "",
        }
    )


if __name__ == "__main__":
    raise SystemExit(main())
