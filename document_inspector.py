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
from ebook_markdown_pipeline.docling_backend import DOCLING_FORMATS, docling_available  # noqa: E402
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
    structure_strategy = directory_structure_strategy(
        document_count=len(document_sources),
        image_count=len(image_sources),
    )
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
        "structure_strategy": structure_strategy,
        "next_actions": directory_next_actions(recommendation, structure_strategy),
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
    structure_strategy = pdf_structure_strategy(preflight)
    return {
        "status": "ok",
        "input": str(input_path),
        "kind": "pdf",
        "extension": ".pdf",
        "size_bytes": input_path.stat().st_size,
        "preflight": asdict(preflight),
        "recommendation": recommend_pdf_tool(preflight),
        "structure_strategy": structure_strategy,
        "next_actions": pdf_next_actions(preflight, structure_strategy),
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
        "structure_strategy": {
            "mode": "single_image_location",
            "confidence": "medium" if width and height and min(width, height) >= 600 else "low",
            "reason": "Single images can be indexed or grouped with neighboring screenshots, but one image alone cannot infer book structure.",
        },
        "next_actions": [
            {"tool": "start_location_index", "why": "find whether this image contains a query"},
            {"tool": "start_image_book_rebuild", "why": "use the parent folder when this image is part of a screenshot sequence"},
        ],
        "warnings": warnings,
    }


def inspect_supported_document(input_path: Path) -> dict[str, Any]:
    suffix = input_path.suffix.lower()
    source_kind = detect_source_kind(input_path)
    if suffix in PANDOC_DIRECT_FORMATS:
        recommendation = "convert_document_pandoc"
    elif suffix in CALIBRE_INTERMEDIATE_FORMATS:
        recommendation = "convert_document_calibre_then_pandoc"
    elif suffix in DOCLING_FORMATS:
        recommendation = "convert_document_docling"
    else:
        recommendation = "convert_document"
    warnings = []
    if suffix in DOCLING_FORMATS and not docling_available():
        warnings.append("Docling optional backend is not installed.")
    return {
        "status": "ok",
        "input": str(input_path),
        "kind": source_kind,
        "extension": suffix,
        "size_bytes": input_path.stat().st_size,
        "recommendation": recommendation,
        "structure_strategy": supported_document_structure_strategy(suffix),
        "next_actions": supported_document_next_actions(suffix, recommendation),
        "warnings": warnings,
    }


def directory_structure_strategy(*, document_count: int, image_count: int) -> dict[str, Any]:
    if image_count and not document_count:
        return {
            "mode": "image_book_or_location_index",
            "confidence": "medium" if image_count >= 8 else "low",
            "reason": "Image folders need OCR plus ordering/deduplication; small sets are usually better treated as page/image location indexes.",
        }
    if document_count and image_count:
        return {
            "mode": "mixed_material_routing",
            "confidence": "medium",
            "reason": "Mixed folders should inspect samples and route documents/images separately.",
        }
    if document_count:
        return {
            "mode": "document_conversion",
            "confidence": "high",
            "reason": "Supported document formats can use the normal conversion planner.",
        }
    return {"mode": "none", "confidence": "low", "reason": "No supported material found."}


def directory_next_actions(recommendation: str, strategy: dict[str, Any]) -> list[dict[str, str]]:
    mode = str(strategy.get("mode") or "")
    if mode == "image_book_or_location_index":
        return [
            {"tool": "start_image_book_rebuild", "why": "recover Markdown order from screenshots when there are enough images"},
            {"tool": "start_location_index", "why": "use page/image-level search when exact full Markdown is not needed"},
        ]
    if recommendation == "inspect_then_route":
        return [{"tool": "process_material", "why": "let the router split mixed material by intent and file type"}]
    if recommendation == "scan_books":
        return [{"tool": "scan_books", "why": "preview conversion pipelines and output paths before running"}]
    return []


def pdf_structure_strategy(preflight) -> dict[str, Any]:
    if preflight.scanned_likely:
        return {
            "mode": "ocr_first_with_review",
            "confidence": "medium",
            "reason": "Weak text layer means structure must be inferred from OCR text, page images, and manual review.",
            "preferred_tools": ["umi", "mineru"],
        }
    if preflight.complex_layout_likely:
        return {
            "mode": "layout_aware_structure_recovery",
            "confidence": "medium",
            "reason": "Complex layout needs a structure-aware parser and pipeline comparison.",
            "preferred_tools": ["mineru", "docling", "marker"],
        }
    return {
        "mode": "text_layer_conversion",
        "confidence": "high",
        "reason": "PDF appears to have a usable text layer; fast extraction plus quality review is usually enough.",
        "preferred_tools": [preflight.recommended_pipeline or "pymupdf4llm"],
    }


def pdf_next_actions(preflight, strategy: dict[str, Any]) -> list[dict[str, str]]:
    mode = str(strategy.get("mode") or "")
    if mode == "ocr_first_with_review":
        return [
            {"tool": "start_location_index", "why": "build a page-level index quickly before full OCR conversion if only coarse location is needed"},
            {"tool": "start_conversion", "pdf_pipeline_mode": "umi", "why": "OCR-first fallback for long scanned materials"},
            {"tool": "export_location_review_pack", "why": "review representative OCR pages/images"},
        ]
    if mode == "layout_aware_structure_recovery":
        return [
            {"tool": "start_conversion", "pdf_pipeline_mode": "mineru", "why": "recover headings, tables, and layout blocks"},
            {"tool": "start_conversion", "pdf_pipeline_mode": "docling", "why": "run a versioned second pass when MinerU output needs structure comparison"},
            {"tool": "start_conversion", "pdf_pipeline_mode": "pymupdf4llm", "why": "use a lightweight baseline for text-layer comparison"},
        ]
    return [
        {"tool": "start_conversion", "pdf_pipeline_mode": preflight.recommended_pipeline or "pymupdf4llm", "why": "convert with the recommended lightweight route"},
        {"tool": "read_artifact", "artifact_type": "review_report", "why": "confirm quality before accepting"},
    ]


def supported_document_structure_strategy(suffix: str) -> dict[str, str]:
    if suffix in {".epub"} | KINDLE_LIKE_EXTENSIONS:
        return {
            "mode": "toc_aligned_conversion",
            "confidence": "high",
            "reason": "Use ebook TOC/nav metadata when body headings are weak.",
        }
    if suffix in DOCLING_FORMATS:
        return {
            "mode": "docling_or_pandoc_structure",
            "confidence": "medium",
            "reason": "Office-like documents may preserve layout better through Docling when installed.",
        }
    return {
        "mode": "pandoc_text_structure",
        "confidence": "medium",
        "reason": "Pandoc can convert the document; quality review should catch missing headings or noise.",
    }


KINDLE_LIKE_EXTENSIONS = {".azw", ".azw3", ".mobi", ".kfx"}


def supported_document_next_actions(suffix: str, recommendation: str) -> list[dict[str, str]]:
    actions = [{"tool": "scan_books", "why": "preview detected format, pipeline, and output path"}]
    if suffix in {".epub"} | KINDLE_LIKE_EXTENSIONS:
        actions.append({"tool": "start_conversion", "why": "convert with TOC alignment and postprocess quality checks"})
    elif "docling" in recommendation:
        actions.append({"tool": "start_conversion", "why": "try Docling-backed conversion when available"})
    else:
        actions.append({"tool": "start_conversion", "why": "run normal conversion and inspect review checklist"})
    return actions


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
