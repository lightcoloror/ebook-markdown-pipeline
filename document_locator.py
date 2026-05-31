from __future__ import annotations

import argparse
import json
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
            if source.suffix.lower() in PDF_EXTENSIONS:
                records.extend(index_pdf(source, options, ocr_mode, ensure_ocr_engine))
            elif source.suffix.lower() in IMAGE_EXTENSIONS:
                records.append(index_image(source, ocr_mode, ensure_ocr_engine))
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
    conn = sqlite3.connect(str(index_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT
              locations.source,
              locations.kind,
              locations.page,
              locations.char_count,
              locations.engine,
              snippet(location_fts, 0, '[', ']', ' ... ', 12) AS snippet
            FROM location_fts
            JOIN locations ON locations.id = location_fts.rowid
            WHERE location_fts MATCH ?
            ORDER BY bm25(location_fts)
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
        return {
            "index": str(index_path),
            "query": query,
            "count": len(rows),
            "matches": [dict(row) for row in rows],
        }
    finally:
        conn.close()


def collect_location_sources(input_path: Path, *, recursive: bool, include_hidden: bool) -> list[Path]:
    if input_path.is_file():
        return [input_path] if input_path.suffix.lower() in SUPPORTED_LOCATION_EXTENSIONS else []
    if not input_path.exists():
        return []
    pattern = "**/*" if recursive else "*"
    sources = []
    for path in input_path.glob(pattern):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_LOCATION_EXTENSIONS:
            continue
        if not include_hidden and any(part.startswith(".") for part in path.parts):
            continue
        sources.append(path)
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
