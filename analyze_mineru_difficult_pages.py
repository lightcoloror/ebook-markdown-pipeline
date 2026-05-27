from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


TITLE_TYPES = {"title", "doc_title", "paragraph_title"}
IMAGE_TYPES = {"image", "image_body", "chart", "chart_body", "seal", "header_image", "footer_image"}
TABLE_TYPES = {"table", "table_body"}
FURNITURE_TYPES = {"header", "footer", "page_number", "page_header", "page_footer"}
FOOTNOTE_TYPES = {"footnote", "page_footnote", "image_footnote", "table_footnote", "chart_footnote"}
TEXT_TYPES = {"text", "abstract", "ref_text", "list", "index", "aside_text", "page_aside_text"}


@dataclass
class PageScore:
    page: int
    score: int
    reasons: list[str]
    block_counts: dict[str, int]
    text_chars: int


def main() -> int:
    parser = argparse.ArgumentParser(description="Score MinerU middle.json pages that may benefit from hybrid parsing.")
    parser.add_argument("path", type=Path, help="MinerU _middle.json file or a directory containing it")
    parser.add_argument("--top", type=int, default=30, help="Number of rows to print")
    parser.add_argument("--threshold", type=int, default=6, help="Score threshold for hybrid candidates")
    args = parser.parse_args()

    middle_json = find_middle_json(args.path)
    scores = score_middle_json(middle_json)
    candidates = [item for item in scores if item.score >= args.threshold]

    print(f"Analyzed: {middle_json}")
    print(f"Pages: {len(scores)}")
    print(f"Hybrid candidates: {len(candidates)} (threshold={args.threshold})")
    print()

    for item in sorted(scores, key=lambda row: (-row.score, row.page))[: args.top]:
        reason_text = "; ".join(item.reasons) if item.reasons else "normal"
        print(f"page={item.page + 1}\tscore={item.score}\ttext={item.text_chars}\t{reason_text}")
    return 0


def find_middle_json(path: Path) -> Path:
    if path.is_file():
        return path
    matches = sorted(path.rglob("*_middle.json"))
    if not matches:
        raise FileNotFoundError(f"No *_middle.json found under {path}")
    return max(matches, key=lambda item: item.stat().st_size)


def score_middle_json(path: Path) -> list[PageScore]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [score_page(page_info, index) for index, page_info in enumerate(data.get("pdf_info", []))]


def score_page(page_info: dict[str, Any], index: int) -> PageScore:
    blocks = flatten_blocks(page_info)
    counts = count_block_types(blocks)
    text = "\n".join(extract_text(block) for block in blocks).strip()
    text_chars = len(re.sub(r"\s+", "", text))
    page_area = page_area_of(page_info)
    visual_area = sum(block_area(block) for block in blocks if block_type(block) in IMAGE_TYPES | TABLE_TYPES)
    visual_ratio = visual_area / page_area if page_area else 0

    score = 0
    reasons: list[str] = []

    if index <= 2 and visual_ratio > 0.25:
        score += 4
        reasons.append("cover-like")
    if counts.get("index", 0) > 0 or looks_like_toc(text):
        score += 5
        reasons.append("toc/index")
    if visual_ratio > 0.45:
        score += 4
        reasons.append(f"visual-heavy({visual_ratio:.0%})")
    if counts.get("table", 0) + counts.get("table_body", 0) >= 1:
        score += 4
        reasons.append("table")
    title_count = sum(counts.get(kind, 0) for kind in TITLE_TYPES)
    if title_count >= 5:
        score += 3
        reasons.append(f"many-titles({title_count})")
    if text_chars < 80 and visual_ratio > 0.15:
        score += 3
        reasons.append("low-text-with-visual")
    furniture_count = sum(counts.get(kind, 0) for kind in FURNITURE_TYPES)
    if furniture_count >= 2:
        score += 2
        reasons.append("page-furniture")
    footnote_count = sum(counts.get(kind, 0) for kind in FOOTNOTE_TYPES)
    if footnote_count:
        score += min(3, footnote_count)
        reasons.append(f"footnotes({footnote_count})")
    if high_short_line_ratio(text):
        score += 2
        reasons.append("many-short-lines")
    if noisy_text(text):
        score += 2
        reasons.append("ocr-noise")

    return PageScore(page=index, score=score, reasons=reasons, block_counts=counts, text_chars=text_chars)


def flatten_blocks(page_info: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for key in ("para_blocks", "preproc_blocks", "discarded_blocks"):
        for block in page_info.get(key) or []:
            collect_block(block, found)
    return found


def collect_block(block: dict[str, Any], found: list[dict[str, Any]]) -> None:
    found.append(block)
    for child in block.get("blocks") or []:
        collect_block(child, found)


def count_block_types(blocks: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for block in blocks:
        kind = block_type(block)
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def block_type(block: dict[str, Any]) -> str:
    return str(block.get("type") or block.get("label") or "").lower()


def extract_text(block: dict[str, Any]) -> str:
    parts: list[str] = []
    if isinstance(block.get("text"), str):
        parts.append(block["text"])
    for line in block.get("lines") or []:
        for span in line.get("spans") or []:
            content = span.get("content") or span.get("text")
            if isinstance(content, str):
                parts.append(content)
    return "\n".join(parts)


def page_area_of(page_info: dict[str, Any]) -> float:
    page_size = page_info.get("page_size") or []
    if len(page_size) >= 2:
        return float(page_size[0] * page_size[1])
    return 0.0


def block_area(block: dict[str, Any]) -> float:
    bbox = block.get("bbox") or []
    if len(bbox) >= 4:
        return max(0.0, float(bbox[2] - bbox[0])) * max(0.0, float(bbox[3] - bbox[1]))
    return 0.0


def looks_like_toc(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 5:
        return False
    hits = sum(1 for line in lines if re.search(r"(\.{2,}|\s{2,}|第.+[章节篇部]).{0,60}\d{1,4}$", line))
    return hits >= 3


def high_short_line_ratio(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 8:
        return False
    short = sum(1 for line in lines if len(line) <= 12)
    return short / len(lines) > 0.55


def noisy_text(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if len(compact) < 40:
        return False
    odd = len(re.findall(r"[□�|]{1}|[A-Za-z]{1,2}[^\w\s][A-Za-z]{1,2}", compact))
    return odd / max(len(compact), 1) > 0.03


if __name__ == "__main__":
    raise SystemExit(main())
