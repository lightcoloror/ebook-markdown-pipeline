from __future__ import annotations

import csv
import importlib.util
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


def pdfplumber_available() -> bool:
    return importlib.util.find_spec("pdfplumber") is not None


def camelot_available() -> bool:
    return importlib.util.find_spec("camelot") is not None


def analyze_pdf_layout_with_pdfplumber(
    source: Path,
    *,
    sample_pages: int = 8,
    output_dir: Path | None = None,
    max_tables: int = 20,
) -> dict[str, Any]:
    if not pdfplumber_available():
        return {
            "status": "missing_dependency",
            "tool": "pdfplumber",
            "message": "pdfplumber is not installed.",
            "camelot_available": camelot_available(),
        }

    import pdfplumber

    output_dir = Path(output_dir) if output_dir else None
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)

    pages: list[dict[str, Any]] = []
    table_artifacts: list[dict[str, Any]] = []
    header_footer_candidates: Counter[str] = Counter()
    try:
        with pdfplumber.open(str(source)) as pdf:
            page_count = len(pdf.pages)
            indexes = sample_indexes(page_count, sample_pages)
            for page_index in indexes:
                page = pdf.pages[page_index]
                words = page.extract_words() or []
                chars = page.chars or []
                lines = page.lines or []
                rects = page.rects or []
                curves = page.curves or []
                images = page.images or []
                text = page.extract_text() or ""
                tables = safe_find_tables(page)
                top_bottom = page_header_footer_candidates(words, page.height)
                header_footer_candidates.update(top_bottom)
                page_payload = {
                    "page": page_index + 1,
                    "width": round(float(page.width), 2),
                    "height": round(float(page.height), 2),
                    "char_count": len(chars),
                    "word_count": len(words),
                    "text_chars": len(text),
                    "line_count": len(lines),
                    "rect_count": len(rects),
                    "curve_count": len(curves),
                    "image_count": len(images),
                    "table_count": len(tables),
                    "two_column_likely": looks_two_column(words, page.width),
                    "header_footer_candidates": top_bottom[:6],
                }
                pages.append(page_payload)
                if output_dir and tables and len(table_artifacts) < max_tables:
                    for table_number, table in enumerate(tables, start=1):
                        if len(table_artifacts) >= max_tables:
                            break
                        rows = table.extract() or []
                        artifact = write_table_artifacts(output_dir, page_index + 1, table_number, rows)
                        artifact.update({"page": page_index + 1, "table_number": table_number, "rows": len(rows)})
                        table_artifacts.append(artifact)
    except Exception as exc:  # noqa: BLE001
        payload = {
            "status": "failed",
            "tool": "pdfplumber",
            "source": str(source),
            "message": str(exc),
            "camelot_available": camelot_available(),
        }
        if output_dir:
            (output_dir / "table-diagnostics.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    table_pages = [item["page"] for item in pages if item.get("table_count")]
    two_column_pages = [item["page"] for item in pages if item.get("two_column_likely")]
    image_heavy_pages = [item["page"] for item in pages if int(item.get("image_count") or 0) >= 1 and int(item.get("text_chars") or 0) < 200]
    repeated_noise = [
        {"text": text, "count": count}
        for text, count in header_footer_candidates.most_common(10)
        if count >= 2 and len(text) >= 2
    ]
    payload = {
        "status": "ok",
        "tool": "pdfplumber",
        "source": str(source),
        "sampled_pages": len(pages),
        "pages": pages,
        "summary": {
            "table_pages": table_pages,
            "two_column_pages": two_column_pages,
            "image_heavy_pages": image_heavy_pages,
            "repeated_header_footer_candidates": repeated_noise,
            "table_artifact_count": len(table_artifacts),
            "camelot_available": camelot_available(),
        },
        "table_artifacts": table_artifacts,
    }
    if output_dir:
        (output_dir / "table-diagnostics.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def sample_indexes(page_count: int, sample_pages: int) -> list[int]:
    if page_count <= 0:
        return []
    if page_count <= sample_pages:
        return list(range(page_count))
    indexes = {0, page_count - 1}
    step = max(1, page_count // max(sample_pages - len(indexes), 1))
    for index in range(1, page_count - 1, step):
        indexes.add(index)
        if len(indexes) >= sample_pages:
            break
    return sorted(indexes)


def safe_find_tables(page) -> list[Any]:
    try:
        return list(page.find_tables() or [])
    except Exception:
        return []


def page_header_footer_candidates(words: list[dict[str, Any]], page_height: float) -> list[str]:
    candidates: list[str] = []
    for word in words:
        top = float(word.get("top") or 0)
        bottom = float(word.get("bottom") or 0)
        if top <= page_height * 0.08 or bottom >= page_height * 0.92:
            text = normalize_noise_text(str(word.get("text") or ""))
            if text:
                candidates.append(text)
    return candidates


def normalize_noise_text(value: str) -> str:
    value = re.sub(r"\s+", " ", value.strip())
    return value[:120]


def looks_two_column(words: list[dict[str, Any]], page_width: float) -> bool:
    if len(words) < 40:
        return False
    left = 0
    right = 0
    middle = 0
    for word in words:
        x0 = float(word.get("x0") or 0)
        x1 = float(word.get("x1") or x0)
        center = (x0 + x1) / 2
        if center < page_width * 0.42:
            left += 1
        elif center > page_width * 0.58:
            right += 1
        else:
            middle += 1
    return left >= 12 and right >= 12 and middle <= max(10, int((left + right) * 0.25))


def write_table_artifacts(output_dir: Path, page_number: int, table_number: int, rows: list[list[Any]]) -> dict[str, Any]:
    stem = f"page-{page_number:04d}-table-{table_number:02d}"
    csv_path = output_dir / f"{stem}.csv"
    md_path = output_dir / f"{stem}.md"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        for row in rows:
            writer.writerow(["" if cell is None else str(cell) for cell in row])
    md_path.write_text(render_markdown_table(rows), encoding="utf-8")
    return {"csv": str(csv_path), "markdown": str(md_path)}


def render_markdown_table(rows: list[list[Any]]) -> str:
    if not rows:
        return ""
    normalized = [["" if cell is None else str(cell).replace("\n", " ").strip() for cell in row] for row in rows]
    width = max(len(row) for row in normalized)
    padded = [row + [""] * (width - len(row)) for row in normalized]
    header = padded[0]
    lines = ["| " + " | ".join(escape_markdown_cell(cell) for cell in header) + " |"]
    lines.append("| " + " | ".join("---" for _ in range(width)) + " |")
    for row in padded[1:]:
        lines.append("| " + " | ".join(escape_markdown_cell(cell) for cell in row) + " |")
    return "\n".join(lines) + "\n"


def escape_markdown_cell(value: str) -> str:
    return value.replace("|", "\\|")
