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


def tabula_available() -> bool:
    return importlib.util.find_spec("tabula") is not None


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
            "tabula_available": tabula_available(),
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
            "tabula_available": tabula_available(),
        }
        if output_dir:
            (output_dir / "table-diagnostics.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    table_pages = [item["page"] for item in pages if item.get("table_count")]
    camelot_diagnostics = extract_tables_with_camelot(
        source,
        output_dir=output_dir,
        candidate_pages=table_pages,
        max_tables=max_tables,
    )
    tabula_diagnostics = extract_tables_with_tabula(
        source,
        output_dir=output_dir,
        candidate_pages=table_pages,
        max_tables=max_tables,
    )
    two_column_pages = [item["page"] for item in pages if item.get("two_column_likely")]
    image_heavy_pages = [item["page"] for item in pages if int(item.get("image_count") or 0) >= 1 and int(item.get("text_chars") or 0) < 200]
    repeated_noise = [
        {"text": text, "count": count}
        for text, count in header_footer_candidates.most_common(10)
        if count >= 2 and len(text) >= 2
    ]
    summary = {
        "table_pages": table_pages,
        "two_column_pages": two_column_pages,
        "image_heavy_pages": image_heavy_pages,
        "repeated_header_footer_candidates": repeated_noise,
        "table_artifact_count": len(table_artifacts),
        "camelot_table_artifact_count": len(camelot_diagnostics.get("table_artifacts") or []),
        "camelot_available": camelot_available(),
        "camelot_status": camelot_diagnostics.get("status"),
        "tabula_table_artifact_count": len(tabula_diagnostics.get("table_artifacts") or []),
        "tabula_available": tabula_available(),
        "tabula_status": tabula_diagnostics.get("status"),
    }
    layout_evidence = build_pdf_layout_evidence(source=source, pages=pages, summary=summary, status="ok")
    table_candidates = build_table_candidates(
        source=source,
        table_artifacts=table_artifacts,
        camelot_diagnostics=camelot_diagnostics,
        tabula_diagnostics=tabula_diagnostics,
    )
    payload = {
        "status": "ok",
        "tool": "pdfplumber",
        "source": str(source),
        "sampled_pages": len(pages),
        "pages": pages,
        "summary": summary,
        "pdf_layout_evidence": evidence_summary(layout_evidence),
        "table_candidates": table_candidates_summary(table_candidates),
        "table_artifacts": table_artifacts,
        "camelot_diagnostics": camelot_diagnostics,
        "tabula_diagnostics": tabula_diagnostics,
    }
    if output_dir:
        evidence_path = output_dir / "pdf-layout-evidence.json"
        evidence_path.write_text(json.dumps(layout_evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["pdf_layout_evidence_artifact"] = str(evidence_path)
        table_candidates_path = output_dir / "table-candidates.json"
        table_candidates_path.write_text(json.dumps(table_candidates, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["table_candidates_artifact"] = str(table_candidates_path)
        (output_dir / "table-diagnostics.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload



def build_pdf_layout_evidence(*, source: Path, pages: list[dict[str, Any]], summary: dict[str, Any], status: str) -> dict[str, Any]:
    page_evidence = [pdfplumber_page_to_layout_evidence(page) for page in pages]
    text_char_count = sum(int(page.get("text_chars") or 0) for page in page_evidence)
    line_count = sum(int(page.get("line_count") or 0) for page in page_evidence)
    table_count = sum(int(page.get("table_count") or 0) for page in page_evidence)
    image_count = sum(int(page.get("image_count") or 0) for page in page_evidence)
    rect_count = sum(int(page.get("rect_count") or 0) for page in page_evidence)
    curve_count = sum(int(page.get("curve_count") or 0) for page in page_evidence)
    page_count = len(page_evidence)
    avg_chars = round(text_char_count / page_count, 2) if page_count else 0
    repeated_noise = list(summary.get("repeated_header_footer_candidates") or [])
    flags = {
        "text_layer_present": text_char_count > 0,
        "low_text_density": avg_chars < 80,
        "layout_heavy_suspected": bool(summary.get("two_column_pages") or summary.get("image_heavy_pages") or repeated_noise),
        "table_heavy_suspected": bool(summary.get("table_pages") or table_count > 0),
        "image_heavy_suspected": bool(summary.get("image_heavy_pages")),
        "two_column_suspected": bool(summary.get("two_column_pages")),
        "repeated_header_footer_suspected": bool(repeated_noise),
    }
    return {
        "schema_version": "pdf-layout-evidence-v1",
        "backend": "pdfplumber",
        "status": status,
        "source": str(source),
        "page_count": page_count,
        "sampled_pages": page_count,
        "text_char_count": text_char_count,
        "line_count": line_count,
        "table_count": table_count,
        "image_count": image_count,
        "rect_count": rect_count,
        "curve_count": curve_count,
        "flags": flags,
        "summary": {
            "table_pages": list(summary.get("table_pages") or []),
            "two_column_pages": list(summary.get("two_column_pages") or []),
            "image_heavy_pages": list(summary.get("image_heavy_pages") or []),
            "repeated_header_footer_candidates": repeated_noise[:10],
        },
        "pages": page_evidence,
    }


def pdfplumber_page_to_layout_evidence(page: dict[str, Any]) -> dict[str, Any]:
    return {
        "page": page.get("page"),
        "width": page.get("width"),
        "height": page.get("height"),
        "text_chars": int(page.get("text_chars") or 0),
        "line_count": int(page.get("line_count") or 0),
        "char_count": int(page.get("char_count") or 0),
        "word_count": int(page.get("word_count") or 0),
        "rect_count": int(page.get("rect_count") or 0),
        "curve_count": int(page.get("curve_count") or 0),
        "image_count": int(page.get("image_count") or 0),
        "table_count": int(page.get("table_count") or 0),
        "two_column_likely": bool(page.get("two_column_likely")),
        "header_footer_candidates": list(page.get("header_footer_candidates") or [])[:6],
    }


def evidence_summary(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": evidence.get("schema_version"),
        "backend": evidence.get("backend"),
        "page_count": evidence.get("page_count"),
        "text_char_count": evidence.get("text_char_count"),
        "line_count": evidence.get("line_count"),
        "table_count": evidence.get("table_count"),
        "image_count": evidence.get("image_count"),
        "flags": evidence.get("flags") or {},
    }


def build_table_candidates(
    *,
    source: Path,
    table_artifacts: list[dict[str, Any]],
    camelot_diagnostics: dict[str, Any],
    tabula_diagnostics: dict[str, Any],
) -> dict[str, Any]:
    pages: dict[int, dict[str, Any]] = {}
    artifacts: list[dict[str, Any]] = []
    for backend, items in [
        ("pdfplumber", table_artifacts),
        ("camelot", [item for item in camelot_diagnostics.get("table_artifacts") or [] if isinstance(item, dict)]),
        ("tabula", [item for item in tabula_diagnostics.get("table_artifacts") or [] if isinstance(item, dict)]),
    ]:
        for item in items:
            table = table_artifact_to_candidate(item, backend=backend)
            page_number = int(table.get("page") or 0)
            page_payload = pages.setdefault(page_number, {"page": page_number, "tables": []})
            page_payload["tables"].append(table)
            for artifact_type in ("csv", "markdown", "html", "json"):
                path = item.get(artifact_type)
                if path:
                    artifacts.append({"type": artifact_type, "path": str(path), "backend": backend, "page": page_number})
    ordered_pages = [pages[key] for key in sorted(pages)]
    return {
        "schema_version": "table-candidates-v1",
        "backend": "pdf_layout_diagnostics",
        "status": "review" if ordered_pages else "empty",
        "source": str(source),
        "pages": ordered_pages,
        "artifacts": artifacts,
        "warnings": [
            "table candidates are side evidence only; compare against final Markdown before promotion",
        ],
    }


def table_artifact_to_candidate(item: dict[str, Any], *, backend: str) -> dict[str, Any]:
    page_number = int(item.get("page") or 0)
    table = {
        "backend": backend,
        "page": page_number,
        "table_number": int(item.get("table_number") or 0),
        "row_count": int(item.get("rows") or 0),
        "csv": item.get("csv"),
        "markdown": item.get("markdown"),
    }
    for key in ("accuracy", "whitespace"):
        if item.get(key) is not None:
            table[key] = item.get(key)
    return table


def table_candidates_summary(payload: dict[str, Any]) -> dict[str, Any]:
    pages = [page for page in payload.get("pages") or [] if isinstance(page, dict)]
    table_count = sum(len(page.get("tables") or []) for page in pages)
    backends = sorted({str(table.get("backend")) for page in pages for table in page.get("tables") or [] if table.get("backend")})
    return {
        "schema_version": payload.get("schema_version"),
        "backend": payload.get("backend"),
        "status": payload.get("status"),
        "page_count": len(pages),
        "table_count": table_count,
        "backends": backends,
        "artifact_count": len(payload.get("artifacts") or []),
    }

def extract_tables_with_camelot(
    source: Path,
    *,
    output_dir: Path | None,
    candidate_pages: list[int],
    max_tables: int,
) -> dict[str, Any]:
    if not candidate_pages:
        return {
            "status": "skipped_no_table_pages",
            "tool": "camelot",
            "source": str(source),
            "candidate_pages": [],
            "table_artifacts": [],
        }
    if not camelot_available():
        return {
            "status": "missing_dependency",
            "tool": "camelot",
            "source": str(source),
            "candidate_pages": candidate_pages,
            "message": "Camelot is not installed.",
            "table_artifacts": [],
        }
    if output_dir is None:
        return {
            "status": "skipped_no_output_dir",
            "tool": "camelot",
            "source": str(source),
            "candidate_pages": candidate_pages,
            "table_artifacts": [],
        }
    output_dir.mkdir(parents=True, exist_ok=True)

    import camelot

    pages_spec = ",".join(str(page) for page in candidate_pages)
    artifacts: list[dict[str, Any]] = []
    try:
        tables = camelot.read_pdf(str(source), pages=pages_spec, flavor="stream")
        for index, table in enumerate(tables, start=1):
            if len(artifacts) >= max_tables:
                break
            rows = dataframe_to_rows(getattr(table, "df", None))
            artifact = write_table_artifacts(output_dir, int(getattr(table, "page", 0) or 0), index, rows, prefix="camelot")
            artifact.update(
                {
                    "page": int(getattr(table, "page", 0) or 0),
                    "table_number": index,
                    "rows": len(rows),
                    "accuracy": safe_float(getattr(table, "accuracy", None)),
                    "whitespace": safe_float(getattr(table, "whitespace", None)),
                }
            )
            artifacts.append(artifact)
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "failed",
            "tool": "camelot",
            "source": str(source),
            "candidate_pages": candidate_pages,
            "pages": pages_spec,
            "message": str(exc),
            "table_artifacts": artifacts,
        }
    return {
        "status": "ok",
        "tool": "camelot",
        "source": str(source),
        "candidate_pages": candidate_pages,
        "pages": pages_spec,
        "table_artifacts": artifacts,
    }


def extract_tables_with_tabula(
    source: Path,
    *,
    output_dir: Path | None,
    candidate_pages: list[int],
    max_tables: int,
) -> dict[str, Any]:
    if not candidate_pages:
        return {
            "status": "skipped_no_table_pages",
            "tool": "tabula",
            "source": str(source),
            "candidate_pages": [],
            "table_artifacts": [],
        }
    if not tabula_available():
        return {
            "status": "missing_dependency",
            "tool": "tabula",
            "source": str(source),
            "candidate_pages": candidate_pages,
            "message": "tabula-py is not installed.",
            "table_artifacts": [],
        }
    if output_dir is None:
        return {
            "status": "skipped_no_output_dir",
            "tool": "tabula",
            "source": str(source),
            "candidate_pages": candidate_pages,
            "table_artifacts": [],
        }
    output_dir.mkdir(parents=True, exist_ok=True)

    import tabula

    pages_spec = ",".join(str(page) for page in candidate_pages)
    artifacts: list[dict[str, Any]] = []
    try:
        tables = tabula.read_pdf(
            str(source),
            pages=pages_spec,
            multiple_tables=True,
            stream=True,
            lattice=False,
        )
        for index, table in enumerate(tables or [], start=1):
            if len(artifacts) >= max_tables:
                break
            rows = dataframe_to_rows(table)
            artifact = write_table_artifacts(output_dir, 0, index, rows, prefix="tabula")
            artifact.update(
                {
                    "page": 0,
                    "table_number": index,
                    "rows": len(rows),
                }
            )
            artifacts.append(artifact)
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "failed",
            "tool": "tabula",
            "source": str(source),
            "candidate_pages": candidate_pages,
            "pages": pages_spec,
            "message": str(exc),
            "table_artifacts": artifacts,
        }
    return {
        "status": "ok",
        "tool": "tabula",
        "source": str(source),
        "candidate_pages": candidate_pages,
        "pages": pages_spec,
        "table_artifacts": artifacts,
    }


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


def dataframe_to_rows(dataframe: Any) -> list[list[Any]]:
    if dataframe is None:
        return []
    try:
        values = dataframe.values.tolist()
    except Exception:
        return []
    return [["" if cell is None else str(cell) for cell in row] for row in values]


def safe_float(value: Any) -> float | None:
    try:
        return round(float(value), 3)
    except Exception:
        return None


def write_table_artifacts(output_dir: Path, page_number: int, table_number: int, rows: list[list[Any]], *, prefix: str = "pdfplumber") -> dict[str, Any]:
    stem = f"{prefix}-page-{page_number:04d}-table-{table_number:02d}"
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
