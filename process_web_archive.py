from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ebook_markdown_pipeline.image_book_rebuilder import rebuild_image_book_from_sources  # noqa: E402


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


def _read_text(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _copy_text(source: Path, target: Path) -> bool:
    if not source.exists() or not source.is_file():
        return False
    target.write_text(source.read_text(encoding="utf-8", errors="replace"), encoding="utf-8", newline="\n")
    return True


def _build_visual_blocks(pages: list[dict[str, Any]], structure: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for index, page in enumerate(pages, start=1):
        text = str(page.get("text") or "")
        blocks.append(
            {
                "type": "ocr_page",
                "index": index,
                "source": page.get("source") or "",
                "file_name": page.get("file_name") or "",
                "width": page.get("width") or 0,
                "height": page.get("height") or 0,
                "char_count": page.get("char_count") if page.get("char_count") is not None else len(text),
                "ocr_status": page.get("ocr_status") or "",
                "ocr_message": page.get("ocr_message") or "",
                "text_preview": text[:240],
                "title_candidates": page.get("title_candidates") or [],
            }
        )
    for item in structure.get("items") or []:
        if isinstance(item, dict):
            blocks.append({"type": "structure_heading", **item})
    return blocks


def _markdown_table_candidates(markdown: str, source_path: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    lines = (markdown or "").splitlines()
    index = 0
    while index < len(lines) - 1:
        header = lines[index]
        separator = lines[index + 1]
        if "|" in header and re.search(r"\|\s*:?-{3,}:?\s*\|", separator):
            start = index + 1
            rows = [header, separator]
            index += 2
            while index < len(lines) and "|" in lines[index].strip():
                rows.append(lines[index])
                index += 1
            candidates.append(
                {
                    "type": "markdown_table",
                    "source": source_path,
                    "start_line": start,
                    "end_line": start + len(rows) - 1,
                    "row_count": max(len(rows) - 2, 0),
                    "column_count": max(len([part for part in header.split("|") if part.strip()]), 0),
                    "confidence": 0.85,
                    "preview": "\n".join(rows[:6]),
                }
            )
            continue
        index += 1
    return candidates


def _ocr_table_candidates(ocr_text: str, screenshot: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    lines = [line.strip() for line in (ocr_text or "").splitlines()]
    run: list[tuple[int, str]] = []
    for line_no, line in enumerate(lines, start=1):
        looks_tabular = "\t" in line or len(re.split(r"\s{2,}", line)) >= 3
        if looks_tabular:
            run.append((line_no, line))
            continue
        if len(run) >= 3:
            candidates.append(_ocr_table_candidate(run, screenshot))
        run = []
    if len(run) >= 3:
        candidates.append(_ocr_table_candidate(run, screenshot))
    return candidates


def _ocr_table_candidate(run: list[tuple[int, str]], screenshot: str) -> dict[str, Any]:
    split_counts = [len(re.split(r"\s{2,}|\t+", line)) for _, line in run]
    return {
        "type": "ocr_tabular_text",
        "source": screenshot,
        "start_line": run[0][0],
        "end_line": run[-1][0],
        "row_count": len(run),
        "column_count_estimate": max(split_counts or [0]),
        "confidence": 0.45,
        "preview": "\n".join(line for _, line in run[:8]),
    }


def _image_positions_from_manifest(manifest: dict[str, Any], source_markdown: str) -> list[dict[str, Any]]:
    markdown_lines = source_markdown.splitlines()
    line_by_src: dict[str, int] = {}
    for line_no, line in enumerate(markdown_lines, start=1):
        for match in re.finditer(r"!\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", line):
            line_by_src.setdefault(match.group(1), line_no)
    positions: list[dict[str, Any]] = []
    for index, item in enumerate(manifest.get("image_assets") or [], start=1):
        markdown_path = str(item.get("markdown_path") or "")
        asset_path = str(item.get("asset_path") or "")
        rebuild_path = str(item.get("rebuild_input_path") or "")
        document_bbox = item.get("document_bbox") or None
        viewport_bbox = item.get("viewport_bbox") or None
        has_bbox = isinstance(document_bbox, list) and len(document_bbox) == 4
        positions.append(
            {
                "type": "dom_image_position" if has_bbox else "archive_image_asset",
                "index": int(item.get("index") or index),
                "source": item.get("url") or "",
                "asset_path": asset_path,
                "rebuild_input_path": rebuild_path,
                "markdown_path": markdown_path,
                "markdown_line": line_by_src.get(markdown_path) or line_by_src.get(asset_path) or 0,
                "alt": item.get("alt") or "",
                "width": item.get("width") or 0,
                "height": item.get("height") or 0,
                "bbox": document_bbox,
                "viewport_bbox": viewport_bbox,
                "rendered_width": item.get("rendered_width") or 0,
                "rendered_height": item.get("rendered_height") or 0,
                "coordinate_space": "document_pixels" if has_bbox else "document_order",
                "position_confidence": 0.75 if has_bbox else 0.25,
                "note": (
                    "Image position comes from browser DOM getBoundingClientRect."
                    if has_bbox
                    else "Image is indexed from archive assets; exact screenshot coordinates are not available yet."
                ),
            }
        )
    return positions


def _screenshot_image_region_candidates(screenshot: str) -> list[dict[str, Any]]:
    screenshot_path = Path(screenshot)
    if not screenshot_path.exists():
        return []
    try:
        from PIL import Image, ImageStat
    except Exception:
        return []
    try:
        with Image.open(screenshot_path) as image:
            rgb = image.convert("RGB")
            original_width, original_height = rgb.size
            target_width = 240
            scale = max(original_width / target_width, 1.0)
            small = rgb.resize((int(original_width / scale), int(original_height / scale)))
    except Exception:
        return []

    cell = 12
    cols = max(small.width // cell, 1)
    rows = max(small.height // cell, 1)
    active: set[tuple[int, int]] = set()
    for row in range(rows):
        for col in range(cols):
            left = col * cell
            top = row * cell
            right = min(left + cell, small.width)
            bottom = min(top + cell, small.height)
            crop = small.crop((left, top, right, bottom))
            stat = ImageStat.Stat(crop)
            mean = stat.mean
            extrema = stat.extrema
            brightness = sum(mean) / 3
            channel_range = max(high - low for low, high in extrema)
            color_spread = max(mean) - min(mean)
            nonwhiteish = brightness < 232
            visually_dense = brightness < 205 and channel_range > 28
            colorful = color_spread > 18 and channel_range > 35
            if nonwhiteish and (visually_dense or colorful):
                active.add((row, col))

    seen: set[tuple[int, int]] = set()
    regions: list[dict[str, Any]] = []
    for start in sorted(active):
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        cells: list[tuple[int, int]] = []
        while stack:
            item = stack.pop()
            cells.append(item)
            row, col = item
            for neighbor in ((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)):
                if neighbor in active and neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        min_row = min(row for row, _ in cells)
        max_row = max(row for row, _ in cells)
        min_col = min(col for _, col in cells)
        max_col = max(col for _, col in cells)
        bbox_small = [min_col * cell, min_row * cell, min((max_col + 1) * cell, small.width), min((max_row + 1) * cell, small.height)]
        width = (bbox_small[2] - bbox_small[0]) * scale
        height = (bbox_small[3] - bbox_small[1]) * scale
        area = width * height
        if width < 90 or height < 70 or area < original_width * original_height * 0.008:
            continue
        bbox = [round(value * scale, 1) for value in bbox_small]
        regions.append(
            {
                "type": "screenshot_image_region",
                "index": len(regions) + 1,
                "source": str(screenshot_path),
                "bbox": bbox,
                "coordinate_space": "screenshot_pixels",
                "width": round(width, 1),
                "height": round(height, 1),
                "position_confidence": 0.4,
                "note": "Heuristic large visual-region candidate from screenshot pixels; verify manually before treating as exact image placement.",
            }
        )
    return sorted(regions, key=lambda item: (item["bbox"][1], item["bbox"][0]))[:40]


def _run_screenshot_ocr(screenshot: str, output_root: Path) -> dict[str, Any]:
    screenshot_path = Path(screenshot)
    ocr_output = output_root / "image_book_rebuild"
    if not screenshot_path.exists():
        return {"status": "skipped", "warning": f"screenshot not found: {screenshot}"}
    try:
        result = rebuild_image_book_from_sources(
            [screenshot_path],
            ocr_output,
            input_label=str(screenshot_path),
            title=screenshot_path.stem,
            ocr_mode="auto",
        )
    except Exception as exc:
        return {"status": "failed", "warning": f"screenshot OCR failed: {exc}", "output": str(ocr_output)}

    pages_path = Path(str(result.get("pages") or ""))
    structure_path = Path(str(result.get("structure_json") or ""))
    pages = _read_jsonl(pages_path)
    structure = _read_json(structure_path)
    ocr_text_chars = sum(int(page.get("char_count") or len(str(page.get("text") or ""))) for page in pages)
    status = "ok" if ocr_text_chars > 0 else "no_text"
    return {
        "status": status,
        "result": result,
        "pages": pages,
        "structure": structure,
        "ocr_text_chars": ocr_text_chars,
        "output": str(ocr_output),
        "warning": "" if status == "ok" else "screenshot OCR produced no text",
    }


def process_web_archive(archive_path: str, output_dir: str = "") -> dict[str, Any]:
    archive_root = Path(archive_path)
    if not archive_root.is_dir():
        raise FileNotFoundError(f"archive directory not found: {archive_path}")
    manifest_path = archive_root / "rebuild_input" / "manifest.json"
    manifest = _read_json(manifest_path)
    output_root = Path(output_dir) if output_dir else archive_root / "visual_check"
    output_root.mkdir(parents=True, exist_ok=True)

    inputs = manifest.get("inputs") or {}
    screenshot = str(inputs.get("screenshot") or "")
    source_html = str(inputs.get("source_html") or "")
    source_markdown = str(inputs.get("source_markdown") or "")
    source_markdown_text = _read_text(Path(source_markdown)) if source_markdown else ""
    status = "pending_visual_engine"
    warnings = []
    if not screenshot:
        warnings.append("no screenshot available; visual layout/OCR cannot be produced yet")
    if not manifest:
        warnings.append("missing rebuild_input/manifest.json; run wcf archive rebuild --with-visual-check first")

    visual_blocks_path = output_root / "visual_blocks.json"
    table_candidates_path = output_root / "table_candidates.json"
    image_positions_path = output_root / "image_positions.json"

    ocr = _run_screenshot_ocr(screenshot, output_root) if screenshot else {"status": "skipped"}
    if ocr.get("warning"):
        warnings.append(str(ocr["warning"]))

    layout_ocr_path = output_root / "layout_ocr.md"
    ocr_book = Path(str((ocr.get("result") or {}).get("book") or ""))
    if _copy_text(ocr_book, layout_ocr_path):
        status = "ok" if ocr.get("status") == "ok" else "needs_review"
    elif not layout_ocr_path.exists():
        layout_ocr_path.write_text(
            "# Visual OCR Pending\n\n"
            "This file is a placeholder for screenshot/page-image OCR output.\n\n"
            f"- Screenshot: {screenshot}\n"
            f"- Source HTML: {source_html}\n"
            f"- Source Markdown: {source_markdown}\n"
            "\nRun the high-quality OCR/layout backend here before using visual text as evidence.\n",
            encoding="utf-8",
            newline="\n",
        )

    visual_blocks = _build_visual_blocks(ocr.get("pages") or [], ocr.get("structure") or {})
    _write_json(visual_blocks_path, visual_blocks)
    layout_ocr = _read_text(layout_ocr_path)
    table_candidates = _markdown_table_candidates(source_markdown_text, source_markdown) + _ocr_table_candidates(layout_ocr, screenshot)
    image_positions = _image_positions_from_manifest(manifest, source_markdown_text) + _screenshot_image_region_candidates(screenshot)
    _write_json(table_candidates_path, table_candidates)
    _write_json(image_positions_path, image_positions)

    result = {
        "schema_version": "web-archive-visual-check-v1",
        "legacy_schema_version": 1,
        "source_contract": "web-content-fetcher-archive",
        "execution_policy": "consume_existing_archive_only_no_crawling_no_browser_login",
        "status": status,
        "created_at": _now_iso(),
        "archive_path": str(archive_root),
        "manifest_path": str(manifest_path) if manifest_path.exists() else "",
        "output_dir": str(output_root),
        "layout_ocr_path": str(layout_ocr_path),
        "visual_blocks_path": str(visual_blocks_path),
        "table_candidates_path": str(table_candidates_path),
        "image_positions_path": str(image_positions_path),
        "ocr_backend": "image_book_rebuilder",
        "ocr_status": ocr.get("status") or "skipped",
        "ocr_text_chars": ocr.get("ocr_text_chars") or 0,
        "ocr_output_dir": ocr.get("output") or "",
        "visual_block_count": len(visual_blocks),
        "table_candidate_count": len(table_candidates),
        "image_position_count": len(image_positions),
        "warnings": warnings,
        "next_step": "run wcf archive rebuild again; if status remains needs_review, compare final_readable.html with layout_ocr.md and source screenshot",
    }
    _write_json(output_root / "visual_check_result.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare visual-check outputs for a web-content-fetcher archive.")
    parser.add_argument("archive_path")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--format", choices=["json", "summary"], default="json")
    args = parser.parse_args(argv)
    result = process_web_archive(args.archive_path, args.output_dir)
    if args.format == "summary":
        print(f"Status: {result['status']}")
        print(f"Visual output dir: {result['output_dir']}")
        print(f"layout_ocr.md: {result['layout_ocr_path']}")
        print(f"visual_blocks.json: {result['visual_blocks_path']}")
        print(f"table_candidates.json: {result['table_candidates_path']}")
        print(f"image_positions.json: {result['image_positions_path']}")
        if result["warnings"]:
            print("Warnings:")
            for warning in result["warnings"]:
                print(f"- {warning}")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
