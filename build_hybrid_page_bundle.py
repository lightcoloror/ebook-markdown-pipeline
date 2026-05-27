from __future__ import annotations

import argparse
import json
from pathlib import Path

import fitz


def parse_pages(value: str) -> list[int]:
    pages: list[int] = []
    for part in value.split(","):
        item = part.strip()
        if not item:
            continue
        if "-" in item:
            start_text, end_text = item.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if end < start:
                raise ValueError(f"Invalid page range: {item}")
            pages.extend(range(start, end + 1))
        else:
            pages.append(int(item))
    return pages


def extract_pages(source: Path, output_pdf: Path, pages: list[int]) -> None:
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    src_doc = fitz.open(source)
    out_doc = fitz.open()
    try:
        for page in pages:
            if page < 1 or page > src_doc.page_count:
                raise ValueError(f"Page {page} out of range 1..{src_doc.page_count}")
            out_doc.insert_pdf(src_doc, from_page=page - 1, to_page=page - 1)
        out_doc.save(output_pdf)
    finally:
        out_doc.close()
        src_doc.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a small PDF from selected source pages.")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--pages", required=True, help="1-based pages, e.g. 1,9,179-183")
    parser.add_argument("--output-pdf", required=True, type=Path)
    parser.add_argument("--mapping", required=True, type=Path)
    args = parser.parse_args()

    pages = parse_pages(args.pages)
    extract_pages(args.source, args.output_pdf, pages)
    args.mapping.parent.mkdir(parents=True, exist_ok=True)
    mapping = [
        {"bundle_page": index + 1, "source_page": page}
        for index, page in enumerate(pages)
    ]
    args.mapping.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {args.output_pdf}")
    print(f"Wrote {args.mapping}")
    print(f"Pages: {len(pages)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
