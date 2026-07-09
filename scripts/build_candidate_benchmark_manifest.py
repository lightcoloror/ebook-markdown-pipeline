from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR.parent))

from benchmark_utils import load_samples, safe_id, write_json  # noqa: E402
from ebook_markdown_pipeline.candidate_backend_registry import candidate_backends_for_sample_class  # noqa: E402


SCHEMA_VERSION = "candidate-benchmark-plan-v1"
DEFAULT_OUTPUT = PROJECT_DIR / "benchmarks" / "candidate-benchmark-plan.example.json"

CATEGORY_PROFILES: dict[str, dict[str, Any]] = {
    "pdf_text_layer": {
        "candidate_backends": ["pymupdf4llm", "docling", "markitdown"],
        "review_questions": ["Does the fast local route preserve headings and reading order?", "Is a heavy OCR/VLM route unnecessary?"],
        "expected_artifacts": ["markdown", "review_report", "conversion_report"],
    },
    "scanned_pdf": {
        "candidate_backends": ["ocrmypdf", "umi", "mineru"],
        "review_questions": ["Is OCR text complete without repeated headers/footers?", "Can a document VLM replace or simplify an existing heavy route?"],
        "expected_artifacts": ["pages_jsonl", "markdown", "review_report", "document_vlm_result_json"],
    },
    "pdf_two_column": {
        "candidate_backends": ["mineru", "docling", "Marker"],
        "review_questions": ["Is reading order correct across columns?", "Do layout boxes explain any Markdown ordering errors?"],
        "expected_artifacts": ["layout_candidates_json", "layout_overlay_image", "markdown", "review_report"],
    },
    "pdf_table": {
        "candidate_backends": ["pdfplumber", "Camelot", "Tabula", "Docling", "MinerU", "table_to_xlsx"],
        "review_questions": ["Are true tables preserved as tables?", "Are card/infographic layouts not forced into tables?", "Does the XLSX draft open and preserve the expected cell grid?"],
        "expected_artifacts": ["table_candidates_json", "document_vlm_result_json", "table_markdown", "table_html", "table_cells_json", "table_comparison_summary", "table_xlsx"],
    },
    "pdf_formula": {
        "candidate_backends": ["Pix2Text", "Marker", "MinerU", "Docling", "UniMERNet"],
        "review_questions": ["Are formulas preserved as LaTeX/Markdown?", "Are formula regions tied back to source pages?"],
        "expected_artifacts": ["formula_candidates_json", "document_vlm_result_json", "markdown", "review_report"],
    },
    "chinese_hierarchy_document": {
        "candidate_backends": ["Docling", "MarkItDown", "Pandoc", "MinerU", "structure_repair"],
        "review_questions": ["Are Chinese numbered clauses promoted to stable heading levels?", "Are ordinary body lines not over-promoted as headings?", "Do structure repair decisions cite domain grammar, PDF outline, font, MinerU, or Docling evidence?"],
        "expected_artifacts": ["markdown", "conversion_report", "review_report", "structure_report", "structure_json", "heading_candidates_json"],
    },
    "ppt_export_pdf": {
        "candidate_backends": ["mineru", "docling"],
        "review_questions": ["Are slide titles and text boxes preserved page-by-page?", "Is slide layout evidence available for review?"],
        "expected_artifacts": ["layout_candidates_json", "layout_overlay_image", "markdown", "review_report"],
    },
    "infographic_image": {
        "candidate_backends": ["Pix2Text", "Surya", "PaddleOCR-VL", "Qwen-VL"],
        "review_questions": ["Is visual reading order human-readable?", "Are non-table card regions kept out of table output?"],
        "expected_artifacts": ["layout_blocks_json", "markdown", "layout_overlay_image", "document_vlm_result_json", "layout_candidates_json", "table_candidates_json", "formula_candidates_json"],
    },
    "image_set": {
        "candidate_backends": ["image_book_rebuilder", "Umi-OCR", "RapidOCR"],
        "review_questions": ["Are duplicate/overlapping screenshots ordered correctly?", "Does OCR text retain page boundaries?"],
        "expected_artifacts": ["markdown", "order_report", "review_report"],
    },
    "web_archive": {
        "candidate_backends": ["process_web_archive"],
        "review_questions": ["Do screenshot visual checks align with source HTML/Markdown?", "Are image/table positions reviewable?"],
        "expected_artifacts": ["visual_check_json", "visual_blocks_json", "table_candidates_json", "image_positions_json"],
    },
    "academic_pdf": {
        "candidate_backends": ["GROBID", "Nougat", "Marker", "MinerU", "Docling"],
        "review_questions": ["Are title/authors/abstract/references extracted as side evidence?", "Are formulas and two-column reading order acceptable?"],
        "expected_artifacts": ["conversion_report", "structure_report", "formula_candidates_json", "review_report"],
    },
    "doc_office": {
        "candidate_backends": ["Docling", "MarkItDown", "Pandoc", "Tika"],
        "review_questions": ["Does the lightweight baseline preserve structure?", "Is Tika useful only as inspect evidence?"],
        "expected_artifacts": ["markdown", "conversion_report", "review_report"],
    },
}

CATEGORY_ALIASES = {
    "pdf": "pdf_text_layer",
    "complex_pdf": "pdf_two_column",
    "scanned_pdf": "scanned_pdf",
    "pdf_scan": "scanned_pdf",
    "pdf_table_heavy": "pdf_table",
    "chinese_contract": "chinese_hierarchy_document",
    "insurance_policy": "chinese_hierarchy_document",
    "insurance_contract": "chinese_hierarchy_document",
    "policy_contract": "chinese_hierarchy_document",
    "chinese_hierarchy": "chinese_hierarchy_document",
    "table_pdf": "pdf_table",
    "pdf_ppt": "ppt_export_pdf",
    "presentation_pdf": "ppt_export_pdf",
    "image": "infographic_image",
    "image_set_duplicates": "image_set",
    "docling_doc": "doc_office",
    "ebook_epub": "doc_office",
    "text_doc": "doc_office",
}

DEFAULT_SAMPLE_CLASSES = [
    "pdf_text_layer",
    "scanned_pdf",
    "pdf_two_column",
    "chinese_hierarchy_document",
    "pdf_table",
    "pdf_formula",
    "ppt_export_pdf",
    "infographic_image",
    "image_set",
    "web_archive",
    "academic_pdf",
    "doc_office",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a shared candidate benchmark plan without running models or converters.")
    parser.add_argument("--manifest", type=Path, help="Optional benchmark-samples-v1 manifest to normalize into a candidate benchmark plan.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--include-missing-template", action="store_true", default=True)
    args = parser.parse_args()

    samples = load_samples(args.manifest) if args.manifest else []
    payload = build_candidate_benchmark_plan(samples, manifest=args.manifest, include_missing_template=bool(args.include_missing_template))
    write_json(args.output, payload)
    print(json.dumps({"status": "ok", "output": str(args.output), "sample_count": len(payload["samples"]), "class_count": len(payload["sample_classes"])}, ensure_ascii=False))
    return 0


def build_candidate_benchmark_plan(samples: list[dict[str, Any]], *, manifest: Path | None = None, include_missing_template: bool = True) -> dict[str, Any]:
    normalized_samples = [normalize_sample(item) for item in samples if isinstance(item, dict)]
    present_classes = {sample["candidate_class"] for sample in normalized_samples}
    sample_classes = build_sample_classes(present_classes if normalized_samples else set(DEFAULT_SAMPLE_CLASSES), include_missing_template=include_missing_template)
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source_manifest": str(manifest) if manifest else "",
        "execution_policy": "plan_only_no_model_install_no_service_start",
        "promotion_gate": {
            "rule": "A heavy backend must beat or simplify an existing heavy route on shared samples before promotion.",
            "required_evidence": [
                "same sample class",
                "same review questions",
                "artifact evidence readable by read_artifact",
                "backend scorecard with external wrapper evidence",
            ],
        },
        "sample_classes": sample_classes,
        "samples": normalized_samples,
    }


def normalize_sample(item: dict[str, Any]) -> dict[str, Any]:
    category = str(item.get("category") or "unknown")
    candidate_class = normalize_category(category)
    profile = profile_for_class(candidate_class)
    path = str(item.get("path") or "")
    sample_id = str(item.get("id") or safe_id(Path(path).stem or candidate_class))
    return {
        "id": sample_id,
        "path": path,
        "category": category,
        "candidate_class": candidate_class,
        "exists": bool(path and Path(path).exists()),
        "candidate_backends": profile["candidate_backends"],
        "review_questions": profile["review_questions"],
        "expected_artifacts": profile["expected_artifacts"],
        "candidate_backend_previews": profile.get("candidate_backend_previews", []),
    }


def build_sample_classes(classes: set[str], *, include_missing_template: bool) -> list[dict[str, Any]]:
    ordered = [name for name in DEFAULT_SAMPLE_CLASSES if name in classes or include_missing_template]
    for name in sorted(classes):
        if name not in ordered:
            ordered.append(name)
    result = []
    for name in ordered:
        result.append({"class": name, **profile_for_class(name)})
    return result


def profile_for_class(candidate_class: str) -> dict[str, Any]:
    base = CATEGORY_PROFILES.get(candidate_class, default_profile(candidate_class))
    registry_profiles = candidate_backends_for_sample_class(candidate_class)
    profile = dict(base)
    profile["candidate_backends"] = unique_strings(
        [*(base.get("candidate_backends") or []), *(item.display_name for item in registry_profiles)]
    )
    expected_artifacts = list(base.get("expected_artifacts") or [])
    if registry_profiles:
        expected_artifacts.append("external_wrapper_result_json")
    expected_artifacts.extend(artifact for item in registry_profiles for artifact in item.artifact_contract)
    profile["expected_artifacts"] = unique_strings(expected_artifacts)
    profile["candidate_registry_keys"] = [item.key for item in registry_profiles]
    profile["candidate_backend_previews"] = [candidate_preview_for_class(item, candidate_class) for item in registry_profiles]
    return profile


def candidate_preview_for_class(profile, candidate_class: str) -> dict[str, Any]:
    preview = profile.run_preview(capability=", ".join(profile.capability_names), trigger=f"shared benchmark sample class: {candidate_class}")
    return {
        "backend": profile.display_name,
        "registry_key": profile.key,
        "sample_class": candidate_class,
        "role": profile.role,
        "best_for": profile.best_for,
        "default_policy": profile.default_policy,
        "artifact_contract": list(profile.artifact_contract),
        "run_preview": preview,
    }


def normalize_category(category: str) -> str:
    return CATEGORY_ALIASES.get(category, category if category in CATEGORY_PROFILES else "doc_office")


def default_profile(name: str) -> dict[str, Any]:
    return {
        "candidate_backends": ["Docling", "MarkItDown", "Pandoc"],
        "review_questions": [f"Does {name} output preserve readable Markdown structure?"],
        "expected_artifacts": ["markdown", "conversion_report", "review_report"],
    }


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


if __name__ == "__main__":
    raise SystemExit(main())
