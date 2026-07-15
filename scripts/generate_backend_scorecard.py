from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline import (  # noqa: E402
    default_options,
    dependency_health_report,
    environment_capability_summary,
    normalize_command_options,
)
from ebook_markdown_pipeline.candidate_backend_registry import (  # noqa: E402
    CANDIDATE_BACKENDS as CANDIDATE_BACKEND_REGISTRY,
)


SCHEMA_VERSION = "optional-backend-scorecard-v1"
DEFAULT_OUTPUT = PROJECT_DIR / "benchmarks" / "runs" / "backend-scorecard"
CANDIDATE_ARTIFACT_NAMES = {"layout-candidates.json", "table-candidates.json", "formula-candidates.json", "document-vlm-result.json"}
CANDIDATE_SCHEMA_TO_ARTIFACT_TYPE = {
    "layout-candidates-v1": "layout_candidates_json",
    "table-candidates-v1": "table_candidates_json",
    "formula-candidates-v1": "formula_candidates_json",
    "document-vlm-result-v1": "document_vlm_result_json",
}


@dataclass(frozen=True)
class BackendProfile:
    name: str
    module: str
    role: str
    best_for: str
    install_cost: str
    gpu_or_model: str
    license_note: str
    default_policy: str
    health_names: tuple[str, ...]
    capability_names: tuple[str, ...] = ()


def backend_profile_from_candidate(profile) -> BackendProfile:
    return BackendProfile(
        profile.display_name,
        profile.module,
        profile.role,
        profile.best_for,
        profile.install_cost,
        profile.gpu_or_model,
        profile.license_note,
        profile.default_policy,
        tuple(profile.health_names),
        tuple(profile.capability_names),
    )


BACKENDS: tuple[BackendProfile, ...] = (
    BackendProfile(
        "MarkItDown",
        "markitdown_backend.py",
        "fast multi-format Markdown baseline",
        "Office/HTML/PDF comparison baseline when a cheap second opinion is useful",
        "low/medium",
        "no GPU; optional Python package",
        "MIT upstream; do not vendor dependency",
        "comparison only; not default router",
        ("markitdown",),
        ("markitdown_baseline",),
    ),
    BackendProfile(
        "OCRmyPDF",
        "ocrmypdf_preprocessor.py",
        "searchable-PDF preprocessing",
        "scanned PDF preprocessing before fast text-layer extraction",
        "medium",
        "Tesseract/language data; no project-bundled models",
        "MPL-2.0 upstream plus OCR engine terms",
        "recommended rerun only when preflight says scanned",
        ("OCRmyPDF",),
        ("scanned_pdf_preprocess",),
    ),
    BackendProfile(
        "pdf-craft",
        "pdfcraft_backend.py",
        "scanned-book PDF-to-Markdown experiment",
        "TOC-heavy scanned books where a scanned-book-specific parser is worth trying",
        "heavy",
        "DeepSeek OCR model and Poppler/GPU setup may be required",
        "upstream/package/model terms must be reviewed before redistribution",
        "explicit only until fixture quality beats safer routes",
        ("pdf-craft",),
        ("scanned_book_reconstruction",),
    ),
    BackendProfile(
        "Tabula",
        "pdf_layout_diagnostics.py",
        "text-based PDF table fallback",
        "text-layer PDFs with table pages when Camelot/pdfplumber evidence is weak",
        "medium",
        "Java required; no GPU",
        "MIT/Apache ecosystem; Java runtime terms apply",
        "diagnostic/table-only; not a main converter",
        ("Tabula",),
        ("pdf_table_extraction",),
    ),
    BackendProfile(
        "CnOCR",
        "ocr_providers.py",
        "Chinese/English OCR comparison provider",
        "Chinese screenshots and OCR provider benchmarks",
        "low/medium",
        "Python OCR models may download on first use; no default GPU requirement",
        "Apache-2.0 upstream; model terms still separate",
        "comparison/fallback candidate; not default until benchmarks improve",
        ("CnOCR",),
        ("cnocr_chinese_ocr",),
    ),
    BackendProfile(
        "Pix2Text",
        "scripts/pix2text_image_to_md.py",
        "Chinese screenshot/formula/image Markdown enhancement",
        "layout-heavy Chinese screenshots and formula-heavy images",
        "medium/heavy",
        "optional OCR/formula models; CPU possible but may be slow",
        "upstream code/model terms must be checked before redistribution",
        "first optional image-layout enhancement when installed",
        ("Pix2Text wrapper",),
        ("image_layout_enhancement",),
    ),
    BackendProfile(
        "Surya",
        "scripts/surya_image_to_md.py",
        "OCR/layout/reading-order/table experiment",
        "complex image pages, reading-order checks, and table/layout experiments",
        "heavy",
        "may use local models or a VLM inference server",
        "Apache-2.0 code; model/commercial-use terms separate",
        "explicit experiment until scorecard/fixtures justify recommendations",
        ("Surya wrapper",),
        ("image_layout_enhancement",),
    ),
    BackendProfile(
        "PaddleOCR-VL",
        "scripts/paddleocr_vl_image_to_md.py",
        "document VLM image/page parser experiment",
        "layout-heavy multilingual pages, infographics, tables, formulas, and chart-like images",
        "heavy",
        "PaddleOCR/Paddle runtime and model cache; GPU may be useful",
        "Apache-2.0 code; model/runtime terms separate",
        "explicit experiment until sidecar evidence beats or simplifies another heavy VLM route",
        ("PaddleOCR-VL wrapper",),
        ("image_layout_enhancement",),
    ),
    BackendProfile(
        "Qwen-VL",
        "scripts/qwen_vl_image_to_md.py",
        "general VLM layout/infographic comparison route",
        "difficult visual pages when a remote or local Qwen VLM is explicitly selected",
        "heavy",
        "local model cache or remote provider; no default model install",
        "Qwen code/model/runtime terms checked separately before redistribution",
        "explicit comparison or remote VlmLayoutProvider candidate only",
        ("Qwen-VL wrapper",),
        ("image_layout_enhancement",),
    ),
    BackendProfile(
        "GOT-OCR",
        "scripts/got_ocr_image_to_md.py",
        "CUDA image OCR experiment",
        "single difficult images when a GOT model is already configured",
        "heavy",
        "CUDA/model script required",
        "upstream/model terms must be reviewed before redistribution",
        "explicit only",
        ("GOT-OCR wrapper",),
        ("got_ocr_experiment",),
    ),
    BackendProfile(
        "DeepSeek-OCR",
        "scripts/deepseek_ocr_image_to_md.py",
        "Transformers VLM OCR experiment",
        "difficult image OCR experiments with configured model/runtime",
        "heavy",
        "CUDA/Transformers/model recommended",
        "upstream/model terms must be reviewed before redistribution",
        "explicit only",
        ("DeepSeek-OCR wrapper",),
        ("deepseek_ocr_experiment",),
    ),
    BackendProfile(
        "olmOCR",
        "olmocr_backend.py",
        "VLM PDF/image OCR benchmark backend",
        "GPU/remote VLM comparison for complex scanned PDFs",
        "heavy",
        "GPU or remote inference strongly recommended",
        "upstream/model terms must be reviewed before redistribution",
        "explicit benchmark only",
        ("olmOCR",),
        ("pdf_vlm_ocr_benchmark",),
    ),
    BackendProfile(
        "Apache Tika",
        "tika_backend.py",
        "MIME/metadata/text-sample inspection",
        "unknown file formats and broad metadata inspection",
        "medium",
        "server/Java command; no GPU",
        "Apache-2.0 upstream",
        "explicit inspect only",
        ("Apache Tika",),
        ("format_metadata_inspection",),
    ),
    BackendProfile(
        "GROBID",
        "grobid_backend.py",
        "academic PDF/TEI inspection",
        "papers, DOI/authors/abstract/reference evidence",
        "heavy",
        "server/Docker recommended; no project-bundled models",
        "Apache-2.0 upstream",
        "explicit academic inspect only",
        ("GROBID",),
        ("academic_pdf_analysis",),
    ),
    *(backend_profile_from_candidate(profile) for profile in CANDIDATE_BACKEND_REGISTRY),
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an optional backend availability and recommendation scorecard.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT / time.strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--fast", action="store_true", default=True, help="Skip expensive version/model probes. Enabled by default.")
    parser.add_argument(
        "--external-wrapper-result",
        type=Path,
        action="append",
        default=[],
        help="Read one external-wrapper-result.json artifact and attach it to the matching candidate backend.",
    )
    parser.add_argument(
        "--external-wrapper-root",
        type=Path,
        action="append",
        default=[],
        help="Recursively scan a directory for external-wrapper-result.json artifacts.",
    )
    parser.add_argument(
        "--candidate-artifact",
        type=Path,
        action="append",
        default=[],
        help="Read one layout/table/formula/document-VLM candidate JSON sidecar.",
    )
    parser.add_argument(
        "--candidate-artifact-root",
        type=Path,
        action="append",
        default=[],
        help="Recursively scan a directory for candidate sidecar JSON artifacts.",
    )
    parser.add_argument(
        "--review-bundle",
        type=Path,
        action="append",
        default=[],
        help="Read one layout-table-review-bundle.json and attach table_review_matrix evidence to matching backends.",
    )
    parser.add_argument(
        "--review-bundle-root",
        type=Path,
        action="append",
        default=[],
        help="Recursively scan a directory for layout-table-review-bundle.json files.",
    )
    parser.add_argument("--quality-evaluation", type=Path, action="append", default=[], help="Read one document-quality-evaluation.json and attach offline evidence to matching backends.")
    parser.add_argument("--quality-evaluation-root", type=Path, action="append", default=[], help="Recursively scan a directory for document-quality-evaluation.json files.")
    args = parser.parse_args()

    options = normalize_command_options(default_options())
    checks = dependency_health_report([], options, fast=bool(args.fast))
    capabilities = environment_capability_summary(checks)
    wrapper_results = collect_external_wrapper_results(args.external_wrapper_result, args.external_wrapper_root)
    candidate_artifacts = collect_candidate_artifacts(args.candidate_artifact, [*args.candidate_artifact_root, *args.external_wrapper_root])
    review_bundle_evidence = collect_review_bundle_evidence(args.review_bundle, args.review_bundle_root)
    quality_evaluation_evidence = collect_document_quality_evaluations(args.quality_evaluation, args.quality_evaluation_root)
    payload = build_scorecard(checks, capabilities, output=args.output, wrapper_results=wrapper_results, candidate_artifacts=[*candidate_artifacts, *review_bundle_evidence, *quality_evaluation_evidence])
    write_scorecard(args.output, payload)
    print(json.dumps({"status": payload["summary"]["status"], "output": str(args.output), "backend_count": len(payload["backends"])}, ensure_ascii=False))
    return 0


def build_scorecard(
    checks: list[dict[str, str]],
    capabilities: list[dict[str, str]],
    *,
    output: Path | None = None,
    wrapper_results: list[dict[str, Any]] | None = None,
    candidate_artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    check_by_name = {str(item.get("name") or "").lower(): item for item in checks}
    capability_by_name = {str(item.get("name") or "").lower(): item for item in capabilities}
    results_by_backend = group_external_wrapper_results(wrapper_results or [])
    candidate_artifacts_by_backend = group_candidate_artifacts(candidate_artifacts or [])
    backends = [score_backend(profile, check_by_name, capability_by_name, results_by_backend, candidate_artifacts_by_backend) for profile in BACKENDS]
    summary = summarize_backends(backends)
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "output": str(output) if output else "",
        "summary": summary,
        "external_wrapper_result_count": len(wrapper_results or []),
        "candidate_artifact_count": len(candidate_artifacts or []),
        "backends": backends,
    }


def score_backend(
    profile: BackendProfile,
    check_by_name: dict[str, dict[str, str]],
    capability_by_name: dict[str, dict[str, str]],
    results_by_backend: dict[str, list[dict[str, Any]]] | None = None,
    candidate_artifacts_by_backend: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    health_records = [check_by_name.get(name.lower()) for name in profile.health_names]
    health_records = [item for item in health_records if item]
    capability_records = [capability_by_name.get(name.lower()) for name in profile.capability_names]
    capability_records = [item for item in capability_records if item]
    external_results = external_results_for_profile(profile, results_by_backend or {})
    candidate_artifacts = candidate_artifacts_for_profile(profile, candidate_artifacts_by_backend or {})
    status = combined_status(health_records + capability_records)
    score = recommendation_score(status, profile.install_cost, profile.default_policy)
    if external_results:
        score = min(100, score + 5)
    if candidate_artifacts:
        score = min(100, score + 5)
    quality_signals = summarize_quality_signals(external_results, candidate_artifacts)
    return {
        **asdict(profile),
        "status": status,
        "recommendation_score": score,
        "recommendation": recommendation_text(status, score, profile.default_policy),
        "health": health_records,
        "capabilities": capability_records,
        "external_results": external_results,
        "candidate_artifacts": candidate_artifacts,
        "quality_signals": quality_signals,
        "promotion_gate": promotion_gate_for_backend(profile, status, quality_signals),
    }


def collect_external_wrapper_results(result_paths: list[Path], roots: list[Path]) -> list[dict[str, Any]]:
    candidates: list[Path] = []
    for path in result_paths:
        candidates.append(path)
    for root in roots:
        if root.exists() and root.is_file() and root.name == "external-wrapper-result.json":
            candidates.append(root)
        elif root.exists() and root.is_dir():
            candidates.extend(root.rglob("external-wrapper-result.json"))
    results = []
    seen: set[str] = set()
    for path in candidates:
        resolved = str(path.resolve()) if path.exists() else str(path)
        if resolved in seen:
            continue
        seen.add(resolved)
        loaded = load_external_wrapper_result(path)
        if loaded:
            results.append(loaded)
    return results


def load_external_wrapper_result(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != "external-wrapper-result-v1":
        return None
    artifacts = [item for item in payload.get("artifacts") or [] if isinstance(item, dict)]
    warnings = [str(item) for item in payload.get("warnings") or []]
    return {
        "path": str(path),
        "backend": payload.get("backend"),
        "mode": payload.get("mode"),
        "status": payload.get("status"),
        "artifact_count": len(artifacts),
        "artifact_types": sorted({str(item.get("type") or "") for item in artifacts if item.get("type")}),
        "metrics": payload.get("metrics") or {},
        "warning_count": len(warnings),
        "warnings_preview": warnings[:5],
        "quality_signals": quality_signals_from_external_wrapper(payload, artifacts, warnings),
    }


def collect_candidate_artifacts(artifact_paths: list[Path], roots: list[Path]) -> list[dict[str, Any]]:
    candidates: list[Path] = []
    candidates.extend(artifact_paths)
    for root in roots:
        if root.exists() and root.is_file() and root.name in CANDIDATE_ARTIFACT_NAMES:
            candidates.append(root)
        elif root.exists() and root.is_dir():
            for name in sorted(CANDIDATE_ARTIFACT_NAMES):
                candidates.extend(root.rglob(name))
    results = []
    seen: set[str] = set()
    for path in candidates:
        resolved = str(path.resolve()) if path.exists() else str(path)
        if resolved in seen:
            continue
        seen.add(resolved)
        loaded = load_candidate_artifact(path)
        if loaded:
            results.append(loaded)
    return results


def collect_document_quality_evaluations(paths: list[Path], roots: list[Path]) -> list[dict[str, Any]]:
    candidates = [*paths]
    for root in roots:
        if root.exists() and root.is_file() and root.name == "document-quality-evaluation.json":
            candidates.append(root)
        elif root.exists() and root.is_dir():
            candidates.extend(root.rglob("document-quality-evaluation.json"))
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        if not path.exists() or not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or payload.get("schema_version") != "document-quality-evaluation-v1":
            continue
        for evaluation in payload.get("backend_evaluations") or []:
            if not isinstance(evaluation, dict) or not evaluation.get("backend"):
                continue
            dimensions = evaluation.get("dimensions") if isinstance(evaluation.get("dimensions"), dict) else {}
            evaluated = [name for name, item in dimensions.items() if isinstance(item, dict) and item.get("status") == "evaluated"]
            not_evaluated = [name for name, item in dimensions.items() if isinstance(item, dict) and item.get("status") == "not_evaluated"]
            signals = {
                "evidence_count": 1,
                "quality_evaluation_count": 1,
                "quality_dimension_evaluated_count": len(evaluated),
                "quality_dimension_not_evaluated_count": len(not_evaluated),
                **{f"has_{name}_quality_evaluation": name in evaluated for name in ("text", "table", "formula", "layout", "reading_order")},
            }
            rows.append({"path": str(path), "backend": evaluation["backend"], "mode": "offline_quality_evaluation", "status": evaluation.get("status") or "review", "artifact_type": "document_quality_evaluation_json", "schema_version": payload.get("schema_version"), "quality_signals": compact_quality_signals(signals)})
    return rows


def collect_review_bundle_evidence(bundle_paths: list[Path], roots: list[Path]) -> list[dict[str, Any]]:
    candidates: list[Path] = []
    candidates.extend(bundle_paths)
    for root in roots:
        if root.exists() and root.is_file() and root.name == "layout-table-review-bundle.json":
            candidates.append(root)
        elif root.exists() and root.is_dir():
            candidates.extend(root.rglob("layout-table-review-bundle.json"))
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in candidates:
        resolved = str(path.resolve()) if path.exists() else str(path)
        if resolved in seen:
            continue
        seen.add(resolved)
        results.extend(load_review_bundle_table_evidence(path))
    return results


def load_review_bundle_table_evidence(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict) or payload.get("schema_version") != "layout-table-review-bundle-v1":
        return []
    rows: list[dict[str, Any]] = []
    for page_matrix in payload.get("table_review_matrix") or []:
        if not isinstance(page_matrix, dict) or page_matrix.get("schema_version") != "table-review-matrix-v1":
            continue
        for row in page_matrix.get("rows") or []:
            if not isinstance(row, dict):
                continue
            backend = row.get("backend")
            if not backend:
                continue
            warnings = [str(item) for item in row.get("warnings") or []]
            rows.append(
                {
                    "path": str(path),
                    "backend": backend,
                    "mode": "table_review_matrix",
                    "status": "review",
                    "artifact_type": "table_review_matrix",
                    "schema_version": "table-review-matrix-v1",
                    "page_count": 1,
                    "page_locator": page_matrix.get("locator"),
                    "table_count": int_or_zero(row.get("table_count")),
                    "artifact_count": int_or_zero(row.get("artifact_ref_count")) or len(row.get("artifact_refs") or []),
                    "warning_count": len(warnings),
                    "warnings_preview": warnings[:5],
                    "quality_signals": quality_signals_from_table_review_row(row, page_matrix, warnings),
                }
            )
    return rows


def quality_signals_from_table_review_row(row: dict[str, Any], page_matrix: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    has_html = bool(row.get("has_html"))
    has_markdown = bool(row.get("has_markdown"))
    has_cells_json = bool(row.get("has_cells_json"))
    has_overlay = bool(row.get("has_overlay"))
    completeness = sum(1 for value in (has_html, has_markdown, has_cells_json, has_overlay) if value)
    comparison_summary = page_matrix.get("comparison_summary") if isinstance(page_matrix.get("comparison_summary"), dict) else {}
    missing_evidence = [str(item) for item in row.get("missing_evidence") or [] if item]
    conflict_tags = [str(item) for item in comparison_summary.get("conflict_tags") or [] if item]
    return compact_quality_signals(
        {
            "evidence_count": 1,
            "candidate_artifact_count": 1,
            "table_review_matrix_count": 1,
            "page_count": 1,
            "table_count": int_or_zero(row.get("table_count")),
            "table_backend_count": int_or_zero(page_matrix.get("backend_count")),
            "table_artifact_ref_count": int_or_zero(row.get("artifact_ref_count")) or len(row.get("artifact_refs") or []),
            "table_markdown_excerpt_count": int_or_zero(row.get("markdown_excerpt_count")),
            "table_evidence_completeness": completeness,
            "table_evidence_completeness_score": row.get("evidence_completeness_score"),
            "table_missing_evidence_count": len(missing_evidence),
            "table_conflict_count": len(conflict_tags),
            "warning_count": len(warnings),
            "has_table_evidence": True,
            "has_table_html": has_html,
            "has_table_markdown": has_markdown,
            "has_table_cells_json": has_cells_json,
            "has_table_overlay": has_overlay,
            "needs_card_layout_false_positive_review": "check_card_layout_false_positive" in warnings,
            "table_count_agrees_across_backends": comparison_summary.get("agrees_on_table_count"),
            "table_conflict_tags": conflict_tags,
            "table_missing_evidence": missing_evidence,
        }
    )

def load_candidate_artifact(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    schema_version = str(payload.get("schema_version") or "")
    artifact_type = CANDIDATE_SCHEMA_TO_ARTIFACT_TYPE.get(schema_version)
    if not artifact_type:
        return None
    pages = [item for item in payload.get("pages") or [] if isinstance(item, dict)]
    warnings = [str(item) for item in payload.get("warnings") or []]
    artifacts = [item for item in payload.get("artifacts") or [] if isinstance(item, dict)]
    return {
        "path": str(path),
        "backend": payload.get("backend"),
        "mode": payload.get("mode"),
        "status": payload.get("status"),
        "artifact_type": artifact_type,
        "schema_version": schema_version,
        "page_count": len(pages) or payload.get("page_count"),
        "block_count": count_candidate_items(pages, "blocks") or payload.get("block_count"),
        "table_count": count_candidate_items(pages, "tables") or payload.get("table_count"),
        "formula_count": count_candidate_items(pages, "formulas") or payload.get("formula_count"),
        "artifact_count": len(artifacts),
        "warning_count": len(warnings),
        "warnings_preview": warnings[:5],
        "quality_signals": quality_signals_from_candidate_payload(payload, pages, artifacts, warnings),
    }


def count_candidate_items(pages: list[dict[str, Any]], key: str) -> int:
    total = 0
    count_field = key[:-1] + "_count" if key.endswith("s") else f"{key}_count"
    for page in pages:
        items = page.get(key)
        if isinstance(items, list):
            total += len(items)
        total += int(page.get(count_field) or 0)
    return total


def quality_signals_from_external_wrapper(payload: dict[str, Any], artifacts: list[dict[str, Any]], warnings: list[str]) -> dict[str, Any]:
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    next_actions = [item for item in payload.get("next_actions") or [] if isinstance(item, dict)]
    command = payload.get("command") if isinstance(payload.get("command"), list) else []
    return compact_quality_signals(
        {
            "evidence_count": 1,
            "external_result_count": 1,
            "candidate_artifact_count": 0,
            "artifact_types": sorted({str(item.get("type") or "") for item in artifacts if item.get("type")} ),
            "page_count": int_or_zero(metrics.get("page_count") or metrics.get("pages")),
            "markdown_char_count": int_or_zero(metrics.get("markdown_chars") or metrics.get("markdown_char_count")),
            "duration_seconds": float_or_none(metrics.get("duration_seconds") or metrics.get("elapsed_seconds") or metrics.get("runtime_seconds")),
            "model_cache_bytes": int_or_zero(metrics.get("model_cache_bytes") or metrics.get("cache_bytes")),
            "warning_count": len(warnings),
            "next_action_count": len(next_actions),
            "has_fallback_path": bool(metrics.get("fallback_path") or any("fallback" in json.dumps(item, ensure_ascii=False).lower() for item in next_actions)),
            "command_present": bool(command),
        }
    )


def quality_signals_from_candidate_payload(payload: dict[str, Any], pages: list[dict[str, Any]], artifacts: list[dict[str, Any]], warnings: list[str]) -> dict[str, Any]:
    block_count = count_candidate_items(pages, "blocks") or int_or_zero(payload.get("block_count"))
    table_count = count_candidate_items(pages, "tables") or int_or_zero(payload.get("table_count"))
    formula_count = count_candidate_items(pages, "formulas") or int_or_zero(payload.get("formula_count"))
    layout_counts = layout_candidate_signal_counts(pages)
    table_counts = table_candidate_signal_counts(pages)
    formula_counts = formula_candidate_signal_counts(pages)
    return compact_quality_signals(
        {
            "evidence_count": 1,
            "external_result_count": 0,
            "candidate_artifact_count": 1,
            "artifact_types": sorted({str(item.get("type") or "") for item in artifacts if item.get("type")} ),
            "page_count": len(pages) or int_or_zero(payload.get("page_count")),
            "block_count": block_count,
            "table_count": table_count,
            "formula_count": formula_count,
            "bbox_count": count_candidate_field(pages, "bbox"),
            "reading_order_count": count_candidate_field(pages, "reading_order"),
            "markdown_char_count": markdown_char_count_from_candidate(payload, pages),
            "warning_count": len(warnings),
            **layout_counts,
            **table_counts,
            **formula_counts,
            "has_layout_evidence": bool(block_count or layout_counts.get("layout_bbox_count") or layout_counts.get("layout_overlay_count")),
            "has_table_evidence": bool(table_count),
            "has_formula_evidence": bool(formula_count),
            "has_document_vlm_evidence": payload.get("schema_version") == "document-vlm-result-v1",
            "needs_formula_retention_review": bool(formula_count),
        }
    )



def layout_candidate_signal_counts(pages: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "layout_label_count": 0,
        "layout_bbox_count": 0,
        "layout_overlay_count": 0,
    }
    for page in pages:
        if not isinstance(page, dict):
            continue
        if any(page.get(key) for key in ("overlay", "overlay_path", "overlay_image", "layout_overlay", "layout_overlay_path")):
            counts["layout_overlay_count"] += 1
        for block in page.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            if block.get("label") or block.get("type") or block.get("category"):
                counts["layout_label_count"] += 1
            if block.get("bbox") is not None:
                counts["layout_bbox_count"] += 1
            if any(block.get(key) for key in ("overlay", "overlay_path", "overlay_image")):
                counts["layout_overlay_count"] += 1
    return counts


def table_candidate_signal_counts(pages: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "table_html_count": 0,
        "table_markdown_count": 0,
        "table_cells_json_count": 0,
        "table_overlay_count": 0,
        "table_bbox_count": 0,
    }
    for page in pages:
        if not isinstance(page, dict):
            continue
        for table in page.get("tables") or []:
            if not isinstance(table, dict):
                continue
            if table.get("html") or table.get("html_path"):
                counts["table_html_count"] += 1
            if table.get("markdown") or table.get("markdown_path"):
                counts["table_markdown_count"] += 1
            if table.get("cells") or table.get("cells_path") or table.get("cells_json_path"):
                counts["table_cells_json_count"] += 1
            if table.get("overlay") or table.get("overlay_path") or table.get("overlay_image"):
                counts["table_overlay_count"] += 1
            if table.get("bbox") is not None:
                counts["table_bbox_count"] += 1
    return counts


def formula_candidate_signal_counts(pages: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "formula_latex_count": 0,
        "formula_markdown_count": 0,
        "formula_bbox_count": 0,
        "formula_source_ref_count": 0,
        "formula_confidence_count": 0,
    }
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_source = any(page.get(key) for key in ("source", "image", "image_path", "page_image", "source_image"))
        for formula in page.get("formulas") or []:
            if not isinstance(formula, dict):
                continue
            if formula.get("latex") or formula.get("formula"):
                counts["formula_latex_count"] += 1
            if formula.get("markdown") or formula.get("markdown_path"):
                counts["formula_markdown_count"] += 1
            if formula.get("bbox") is not None or formula.get("position") is not None:
                counts["formula_bbox_count"] += 1
            if page_source or any(formula.get(key) for key in ("source", "image", "image_path", "crop_path", "source_image")):
                counts["formula_source_ref_count"] += 1
            if formula.get("confidence") is not None or formula.get("score") is not None:
                counts["formula_confidence_count"] += 1
    counts["formula_evidence_completeness"] = sum(
        1
        for key in ("formula_latex_count", "formula_markdown_count", "formula_bbox_count", "formula_source_ref_count", "formula_confidence_count")
        if counts.get(key)
    )
    return counts

def summarize_quality_signals(external_results: list[dict[str, Any]], candidate_artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    aggregate: dict[str, Any] = {
        "evidence_count": len(external_results) + len(candidate_artifacts),
        "external_result_count": len(external_results),
        "candidate_artifact_count": len(candidate_artifacts),
        "artifact_types": sorted(
            {
                *(artifact_type for item in external_results for artifact_type in item.get("artifact_types") or []),
                *(str(item.get("artifact_type") or "") for item in candidate_artifacts if item.get("artifact_type")),
            }
        ),
        "statuses": sorted({str(item.get("status") or "") for item in [*external_results, *candidate_artifacts] if item.get("status")}),
        "modes": sorted({str(item.get("mode") or "") for item in [*external_results, *candidate_artifacts] if item.get("mode")}),
    }
    for key in (
        "page_count",
        "block_count",
        "table_count",
        "formula_count",
        "bbox_count",
        "reading_order_count",
        "markdown_char_count",
        "warning_count",
        "next_action_count",
        "model_cache_bytes",
        "layout_label_count",
        "layout_bbox_count",
        "layout_overlay_count",
        "table_html_count",
        "table_markdown_count",
        "table_cells_json_count",
        "table_overlay_count",
        "table_bbox_count",
        "formula_latex_count",
        "formula_markdown_count",
        "formula_bbox_count",
        "formula_source_ref_count",
        "formula_confidence_count",
        "table_review_matrix_count",
        "table_backend_count",
        "table_artifact_ref_count",
        "table_markdown_excerpt_count",
        "table_missing_evidence_count",
        "table_conflict_count",
        "quality_evaluation_count",
        "quality_dimension_evaluated_count",
        "quality_dimension_not_evaluated_count",
    ):
        aggregate[key] = sum(int_or_zero((item.get("quality_signals") or {}).get(key) if isinstance(item.get("quality_signals"), dict) else item.get(key)) for item in [*external_results, *candidate_artifacts])
    aggregate["table_evidence_completeness"] = max((int_or_zero((item.get("quality_signals") or {}).get("table_evidence_completeness")) for item in [*external_results, *candidate_artifacts] if isinstance(item.get("quality_signals"), dict)), default=0)
    aggregate["table_evidence_completeness_score"] = max((float((item.get("quality_signals") or {}).get("table_evidence_completeness_score") or 0) for item in [*external_results, *candidate_artifacts] if isinstance(item.get("quality_signals"), dict)), default=0)
    aggregate["formula_evidence_completeness"] = max((int_or_zero((item.get("quality_signals") or {}).get("formula_evidence_completeness")) for item in [*external_results, *candidate_artifacts] if isinstance(item.get("quality_signals"), dict)), default=0)
    durations = [
        float(item.get("quality_signals", {}).get("duration_seconds"))
        for item in external_results
        if isinstance(item.get("quality_signals"), dict) and item.get("quality_signals", {}).get("duration_seconds") is not None
    ]
    if durations:
        aggregate["duration_seconds"] = round(sum(durations), 3)
    for key in (
        "has_layout_evidence",
        "has_table_evidence",
        "has_formula_evidence",
        "has_document_vlm_evidence",
        "has_table_html",
        "has_table_markdown",
        "has_table_cells_json",
        "has_table_overlay",
        "needs_card_layout_false_positive_review",
        "table_count_agrees_across_backends",
        "needs_formula_retention_review",
        "has_fallback_path",
        "command_present",
        "has_text_quality_evaluation",
        "has_table_quality_evaluation",
        "has_formula_quality_evaluation",
        "has_layout_quality_evaluation",
        "has_reading_order_quality_evaluation",
    ):
        aggregate[key] = any(bool((item.get("quality_signals") or {}).get(key)) for item in [*external_results, *candidate_artifacts] if isinstance(item.get("quality_signals"), dict))
    return compact_quality_signals(aggregate)


def count_candidate_field(pages: list[dict[str, Any]], field: str) -> int:
    total = 0
    for page in pages:
        for key in ("blocks", "tables", "formulas"):
            items = page.get(key)
            if not isinstance(items, list):
                continue
            total += sum(1 for item in items if isinstance(item, dict) and item.get(field) is not None)
    return total


def markdown_char_count_from_candidate(payload: dict[str, Any], pages: list[dict[str, Any]]) -> int:
    total = int_or_zero(payload.get("markdown_char_count"))
    preview = payload.get("markdown_text_preview")
    if isinstance(preview, str):
        total += len(preview)
    for page in pages:
        for key in ("blocks", "tables", "formulas"):
            items = page.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                total += int_or_zero(item.get("text_char_count"))
                for text_key in ("text", "markdown", "latex"):
                    value = item.get(text_key)
                    if isinstance(value, str):
                        total += len(value)
    return total


def compact_quality_signals(signals: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in signals.items():
        if value in (None, "", [], {}, 0, 0.0, False):
            continue
        compact[key] = value
    return compact


def int_or_zero(value: Any) -> int:
    try:
        if value is None or value == "":
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None

def group_candidate_artifacts(artifacts: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in artifacts:
        backend = normalize_external_backend_name(str(item.get("backend") or ""))
        if backend:
            grouped.setdefault(backend, []).append(item)
    return grouped


def candidate_artifacts_for_profile(profile: BackendProfile, artifacts_by_backend: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    keys = {normalize_external_backend_name(profile.name), *(normalize_external_backend_name(name) for name in profile.health_names)}
    matches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in keys:
        for item in artifacts_by_backend.get(key, []):
            path = str(item.get("path") or "")
            if path in seen:
                continue
            seen.add(path)
            matches.append(item)
    return matches


def group_external_wrapper_results(results: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in results:
        backend = normalize_external_backend_name(str(item.get("backend") or ""))
        if backend:
            grouped.setdefault(backend, []).append(item)
    return grouped


def external_results_for_profile(profile: BackendProfile, results_by_backend: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    keys = {normalize_external_backend_name(profile.name), *(normalize_external_backend_name(name) for name in profile.health_names)}
    matches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in keys:
        for item in results_by_backend.get(key, []):
            path = str(item.get("path") or "")
            if path in seen:
                continue
            seen.add(path)
            matches.append(item)
    return matches


def normalize_external_backend_name(name: str) -> str:
    lowered = name.lower().replace("-", "_").replace(".", "_").replace(" ", "_").strip()
    aliases = {
        "monkeyocr_worker": "monkeyocr",
        "monkeyocr": "monkeyocr",
        "dots_mocr_provider": "dots_mocr",
        "dots_mocr": "dots_mocr",
        "doclayout_yolo_baseline": "doclayout_yolo",
        "doclayout_yolo": "doclayout_yolo",
        "pdf_table_worker": "pdf_table",
        "pdf_table": "pdf_table",
        "paddleocr_vl": "paddleocr_vl",
        "paddle_ocr_vl": "paddleocr_vl",
        "qwen_vl": "qwen_vl",
        "fake_vlm_layout": "qwen_vl",
        "fake_ocr_layout": "qwen_vl",
    }
    return aliases.get(lowered, lowered)


def combined_status(records: list[dict[str, str]]) -> str:
    statuses = {str(item.get("status") or "missing") for item in records}
    if "ok" in statuses:
        return "ok"
    if statuses.intersection({"degraded", "warning", "caution"}):
        return "degraded"
    for candidate_status in ("needs_server", "needs_model", "needs_env", "planned_only"):
        if candidate_status in statuses:
            return candidate_status
    return "missing"


def recommendation_score(status: str, install_cost: str, policy: str) -> int:
    score = {"ok": 55, "degraded": 35, "needs_server": 28, "needs_model": 25, "needs_env": 22, "planned_only": 18, "missing": 10}.get(status, 10)
    if "low" in install_cost:
        score += 20
    elif "medium" in install_cost:
        score += 12
    elif "heavy" in install_cost:
        score += 4
    if "default" in policy or "recommended" in policy:
        score += 10
    if "explicit only" in policy:
        score -= 8
    if "not default" in policy:
        score -= 5
    return max(0, min(score, 100))


def recommendation_text(status: str, score: int, policy: str) -> str:
    if status == "missing":
        return "skip until explicitly needed; optional missing is OK"
    if status in {"planned_only", "needs_env", "needs_model", "needs_server"}:
        return f"candidate-only; prepare environment before execution: {policy}"
    if score >= 75:
        return "safe to expose as recommended/manual follow-up when matching risks are detected"
    if score >= 55:
        return "keep as optional comparison or diagnostic backend"
    return f"keep explicit only: {policy}"


PROMOTION_REQUIRED_EVIDENCE = [
    "same_sample_class",
    "same_review_questions",
    "readable_artifacts",
    "quality_signals",
    "compare_against_existing_route",
    "no_model_install_by_surprise",
]


PROMOTION_ENV_BLOCKED_STATUSES = {"planned_only", "needs_env", "needs_model", "needs_server"}


def promotion_gate_for_backend(profile: BackendProfile, backend_status: str, quality_signals: dict[str, Any]) -> dict[str, Any]:
    evidence_count = int_or_zero(quality_signals.get("evidence_count"))
    heavy_backend = "heavy" in profile.install_cost.lower()
    explicit_policy = any(token in profile.default_policy.lower() for token in ("explicit", "candidate-only", "experiment"))
    comparable_evidence = any(
        [
            bool(quality_signals.get("has_layout_evidence")),
            bool(quality_signals.get("has_table_evidence")),
            bool(quality_signals.get("has_formula_evidence")),
            bool(quality_signals.get("has_document_vlm_evidence")),
            int_or_zero(quality_signals.get("block_count")) > 0,
            int_or_zero(quality_signals.get("table_count")) > 0,
            int_or_zero(quality_signals.get("formula_count")) > 0,
            int_or_zero(quality_signals.get("bbox_count")) > 0,
            int_or_zero(quality_signals.get("reading_order_count")) > 0,
            int_or_zero(quality_signals.get("quality_dimension_evaluated_count")) > 0,
        ]
    )
    reasons: list[str] = []
    if explicit_policy:
        reasons.append("default policy requires explicit review")
    if evidence_count == 0:
        reasons.append("no scorecard evidence yet")
        return {
            "status": "no_evidence",
            "decision": "do_not_promote",
            "evidence_count": evidence_count,
            "reasons": reasons,
            "required_evidence": PROMOTION_REQUIRED_EVIDENCE,
        }
    if backend_status in PROMOTION_ENV_BLOCKED_STATUSES:
        reasons.append(f"backend status is {backend_status}")
        return {
            "status": "environment_not_ready",
            "decision": "plan_or_fix_environment_first",
            "evidence_count": evidence_count,
            "reasons": reasons,
            "required_evidence": PROMOTION_REQUIRED_EVIDENCE,
        }
    if heavy_backend and evidence_count < 2:
        reasons.append("heavy backend needs shared-sample evidence against an existing route")
        return {
            "status": "insufficient_evidence",
            "decision": "review_only",
            "evidence_count": evidence_count,
            "reasons": reasons,
            "required_evidence": PROMOTION_REQUIRED_EVIDENCE,
        }
    if not comparable_evidence:
        reasons.append("evidence lacks layout/table/formula/document-VLM comparison signals")
        return {
            "status": "insufficient_quality_signals",
            "decision": "review_only",
            "evidence_count": evidence_count,
            "reasons": reasons,
            "required_evidence": PROMOTION_REQUIRED_EVIDENCE,
        }
    reasons.append("compare on shared manifest before promotion")
    return {
        "status": "review_candidate",
        "decision": "compare_on_shared_manifest",
        "evidence_count": evidence_count,
        "reasons": reasons,
        "required_evidence": PROMOTION_REQUIRED_EVIDENCE,
    }


def summarize_backends(backends: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    promotion_gate_counts: dict[str, int] = {}
    for item in backends:
        status = str(item.get("status") or "missing")
        counts[status] = counts.get(status, 0) + 1
        gate_decision = str((item.get("promotion_gate") or {}).get("decision") or "unknown")
        promotion_gate_counts[gate_decision] = promotion_gate_counts.get(gate_decision, 0) + 1
    return {
        "status": "ok",
        "backend_count": len(backends),
        "status_counts": counts,
        "promotion_gate_counts": promotion_gate_counts,
        "ready": [item["name"] for item in backends if item.get("status") == "ok"],
        "missing_optional": [item["name"] for item in backends if item.get("status") == "missing"],
        "recommended_candidates": [
            item["name"]
            for item in backends
            if item.get("status") == "ok" and int(item.get("recommendation_score") or 0) >= 75
        ],
    }


def write_scorecard(output: Path, payload: dict[str, Any]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "backend-scorecard.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    (output / "backend-scorecard.md").write_text(render_markdown(payload), encoding="utf-8", newline="\n")


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "# Optional Backend Scorecard",
        "",
        f"- Status: {summary.get('status', 'unknown')}",
        f"- Backend count: {summary.get('backend_count', 0)}",
        f"- Ready: {', '.join(summary.get('ready') or []) or 'none'}",
        f"- Missing optional: {', '.join(summary.get('missing_optional') or []) or 'none'}",
        f"- Recommended candidates: {', '.join(summary.get('recommended_candidates') or []) or 'none'}",
        f"- External wrapper results: {payload.get('external_wrapper_result_count', 0)}",
        f"- Candidate artifacts: {payload.get('candidate_artifact_count', 0)}",
        f"- Promotion gate counts: {summary.get('promotion_gate_counts', {})}",
        "",
        "| Backend | Status | Score | Evidence | Tables | Formulas | Warnings | Role | Best For | Cost | GPU/Model | Default Policy | Recommendation |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- | --- |",
    ]
    for item in payload.get("backends") or []:
        lines.append(
            "| "
            + " | ".join(
                escape_table(str(value))
                for value in [
                    item.get("name", ""),
                    item.get("status", ""),
                    item.get("recommendation_score", ""),
                    (item.get("quality_signals") or {}).get("evidence_count", ""),
                    (item.get("quality_signals") or {}).get("table_count", ""),
                    (item.get("quality_signals") or {}).get("formula_count", ""),
                    (item.get("quality_signals") or {}).get("warning_count", ""),
                    item.get("role", ""),
                    item.get("best_for", ""),
                    item.get("install_cost", ""),
                    item.get("gpu_or_model", ""),
                    item.get("default_policy", ""),
                    item.get("recommendation", ""),
                ]
            )
            + " |"
        )
    wrapper_lines = render_external_result_lines(payload)
    if wrapper_lines:
        lines.extend(["", "## External Wrapper Evidence", "", *wrapper_lines])
    candidate_lines = render_candidate_artifact_lines(payload)
    if candidate_lines:
        lines.extend(["", "## Candidate Artifact Evidence", "", *candidate_lines])
    promotion_lines = render_promotion_gate_lines(payload)
    if promotion_lines:
        lines.extend(["", "## Promotion Gate", "", *promotion_lines])
    lines.extend(["", "Missing optional backends do not fail the minimal install or release gate. Promote a backend only after fixture evidence shows quality improvement."])
    return "\n".join(lines).rstrip() + "\n"


def render_external_result_lines(payload: dict[str, Any]) -> list[str]:
    lines = []
    for item in payload.get("backends") or []:
        results = item.get("external_results") or []
        if not results:
            continue
        lines.append(f"### {item.get('name')}")
        for result in results:
            artifact_types = ", ".join(result.get("artifact_types") or []) or "none"
            lines.append(
                f"- {result.get('status', 'unknown')} / {result.get('mode', 'unknown')}: "
                f"{result.get('artifact_count', 0)} artifacts ({artifact_types}) at `{result.get('path')}`"
            )
    return lines


def render_candidate_artifact_lines(payload: dict[str, Any]) -> list[str]:
    lines = []
    for item in payload.get("backends") or []:
        artifacts = item.get("candidate_artifacts") or []
        if not artifacts:
            continue
        signals = item.get("quality_signals") or {}
        summary_bits = []
        for key in ("evidence_count", "block_count", "table_count", "formula_count", "bbox_count", "reading_order_count", "markdown_char_count", "warning_count", "layout_overlay_count", "table_html_count", "table_markdown_count", "table_cells_json_count", "table_overlay_count", "formula_latex_count", "formula_bbox_count", "formula_source_ref_count", "formula_evidence_completeness", "table_review_matrix_count", "table_artifact_ref_count", "table_markdown_excerpt_count", "table_evidence_completeness", "table_evidence_completeness_score", "table_missing_evidence_count", "table_conflict_count"):
            if signals.get(key):
                summary_bits.append(f"{key}={signals.get(key)}")
        lines.append(f"### {item.get('name')}" + (f" ({', '.join(summary_bits)})" if summary_bits else ""))
        for candidate in artifacts:
            counts = []
            for key in ("page_count", "block_count", "table_count", "formula_count"):
                value = candidate.get(key)
                if value:
                    counts.append(f"{key}={value}")
            count_text = ", ".join(counts) or "no counted items"
            lines.append(
                f"- {candidate.get('artifact_type', 'candidate_json')} / {candidate.get('status', 'unknown')} / {candidate.get('mode', 'unknown')}: "
                f"{count_text} at `{candidate.get('path')}`"
            )
    return lines


def render_promotion_gate_lines(payload: dict[str, Any]) -> list[str]:
    lines = []
    for item in payload.get("backends") or []:
        gate = item.get("promotion_gate") or {}
        decision = str(gate.get("decision") or "unknown")
        status = str(gate.get("status") or "unknown")
        reasons = "; ".join(str(reason) for reason in gate.get("reasons") or []) or "no reason recorded"
        lines.append(f"- **{item.get('name')}**: {decision} / {status}; {reasons}")
    return lines


def escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


if __name__ == "__main__":
    raise SystemExit(main())
