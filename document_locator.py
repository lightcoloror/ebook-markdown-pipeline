from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

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


PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
SUPPORTED_LOCATION_EXTENSIONS = PDF_EXTENSIONS | IMAGE_EXTENSIONS


@dataclass
class LocationRecord:
    source: str
    kind: str
    page: int | None
    text: str
    char_count: int
    engine: str
    status: str
    message: str = ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and query page/image-level text location indexes.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    index_parser = subparsers.add_parser("index", help="Index PDFs and images at page/image granularity.")
    index_parser.add_argument("input", type=Path)
    index_parser.add_argument("output", type=Path)
    index_parser.add_argument("--recursive", action="store_true")
    index_parser.add_argument("--include-hidden", action="store_true")
    index_parser.add_argument("--ocr", choices=["auto", "always", "never"], default="auto")
    index_parser.add_argument("--umi-render-dpi", type=int, default=200)
    index_parser.add_argument("--umi-paddle-exe", default=suggested_umi_paddle_exe())
    index_parser.add_argument("--umi-paddle-module", default=suggested_umi_paddle_module())

    query_parser = subparsers.add_parser("query", help="Query a generated SQLite location index.")
    query_parser.add_argument("index", type=Path)
    query_parser.add_argument("query")
    query_parser.add_argument("--limit", type=int, default=20)
    query_parser.add_argument("--format", choices=["json", "markdown"], default="json")

    args = parser.parse_args()
    if args.command == "index":
        result = build_location_index(
            input_path=args.input,
            output_dir=args.output,
            recursive=args.recursive,
            include_hidden=args.include_hidden,
            ocr_mode=args.ocr,
            umi_render_dpi=args.umi_render_dpi,
            umi_paddle_exe=args.umi_paddle_exe,
            umi_paddle_module=args.umi_paddle_module,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "query":
        result = query_location_index(args.index, args.query, limit=args.limit)
        if args.format == "markdown":
            print(render_query_markdown(result))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    return 2


def build_location_index(
    input_path: Path,
    output_dir: Path,
    *,
    recursive: bool = True,
    include_hidden: bool = False,
    ocr_mode: str = "auto",
    umi_render_dpi: int = 200,
    umi_paddle_exe: str | None = None,
    umi_paddle_module: str | None = None,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    sources = collect_location_sources(input_path, recursive=recursive, include_hidden=include_hidden)
    jsonl_path = output_dir / "document_locations.jsonl"
    sqlite_path = output_dir / "document_locations.sqlite"

    options = normalize_command_options(
        default_options(
            umi_render_dpi=umi_render_dpi,
            umi_paddle_exe=umi_paddle_exe or suggested_umi_paddle_exe(),
            umi_paddle_module=umi_paddle_module or suggested_umi_paddle_module(),
        )
    )
    ocr_engine = None
    records: list[LocationRecord] = []
    def ensure_ocr_engine():
        nonlocal ocr_engine
        if ocr_engine is None:
            ocr_engine = create_umi_paddle_engine(options)
        return ocr_engine

    try:
        for source in sources:
            try:
                if source.suffix.lower() in PDF_EXTENSIONS:
                    records.extend(index_pdf(source, options, ocr_mode, ensure_ocr_engine))
                elif source.suffix.lower() in IMAGE_EXTENSIONS:
                    records.append(index_image(source, ocr_mode, ensure_ocr_engine))
            except Exception as exc:  # noqa: BLE001
                records.append(
                    LocationRecord(
                        source=str(source),
                        kind="file",
                        page=None,
                        text="",
                        char_count=0,
                        engine="error",
                        status="failed",
                        message=str(exc),
                    )
                )
    finally:
        if ocr_engine is not None:
            close_umi_paddle_engine(ocr_engine)

    write_jsonl(jsonl_path, records)
    write_sqlite(sqlite_path, records)
    return {
        "input": str(input_path),
        "output": str(output_dir),
        "jsonl": str(jsonl_path),
        "sqlite": str(sqlite_path),
        "source_count": len(sources),
        "record_count": len(records),
        "ocr_mode": ocr_mode,
        "status_counts": count_by_status(records),
    }


def query_location_index(index_path: Path, query: str, *, limit: int = 20) -> dict:
    query = query.strip()
    limit = clamp_limit(limit)
    if not query:
        return empty_query_result(index_path, query, message="Query is empty.")
    if not index_path.exists():
        return empty_query_result(index_path, query, message="Index file not found.")

    conn = sqlite3.connect(str(index_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = []
        used_query = query
        search_mode = "fts"
        for candidate_query in build_fts_query_candidates(query):
            rows = execute_location_query(conn, candidate_query, limit)
            used_query = candidate_query
            if rows:
                break
        if not rows:
            rows = execute_like_query(conn, query, limit)
            used_query = query
            search_mode = "like"
        if not rows:
            rows = execute_like_terms_query(conn, split_query_terms(query), limit)
            used_query = " AND ".join(split_query_terms(query))
            search_mode = "like_terms"
        return {
            "index": str(index_path),
            "query": query,
            "used_query": used_query,
            "search_mode": search_mode,
            "count": len(rows),
            "matches": enrich_matches(rows, query),
        }
    finally:
        conn.close()


def clamp_limit(limit: int) -> int:
    return min(max(limit, 1), 200)


def empty_query_result(index_path: Path, query: str, *, message: str | None = None) -> dict:
    result = {
        "index": str(index_path),
        "query": query,
        "used_query": query,
        "search_mode": "none",
        "count": 0,
        "matches": [],
    }
    if message:
        result["message"] = message
    return result


def execute_location_query(conn: sqlite3.Connection, query: str, limit: int) -> list[sqlite3.Row]:
    try:
        return conn.execute(
            """
            SELECT
              locations.source,
              locations.kind,
              locations.page,
              locations.char_count,
              locations.engine,
              locations.text,
              snippet(location_fts, 0, '[', ']', ' ... ', 12) AS snippet
            FROM location_fts
            JOIN locations ON locations.id = location_fts.rowid
            WHERE location_fts MATCH ?
            ORDER BY bm25(location_fts)
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        return []


def execute_like_query(conn: sqlite3.Connection, query: str, limit: int) -> list[sqlite3.Row]:
    pattern = f"%{escape_like(query)}%"
    try:
        rows = conn.execute(
            """
            SELECT source, kind, page, char_count, engine, text
            FROM locations
            WHERE text LIKE ? ESCAPE '\\'
            ORDER BY char_count DESC
            LIMIT ?
            """,
            (pattern, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [row_with_snippet(row, query) for row in rows]


def execute_like_terms_query(conn: sqlite3.Connection, terms: list[str], limit: int) -> list[sqlite3.Row]:
    if not terms:
        return []
    clauses = " AND ".join(["lower(text) LIKE ? ESCAPE '\\'"] * len(terms))
    patterns = [f"%{escape_like(term.lower())}%" for term in terms]
    try:
        rows = conn.execute(
            f"""
            SELECT source, kind, page, char_count, engine, text
            FROM locations
            WHERE {clauses}
            ORDER BY char_count DESC
            LIMIT ?
            """,
            (*patterns, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [row_with_snippet(row, terms[0]) for row in rows]


def row_with_snippet(row: sqlite3.Row, query: str) -> dict:
    text = row["text"]
    position = text.lower().find(query.lower())
    if position < 0:
        position = 0
    start = max(0, position - 48)
    end = min(len(text), position + len(query) + 96)
    snippet = highlight_term(text[start:end], query)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return {
        "source": row["source"],
        "kind": row["kind"],
        "page": row["page"],
        "char_count": row["char_count"],
        "engine": row["engine"],
        "text": text,
        "snippet": f"{prefix}{snippet}{suffix}",
    }


def enrich_matches(rows: Iterable[sqlite3.Row | dict], query: str) -> list[dict]:
    query_terms = split_query_terms(query)
    matches = []
    for row in rows:
        match = dict(row)
        text = str(match.pop("text", ""))
        source = str(match.get("source", ""))
        page = match.get("page")
        token_hits = count_token_hits(text, query_terms)
        match.update(
            {
                "source_name": Path(source).name,
                "location": f"page {page}" if page else "image",
                "match_quality": classify_match_quality(text, query, query_terms),
                "token_hits": token_hits,
            }
        )
        matches.append(match)
    return sorted(matches, key=match_sort_key)


def split_query_terms(query: str) -> list[str]:
    return [token.lower() for token in re.split(r"[^\w\u4e00-\u9fff]+|_", query) if token]


def count_token_hits(text: str, terms: Iterable[str]) -> int:
    lowered = text.lower()
    return sum(1 for term in terms if term and term in lowered)


def classify_match_quality(text: str, query: str, terms: list[str]) -> str:
    lowered = text.lower()
    normalized_query = query.lower()
    if normalized_query and normalized_query in lowered:
        return "exact"
    token_hits = count_token_hits(text, terms)
    if terms and token_hits == len(terms):
        return "all_terms"
    if token_hits:
        return "partial_terms"
    return "unknown"


def match_sort_key(match: dict) -> tuple[int, int, str, int]:
    quality_rank = {"exact": 0, "all_terms": 1, "partial_terms": 2, "unknown": 3}
    page = match.get("page") or 0
    return (quality_rank.get(str(match.get("match_quality")), 9), -int(match.get("token_hits") or 0), str(match.get("source")), page)


def highlight_term(text: str, term: str) -> str:
    if not term:
        return text
    return re.sub(re.escape(term), lambda item: f"[{item.group(0)}]", text, count=1, flags=re.IGNORECASE)


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def build_fts_query_candidates(query: str) -> list[str]:
    candidates = [query]
    tokens = [token for token in re.split(r"[^\w\u4e00-\u9fff]+|_", query) if token]
    if len(tokens) > 1:
        candidates.append(" ".join(tokens))
        candidates.append(" OR ".join(tokens))
    return dedupe_preserve_order(candidates)


def dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def render_query_markdown(result: dict) -> str:
    lines = [
        f"# Location Query: {result['query']}",
        "",
        f"- Index: `{result['index']}`",
        f"- Search mode: `{result.get('search_mode', 'fts')}`",
        f"- Used query: `{result.get('used_query', result['query'])}`",
        f"- Matches: {result['count']}",
        "",
    ]
    if not result["matches"]:
        lines.append("No matches.")
        return "\n".join(lines).rstrip() + "\n"
    lines.extend(["| Source | Location | Quality | Engine | Snippet |", "| --- | --- | --- | --- | --- |"])
    for match in result["matches"]:
        source = markdown_cell(str(match["source"]))
        location = markdown_cell(str(match.get("location") or (f"Page {match['page']}" if match.get("page") else "Image")))
        quality = markdown_cell(str(match.get("match_quality", "")))
        engine = markdown_cell(str(match["engine"]))
        snippet = markdown_cell(str(match["snippet"]).replace("\n", " "))
        lines.append(f"| {source} | {location} | {quality} | {engine} | {snippet} |")
    return "\n".join(lines).rstrip() + "\n"


def markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def collect_location_sources(input_path: Path, *, recursive: bool, include_hidden: bool) -> list[Path]:
    if input_path.is_file():
        return [input_path.resolve()] if input_path.suffix.lower() in SUPPORTED_LOCATION_EXTENSIONS else []
    if not input_path.exists():
        return []
    pattern = "**/*" if recursive else "*"
    sources = []
    for path in input_path.glob(pattern):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_LOCATION_EXTENSIONS:
            continue
        if not include_hidden and any(part.startswith(".") for part in path.parts):
            continue
        sources.append(path.resolve())
    return sorted(sources, key=lambda item: str(item).lower())


def index_pdf(source: Path, options: argparse.Namespace, ocr_mode: str, ensure_ocr_engine) -> list[LocationRecord]:
    import pymupdf

    records = []
    document = pymupdf.open(str(source))
    try:
        with tempfile.TemporaryDirectory(prefix="location-pdf-pages-") as tmpdir:
            tmpdir_path = Path(tmpdir)
            for page_index in range(len(document)):
                page = document[page_index]
                page_number = page_index + 1
                text = "" if ocr_mode == "always" else page.get_text("text").strip()
                engine = "pymupdf"
                if not text and ocr_mode in {"auto", "always"}:
                    ocr_engine = ensure_ocr_engine()
                    image_path = tmpdir_path / f"{source.stem}-page-{page_number:04d}.png"
                    page.get_pixmap(dpi=options.umi_render_dpi).save(str(image_path))
                    text = umi_ocr_image(image_path, ocr_engine).strip()
                    engine = "umi-ocr"
                records.append(
                    LocationRecord(
                        source=str(source),
                        kind="pdf_page",
                        page=page_number,
                        text=text,
                        char_count=len(text),
                        engine=engine,
                        status="ok" if text else "empty",
                    )
                )
    finally:
        document.close()
    return records


def index_image(source: Path, ocr_mode: str, ensure_ocr_engine) -> LocationRecord:
    if ocr_mode == "never":
        return LocationRecord(
            source=str(source),
            kind="image",
            page=None,
            text="",
            char_count=0,
            engine="none",
            status="skipped",
            message="OCR disabled.",
        )
    ocr_engine = ensure_ocr_engine()
    text = umi_ocr_image(source, ocr_engine).strip()
    return LocationRecord(
        source=str(source),
        kind="image",
        page=None,
        text=text,
        char_count=len(text),
        engine="umi-ocr",
        status="ok" if text else "empty",
    )


def write_jsonl(path: Path, records: Iterable[LocationRecord]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")


def write_sqlite(path: Path, records: list[LocationRecord]) -> None:
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            """
            CREATE TABLE locations (
              id INTEGER PRIMARY KEY,
              source TEXT NOT NULL,
              kind TEXT NOT NULL,
              page INTEGER,
              text TEXT NOT NULL,
              char_count INTEGER NOT NULL,
              engine TEXT NOT NULL,
              status TEXT NOT NULL,
              message TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE VIRTUAL TABLE location_fts USING fts5(text, content='locations', content_rowid='id')")
        for record in records:
            cursor = conn.execute(
                """
                INSERT INTO locations (source, kind, page, text, char_count, engine, status, message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.source,
                    record.kind,
                    record.page,
                    record.text,
                    record.char_count,
                    record.engine,
                    record.status,
                    record.message,
                ),
            )
            conn.execute("INSERT INTO location_fts(rowid, text) VALUES (?, ?)", (cursor.lastrowid, record.text))
        conn.commit()
    finally:
        conn.close()


def count_by_status(records: Iterable[LocationRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        counts[record.status] = counts.get(record.status, 0) + 1
    return counts


if __name__ == "__main__":
    raise SystemExit(main())
