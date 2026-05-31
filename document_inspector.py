from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ebook_markdown_pipeline import default_options, normalize_command_options  # noqa: E402
from ebook_markdown_pipeline.batch_convert_books import (  # noqa: E402
    CALIBRE_INTERMEDIATE_FORMATS,
    PANDOC_DIRECT_FORMATS,
    PDF_FORMATS,
    SUPPORTED_FORMATS,
    detect_source_kind,
    inspect_pdf_preflight,
)
from ebook_markdown_pipeline.document_locator import IMAGE_EXTENSIONS  # noqa: E402
from ebook_markdown_pipeline.image_book_rebuilder import collect_image_sources, image_metadata  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect documents/images and recommend recognition tools.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--include-hidden", action="store_true")
    parser.add_argument("--sample-pages", type=int, default=8)
    args = parser.parse_args()
    result = inspect_document(
        args.input,
        recursive=args.recursive,
        include_hidden=args.include_hidden,
        sample_pages=args.sample_pages,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def inspect_document(
    input_path: Path,
    *,
    recursive: bool = True,
    include_hidden: bool = False,
    sample_pages: int = 8,
) -> dict[str, Any]:
    if input_path.is_dir():
        return inspect_directory(input_path, recursive=recursive, include_hidden=include_hidden, sample_pages=sample_pages)
    if not input_path.exists():
        return {
            "status": "missing",
            "input": str(input_path),
            "kind": "missing",
            "recommendation": "check_path",
            "warnings": [f"Input does not exist: {input_path}"],
        }
    return inspect_file(input_path, sample_pages=sample_pages)


def inspect_directory(
    input_path: Path,
    *,
    recursive: bool,
    include_hidden: bool,
    sample_pages: int,
) -> dict[str, Any]:
    image_sources = collect_image_sources(input_path, recursive=recursive, include_hidden=include_hidden)
    document_sources = collect_document_sources(input_path, recursive=recursive, include_hidden=include_hidden)
    sample_files = [inspect_file(path, sample_pages=sample_pages) for path in (document_sources + image_sources)[:20]]
    warnings = []
    if not document_sources and not image_sources:
        warnings.append("No supported document/image files found.")
    recommendation = "rebuild_image_book" if image_sources and not document_sources else "scan_books"
    if document_sources and image_sources:
        recommendation = "inspect_then_route"
    return {
        "status": "ok",
        "input": str(input_path),
        "kind": "directory",
        "recursive": recursive,
        "counts": {
            "documents": len(document_sources),
            "images": len(image_sources),
            "total_supported": len(document_sources) + len(image_sources),
        },
        "recommendation": recommendation,
        "warnings": warnings,
        "sample_files": sample_files,
    }


def inspect_file(input_path: Path, *, sample_pages: int) -> dict[str, Any]:
    suffix = input_path.suffix.lower()
    if suffix in PDF_FORMATS:
        return inspect_pdf(input_path, sample_pages=sample_pages)
    if suffix in IMAGE_EXTENSIONS:
        return inspect_image(input_path)
    if suffix in SUPPORTED_FORMATS:
        return inspect_supported_document(input_path)
    return {
        "status": "unsupported",
        "input": str(input_path),
        "kind": "unsupported",
        "extension": suffix,
        "recommendation": "unsupported",
        "warnings": [f"Unsupported file extension: {suffix}"],
    }


def inspect_pdf(input_path: Path, *, sample_pages: int) -> dict[str, Any]:
    options = normalize_command_options(default_options())
    preflight = inspect_pdf_preflight(input_path, options, sample_pages=sample_pages)
    warnings = []
    if preflight.scanned_likely:
        warnings.append("PDF appears scanned or has weak text layer.")
    if preflight.complex_layout_likely:
        warnings.append("PDF appears to have complex layout, images, tables, or multiple columns.")
    if preflight.page_count >= 200:
        warnings.append("Long PDF; prefer segmented processing and progress polling.")
    return {
        "status": "ok",
        "input": str(input_path),
        "kind": "pdf",
        "extension": ".pdf",
        "size_bytes": input_path.stat().st_size,
        "preflight": asdict(preflight),
        "recommendation": recommend_pdf_tool(preflight),
        "warnings": warnings,
    }


def inspect_image(input_path: Path) -> dict[str, Any]:
    width, height, image_hash = image_metadata(input_path)
    warnings = []
    if width == 0 or height == 0:
        warnings.append("Could not read image dimensions.")
    if min(width, height) < 600 and width and height:
        warnings.append("Image may be low resolution for OCR.")
    return {
        "status": "ok",
        "input": str(input_path),
        "kind": "image",
        "extension": input_path.suffix.lower(),
        "size_bytes": input_path.stat().st_size,
        "image": {
            "width": width,
            "height": height,
            "hash": image_hash,
        },
        "recommendation": "build_location_index_or_rebuild_image_book",
        "warnings": warnings,
    }


def inspect_supported_document(input_path: Path) -> dict[str, Any]:
    suffix = input_path.suffix.lower()
    source_kind = detect_source_kind(input_path)
    if suffix in PANDOC_DIRECT_FORMATS:
        recommendation = "convert_document_pandoc"
    elif suffix in CALIBRE_INTERMEDIATE_FORMATS:
        recommendation = "convert_document_calibre_then_pandoc"
    else:
        recommendation = "convert_document"
    return {
        "status": "ok",
        "input": str(input_path),
        "kind": source_kind,
        "extension": suffix,
        "size_bytes": input_path.stat().st_size,
        "recommendation": recommendation,
        "warnings": [],
    }


def collect_document_sources(input_path: Path, *, recursive: bool, include_hidden: bool) -> list[Path]:
    root = input_path.resolve()
    pattern = "**/*" if recursive else "*"
    sources = []
    for path in root.glob(pattern):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_FORMATS:
            continue
        relative_parts = path.relative_to(root).parts
        if not include_hidden and any(part.startswith(".") for part in relative_parts):
            continue
        sources.append(path.resolve())
    return sorted(sources, key=lambda item: str(item).lower())


def recommend_pdf_tool(preflight) -> str:
    if preflight.scanned_likely:
        return "build_location_index_or_mineru_ocr"
    if preflight.complex_layout_likely:
        return "mineru"
    return f"convert_document_{preflight.recommended_pipeline}"


if __name__ == "__main__":
    raise SystemExit(main())
