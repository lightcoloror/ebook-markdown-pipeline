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
from ebook_markdown_pipeline.artifact_schema import artifact, with_artifacts  # noqa: E402
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
    ocr_status: str = "ok"
    ocr_message: str = ""
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

    reorder_parser = subparsers.add_parser("rebuild-from-order", help="Rebuild Markdown from pages.jsonl and a manually edited order.md.")
    reorder_parser.add_argument("pages", type=Path)
    reorder_parser.add_argument("order", type=Path)
    reorder_parser.add_argument("output", type=Path)
    reorder_parser.add_argument("--title", default="")

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
    if args.command == "rebuild-from-order":
        result = rebuild_image_book_from_order(args.pages, args.order, args.output, title=args.title)
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
    structure_md = output_dir / "structure.md"
    structure_json = output_dir / "structure.json"
    book_md = output_dir / "book.md"

    emit_progress(progress_callback, "write", f"Write outputs to {output_dir}")
    write_pages_jsonl(pages_jsonl, pages)
    clusters_json.write_text(json.dumps(duplicate_groups, ensure_ascii=False, indent=2), encoding="utf-8")
    order_md.write_text(render_order_markdown(ordered_pages), encoding="utf-8")
    review_md.write_text(render_review_markdown(pages, ordered_pages, duplicate_groups), encoding="utf-8")
    structure_payload = build_structure_outline(ordered_pages)
    structure_json.write_text(json.dumps(structure_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    structure_md.write_text(render_structure_markdown(structure_payload), encoding="utf-8")
    book_md.write_text(render_book_markdown(title, ordered_pages), encoding="utf-8")

    return with_artifacts(
        {
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
        "structure": str(structure_md),
        "structure_json": str(structure_json),
        },
        [
            artifact("markdown", book_md, label="Rebuilt Markdown", media_type="text/markdown"),
            artifact("pages_jsonl", pages_jsonl, label="Per-image OCR metadata", media_type="application/x-jsonlines"),
            artifact("clusters_json", clusters_json, label="Duplicate groups", media_type="application/json"),
            artifact("order_report", order_md, label="Inferred order report", media_type="text/markdown"),
            artifact("structure_report", structure_md, label="Inferred structure outline", media_type="text/markdown"),
            artifact("structure_json", structure_json, label="Inferred structure outline JSON", media_type="application/json"),
            artifact("review_report", review_md, label="Image book review checklist", media_type="text/markdown"),
        ],
    )


def rebuild_image_book_from_order(
    pages_jsonl: Path,
    order_markdown: Path,
    output_dir: Path,
    *,
    title: str = "",
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    pages = load_pages_jsonl(pages_jsonl)
    manual_sources = parse_order_markdown_sources(order_markdown)
    page_by_source = {normalize_source_key(page.source): page for page in pages}
    ordered_pages: list[ScreenshotPage] = []
    missing_sources: list[str] = []
    used_sources: set[str] = set()

    for source in manual_sources:
        key = normalize_source_key(source)
        page = page_by_source.get(key)
        if page is None:
            missing_sources.append(source)
            continue
        used_sources.add(key)
        ordered_pages.append(page)

    remaining_pages = [page for page in pages if normalize_source_key(page.source) not in used_sources and not page.duplicate_of]
    if remaining_pages:
        ordered_pages.extend(infer_page_order(remaining_pages))

    for index, page in enumerate(ordered_pages, start=1):
        page.order_index = index
        if normalize_source_key(page.source) in used_sources:
            page.order_confidence = max(page.order_confidence, 0.99)
            page.order_reason = "manual order.md"

    book_md = output_dir / "book.md"
    order_md = output_dir / "order.md"
    review_md = output_dir / "review.md"
    structure_md = output_dir / "structure.md"
    structure_json = output_dir / "structure.json"
    book_title = title or output_dir.name or "Rebuilt Image Book"
    book_md.write_text(render_book_markdown(book_title, ordered_pages), encoding="utf-8", newline="\n")
    order_md.write_text(render_order_markdown(ordered_pages), encoding="utf-8", newline="\n")
    review_md.write_text(render_manual_order_review_markdown(pages_jsonl, order_markdown, ordered_pages, missing_sources, remaining_pages), encoding="utf-8", newline="\n")
    structure_payload = build_structure_outline(ordered_pages)
    structure_json.write_text(json.dumps(structure_payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    structure_md.write_text(render_structure_markdown(structure_payload), encoding="utf-8", newline="\n")

    return with_artifacts(
        {
            "input": str(pages_jsonl),
            "order": str(order_markdown),
            "output": str(output_dir),
            "page_count": len(pages),
            "manual_order_count": len(manual_sources),
            "ordered_count": len(ordered_pages),
            "missing_source_count": len(missing_sources),
            "appended_unordered_count": len(remaining_pages),
            "book": str(book_md),
            "rebuilt_order": str(order_md),
            "review": str(review_md),
            "structure": str(structure_md),
            "structure_json": str(structure_json),
            "warnings": manual_order_warnings(missing_sources, remaining_pages),
        },
        [
            artifact("markdown", book_md, label="Manually reordered Markdown", media_type="text/markdown"),
            artifact("order_report", order_md, label="Rebuilt order report", media_type="text/markdown"),
            artifact("structure_report", structure_md, label="Inferred structure outline", media_type="text/markdown"),
            artifact("structure_json", structure_json, label="Inferred structure outline JSON", media_type="application/json"),
            artifact("review_report", review_md, label="Manual order review", media_type="text/markdown"),
        ],
    )


def load_pages_jsonl(path: Path) -> list[ScreenshotPage]:
    pages: list[ScreenshotPage] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            pages.append(ScreenshotPage(**data))
    return pages


def parse_order_markdown_sources(path: Path) -> list[str]:
    sources: list[str] = []
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line.startswith("|") or "Source" in line or re.match(r"^\|\s*-+", line):
            continue
        cells = split_markdown_table_row(line)
        if len(cells) < 2:
            continue
        source = cells[1].strip().replace("\\|", "|")
        if source:
            sources.append(source)
    return sources


def split_markdown_table_row(line: str) -> list[str]:
    cells: list[str] = []
    current = []
    escaped = False
    trimmed = line.strip()
    if trimmed.startswith("|"):
        trimmed = trimmed[1:]
    if trimmed.endswith("|"):
        trimmed = trimmed[:-1]
    for char in trimmed:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            current.append(char)
            escaped = True
            continue
        if char == "|":
            cells.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    cells.append("".join(current).strip())
    return cells


def normalize_source_key(source: str) -> str:
    return str(Path(source)).replace("\\", "/").lower()


def manual_order_warnings(missing_sources: list[str], remaining_pages: list[ScreenshotPage]) -> list[str]:
    warnings = []
    if missing_sources:
        warnings.append(f"{len(missing_sources)} source(s) in order.md were not found in pages.jsonl.")
    if remaining_pages:
        warnings.append(f"{len(remaining_pages)} page(s) were not listed in order.md and were appended automatically.")
    return warnings


def render_manual_order_review_markdown(
    pages_jsonl: Path,
    order_markdown: Path,
    ordered_pages: list[ScreenshotPage],
    missing_sources: list[str],
    remaining_pages: list[ScreenshotPage],
) -> str:
    lines = [
        "# 人工顺序重建复查 / Manual Order Rebuild Review",
        "",
        f"- Pages: `{pages_jsonl}`",
        f"- Edited order: `{order_markdown}`",
        f"- Ordered pages: {len(ordered_pages)}",
        f"- Missing sources in pages.jsonl: {len(missing_sources)}",
        f"- Appended unordered pages: {len(remaining_pages)}",
        "",
    ]
    if missing_sources:
        lines.extend(["## Missing Sources", ""])
        for source in missing_sources:
            lines.append(f"- `{source}`")
        lines.append("")
    if remaining_pages:
        lines.extend(["## Appended Pages", ""])
        for page in remaining_pages:
            lines.append(f"- `{page.source}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


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
    def reset_ocr_engine() -> None:
        nonlocal ocr_engine
        if ocr_engine is not None:
            close_umi_paddle_engine(ocr_engine)
        ocr_engine = create_umi_paddle_engine(options)

    try:
        if ocr_mode != "never":
            reset_ocr_engine()
        source_list = list(sources)
        for index, source in enumerate(source_list, start=1):
            emit_progress(progress_callback, "ocr_page", f"OCR image {index}/{len(source_list)}: {source.name}", index=index, total=len(source_list), source=source)
            text = ""
            ocr_status = "skipped" if ocr_engine is None else "ok"
            ocr_message = ""
            if ocr_engine is not None:
                try:
                    text = umi_ocr_image(source, ocr_engine).strip()
                except Exception as exc:  # noqa: BLE001
                    first_error = str(exc)
                    try:
                        reset_ocr_engine()
                        text = umi_ocr_image(source, ocr_engine).strip()
                        ocr_message = f"Recovered after OCR engine restart: {first_error}"
                    except Exception as retry_exc:  # noqa: BLE001
                        ocr_status = "failed"
                        ocr_message = f"{first_error}; retry failed: {retry_exc}"
            width, height, image_hash = image_metadata(source)
            normalized_text = normalize_text_for_hash(text)
            titles = detect_title_candidates(text)
            filename_number = extract_filename_number(source)
            pages.append(
                ScreenshotPage(
                    source=str(source),
                    file_name=source.name,
                    width=width,
                    height=height,
                    mtime=source.stat().st_mtime,
                    filename_number=filename_number,
                    page_number=extract_page_number(text, filename_number=filename_number),
                    text=text,
                    char_count=len(text),
                    text_hash=short_hash(normalized_text),
                    image_hash=image_hash,
                    ocr_status=ocr_status,
                    ocr_message=ocr_message,
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
    text = remove_repeated_screenshot_noise(text)
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


def remove_repeated_screenshot_noise(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    counts: dict[str, int] = {}
    for line in lines:
        key = screenshot_noise_key(line)
        if key:
            counts[key] = counts.get(key, 0) + 1
    noisy = {key for key, count in counts.items() if count >= 3 and len(key) <= 18}
    if not noisy:
        return text
    cleaned = []
    for line in lines:
        key = screenshot_noise_key(line)
        if key in noisy:
            cleaned.append(f"<!-- repeated screenshot header/footer: {line.strip()} -->")
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


def screenshot_noise_key(line: str) -> str:
    stripped = re.sub(r"\s+", "", line.strip())
    if not stripped or len(stripped) > 24:
        return ""
    if re.match(r"^\d{1,4}$", stripped):
        return ""
    if re.match(r"^(第[一二三四五六七八九十百千万\d]+[章节篇部卷]|Chapter\d+|Part\w+)", stripped, re.I):
        return ""
    if re.search(r"[。！？!?；;：:，,、]$", stripped):
        return ""
    return stripped


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


def score_title_candidate(line: str, *, line_index: int, previous_blank: bool, next_blank: bool) -> tuple[float, list[str], int | None]:
    normalized = line.strip()
    signals: list[str] = []
    level = infer_heading_level(normalized, previous_blank=previous_blank)
    score = 0.0
    if level:
        score += 0.55
        signals.append(f"heading_pattern_level_{level}")
    if line_index <= 6:
        score += 0.12
        signals.append("near_page_top")
    if previous_blank:
        score += 0.08
        signals.append("previous_blank")
    if next_blank:
        score += 0.08
        signals.append("next_blank")
    if 2 <= len(normalized) <= 32 and not re.search(r"[。！？.!?，,；;：:]$", normalized):
        score += 0.18
        signals.append("short_title_like_line")
    if re.search(r"^(序|前言|目录|后记|附录|致谢|引言|绪论)$", normalized, re.I):
        score += 0.25
        signals.append("front_matter_title")
        level = level or 2
    if re.search(r"^(chapter|section|part)\b", normalized, re.I):
        score += 0.18
        signals.append("english_heading_keyword")
        level = level or 2
    if re.match(r"^\d+(?:\.\d+){0,3}\s+.+", normalized):
        score += 0.2
        signals.append("numbered_heading")
        level = level or infer_heading_level(normalized, previous_blank=True)
    if re.search(r"^[\-•·*]\s+", normalized):
        score -= 0.35
        signals.append("list_item_penalty")
    if len(normalized) > 48:
        score -= 0.3
        signals.append("too_long_penalty")
    if re.search(r"[。！？.!?]$", normalized):
        score -= 0.25
        signals.append("sentence_ending_penalty")
    return max(0.0, min(score, 1.0)), signals, level


def detect_title_candidate_details(text: str, *, limit: int = 6) -> list[dict]:
    normalized_lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    details = []
    for index, line in enumerate(normalized_lines):
        if not line:
            continue
        previous_blank = index == 0 or not normalized_lines[index - 1]
        next_blank = index == len(normalized_lines) - 1 or not normalized_lines[index + 1]
        score, signals, level = score_title_candidate(
            line,
            line_index=index,
            previous_blank=previous_blank,
            next_blank=next_blank,
        )
        if score < 0.42:
            continue
        details.append(
            {
                "title": line,
                "level": level or 3,
                "confidence": round(score, 3),
                "signals": signals,
                "line_index": index,
            }
        )
    details.sort(key=lambda item: (-float(item["confidence"]), int(item["line_index"])))
    return details[:limit]


def build_structure_outline(pages: list[ScreenshotPage]) -> dict:
    items = []
    for page in pages:
        details = title_details_for_page(page)
        for detail in details:
            title = str(detail.get("title") or "")
            items.append(
                {
                    "order_index": page.order_index,
                    "source": page.source,
                    "page_number": page.page_number,
                    "level": int(detail.get("level") or 3),
                    "title": title,
                    "confidence": detail.get("confidence"),
                    "signals": detail.get("signals") or [],
                    "line_index": detail.get("line_index"),
                    "order_confidence": round(page.order_confidence, 3),
                    "order_reason": page.order_reason,
                }
            )
    return {
        "schema_version": "image-book-structure-v1",
        "item_count": len(items),
        "page_count": len(pages),
        "items": items,
    }


def title_details_for_page(page: ScreenshotPage) -> list[dict]:
    details = detect_title_candidate_details(page.text)
    if details:
        return details
    fallback = page.title_candidates or detect_title_candidates(page.text)
    return [
        {
            "title": title,
            "level": infer_heading_level(title, previous_blank=True) or 3,
            "confidence": 0.5,
            "signals": ["legacy_title_candidate"],
            "line_index": None,
        }
        for title in fallback
    ]


def render_structure_markdown(payload: dict) -> str:
    lines = [
        "# 结构草图 / Inferred Structure Outline",
        "",
        f"- Pages: {payload.get('page_count', 0)}",
        f"- Structure items: {payload.get('item_count', 0)}",
        "",
    ]
    items = payload.get("items") or []
    if not items:
        lines.append("No title candidates were detected. Check `review.md` and `pages.jsonl` before accepting the rebuilt Markdown.")
        return "\n".join(lines).rstrip() + "\n"
    for item in items:
        level = max(1, min(int(item.get("level") or 3), 6))
        prefix = "#" * level
        page = item.get("page_number") or ""
        source = item.get("source") or ""
        confidence = item.get("order_confidence")
        reason = item.get("order_reason") or ""
        title_confidence = item.get("confidence")
        signals = ", ".join(str(value) for value in item.get("signals") or [])
        lines.append(f"{prefix} {item.get('title')}")
        lines.append("")
        lines.append(f"- Source: `{source}`")
        if page:
            lines.append(f"- Page number: {page}")
        if title_confidence is not None:
            lines.append(f"- Title confidence: {title_confidence}")
        if signals:
            lines.append(f"- Title signals: {signals}")
        lines.append(f"- Order confidence: {confidence}")
        lines.append(f"- Order reason: {reason}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


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
    ocr_failed = [page for page in pages if page.ocr_status == "failed"]
    ocr_recovered = [page for page in pages if page.ocr_status == "ok" and page.ocr_message]
    lines = ["# 截图成书复查清单 / Image Book Review", ""]
    lines.append(f"- Total images: {len(pages)}")
    lines.append(f"- Ordered representatives: {len(ordered_pages)}")
    lines.append(f"- Duplicate groups: {len(duplicate_groups)}")
    lines.append(f"- Low-confidence order items: {len(low_confidence)}")
    lines.append(f"- Empty OCR items: {len(no_text)}")
    lines.append(f"- OCR failed items: {len(ocr_failed)}")
    lines.append(f"- OCR recovered items: {len(ocr_recovered)}")
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
    if ocr_failed:
        lines.extend(["## OCR 失败 / OCR Failed", ""])
        for page in ocr_failed:
            lines.append(f"- `{page.source}`: {markdown_cell(page.ocr_message)}")
        lines.append("")
    if ocr_recovered:
        lines.extend(["## OCR 重试恢复 / OCR Recovered After Retry", ""])
        for page in ocr_recovered:
            lines.append(f"- `{page.source}`: {markdown_cell(page.ocr_message)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_pages_jsonl(path: Path, pages: Iterable[ScreenshotPage]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for page in pages:
            handle.write(json.dumps(asdict(page), ensure_ascii=False) + "\n")


def detect_title_candidates(text: str) -> list[str]:
    return [str(item["title"]) for item in detect_title_candidate_details(text, limit=5)]


def extract_page_number(text: str, *, filename_number: int | None = None) -> int | None:
    candidates = []
    for line in text.splitlines()[:8] + text.splitlines()[-8:]:
        stripped = line.strip()
        fraction = re.search(r"\b0*(\d{1,4})\s*[/／]\s*0*(\d{1,4})\b", stripped)
        if fraction:
            page = int(fraction.group(1))
            total = int(fraction.group(2))
            if 1 <= page <= max(total, page):
                return page
        compact_digits = re.sub(r"\D+", "", stripped)
        if filename_number is not None and compact_digits:
            # OCR often turns "01/08" into "01108" or "041 08".
            # If the OCR line begins with the filename/page sequence, trust
            # the filename-local number instead of the noisy raw OCR number.
            filename_variants = {
                str(filename_number),
                str(filename_number).zfill(2),
                str(filename_number).zfill(3),
            }
            if any(compact_digits.startswith(prefix) for prefix in filename_variants) and len(compact_digits) >= 3:
                return filename_number
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
