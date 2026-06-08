from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
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
    mineru_environment,
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
    ocr_blocks: list[dict] | None = None
    layout_profile: dict | None = None
    layout_enhancements: list[dict] | None = None
    split_group: str = ""
    split_index: int | None = None
    split_y_start: int | None = None
    split_y_end: int | None = None


ProgressCallback = Callable[[dict], None]


def default_vlm_python() -> str:
    candidate = Path(r"C:\Users\lightcolor\.conda\envs\pytorch-cuda121\python.exe")
    return str(candidate) if candidate.exists() else sys.executable


def default_paddleocr_vl_command() -> str:
    script = Path(__file__).resolve().parent / "scripts" / "paddleocr_vl_image_to_md.py"
    if not script.exists():
        return ""
    return f'"{default_vlm_python()}" "{script}" --input {{input}} --output {{output}}'


def default_qwen_vl_command() -> str:
    script = Path(__file__).resolve().parent / "scripts" / "qwen_vl_image_to_md.py"
    if not script.exists():
        return ""
    return f'"{default_vlm_python()}" "{script}" --input {{input}} --output {{output}}'


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
    build_parser.add_argument("--no-auto-split-long-images", action="store_true")
    build_parser.add_argument("--long-image-threshold-ratio", type=float, default=3.0)
    build_parser.add_argument("--long-image-threshold-height", type=int, default=4200)
    build_parser.add_argument("--long-image-chunk-height", type=int, default=2200)
    build_parser.add_argument("--long-image-overlap", type=int, default=180)
    build_parser.add_argument("--enhance-layout-heavy", choices=["auto", "never"], default="auto")
    build_parser.add_argument("--layout-enhancer-order", default="paddleocr-vl,mineru-vlm,qwen-vl")
    build_parser.add_argument("--layout-enhancer-timeout", type=float, default=180.0)
    build_parser.add_argument("--mineru-command", default="mineru")
    build_parser.add_argument("--mineru-method", default="auto")
    build_parser.add_argument("--mineru-backend", default="vlm-transformers")
    build_parser.add_argument("--mineru-lang", default="ch")
    build_parser.add_argument("--paddleocr-vl-command", default=os.environ.get("PADDLEOCR_VL_COMMAND", default_paddleocr_vl_command()))
    build_parser.add_argument("--qwen-vl-command", default=os.environ.get("QWEN_VL_COMMAND", default_qwen_vl_command()))

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
            auto_split_long_images=not args.no_auto_split_long_images,
            long_image_threshold_ratio=args.long_image_threshold_ratio,
            long_image_threshold_height=args.long_image_threshold_height,
            long_image_chunk_height=args.long_image_chunk_height,
            long_image_overlap=args.long_image_overlap,
            enhance_layout_heavy=args.enhance_layout_heavy,
            layout_enhancer_order=args.layout_enhancer_order,
            layout_enhancer_timeout=args.layout_enhancer_timeout,
            mineru_command=args.mineru_command,
            mineru_method=args.mineru_method,
            mineru_backend=args.mineru_backend,
            mineru_lang=args.mineru_lang,
            paddleocr_vl_command=args.paddleocr_vl_command,
            qwen_vl_command=args.qwen_vl_command,
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
    auto_split_long_images: bool = True,
    long_image_threshold_ratio: float = 3.0,
    long_image_threshold_height: int = 4200,
    long_image_chunk_height: int = 2200,
    long_image_overlap: int = 180,
    enhance_layout_heavy: str = "auto",
    layout_enhancer_order: str = "paddleocr-vl,mineru-vlm,qwen-vl",
    layout_enhancer_timeout: float = 180.0,
    mineru_command: str = "mineru",
    mineru_method: str = "auto",
    mineru_backend: str = "vlm-transformers",
    mineru_lang: str = "ch",
    paddleocr_vl_command: str = "",
    qwen_vl_command: str = "",
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
        auto_split_long_images=auto_split_long_images,
        long_image_threshold_ratio=long_image_threshold_ratio,
        long_image_threshold_height=long_image_threshold_height,
        long_image_chunk_height=long_image_chunk_height,
        long_image_overlap=long_image_overlap,
        enhance_layout_heavy=enhance_layout_heavy,
        layout_enhancer_order=layout_enhancer_order,
        layout_enhancer_timeout=layout_enhancer_timeout,
        mineru_command=mineru_command,
        mineru_method=mineru_method,
        mineru_backend=mineru_backend,
        mineru_lang=mineru_lang,
        paddleocr_vl_command=paddleocr_vl_command,
        qwen_vl_command=qwen_vl_command,
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
    auto_split_long_images: bool = True,
    long_image_threshold_ratio: float = 3.0,
    long_image_threshold_height: int = 4200,
    long_image_chunk_height: int = 2200,
    long_image_overlap: int = 180,
    enhance_layout_heavy: str = "auto",
    layout_enhancer_order: str = "paddleocr-vl,mineru-vlm,qwen-vl",
    layout_enhancer_timeout: float = 180.0,
    mineru_command: str = "mineru",
    mineru_method: str = "auto",
    mineru_backend: str = "vlm-transformers",
    mineru_lang: str = "ch",
    paddleocr_vl_command: str = "",
    qwen_vl_command: str = "",
    progress_callback: ProgressCallback | None = None,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    source_list = [
        source.resolve()
        for source in sources
        if source.exists() and source.is_file() and source.suffix.lower() in IMAGE_EXTENSIONS
    ]
    split_manifest = []
    if auto_split_long_images:
        source_list, split_manifest = expand_long_image_sources(
            source_list,
            output_dir / "_auto_split",
            threshold_ratio=long_image_threshold_ratio,
            threshold_height=long_image_threshold_height,
            chunk_height=long_image_chunk_height,
            overlap=long_image_overlap,
            progress_callback=progress_callback,
        )
    emit_progress(progress_callback, "ocr", f"OCR {len(source_list)} image(s)", index=0, total=len(source_list))
    pages = ocr_screenshot_pages(
        source_list,
        ocr_mode=ocr_mode,
        umi_paddle_exe=umi_paddle_exe,
        umi_paddle_module=umi_paddle_module,
        progress_callback=progress_callback,
    )
    attach_split_metadata(pages, split_manifest)
    emit_progress(progress_callback, "dedupe", "Detect duplicate screenshots")
    duplicate_groups = mark_duplicates(pages)
    representatives = choose_representatives(pages)
    emit_progress(progress_callback, "order", "Infer screenshot order")
    ordered_pages = infer_page_order(representatives)
    enhancement_payload = run_layout_heavy_enhancements(
        ordered_pages,
        output_dir,
        mode=enhance_layout_heavy,
        order=layout_enhancer_order,
        timeout_seconds=layout_enhancer_timeout,
        mineru_command=mineru_command,
        mineru_method=mineru_method,
        mineru_backend=mineru_backend,
        mineru_lang=mineru_lang,
        paddleocr_vl_command=paddleocr_vl_command or default_paddleocr_vl_command(),
        qwen_vl_command=qwen_vl_command or default_qwen_vl_command(),
        progress_callback=progress_callback,
    )

    pages_jsonl = output_dir / "pages.jsonl"
    clusters_json = output_dir / "clusters.json"
    order_md = output_dir / "order.md"
    review_md = output_dir / "review.md"
    structure_md = output_dir / "structure.md"
    structure_json = output_dir / "structure.json"
    layout_md = output_dir / "layout.md"
    enhancement_md = output_dir / "enhancement.md"
    enhancement_json = output_dir / "enhancement.json"
    enhanced_md = output_dir / "enhanced.md"
    book_md = output_dir / "book.md"

    emit_progress(progress_callback, "write", f"Write outputs to {output_dir}")
    write_pages_jsonl(pages_jsonl, pages)
    clusters_json.write_text(json.dumps(duplicate_groups, ensure_ascii=False, indent=2), encoding="utf-8")
    order_md.write_text(render_order_markdown(ordered_pages), encoding="utf-8")
    review_md.write_text(render_review_markdown(pages, ordered_pages, duplicate_groups), encoding="utf-8")
    structure_payload = build_structure_outline(ordered_pages)
    structure_json.write_text(json.dumps(structure_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    structure_md.write_text(render_structure_markdown(structure_payload), encoding="utf-8")
    layout_md.write_text(render_layout_markdown(ordered_pages), encoding="utf-8")
    enhancement_json.write_text(json.dumps(enhancement_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    enhancement_md.write_text(render_enhancement_markdown(enhancement_payload), encoding="utf-8")
    book_md.write_text(render_book_markdown(title, ordered_pages), encoding="utf-8")
    enhanced_md.write_text(render_book_markdown(title, ordered_pages, prefer_enhanced=True), encoding="utf-8")

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
        "layout": str(layout_md),
        "enhancement": str(enhancement_md),
        "enhancement_json": str(enhancement_json),
        "enhanced_book": str(enhanced_md),
        },
        [
            artifact("markdown", book_md, label="Rebuilt Markdown", media_type="text/markdown"),
            artifact("pages_jsonl", pages_jsonl, label="Per-image OCR metadata", media_type="application/x-jsonlines"),
            artifact("clusters_json", clusters_json, label="Duplicate groups", media_type="application/json"),
            artifact("order_report", order_md, label="Inferred order report", media_type="text/markdown"),
            artifact("structure_report", structure_md, label="Inferred structure outline", media_type="text/markdown"),
            artifact("structure_json", structure_json, label="Inferred structure outline JSON", media_type="application/json"),
            artifact("layout_report", layout_md, label="Image layout and infographic review", media_type="text/markdown"),
            artifact("enhancement_report", enhancement_md, label="Layout-heavy enhancement report", media_type="text/markdown"),
            artifact("enhancement_json", enhancement_json, label="Layout-heavy enhancement JSON", media_type="application/json"),
            artifact("enhanced_markdown", enhanced_md, label="Enhanced Markdown", media_type="text/markdown"),
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
    layout_md = output_dir / "layout.md"
    enhancement_md = output_dir / "enhancement.md"
    enhancement_json = output_dir / "enhancement.json"
    enhanced_md = output_dir / "enhanced.md"
    book_title = title or output_dir.name or "Rebuilt Image Book"
    book_md.write_text(render_book_markdown(book_title, ordered_pages), encoding="utf-8", newline="\n")
    enhanced_md.write_text(render_book_markdown(book_title, ordered_pages, prefer_enhanced=True), encoding="utf-8", newline="\n")
    order_md.write_text(render_order_markdown(ordered_pages), encoding="utf-8", newline="\n")
    review_md.write_text(render_manual_order_review_markdown(pages_jsonl, order_markdown, ordered_pages, missing_sources, remaining_pages), encoding="utf-8", newline="\n")
    structure_payload = build_structure_outline(ordered_pages)
    structure_json.write_text(json.dumps(structure_payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    structure_md.write_text(render_structure_markdown(structure_payload), encoding="utf-8", newline="\n")
    layout_md.write_text(render_layout_markdown(ordered_pages), encoding="utf-8", newline="\n")
    enhancement_payload = build_existing_enhancement_payload(ordered_pages)
    enhancement_json.write_text(json.dumps(enhancement_payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    enhancement_md.write_text(render_enhancement_markdown(enhancement_payload), encoding="utf-8", newline="\n")

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
            "layout": str(layout_md),
            "enhancement": str(enhancement_md),
            "enhancement_json": str(enhancement_json),
            "enhanced_book": str(enhanced_md),
            "warnings": manual_order_warnings(missing_sources, remaining_pages),
        },
        [
            artifact("markdown", book_md, label="Manually reordered Markdown", media_type="text/markdown"),
            artifact("order_report", order_md, label="Rebuilt order report", media_type="text/markdown"),
            artifact("structure_report", structure_md, label="Inferred structure outline", media_type="text/markdown"),
            artifact("structure_json", structure_json, label="Inferred structure outline JSON", media_type="application/json"),
            artifact("layout_report", layout_md, label="Image layout and infographic review", media_type="text/markdown"),
            artifact("enhancement_report", enhancement_md, label="Layout-heavy enhancement report", media_type="text/markdown"),
            artifact("enhancement_json", enhancement_json, label="Layout-heavy enhancement JSON", media_type="application/json"),
            artifact("enhanced_markdown", enhanced_md, label="Enhanced Markdown", media_type="text/markdown"),
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


def expand_long_image_sources(
    sources: list[Path],
    split_root: Path,
    *,
    threshold_ratio: float,
    threshold_height: int,
    chunk_height: int,
    overlap: int,
    progress_callback: ProgressCallback | None = None,
) -> tuple[list[Path], list[dict]]:
    expanded: list[Path] = []
    manifest: list[dict] = []
    for source in sources:
        width, height, _ = image_metadata(source)
        if not should_split_long_image(width, height, threshold_ratio=threshold_ratio, threshold_height=threshold_height):
            expanded.append(source)
            continue
        emit_progress(progress_callback, "split_long_image", f"Split long image: {source.name}", source=source)
        parts = split_long_image(
            source,
            split_root / safe_name(source.stem),
            chunk_height=chunk_height,
            overlap=overlap,
            width=width,
            height=height,
        )
        expanded.extend(Path(item["path"]) for item in parts)
        manifest.extend(parts)
    if manifest:
        split_root.mkdir(parents=True, exist_ok=True)
        (split_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    return expanded, manifest


def should_split_long_image(width: int, height: int, *, threshold_ratio: float, threshold_height: int) -> bool:
    if width <= 0 or height <= 0:
        return False
    return height >= threshold_height and height / max(width, 1) >= threshold_ratio


def split_long_image(
    source: Path,
    output_dir: Path,
    *,
    chunk_height: int,
    overlap: int,
    width: int,
    height: int,
) -> list[dict]:
    from PIL import Image

    output_dir.mkdir(parents=True, exist_ok=True)
    chunk_height = max(400, int(chunk_height or 2200))
    overlap = max(0, min(int(overlap or 0), chunk_height // 2))
    records = []
    image = Image.open(source)
    index = 1
    y = 0
    while y < height:
        y2 = min(height, y + chunk_height)
        part = image.crop((0, y, width, y2))
        part_path = output_dir / f"{index:03d}_{y:05d}-{y2:05d}_{safe_name(source.stem)}{source.suffix.lower() or '.png'}"
        part.save(part_path)
        records.append(
            {
                "source": str(source),
                "path": str(part_path.resolve()),
                "split_group": str(source.resolve()),
                "split_index": index,
                "split_y_start": y,
                "split_y_end": y2,
                "width": width,
                "height": height,
                "overlap": overlap,
            }
        )
        if y2 >= height:
            break
        y = max(0, y2 - overlap)
        index += 1
    return records


def attach_split_metadata(pages: list[ScreenshotPage], manifest: list[dict]) -> None:
    if not manifest:
        return
    by_path = {normalize_source_key(str(item.get("path") or "")): item for item in manifest}
    for page in pages:
        item = by_path.get(normalize_source_key(page.source))
        if not item:
            continue
        page.split_group = str(item.get("split_group") or "")
        page.split_index = int(item["split_index"]) if item.get("split_index") is not None else None
        page.split_y_start = int(item["split_y_start"]) if item.get("split_y_start") is not None else None
        page.split_y_end = int(item["split_y_end"]) if item.get("split_y_end") is not None else None
        page.order_confidence = max(page.order_confidence, 0.99)
        page.order_reason = "auto_split_filename_order"


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
            ocr_blocks: list[dict] = []
            ocr_status = "skipped" if ocr_engine is None else "ok"
            ocr_message = ""
            if ocr_engine is not None:
                try:
                    text, ocr_blocks = umi_ocr_image_with_blocks(source, ocr_engine)
                    text = text.strip()
                except Exception as exc:  # noqa: BLE001
                    first_error = str(exc)
                    try:
                        reset_ocr_engine()
                        text, ocr_blocks = umi_ocr_image_with_blocks(source, ocr_engine)
                        text = text.strip()
                        ocr_message = f"Recovered after OCR engine restart: {first_error}"
                    except Exception as retry_exc:  # noqa: BLE001
                        ocr_status = "failed"
                        ocr_message = f"{first_error}; retry failed: {retry_exc}"
            width, height, image_hash = image_metadata(source)
            normalized_text = normalize_text_for_hash(text)
            titles = detect_title_candidates(text)
            filename_number = extract_filename_number(source)
            layout_profile = build_layout_profile(text, ocr_blocks, width=width, height=height)
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
                    ocr_blocks=ocr_blocks,
                    layout_profile=layout_profile,
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


def run_layout_heavy_enhancements(
    pages: list[ScreenshotPage],
    output_dir: Path,
    *,
    mode: str,
    order: str,
    timeout_seconds: float,
    mineru_command: str,
    mineru_method: str,
    mineru_backend: str,
    mineru_lang: str,
    paddleocr_vl_command: str,
    qwen_vl_command: str,
    progress_callback: ProgressCallback | None,
) -> dict:
    targets = [page for page in pages if is_likely_infographic(page)]
    payload = {
        "schema_version": "image-layout-enhancement-v1",
        "mode": mode,
        "target_count": len(targets),
        "timeout_seconds": timeout_seconds,
        "backends": parse_enhancer_order(order),
        "items": [],
    }
    if mode == "never" or not targets:
        payload["status"] = "skipped"
        payload["reason"] = "disabled" if mode == "never" else "no layout-heavy pages"
        return payload

    enhancement_root = output_dir / "layout_enhancement"
    enhancement_root.mkdir(parents=True, exist_ok=True)
    for index, page in enumerate(targets, start=1):
        emit_progress(
            progress_callback,
            "layout_enhance",
            f"Enhance layout-heavy image {index}/{len(targets)}: {Path(page.source).name}",
            index=index,
            total=len(targets),
            source=Path(page.source),
        )
        item = {
            "source": page.source,
            "file_name": page.file_name,
            "signals": (page.layout_profile or {}).get("signals") or [],
            "attempts": [],
            "status": "skipped",
        }
        page.layout_enhancements = []
        for backend in payload["backends"]:
            attempt = run_layout_enhancer_backend(
                backend,
                page,
                enhancement_root,
                timeout_seconds=timeout_seconds,
                mineru_command=mineru_command,
                mineru_method=mineru_method,
                mineru_backend=mineru_backend,
                mineru_lang=mineru_lang,
                paddleocr_vl_command=paddleocr_vl_command,
                qwen_vl_command=qwen_vl_command,
            )
            item["attempts"].append(attempt)
            page.layout_enhancements.append(attempt)
            if attempt.get("status") == "ok" and attempt.get("text"):
                item["status"] = "ok"
                item["selected_backend"] = backend
                break
            if attempt.get("status") == "ok":
                item["status"] = "ok_empty"
                item["selected_backend"] = backend
                break
        if item["status"] == "skipped":
            item["status"] = "unavailable_or_failed"
        payload["items"].append(item)
    ok_count = sum(1 for item in payload["items"] if item.get("status") in {"ok", "ok_empty"})
    payload["status"] = "ok" if ok_count == len(targets) else "partial" if ok_count else "failed"
    payload["ok_count"] = ok_count
    return payload


def parse_enhancer_order(order: str) -> list[str]:
    aliases = {
        "mineru": "mineru-vlm",
        "mineru-vlm": "mineru-vlm",
        "paddle": "paddleocr-vl",
        "paddleocr": "paddleocr-vl",
        "paddleocr-vl": "paddleocr-vl",
        "qwen": "qwen-vl",
        "qwen-vl": "qwen-vl",
    }
    parsed = []
    for raw in re.split(r"[,;\s]+", order or ""):
        key = raw.strip().lower()
        if not key:
            continue
        backend = aliases.get(key)
        if backend and backend not in parsed:
            parsed.append(backend)
    return parsed or ["paddleocr-vl", "mineru-vlm", "qwen-vl"]


def run_layout_enhancer_backend(
    backend: str,
    page: ScreenshotPage,
    output_root: Path,
    *,
    timeout_seconds: float,
    mineru_command: str,
    mineru_method: str,
    mineru_backend: str,
    mineru_lang: str,
    paddleocr_vl_command: str,
    qwen_vl_command: str,
) -> dict:
    backend_dir = output_root / safe_name(Path(page.source).stem) / backend
    backend_dir.mkdir(parents=True, exist_ok=True)
    if backend == "mineru-vlm":
        return run_mineru_vlm_image_enhancer(
            page,
            backend_dir,
            timeout_seconds=timeout_seconds,
            mineru_command=mineru_command,
            mineru_method=mineru_method,
            mineru_backend=mineru_backend,
            mineru_lang=mineru_lang,
        )
    if backend == "paddleocr-vl":
        return run_template_image_enhancer("paddleocr-vl", paddleocr_vl_command, page, backend_dir, timeout_seconds)
    if backend == "qwen-vl":
        return run_template_image_enhancer("qwen-vl", qwen_vl_command, page, backend_dir, timeout_seconds)
    return {"backend": backend, "status": "skipped", "reason": "unknown backend"}


def run_mineru_vlm_image_enhancer(
    page: ScreenshotPage,
    output_dir: Path,
    *,
    timeout_seconds: float,
    mineru_command: str,
    mineru_method: str,
    mineru_backend: str,
    mineru_lang: str,
) -> dict:
    executable = resolve_executable(mineru_command)
    if not executable:
        return {"backend": "mineru-vlm", "status": "skipped", "reason": f"command not found: {mineru_command}"}
    cmd = [
        executable,
        "-p",
        page.source,
        "-o",
        str(output_dir),
        "-m",
        mineru_method or "auto",
        "-b",
        mineru_backend or "vlm-transformers",
        "-l",
        mineru_lang or "ch",
    ]
    args = argparse.Namespace(mineru_model_source="huggingface", mineru_hf_endpoint="https://hf-mirror.com")
    return run_enhancement_command("mineru-vlm", cmd, output_dir, timeout_seconds, env=mineru_environment(args))


def run_template_image_enhancer(
    backend: str,
    command_template: str,
    page: ScreenshotPage,
    output_dir: Path,
    timeout_seconds: float,
) -> dict:
    if not command_template.strip():
        return {"backend": backend, "status": "skipped", "reason": "command template is not configured"}
    output_file = output_dir / "enhanced.md"
    command_text = command_template.format(input=page.source, output=str(output_file), output_dir=str(output_dir))
    cmd = [part.strip('"') for part in shlex.split(command_text, posix=False)]
    if not cmd:
        return {"backend": backend, "status": "skipped", "reason": "empty command template"}
    executable = resolve_executable(cmd[0])
    if not executable:
        return {"backend": backend, "status": "skipped", "reason": f"command not found: {cmd[0]}"}
    cmd[0] = executable
    return run_enhancement_command(backend, cmd, output_dir, timeout_seconds)


def run_enhancement_command(
    backend: str,
    cmd: list[str],
    output_dir: Path,
    timeout_seconds: float,
    *,
    env: dict[str, str] | None = None,
) -> dict:
    started = {
        "backend": backend,
        "status": "running",
        "command": subprocess.list2cmdline(cmd),
        "output_dir": str(output_dir),
    }
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(output_dir),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_seconds if timeout_seconds > 0 else None,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        started.update({"status": "timeout", "reason": f"timed out after {timeout_seconds:.0f}s", "stdout_tail": tail_text(exc.stdout or "")})
        return started
    except Exception as exc:  # noqa: BLE001
        started.update({"status": "failed", "reason": str(exc)})
        return started

    text_path, text = pick_enhancement_text(output_dir)
    started.update(
        {
            "status": "ok" if completed.returncode == 0 else "failed",
            "returncode": completed.returncode,
            "stdout_tail": tail_text(completed.stdout or ""),
            "artifact": str(text_path) if text_path else "",
            "text": text,
        }
    )
    if completed.returncode != 0 and not started.get("reason"):
        started["reason"] = "non-zero exit"
    return started


def pick_enhancement_text(output_dir: Path) -> tuple[Path | None, str]:
    candidates = sorted(output_dir.rglob("*.md")) + sorted(output_dir.rglob("*.txt"))
    for candidate in candidates:
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            continue
        if text:
            return candidate, text[:20000]
    json_candidates = sorted(output_dir.rglob("*.json"))
    for candidate in json_candidates:
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            continue
        if text:
            return candidate, text[:20000]
    return None, ""


def resolve_executable(command: str) -> str:
    command = str(command or "").strip().strip('"')
    if not command:
        return ""
    path = Path(command)
    if path.exists():
        return str(path)
    found = shutil.which(command)
    return found or ""


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^\w.\-]+", "_", value, flags=re.UNICODE).strip("._")
    return cleaned[:80] or "image"


def tail_text(text: str, limit: int = 3000) -> str:
    text = text if isinstance(text, str) else str(text or "")
    return text[-limit:]


def build_existing_enhancement_payload(pages: list[ScreenshotPage]) -> dict:
    items = []
    for page in pages:
        enhancements = page.layout_enhancements or []
        if not enhancements:
            continue
        selected = next((item for item in enhancements if item.get("status") == "ok"), enhancements[0])
        items.append(
            {
                "source": page.source,
                "file_name": page.file_name,
                "signals": (page.layout_profile or {}).get("signals") or [],
                "status": selected.get("status") or "unknown",
                "selected_backend": selected.get("backend") or "",
                "attempts": enhancements,
            }
        )
    return {
        "schema_version": "image-layout-enhancement-v1",
        "mode": "existing",
        "target_count": len(items),
        "status": "ok" if items else "skipped",
        "items": items,
    }


def umi_ocr_image_with_blocks(image_path: Path, ocr_engine) -> tuple[str, list[dict]]:
    run = getattr(ocr_engine, "run", None)
    if not callable(run):
        return umi_ocr_image(image_path, ocr_engine).strip(), []
    result = run(str(image_path))
    code = result.get("code")
    if code == 101:
        return "", []
    if code != 100:
        raise RuntimeError(f"Umi-OCR failed: {result}")
    lines = []
    blocks = []
    for index, item in enumerate(result.get("data", []), start=1):
        text = (item.get("text") or "").strip()
        if not text:
            continue
        lines.append(text)
        block = {
            "index": index,
            "text": text,
            "score": item.get("score"),
        }
        bbox = normalize_ocr_box(item.get("box") or item.get("bbox"))
        if bbox:
            block["bbox"] = bbox
        blocks.append(block)
    return "\n".join(lines), blocks


def normalize_ocr_box(raw_box) -> list[float] | None:
    if not raw_box:
        return None
    try:
        if isinstance(raw_box, dict):
            values = [raw_box.get(key) for key in ("x1", "y1", "x2", "y2")]
            if all(value is not None for value in values):
                return [round(float(value), 2) for value in values]
        if len(raw_box) == 4 and all(isinstance(value, (int, float)) for value in raw_box):
            x1, y1, x2, y2 = [float(value) for value in raw_box]
            return [round(min(x1, x2), 2), round(min(y1, y2), 2), round(max(x1, x2), 2), round(max(y1, y2), 2)]
        points = []
        for point in raw_box:
            if isinstance(point, dict):
                points.append((float(point.get("x")), float(point.get("y"))))
            elif len(point) >= 2:
                points.append((float(point[0]), float(point[1])))
        if not points:
            return None
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        return [round(min(xs), 2), round(min(ys), 2), round(max(xs), 2), round(max(ys), 2)]
    except Exception:
        return None


def bbox_region(bbox: list[float]) -> str:
    x1, y1, x2, y2 = bbox
    cx = (x1 + x2) / 2
    cy = (y1 + y2) / 2
    horizontal = "left" if cx < 0.33 else "right" if cx > 0.67 else "center"
    vertical = "top" if cy < 0.33 else "bottom" if cy > 0.67 else "middle"
    return f"{vertical}-{horizontal}"


def build_layout_profile(text: str, blocks: list[dict], *, width: int, height: int) -> dict:
    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if line.strip()]
    short_lines = [line for line in lines if len(line) <= 18]
    bullet_like = [line for line in lines if re.match(r"^([\-•·*]|\d+[.、．])\s*", line)]
    blocks_with_bbox = [block for block in blocks if block.get("bbox")]
    region_counts: dict[str, int] = {}
    x_bins = {"left": 0, "center": 0, "right": 0}
    if width > 0 and height > 0:
        for block in blocks_with_bbox:
            bbox = normalize_bbox_to_unit(block["bbox"], width=width, height=height)
            if not bbox:
                continue
            block["bbox_unit"] = bbox
            region = bbox_region(bbox)
            block["region"] = region
            region_counts[region] = region_counts.get(region, 0) + 1
            cx = (bbox[0] + bbox[2]) / 2
            if cx < 0.33:
                x_bins["left"] += 1
            elif cx > 0.67:
                x_bins["right"] += 1
            else:
                x_bins["center"] += 1
    active_columns = sum(1 for count in x_bins.values() if count >= 3)
    short_line_ratio = round(len(short_lines) / max(len(lines), 1), 3)
    bullet_like_ratio = round(len(bullet_like) / max(len(lines), 1), 3)
    aspect_ratio = round(width / height, 3) if width and height else 0.0
    signals = []
    if len(blocks_with_bbox) >= 12 and active_columns >= 2:
        signals.append("multi_region_ocr_blocks")
    if len(lines) >= 10 and short_line_ratio >= 0.55:
        signals.append("short_label_dense")
    if bullet_like_ratio >= 0.35:
        signals.append("list_or_flow_dense")
    if aspect_ratio >= 1.65 or (aspect_ratio and aspect_ratio <= 0.62):
        signals.append("non_page_aspect_ratio")
    likely_infographic = bool(signals) and (len(lines) >= 8 or len(blocks_with_bbox) >= 8)
    return {
        "schema_version": "image-layout-profile-v1",
        "line_count": len(lines),
        "ocr_block_count": len(blocks),
        "ocr_block_with_bbox_count": len(blocks_with_bbox),
        "short_line_ratio": short_line_ratio,
        "bullet_like_ratio": bullet_like_ratio,
        "aspect_ratio": aspect_ratio,
        "active_columns": active_columns,
        "region_counts": region_counts,
        "signals": signals,
        "likely_infographic": likely_infographic,
    }


def normalize_bbox_to_unit(bbox: list[float], *, width: int, height: int) -> list[float] | None:
    if len(bbox) != 4 or width <= 0 or height <= 0:
        return None
    x1, y1, x2, y2 = bbox
    if max(abs(x1), abs(x2)) <= 1.5 and max(abs(y1), abs(y2)) <= 1.5:
        return [round(max(0.0, min(1.0, value)), 4) for value in bbox]
    return [
        round(max(0.0, min(1.0, x1 / width)), 4),
        round(max(0.0, min(1.0, y1 / height)), 4),
        round(max(0.0, min(1.0, x2 / width)), 4),
        round(max(0.0, min(1.0, y2 / height)), 4),
    ]


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
    split_order = infer_split_page_order(pages)
    if split_order is not None:
        return split_order
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


def infer_split_page_order(pages: list[ScreenshotPage]) -> list[ScreenshotPage] | None:
    split_pages = [page for page in pages if page.split_group and page.split_index is not None]
    if not split_pages or len(split_pages) != len(pages):
        return None
    groups = {page.split_group for page in split_pages}
    if len(groups) != 1:
        return None
    ordered = sorted(split_pages, key=lambda page: (int(page.split_index or 0), int(page.split_y_start or 0), page.file_name.lower()))
    for index, page in enumerate(ordered, start=1):
        page.order_index = index
        page.order_confidence = 0.99
        page.previous_overlap_chars = 0
        page.order_reason = "auto_split_filename_order"
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


def render_book_markdown(title: str | Path, pages: list[ScreenshotPage], *, prefer_enhanced: bool = False) -> str:
    title = str(title)
    lines = [f"# {title or 'Rebuilt Image Book'}", ""]
    previous_enhanced_text = ""
    previous_split_group = ""
    for page in pages:
        lines.append(f"<!-- source: {page.source} -->")
        if page.order_confidence < 0.45:
            lines.append(f"<!-- low-confidence-order: {page.order_confidence:.2f} -->")
        enhanced_text = selected_enhancement_text(page) if prefer_enhanced else ""
        if enhanced_text and page.split_group and page.split_group == previous_split_group:
            enhanced_text = trim_repeated_enhanced_prefix(previous_enhanced_text, enhanced_text)
        if is_likely_infographic(page):
            signals = ", ".join(str(signal) for signal in (page.layout_profile or {}).get("signals", []))
            lines.append(f"<!-- likely-infographic: {signals or 'layout-heavy image'} -->")
            lines.append(f"![source image]({page.source})")
            lines.append("")
            lines.append("<!-- Infographic/layout-heavy page: linear OCR may lose visual relationships. See layout.md. -->")
        if enhanced_text:
            lines.append("<!-- enhanced-layout-source: automatic VLM/layout backend -->")
            lines.extend(text_to_markdown(enhanced_text, promote_short_headings=False).splitlines())
            lines.append("")
            lines.append("<!-- original-umi-ocr-text -->")
            previous_enhanced_text = enhanced_text
            previous_split_group = page.split_group
        lines.extend(text_to_markdown(page.text).splitlines())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def is_likely_infographic(page: ScreenshotPage) -> bool:
    profile = page.layout_profile or {}
    return bool(profile.get("likely_infographic"))


def render_layout_markdown(pages: list[ScreenshotPage]) -> str:
    lines = ["# 图片版面复查 / Image Layout Review", ""]
    infographic_pages = [page for page in pages if is_likely_infographic(page)]
    lines.append(f"- Pages: {len(pages)}")
    lines.append(f"- Likely infographic/layout-heavy pages: {len(infographic_pages)}")
    lines.append("")
    if not pages:
        return "\n".join(lines).rstrip() + "\n"
    for page in pages:
        profile = page.layout_profile or {}
        signals = ", ".join(str(signal) for signal in profile.get("signals") or [])
        marker = "needs layout review" if is_likely_infographic(page) else "normal"
        lines.append(f"## {page.order_index or ''} {Path(page.source).name}".strip())
        lines.append("")
        lines.append(f"- Source: `{page.source}`")
        lines.append(f"- Status: {marker}")
        lines.append(f"- Size: {page.width}x{page.height}")
        lines.append(f"- OCR lines: {profile.get('line_count', 0)}")
        lines.append(f"- OCR blocks with bbox: {profile.get('ocr_block_with_bbox_count', 0)}")
        lines.append(f"- Active columns: {profile.get('active_columns', 0)}")
        if signals:
            lines.append(f"- Signals: {signals}")
        region_counts = profile.get("region_counts") or {}
        if region_counts:
            region_text = ", ".join(f"{key}={value}" for key, value in sorted(region_counts.items()))
            lines.append(f"- Regions: {region_text}")
        lines.append("")
        blocks = page.ocr_blocks or []
        if blocks:
            lines.append("| # | Region | BBox | Score | Text |")
            lines.append("| --- | --- | --- | --- | --- |")
            for block in blocks[:120]:
                bbox = block.get("bbox_unit") or block.get("bbox") or ""
                if isinstance(bbox, list):
                    bbox = ",".join(str(value) for value in bbox)
                lines.append(
                    f"| {block.get('index', '')} | {markdown_cell(str(block.get('region') or ''))} | "
                    f"{markdown_cell(str(bbox))} | {markdown_cell(str(block.get('score') or ''))} | "
                    f"{markdown_cell(str(block.get('text') or ''))} |"
                )
            if len(blocks) > 120:
                lines.append(f"| ... | ... | ... | ... | {len(blocks) - 120} more block(s) omitted |")
        else:
            lines.append("No OCR bounding boxes were available; this page used text-only OCR fallback.")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def selected_enhancement_text(page: ScreenshotPage) -> str:
    for enhancement in page.layout_enhancements or []:
        if enhancement.get("status") == "ok" and enhancement.get("text"):
            return str(enhancement.get("text") or "").strip()
    return ""


def trim_repeated_enhanced_prefix(previous_text: str, current_text: str) -> str:
    previous_blocks = markdown_blocks(previous_text)
    current_blocks = markdown_blocks(current_text)
    if not previous_blocks or not current_blocks:
        return current_text
    max_overlap = min(8, len(previous_blocks), len(current_blocks))
    for length in range(max_overlap, 0, -1):
        if previous_blocks[-length:] == current_blocks[:length]:
            return "\n\n".join(current_blocks[length:]).strip()
    return current_text


def markdown_blocks(text: str) -> list[str]:
    blocks = []
    for block in re.split(r"\n\s*\n+", text.replace("\r\n", "\n").replace("\r", "\n")):
        normalized = "\n".join(line.strip() for line in block.splitlines() if line.strip())
        if normalized:
            blocks.append(normalized)
    return blocks


def render_enhancement_markdown(payload: dict) -> str:
    lines = ["# 信息图自动补强 / Layout-Heavy Enhancement", ""]
    lines.append(f"- Status: {payload.get('status', '')}")
    lines.append(f"- Mode: {payload.get('mode', '')}")
    lines.append(f"- Target pages: {payload.get('target_count', 0)}")
    if payload.get("reason"):
        lines.append(f"- Reason: {payload.get('reason')}")
    backends = payload.get("backends") or []
    if backends:
        lines.append(f"- Backend order: {', '.join(str(item) for item in backends)}")
    lines.append("")
    items = payload.get("items") or []
    if not items:
        lines.append("No layout-heavy pages were enhanced.")
        return "\n".join(lines).rstrip() + "\n"
    for item in items:
        lines.append(f"## {item.get('file_name') or Path(str(item.get('source') or '')).name}")
        lines.append("")
        lines.append(f"- Source: `{item.get('source')}`")
        lines.append(f"- Status: {item.get('status')}")
        if item.get("selected_backend"):
            lines.append(f"- Selected backend: {item.get('selected_backend')}")
        signals = ", ".join(str(signal) for signal in item.get("signals") or [])
        if signals:
            lines.append(f"- Signals: {signals}")
        lines.append("")
        attempts = item.get("attempts") or []
        if attempts:
            lines.append("| Backend | Status | Artifact | Reason |")
            lines.append("| --- | --- | --- | --- |")
            for attempt in attempts:
                reason = attempt.get("reason") or attempt.get("stdout_tail") or ""
                lines.append(
                    f"| {markdown_cell(str(attempt.get('backend') or ''))} | "
                    f"{markdown_cell(str(attempt.get('status') or ''))} | "
                    f"{markdown_cell(str(attempt.get('artifact') or ''))} | "
                    f"{markdown_cell(str(reason)[:300])} |"
                )
            lines.append("")
        selected_text = ""
        for attempt in attempts:
            if attempt.get("status") == "ok" and attempt.get("text"):
                selected_text = str(attempt.get("text") or "").strip()
                break
        if selected_text:
            lines.append("### Selected Enhanced Text")
            lines.append("")
            lines.append(selected_text[:5000])
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def text_to_markdown(text: str, *, promote_short_headings: bool = True) -> str:
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
        if should_preserve_markdown_line(line):
            output.append(line)
            previous_blank = False
            continue
        heading_level = infer_heading_level(line, previous_blank=previous_blank, promote_short_headings=promote_short_headings)
        if heading_level:
            output.append(f"{'#' * heading_level} {line}")
        else:
            output.append(line)
        previous_blank = False
    return "\n".join(output).strip()


def should_preserve_markdown_line(line: str) -> bool:
    return bool(
        re.match(r"^#{1,6}\s+\S+", line)
        or re.match(r"^>\s+", line)
        or re.match(r"^(\||[-*+]\s+|\d+[.)]\s+)", line)
        or re.match(r"^</?\w+[^>]*>$", line)
    )


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


def infer_heading_level(line: str, *, previous_blank: bool, promote_short_headings: bool = True) -> int | None:
    normalized = line.strip()
    if re.match(r"^(第[一二三四五六七八九十百千万\d]+[章节篇部卷]|Chapter\s+\d+|Part\s+\w+)\b", normalized, re.IGNORECASE):
        return 2
    dotted = re.match(r"^(\d+(?:\.\d+){0,3})[\s、.．]+", normalized)
    if dotted:
        return min(2 + dotted.group(1).count("."), 5)
    if promote_short_headings and previous_blank and 2 <= len(normalized) <= 28 and not re.search(r"[。！？.!?，,；;：:]$", normalized):
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
    lines.append("| # | Source | Page | Confidence | Reason | Overlap | Split | Title candidates |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for page in pages:
        titles = "; ".join(page.title_candidates or [])
        split = ""
        if page.split_index is not None:
            split = f"{page.split_index} ({page.split_y_start or 0}-{page.split_y_end or 0})"
        lines.append(
            f"| {page.order_index} | {markdown_cell(page.source)} | {page.page_number or ''} | "
            f"{page.order_confidence:.2f} | {markdown_cell(page.order_reason)} | {page.previous_overlap_chars} | {markdown_cell(split)} | {markdown_cell(titles)} |"
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
    infographic_pages = [page for page in ordered_pages if is_likely_infographic(page)]
    split_pages = [page for page in ordered_pages if page.split_group]
    lines = ["# 截图成书复查清单 / Image Book Review", ""]
    lines.append(f"- Total images: {len(pages)}")
    lines.append(f"- Ordered representatives: {len(ordered_pages)}")
    lines.append(f"- Duplicate groups: {len(duplicate_groups)}")
    lines.append(f"- Low-confidence order items: {len(low_confidence)}")
    lines.append(f"- Likely infographic/layout-heavy items: {len(infographic_pages)}")
    lines.append(f"- Auto-split long-image items: {len(split_pages)}")
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

    if infographic_pages:
        lines.extend(["## 疑似信息图/复杂版面 / Infographic Or Layout-Heavy Pages", ""])
        lines.append("These pages should be reviewed with `layout.md`; linear OCR may lose relationships such as arrows, grouping, tables, and side-by-side labels.")
        lines.append("")
        for page in infographic_pages:
            signals = ", ".join(str(signal) for signal in (page.layout_profile or {}).get("signals", []))
            lines.append(f"- #{page.order_index}: `{page.source}` signals={markdown_cell(signals)}")
        lines.append("")

    if split_pages:
        lines.extend(["## 自动长图切分 / Auto-Split Long Image", ""])
        groups = sorted({page.split_group for page in split_pages})
        lines.append(f"- Split groups: {len(groups)}")
        lines.append("- Ordering is pinned to split index / vertical position to avoid OCR page-number mistakes.")
        lines.append("- Adjacent slices may contain overlapped text near boundaries; review `enhanced.md` for duplicates.")
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
