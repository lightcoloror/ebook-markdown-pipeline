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
    parser.add_argument("--model-mode", choices=["local", "online", "hybrid", "auto"], default="local")
    args = parser.parse_args()
    result = inspect_document(
        args.input,
        recursive=args.recursive,
        include_hidden=args.include_hidden,
        sample_pages=args.sample_pages,
        model_mode=args.model_mode,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def inspect_document(
    input_path: Path,
    *,
    recursive: bool = True,
    include_hidden: bool = False,
    sample_pages: int = 8,
    model_mode: str = "local",
) -> dict[str, Any]:
    if input_path.is_dir():
        if is_web_content_archive(input_path):
            return inspect_web_content_archive(input_path, model_mode=model_mode)
        return inspect_directory(input_path, recursive=recursive, include_hidden=include_hidden, sample_pages=sample_pages, model_mode=model_mode)
    if not input_path.exists():
        return {
            "status": "missing",
            "input": str(input_path),
            "kind": "missing",
            "recommendation": "check_path",
            "warnings": [f"Input does not exist: {input_path}"],
        }
    return inspect_file(input_path, sample_pages=sample_pages, model_mode=model_mode)


def is_web_content_archive(input_path: Path) -> bool:
    manifest_path = input_path / "rebuild_input" / "manifest.json"
    if not manifest_path.is_file():
        return False
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    inputs = payload.get("inputs") if isinstance(payload, dict) else None
    return isinstance(inputs, dict) and any(key in inputs for key in {"source_html", "source_markdown", "screenshot"})


def inspect_web_content_archive(input_path: Path, *, model_mode: str = "local") -> dict[str, Any]:
    manifest_path = input_path / "rebuild_input" / "manifest.json"
    payload = {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    inputs = payload.get("inputs") if isinstance(payload, dict) else {}
    image_assets = payload.get("image_assets") if isinstance(payload, dict) else []
    screenshot = str((inputs or {}).get("screenshot") or "")
    warnings = []
    if not screenshot:
        warnings.append("Archive manifest has no screenshot; visual OCR/layout check will create a pending contract.")
    return {
        "status": "ok",
        "input": str(input_path),
        "kind": "web_archive",
        "extension": "",
        "manifest": str(manifest_path),
        "counts": {
            "image_assets": len(image_assets) if isinstance(image_assets, list) else 0,
            "has_screenshot": bool(screenshot),
            "has_source_html": bool((inputs or {}).get("source_html")),
            "has_source_markdown": bool((inputs or {}).get("source_markdown")),
        },
        "recommendation": "process_web_archive_visual_check",
        "structure_strategy": {
            "mode": "web_archive_visual_check",
            "confidence": "medium" if screenshot else "low",
            "reason": "Use web-content-fetcher as the source-of-truth archive and add visual OCR/layout/table/image-position evidence under visual_check/.",
        },
        "online_enhancement": online_enhancement_for_web_archive(has_screenshot=bool(screenshot), model_mode=model_mode),
        "next_actions": [
            {"tool": "process_web_archive", "why": "prepare visual_check artifacts for archive rebuild"},
            {"tool": "read_artifact", "artifact_type": "visual_check_json", "why": "inspect warnings and generated visual-check artifact paths"},
        ],
        "warnings": warnings,
    }


def inspect_directory(
    input_path: Path,
    *,
    recursive: bool,
    include_hidden: bool,
    sample_pages: int,
    model_mode: str,
) -> dict[str, Any]:
    image_sources = collect_image_sources(input_path, recursive=recursive, include_hidden=include_hidden)
    document_sources = collect_document_sources(input_path, recursive=recursive, include_hidden=include_hidden)
    sample_files = [inspect_file(path, sample_pages=sample_pages, model_mode=model_mode) for path in (document_sources + image_sources)[:20]]
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
        "online_enhancement": online_enhancement_for_directory(
            sample_files,
            document_count=len(document_sources),
            image_count=len(image_sources),
            model_mode=model_mode,
        ),
        "next_actions": directory_next_actions(recommendation, structure_strategy),
        "warnings": warnings,
        "sample_files": sample_files,
    }


def inspect_file(input_path: Path, *, sample_pages: int, model_mode: str = "local") -> dict[str, Any]:
    suffix = input_path.suffix.lower()
    if suffix in PDF_FORMATS:
        return inspect_pdf(input_path, sample_pages=sample_pages, model_mode=model_mode)
    if suffix in IMAGE_EXTENSIONS:
        return inspect_image(input_path, model_mode=model_mode)
    if suffix in SUPPORTED_FORMATS:
        return inspect_supported_document(input_path, model_mode=model_mode)
    return {
        "status": "unsupported",
        "input": str(input_path),
        "kind": "unsupported",
        "extension": suffix,
        "recommendation": "unsupported",
        "warnings": [f"Unsupported file extension: {suffix}"],
    }


def inspect_pdf(input_path: Path, *, sample_pages: int, model_mode: str = "local") -> dict[str, Any]:
    options = normalize_command_options(default_options())
    preflight = inspect_pdf_preflight(input_path, options, sample_pages=sample_pages)
    outline = extract_pdf_outline(input_path)
    warnings = []
    if preflight.scanned_likely:
        warnings.append("PDF appears scanned or has weak text layer.")
    if getattr(preflight, "presentation_like", False):
        warnings.append("PDF appears to be a slide deck or PPT export; page-level layout may matter more than book-style chapters.")
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
        "outline": outline,
        "recommendation": recommend_pdf_tool(preflight),
        "structure_strategy": structure_strategy,
        "online_enhancement": online_enhancement_for_pdf(preflight, model_mode=model_mode),
        "next_actions": pdf_next_actions(preflight, structure_strategy),
        "warnings": warnings,
    }


def extract_pdf_outline(input_path: Path, limit: int = 80) -> dict[str, Any]:
    try:
        import pymupdf

        with pymupdf.open(str(input_path)) as doc:
            toc = doc.get_toc(simple=True)
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "count": 0, "items": [], "message": str(exc)}
    items = []
    for level, title, page in toc[:limit]:
        items.append(
            {
                "level": int(level),
                "title": str(title).strip(),
                "page": int(page) if page else None,
            }
        )
    return {
        "status": "ok",
        "count": len(toc),
        "truncated": len(toc) > limit,
        "items": items,
    }


def inspect_image(input_path: Path, *, model_mode: str = "local") -> dict[str, Any]:
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
        "recommendation": "recognize_image_as_markdown",
        "structure_strategy": {
            "mode": "single_image_recognition",
            "confidence": "medium" if width and height and min(width, height) >= 600 else "low",
            "reason": "Default recognition should produce Markdown/review artifacts; use location indexing only when a query asks where information appears.",
        },
        "online_enhancement": online_enhancement_for_image(width=width, height=height, model_mode=model_mode),
        "next_actions": [
            {"tool": "start_image_book_rebuild", "why": "recognize the image into Markdown and review artifacts"},
            {"tool": "start_location_index", "why": "only use when the task is page/image-level keyword location"},
        ],
        "warnings": warnings,
    }


def inspect_supported_document(input_path: Path, *, model_mode: str = "local") -> dict[str, Any]:
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
        "online_enhancement": online_enhancement_for_document(suffix, model_mode=model_mode),
        "next_actions": supported_document_next_actions(suffix, recommendation),
        "warnings": warnings,
    }


def directory_structure_strategy(*, document_count: int, image_count: int) -> dict[str, Any]:
    if image_count and not document_count:
        return {
            "mode": "image_book_recognition",
            "confidence": "medium" if image_count >= 8 else "low",
            "reason": "Image folders default to OCR plus ordering/deduplication for Markdown recognition; use location indexing only when a query asks where information appears.",
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
    if mode in {"image_book_or_location_index", "image_book_recognition"}:
        return [
            {"tool": "start_image_book_rebuild", "why": "recognize screenshots/images into Markdown and review artifacts"},
            {"tool": "start_location_index", "why": "only use page/image-level search when exact location is requested"},
        ]
    if recommendation == "inspect_then_route":
        return [{"tool": "process_material", "why": "let the router split mixed material by intent and file type"}]
    if recommendation == "scan_books":
        return [{"tool": "scan_books", "why": "preview conversion pipelines and output paths before running"}]
    return []


def pdf_structure_strategy(preflight) -> dict[str, Any]:
    if getattr(preflight, "presentation_like", False):
        return {
            "mode": "presentation_pdf_slide_recovery",
            "confidence": "medium",
            "reason": "PDF page aspect ratio and block density look like slides exported from PPT; treat each page as a slide and preserve page-level layout cues.",
            "preferred_tools": ["mineru", "docling", "umi", "pymupdf4llm"],
        }
    if preflight.bookmark_count:
        base = {
            "mode": "bookmark_guided_structure_recovery",
            "confidence": "high",
            "reason": "PDF has built-in bookmarks that can guide Markdown heading reconstruction and review.",
            "preferred_tools": ["mineru", "docling", "pymupdf4llm"],
        }
        if preflight.scanned_likely:
            base["confidence"] = "medium"
            base["reason"] = "PDF has bookmarks, but weak text layer means OCR output still needs manual structure review."
            base["preferred_tools"] = ["mineru", "umi"]
        return base
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
    if mode == "presentation_pdf_slide_recovery":
        return [
            {"tool": "start_conversion", "pdf_pipeline_mode": "mineru", "why": "recover slide titles, text boxes, and visual layout blocks"},
            {"tool": "start_conversion", "pdf_pipeline_mode": "pymupdf4llm", "why": "create a fast text-layer baseline for comparison"},
            {"tool": "start_location_index", "why": "build page-level search when only slide/page location is needed"},
        ]
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
    if mode == "bookmark_guided_structure_recovery":
        return [
            {"tool": "start_conversion", "pdf_pipeline_mode": "mineru", "why": "recover layout while using bookmarks as structure review anchors"},
            {"tool": "read_artifact", "artifact_type": "review_report", "why": "check whether output headings align with PDF bookmarks"},
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


def online_enhancement_base(
    *,
    model_mode: str,
    recommended: bool,
    routes: list[str],
    reason: str,
    estimated_pages: int | None = None,
    estimated_items: int | None = None,
    cost_risk: str = "low",
    privacy_risk: str = "medium",
) -> dict[str, Any]:
    model_mode = model_mode if model_mode in {"local", "online", "hybrid", "auto"} else "local"
    return {
        "model_mode": model_mode,
        "recommended": recommended,
        "enabled_by_model_mode": bool(recommended and model_mode in {"online", "hybrid", "auto"}),
        "remote_call_enabled": False,
        "recommended_routes": routes if recommended else [],
        "estimated_pages": estimated_pages,
        "estimated_items": estimated_items,
        "estimated_cost_risk": cost_risk if recommended else "none",
        "privacy_risk": privacy_risk if recommended else "none",
        "reason": reason,
        "next_step": "Use model_mode=hybrid or online in a future provider-backed pipeline; current inspection never calls remote APIs.",
    }


def online_cost_risk_for_pages(pages: int) -> str:
    if pages >= 100:
        return "high"
    if pages >= 20:
        return "medium"
    return "low"


def online_enhancement_for_pdf(preflight, *, model_mode: str) -> dict[str, Any]:
    pages = int(getattr(preflight, "page_count", 0) or 0)
    routes: list[str] = []
    reasons: list[str] = []
    if getattr(preflight, "presentation_like", False):
        routes.extend(["vlm_layout", "text_structure_llm"])
        reasons.append("presentation-like PDF may need slide/page visual layout recovery")
    if getattr(preflight, "scanned_likely", False):
        routes.extend(["ocr_layout", "vlm_layout"])
        reasons.append("weak text layer or scanned pages may need OCR/VLM enhancement")
    if getattr(preflight, "complex_layout_likely", False):
        routes.extend(["vlm_layout", "table_repair", "text_structure_llm"])
        reasons.append("complex layout/tables/multicolumn signals may need layout-aware enhancement")
    if getattr(preflight, "bookmark_count", 0):
        routes.append("text_structure_llm")
        reasons.append("PDF bookmarks can guide low-confidence heading repair after local conversion")
    routes = unique_strings(routes)
    recommended = bool(routes)
    return online_enhancement_base(
        model_mode=model_mode,
        recommended=recommended,
        routes=routes,
        reason="; ".join(reasons) if reasons else "text-layer PDF usually stays local-first",
        estimated_pages=pages,
        cost_risk=online_cost_risk_for_pages(pages),
        privacy_risk="high" if recommended else "none",
    )


def online_enhancement_for_image(*, width: int, height: int, model_mode: str) -> dict[str, Any]:
    pixels = max(0, width) * max(0, height)
    wide = bool(width and height and max(width, height) / max(1, min(width, height)) >= 1.8)
    layout_heavy = pixels >= 1_800_000 or wide
    routes = ["vlm_layout", "ocr_layout"] if layout_heavy else []
    recommended = bool(routes)
    reason = "large or wide image may be an infographic/layout-heavy screenshot" if layout_heavy else "simple image should use local OCR/image-book recognition first"
    return online_enhancement_base(
        model_mode=model_mode,
        recommended=recommended,
        routes=routes,
        reason=reason,
        estimated_items=1,
        cost_risk="low" if pixels < 4_000_000 else "medium",
        privacy_risk="medium" if recommended else "none",
    )


def online_enhancement_for_document(suffix: str, *, model_mode: str) -> dict[str, Any]:
    structure_risky = suffix in DOCLING_FORMATS
    recommended = bool(structure_risky)
    return online_enhancement_base(
        model_mode=model_mode,
        recommended=recommended,
        routes=["text_structure_llm"] if structure_risky else [],
        reason="Office-like documents may use online text-structure repair only after local conversion reports low confidence."
        if structure_risky
        else "ebook/text documents should stay local-first unless quality review flags weak headings",
        estimated_items=1,
        cost_risk="low",
        privacy_risk="medium" if recommended else "none",
    )


def online_enhancement_for_web_archive(*, has_screenshot: bool, model_mode: str) -> dict[str, Any]:
    recommended = bool(has_screenshot)
    return online_enhancement_base(
        model_mode=model_mode,
        recommended=recommended,
        routes=["vlm_layout", "table_repair"] if has_screenshot else [],
        reason="web archive screenshots can use VLM/table repair as a visual-check enhancement" if has_screenshot else "no screenshot available for visual enhancement",
        estimated_items=1 if has_screenshot else 0,
        cost_risk="low",
        privacy_risk="medium" if recommended else "none",
    )


def online_enhancement_for_directory(sample_files: list[dict[str, Any]], *, document_count: int, image_count: int, model_mode: str) -> dict[str, Any]:
    recommended_samples = [item.get("online_enhancement") or {} for item in sample_files if (item.get("online_enhancement") or {}).get("recommended")]
    routes = unique_strings(route for item in recommended_samples for route in (item.get("recommended_routes") or []))
    estimated_pages = sum(int((item.get("online_enhancement") or {}).get("estimated_pages") or 0) for item in sample_files)
    estimated_items = document_count + image_count
    recommended = bool(routes)
    if not routes and image_count and not document_count:
        reason = "image-only folders should use local image-book recognition first; online enhancement is only for layout-heavy samples"
    elif routes:
        reason = "one or more sampled files look suitable for optional online enhancement"
    else:
        reason = "sampled files do not need online enhancement before local conversion"
    return online_enhancement_base(
        model_mode=model_mode,
        recommended=recommended,
        routes=routes,
        reason=reason,
        estimated_pages=estimated_pages or None,
        estimated_items=estimated_items,
        cost_risk=online_cost_risk_for_pages(estimated_pages) if estimated_pages else ("medium" if estimated_items >= 50 else "low"),
        privacy_risk="high" if recommended and document_count else ("medium" if recommended else "none"),
    )


def unique_strings(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


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
    if getattr(preflight, "presentation_like", False):
        return "presentation_pdf_slide_recovery"
    if preflight.scanned_likely:
        return "build_location_index_or_mineru_ocr"
    if preflight.complex_layout_likely:
        return "mineru"
    return f"convert_document_{preflight.recommended_pipeline}"


if __name__ == "__main__":
    raise SystemExit(main())
