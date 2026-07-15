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

from ebook_converter_mcp import infer_artifact_type, summarize_known_artifact_json  # noqa: E402


SCHEMA_VERSION = "layout-table-review-bundle-v1"

REVIEW_QUESTIONS = [
    "Does layout evidence explain the final Markdown reading order?",
    "Are true tables preserved as tables with cells/HTML/Markdown evidence?",
    "Are card/infographic regions kept out of table output?",
    "Are formula candidates tied back to page/image evidence?",
    "Does any document-VLM output replace an existing heavy route, or only add another option?",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an offline layout/table/formula review bundle from candidate artifacts.")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source", type=Path, help="Optional source document/image path for context.")
    parser.add_argument("--artifact", type=Path, action="append", default=[], help="Candidate JSON artifact to include.")
    parser.add_argument("--external-wrapper-root", type=Path, action="append", default=[], help="Directory to scan for external-wrapper-result.json artifacts.")
    parser.add_argument("--scorecard", type=Path, action="append", default=[], help="Optional backend-scorecard.json files with promotion_gate decisions to merge into the review bundle.")
    parser.add_argument("--candidate-plan", type=Path, action="append", default=[], help="Optional candidate-benchmark-plan JSON files with sample review questions and run previews.")
    parser.add_argument("--quality-evaluation", type=Path, action="append", default=[], help="Optional document-quality-evaluation.json files to attach as offline review evidence.")
    parser.add_argument("--sample-id", help="Optional sample id to match inside candidate benchmark plans.")
    args = parser.parse_args()

    payload = build_review_bundle(args.artifact, args.external_wrapper_root, source=args.source, output=args.output, scorecards=args.scorecard, candidate_plans=args.candidate_plan, quality_evaluations=args.quality_evaluation, sample_id=args.sample_id)
    write_bundle(args.output, payload)
    print(json.dumps({"status": "ok", "output": str(args.output), "artifact_count": len(payload["artifact_summaries"])}, ensure_ascii=False))
    return 0


def build_review_bundle(
    artifacts: list[Path],
    roots: list[Path],
    *,
    source: Path | None = None,
    output: Path | None = None,
    scorecards: list[Path] | None = None,
    candidate_plans: list[Path] | None = None,
    quality_evaluations: list[Path] | None = None,
    sample_id: str | None = None,
) -> dict[str, Any]:
    paths = collect_artifact_paths(artifacts, roots)
    summaries = [summarize_artifact(path) for path in paths]
    summaries = [item for item in summaries if item]
    scorecard_backends = collect_scorecard_backends(scorecards or [])
    promotion_reviews = promotion_reviews_for_bundle(summaries, scorecard_backends)
    quality_evaluation_rows = collect_quality_evaluations(quality_evaluations or [])
    benchmark_context = collect_benchmark_context(candidate_plans or [], source=source, sample_id=sample_id)
    benchmark_context = attach_expected_artifact_coverage(benchmark_context, summaries)
    review_pages = build_review_pages(summaries, source=source)
    table_review_matrix = build_table_review_matrix(review_pages)
    formula_review_matrix = build_formula_review_matrix(review_pages)
    review_questions = merge_review_questions(benchmark_context, REVIEW_QUESTIONS)
    counts = summarize_counts(summaries, promotion_reviews, benchmark_context, review_pages, table_review_matrix, formula_review_matrix, quality_evaluation_rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": str(source) if source else "",
        "output": str(output) if output else "",
        "execution_policy": "review_only_no_model_execution",
        "review_questions": review_questions,
        "summary": counts,
        "artifact_summaries": summaries,
        "scorecard_count": len(scorecards or []),
        "candidate_plan_count": len(candidate_plans or []),
        "quality_evaluations": quality_evaluation_rows,
        "benchmark_context": benchmark_context,
        "review_pages": review_pages,
        "table_review_matrix": table_review_matrix,
        "formula_review_matrix": formula_review_matrix,
        "promotion_reviews": promotion_reviews,
        "next_actions": next_actions_for_bundle(summaries, promotion_reviews, benchmark_context, review_pages, table_review_matrix, formula_review_matrix),
    }


def collect_quality_evaluations(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or payload.get("schema_version") != "document-quality-evaluation-v1":
            continue
        rows.append({"path": str(path), "summary": summarize_known_artifact_json(payload, "document_quality_evaluation_json"), "backend_evaluations": payload.get("backend_evaluations") or []})
    return rows


def collect_benchmark_context(paths: list[Path], *, source: Path | None, sample_id: str | None) -> dict[str, Any]:
    seen: set[str] = set()
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        context = load_benchmark_context(path, source=source, sample_id=sample_id)
        if context:
            return context
    return {}


def load_benchmark_context(path: Path, *, source: Path | None, sample_id: str | None) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or payload.get("schema_version") != "candidate-benchmark-plan-v1":
        return {}
    sample = match_benchmark_sample(payload.get("samples") or [], source=source, sample_id=sample_id)
    if not sample:
        return {}
    candidate_class = str(sample.get("candidate_class") or "")
    class_profile = match_benchmark_class(payload.get("sample_classes") or [], candidate_class)
    review_questions = unique_strings([*(class_profile.get("review_questions") or []), *(sample.get("review_questions") or [])])
    expected_artifacts = unique_strings([*(class_profile.get("expected_artifacts") or []), *(sample.get("expected_artifacts") or [])])
    candidate_previews = sample.get("candidate_backend_previews") or class_profile.get("candidate_backend_previews") or []
    return {
        "schema_version": "candidate-benchmark-context-v1",
        "candidate_plan_path": str(path),
        "sample_id": sample.get("id") or "",
        "sample_path": sample.get("path") or "",
        "candidate_class": candidate_class,
        "exists": bool(sample.get("exists")),
        "review_questions": review_questions,
        "expected_artifacts": expected_artifacts,
        "candidate_backend_previews": [item for item in candidate_previews if isinstance(item, dict)],
        "promotion_gate": payload.get("promotion_gate") or {},
    }


def match_benchmark_sample(samples: list[Any], *, source: Path | None, sample_id: str | None) -> dict[str, Any]:
    normalized_source = normalize_path_for_match(str(source or ""))
    source_name = Path(str(source)).name.lower() if source else ""
    for item in samples:
        if not isinstance(item, dict):
            continue
        if sample_id and str(item.get("id") or "") == sample_id:
            return item
    if not normalized_source:
        return {}
    for item in samples:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        normalized_path = normalize_path_for_match(path)
        if normalized_path and normalized_path == normalized_source:
            return item
        if source_name and Path(path).name.lower() == source_name:
            return item
    return {}


def match_benchmark_class(classes: list[Any], candidate_class: str) -> dict[str, Any]:
    for item in classes:
        if isinstance(item, dict) and str(item.get("class") or "") == candidate_class:
            return item
    return {}


def merge_review_questions(benchmark_context: dict[str, Any], defaults: list[str]) -> list[str]:
    return unique_strings([*(benchmark_context.get("review_questions") or []), *defaults])


def normalize_path_for_match(value: str) -> str:
    if not value:
        return ""
    try:
        return str(Path(value).resolve()).lower()
    except OSError:
        return str(Path(value)).replace("\\", "/").lower()

def attach_expected_artifact_coverage(benchmark_context: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    if not benchmark_context:
        return {}
    enriched = dict(benchmark_context)
    enriched["expected_artifact_coverage"] = expected_artifact_coverage(items, benchmark_context)
    return enriched


def expected_artifact_coverage(items: list[dict[str, Any]], benchmark_context: dict[str, Any]) -> dict[str, Any]:
    expected = unique_strings(benchmark_context.get("expected_artifacts") or [])
    present = collected_artifact_types(items)
    missing = [artifact for artifact in expected if artifact not in present]
    return {
        "schema_version": "expected-artifact-coverage-v1",
        "expected": expected,
        "present": [artifact for artifact in expected if artifact in present],
        "missing": missing,
        "extra_present": [artifact for artifact in present if artifact not in expected],
        "complete": bool(expected) and not missing,
    }


def collected_artifact_types(items: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for item in items:
        artifact_type = str(item.get("artifact_type") or "").strip()
        if artifact_type:
            values.append(artifact_type)
        summary = item.get("summary") or {}
        if isinstance(summary, dict):
            for nested in summary.get("artifacts") or []:
                if isinstance(nested, dict) and nested.get("type"):
                    values.append(str(nested.get("type")))
            for nested_type in summary.get("artifact_types") or []:
                values.append(str(nested_type))
    return unique_strings(values)


def build_review_pages(items: list[dict[str, Any]], *, source: Path | None = None) -> list[dict[str, Any]]:
    pages: dict[str, dict[str, Any]] = {}
    for item in items:
        for entry in item.get("review_entries") or []:
            if not isinstance(entry, dict):
                continue
            locator = str(entry.get("locator") or "document")
            page = pages.setdefault(
                locator,
                {
                    "schema_version": "layout-table-review-page-v1",
                    "locator": locator,
                    "page": entry.get("page"),
                    "source": str(source) if source else str(entry.get("source") or ""),
                    "backends": [],
                    "artifact_types": [],
                    "artifact_refs": [],
                    "markdown_excerpts": [],
                    "block_count": 0,
                    "table_count": 0,
                    "formula_count": 0,
                    "review_targets": [],
                    "table_counts_by_backend": {},
                    "formula_counts_by_backend": {},
                },
            )
            append_unique(page["backends"], entry.get("backend"))
            append_unique(page["artifact_types"], entry.get("artifact_type"))
            page["block_count"] += int(entry.get("block_count") or 0)
            page["table_count"] += int(entry.get("table_count") or 0)
            if entry.get("backend") and int(entry.get("table_count") or 0):
                counts_by_backend = page.setdefault("table_counts_by_backend", {})
                backend_key = str(entry.get("backend") or "")
                counts_by_backend[backend_key] = int(counts_by_backend.get(backend_key) or 0) + int(entry.get("table_count") or 0)
            page["formula_count"] += int(entry.get("formula_count") or 0)
            merge_formula_evidence(page, entry.get("backend"), entry.get("formula_evidence") or {})
            if entry.get("backend") and int(entry.get("formula_count") or 0):
                counts_by_backend = page.setdefault("formula_counts_by_backend", {})
                backend_key = str(entry.get("backend") or "")
                counts_by_backend[backend_key] = int(counts_by_backend.get(backend_key) or 0) + int(entry.get("formula_count") or 0)
            for ref in entry.get("artifact_refs") or []:
                if isinstance(ref, dict):
                    append_unique_dict(page["artifact_refs"], ref)
                    target = review_target_for_ref(ref)
                    if target:
                        append_unique(page["review_targets"], target)
            for excerpt in entry.get("markdown_excerpts") or []:
                if isinstance(excerpt, dict):
                    append_unique_dict(page["markdown_excerpts"], excerpt)
                    append_unique(page["review_targets"], "markdown_excerpt")
            if entry.get("block_count"):
                append_unique(page["review_targets"], "layout_blocks")
            if entry.get("table_count"):
                append_unique(page["review_targets"], "table_candidates")
            if entry.get("formula_count"):
                append_unique(page["review_targets"], "formula_candidates")
    return sorted(pages.values(), key=review_page_sort_key)


def build_table_review_matrix(review_pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matrix = []
    for page in review_pages:
        if not page_has_table_evidence(page):
            continue
        backend_rows: dict[str, dict[str, Any]] = {}
        for ref in page.get("artifact_refs") or []:
            if not isinstance(ref, dict):
                continue
            role = str(ref.get("role") or "")
            backend = str(ref.get("backend") or "unknown")
            if not role.startswith("table_"):
                continue
            row = backend_rows.setdefault(backend, table_review_backend_row(backend, page, table_count=int((page.get("table_counts_by_backend") or {}).get(backend) or 0)))
            row["artifact_refs"].append(ref)
            if role == "table_html":
                row["has_html"] = True
            elif role == "table_markdown":
                row["has_markdown"] = True
            elif role == "table_cells_json":
                row["has_cells_json"] = True
            elif role == "table_overlay":
                row["has_overlay"] = True
            elif role == "table_image":
                row["has_table_image"] = True
        for excerpt in page.get("markdown_excerpts") or []:
            if not isinstance(excerpt, dict) or not str(excerpt.get("source_key") or "").startswith("table"):
                continue
            backend = str(excerpt.get("backend") or "unknown")
            row = backend_rows.setdefault(backend, table_review_backend_row(backend, page, table_count=int((page.get("table_counts_by_backend") or {}).get(backend) or 0)))
            row["markdown_excerpt_count"] += 1
            row["has_markdown"] = True
        for backend, count in (page.get("table_counts_by_backend") or {}).items():
            backend_rows.setdefault(str(backend), table_review_backend_row(str(backend), page, table_count=int(count or 0)))
        rows = sorted((finalize_table_review_row(row) for row in backend_rows.values()), key=lambda item: str(item.get("backend") or ""))
        if not rows:
            continue
        comparison_summary = table_matrix_comparison_summary(rows, page)
        matrix.append(
            {
                "schema_version": "table-review-matrix-v1",
                "locator": page.get("locator") or "document",
                "page": page.get("page"),
                "source": page.get("source") or "",
                "backend_count": len(rows),
                "table_count": page.get("table_count") or 0,
                "comparison_summary": comparison_summary,
                "rows": rows,
                "review_questions": [
                    "Do table candidates represent true tables rather than card/infographic layout?",
                    "Do HTML/Markdown/cell outputs agree across backends on the same page?",
                    "Is overlay evidence present before considering promotion?",
                ],
            }
        )
    return matrix


def build_formula_review_matrix(review_pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matrix = []
    for page in review_pages:
        if not page_has_formula_evidence(page):
            continue
        backend_rows: dict[str, dict[str, Any]] = {}
        for ref in page.get("artifact_refs") or []:
            if not isinstance(ref, dict):
                continue
            role = str(ref.get("role") or "")
            backend = str(ref.get("backend") or "unknown")
            if not role.startswith("formula_"):
                continue
            row = backend_rows.setdefault(backend, formula_review_backend_row(backend, page, formula_count=int((page.get("formula_counts_by_backend") or {}).get(backend) or 0)))
            row["artifact_refs"].append(ref)
            if role == "formula_source":
                row["has_source_ref"] = True
            elif role == "formula_crop":
                row["has_crop"] = True
            elif role == "formula_markdown":
                row["has_markdown"] = True
        for excerpt in page.get("markdown_excerpts") or []:
            if not isinstance(excerpt, dict) or not str(excerpt.get("source_key") or "").startswith("formula"):
                continue
            backend = str(excerpt.get("backend") or "unknown")
            row = backend_rows.setdefault(backend, formula_review_backend_row(backend, page, formula_count=int((page.get("formula_counts_by_backend") or {}).get(backend) or 0)))
            row["markdown_excerpt_count"] += 1
            row["has_markdown"] = True
            if str(excerpt.get("text") or "").strip():
                row["latex_or_markdown_count"] += 1
        for backend, count in (page.get("formula_counts_by_backend") or {}).items():
            row = backend_rows.setdefault(str(backend), formula_review_backend_row(str(backend), page, formula_count=int(count or 0)))
            evidence = (page.get("formula_evidence_by_backend") or {}).get(str(backend)) or {}
            row["latex_or_markdown_count"] += int(evidence.get("latex_or_markdown_count") or 0)
            if evidence.get("bbox_count"):
                row["has_bbox"] = True
            if evidence.get("source_ref_count"):
                row["has_source_ref"] = True
            if evidence.get("confidence_count"):
                row["has_confidence"] = True
        rows = sorted((finalize_formula_review_row(row) for row in backend_rows.values()), key=lambda item: str(item.get("backend") or ""))
        if not rows:
            continue
        matrix.append(
            {
                "schema_version": "formula-review-matrix-v1",
                "locator": page.get("locator") or "document",
                "page": page.get("page"),
                "source": page.get("source") or "",
                "backend_count": len(rows),
                "formula_count": page.get("formula_count") or 0,
                "rows": rows,
                "review_questions": [
                    "Are formula candidates preserved as LaTeX or readable Markdown?",
                    "Are formula regions tied back to source page/image or crop evidence?",
                    "Is confidence/bbox evidence present before using formula output for promotion?",
                ],
            }
        )
    return matrix



def page_has_table_evidence(page: dict[str, Any]) -> bool:
    if int(page.get("table_count") or 0) > 0:
        return True
    if "table_candidates" in (page.get("review_targets") or []):
        return True
    return any(str(ref.get("role") or "").startswith("table_") for ref in page.get("artifact_refs") or [] if isinstance(ref, dict))


def page_has_formula_evidence(page: dict[str, Any]) -> bool:
    if int(page.get("formula_count") or 0) > 0:
        return True
    if "formula_candidates" in (page.get("review_targets") or []):
        return True
    return any(str(ref.get("role") or "").startswith("formula_") for ref in page.get("artifact_refs") or [] if isinstance(ref, dict))


def formula_review_backend_row(backend: str, page: dict[str, Any], *, formula_count: int = 0) -> dict[str, Any]:
    return {
        "schema_version": "formula-review-backend-row-v1",
        "backend": backend,
        "formula_count": int(formula_count or 0),
        "has_latex_or_markdown": False,
        "has_markdown": False,
        "has_bbox": False,
        "has_source_ref": False,
        "has_crop": False,
        "has_confidence": False,
        "latex_or_markdown_count": 0,
        "markdown_excerpt_count": 0,
        "artifact_refs": [],
        "warnings": [],
    }


def finalize_formula_review_row(row: dict[str, Any]) -> dict[str, Any]:
    warnings = []
    if row.get("latex_or_markdown_count"):
        row["has_latex_or_markdown"] = True
    if row.get("formula_count") and not row.get("has_latex_or_markdown"):
        warnings.append("missing_latex_or_markdown")
    if row.get("formula_count") and not row.get("has_bbox"):
        warnings.append("missing_formula_bbox")
    if row.get("formula_count") and not (row.get("has_source_ref") or row.get("has_crop")):
        warnings.append("missing_formula_source_ref")
    if row.get("formula_count") and not row.get("has_confidence"):
        warnings.append("missing_formula_confidence")
    if row.get("formula_count"):
        warnings.append("check_formula_retention")
    row["warnings"] = unique_strings([*row.get("warnings", []), *warnings])
    row["artifact_ref_count"] = len(row.get("artifact_refs") or [])
    return row


def table_review_backend_row(backend: str, page: dict[str, Any], *, table_count: int = 0) -> dict[str, Any]:
    return {
        "schema_version": "table-review-backend-row-v1",
        "backend": backend,
        "table_count": int(table_count or 0),
        "has_html": False,
        "has_markdown": False,
        "has_cells_json": False,
        "has_overlay": False,
        "has_table_image": False,
        "markdown_excerpt_count": 0,
        "artifact_refs": [],
        "warnings": [],
        "missing_evidence": [],
        "risk_tags": [],
        "evidence_completeness_score": 0.0,
    }


def finalize_table_review_row(row: dict[str, Any]) -> dict[str, Any]:
    warnings = []
    missing_evidence = []
    risk_tags = []
    has_readable = bool(row.get("has_html") or row.get("has_markdown"))
    if row.get("table_count") and not row.get("has_overlay"):
        warnings.append("missing_table_overlay")
        missing_evidence.append("table_overlay")
    if row.get("table_count") and not row.get("has_cells_json"):
        warnings.append("missing_cells_json")
        missing_evidence.append("table_cells_json")
    if row.get("table_count") and not has_readable:
        warnings.append("missing_readable_table_output")
        missing_evidence.append("table_html_or_markdown")
    if row.get("table_count"):
        warnings.append("check_card_layout_false_positive")
        risk_tags.append("card_layout_false_positive_review_required")
    present_required = sum(1 for value in (has_readable, bool(row.get("has_cells_json")), bool(row.get("has_overlay"))) if value)
    row["evidence_completeness_score"] = round(present_required / 3, 3) if row.get("table_count") else 0.0
    row["missing_evidence"] = unique_strings([*row.get("missing_evidence", []), *missing_evidence])
    row["risk_tags"] = unique_strings([*row.get("risk_tags", []), *risk_tags])
    row["warnings"] = unique_strings([*row.get("warnings", []), *warnings])
    row["artifact_ref_count"] = len(row.get("artifact_refs") or [])
    return row


def table_matrix_comparison_summary(rows: list[dict[str, Any]], page: dict[str, Any]) -> dict[str, Any]:
    table_counts_by_backend = {str(row.get("backend") or "unknown"): int(row.get("table_count") or 0) for row in rows}
    positive_counts = sorted({count for count in table_counts_by_backend.values() if count > 0})
    missing_overlay = [str(row.get("backend") or "unknown") for row in rows if row.get("table_count") and not row.get("has_overlay")]
    missing_cells = [str(row.get("backend") or "unknown") for row in rows if row.get("table_count") and not row.get("has_cells_json")]
    missing_readable = [str(row.get("backend") or "unknown") for row in rows if row.get("table_count") and not (row.get("has_html") or row.get("has_markdown"))]
    conflict_tags: list[str] = []
    if len(rows) < 2:
        conflict_tags.append("single_backend_only")
    if len(positive_counts) > 1:
        conflict_tags.append("table_count_disagreement")
    if missing_overlay:
        conflict_tags.append("missing_overlay_evidence")
    if missing_cells:
        conflict_tags.append("missing_cells_json")
    if missing_readable:
        conflict_tags.append("missing_readable_table_output")
    if any("check_card_layout_false_positive" in (row.get("warnings") or []) for row in rows):
        conflict_tags.append("card_layout_review_required")
    max_score = max((float(row.get("evidence_completeness_score") or 0) for row in rows), default=0.0)
    return {
        "schema_version": "table-review-comparison-summary-v1",
        "backend_count": len(rows),
        "table_count": int(page.get("table_count") or 0),
        "table_counts_by_backend": table_counts_by_backend,
        "agrees_on_table_count": len(positive_counts) <= 1,
        "missing_overlay_backends": missing_overlay,
        "missing_cells_json_backends": missing_cells,
        "missing_readable_output_backends": missing_readable,
        "max_evidence_completeness_score": round(max_score, 3),
        "incomplete_backend_count": sum(1 for row in rows if row.get("table_count") and float(row.get("evidence_completeness_score") or 0) < 1),
        "conflict_tags": unique_strings(conflict_tags),
        "recommendation": "review_conflicts_before_promotion" if conflict_tags else "table_evidence_ready_for_scorecard_comparison",
    }

def review_entries_for_payload(path: Path, artifact_type: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    backend = str(payload.get("backend") or "")
    if artifact_type == "external_wrapper_result_json" or payload.get("schema_version") == "external-wrapper-result-v1":
        refs = artifact_refs_from_list(payload.get("artifacts") or [], backend=backend, artifact_path=path)
        return [
            {
                "schema_version": "layout-table-review-entry-v1",
                "locator": "document",
                "page": None,
                "backend": backend,
                "artifact_type": "external_wrapper_result_json",
                "artifact_path": str(path),
                "artifact_refs": refs,
                "markdown_excerpts": [],
                "block_count": int((payload.get("metrics") or {}).get("block_count") or 0),
                "table_count": int((payload.get("metrics") or {}).get("table_count") or 0),
                "formula_count": int((payload.get("metrics") or {}).get("formula_count") or 0),
                "formula_evidence": {},
            }
        ]
    if artifact_type not in {"layout_candidates_json", "table_candidates_json", "formula_candidates_json", "document_vlm_result_json", "pdf_layout_evidence_json"}:
        return []
    entries = []
    root_refs = artifact_refs_from_list(payload.get("artifacts") or [], backend=backend, artifact_path=path)
    for page in [item for item in payload.get("pages") or [] if isinstance(item, dict)]:
        locator = page_locator(page)
        refs = [*root_refs, *artifact_refs_from_page(page, backend=backend, artifact_path=path)]
        excerpts = markdown_excerpts_from_page(page, backend=backend, artifact_path=path)
        entries.append(
            {
                "schema_version": "layout-table-review-entry-v1",
                "locator": locator,
                "page": page_number(page),
                "source": page.get("source") or page.get("image") or "",
                "backend": backend,
                "artifact_type": artifact_type,
                "artifact_path": str(path),
                "artifact_refs": refs,
                "markdown_excerpts": excerpts,
                "block_count": count_items(page, "blocks"),
                "table_count": count_items(page, "tables"),
                "formula_count": count_items(page, "formulas"),
                "formula_evidence": formula_evidence_summary(page),
            }
        )
    return entries


def formula_evidence_summary(page: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, int] = {
        "latex_or_markdown_count": 0,
        "bbox_count": 0,
        "source_ref_count": 0,
        "confidence_count": 0,
    }
    page_source = any(page.get(key) for key in ("source", "image", "image_path", "page_image", "source_image"))
    for formula in [item for item in page.get("formulas") or [] if isinstance(item, dict)]:
        if formula.get("latex") or formula.get("formula") or formula.get("markdown"):
            summary["latex_or_markdown_count"] += 1
        if formula.get("bbox") is not None or formula.get("position") is not None:
            summary["bbox_count"] += 1
        if page_source or any(formula.get(key) for key in ("source", "image", "image_path", "crop_path", "source_image")):
            summary["source_ref_count"] += 1
        if formula.get("confidence") is not None or formula.get("score") is not None:
            summary["confidence_count"] += 1
    return summary


def merge_formula_evidence(page: dict[str, Any], backend: Any, evidence: dict[str, Any]) -> None:
    backend_key = str(backend or "")
    if not backend_key or not evidence:
        return
    all_evidence = page.setdefault("formula_evidence_by_backend", {})
    target = all_evidence.setdefault(
        backend_key,
        {"latex_or_markdown_count": 0, "bbox_count": 0, "source_ref_count": 0, "confidence_count": 0},
    )
    for key in ("latex_or_markdown_count", "bbox_count", "source_ref_count", "confidence_count"):
        target[key] = int(target.get(key) or 0) + int(evidence.get(key) or 0)


def artifact_refs_from_page(page: dict[str, Any], *, backend: str, artifact_path: Path) -> list[dict[str, str]]:
    refs = []
    for key, role in [
        ("image", "original_render"),
        ("source", "source_page"),
        ("overlay_path", "layout_overlay"),
        ("layout_overlay", "layout_overlay"),
        ("layout_overlay_image", "layout_overlay"),
        ("ocr_blocks_path", "ocr_blocks"),
        ("markdown_path", "markdown"),
    ]:
        if page.get(key):
            refs.append(review_ref(role, key, page.get(key), backend=backend, artifact_path=artifact_path))
    refs.extend(artifact_refs_from_list(page.get("artifacts") or [], backend=backend, artifact_path=artifact_path))
    for table in [item for item in page.get("tables") or [] if isinstance(item, dict)]:
        for key, role in [
            ("html_path", "table_html"),
            ("markdown_path", "table_markdown"),
            ("cells_path", "table_cells_json"),
            ("overlay_path", "table_overlay"),
            ("image_path", "table_image"),
        ]:
            if table.get(key):
                refs.append(review_ref(role, key, table.get(key), backend=backend, artifact_path=artifact_path))
    return refs


def artifact_refs_from_list(values: list[Any], *, backend: str, artifact_path: Path) -> list[dict[str, str]]:
    refs = []
    for item in values:
        if not isinstance(item, dict):
            continue
        path_value = item.get("path") or item.get("href") or item.get("file")
        if not path_value:
            continue
        refs.append(review_ref(str(item.get("type") or item.get("role") or "artifact"), "path", path_value, backend=backend, artifact_path=artifact_path))
    return refs


def markdown_excerpts_from_page(page: dict[str, Any], *, backend: str, artifact_path: Path) -> list[dict[str, str]]:
    excerpts = []
    for key in ["markdown", "text", "content"]:
        if page.get(key):
            excerpts.append({"backend": backend, "source_key": key, "artifact_path": str(artifact_path), "text": compact_text(page.get(key))})
    for table in [item for item in page.get("tables") or [] if isinstance(item, dict)]:
        if table.get("markdown"):
            excerpts.append({"backend": backend, "source_key": "table.markdown", "artifact_path": str(artifact_path), "text": compact_text(table.get("markdown"))})
    return excerpts


def review_ref(role: str, key: str, value: Any, *, backend: str, artifact_path: Path) -> dict[str, str]:
    return {"role": role, "key": key, "path": str(value), "backend": backend, "artifact_path": str(artifact_path)}


def page_locator(page: dict[str, Any]) -> str:
    number = page_number(page)
    if number is not None:
        return f"page:{number}"
    for key in ["image", "source"]:
        if page.get(key):
            return f"source:{Path(str(page.get(key))).name}"
    return "document"


def page_number(page: dict[str, Any]) -> int | None:
    for key in ["page", "page_number", "index"]:
        try:
            if page.get(key) is not None:
                return int(page.get(key))
        except (TypeError, ValueError):
            continue
    return None


def count_items(page: dict[str, Any], key: str) -> int:
    values = page.get(key)
    if isinstance(values, list):
        return len(values)
    count_key = key[:-1] + "_count" if key.endswith("s") else f"{key}_count"
    return int(page.get(count_key) or 0)


def compact_text(value: Any, limit: int = 320) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def append_unique(values: list[Any], value: Any) -> None:
    if value in {None, ""} or value in values:
        return
    values.append(value)


def append_unique_dict(values: list[dict[str, Any]], value: dict[str, Any]) -> None:
    marker = json.dumps(value, sort_keys=True, ensure_ascii=False)
    if any(json.dumps(item, sort_keys=True, ensure_ascii=False) == marker for item in values):
        return
    values.append(value)


def review_target_for_ref(ref: dict[str, Any]) -> str:
    role = str(ref.get("role") or "")
    if role in {"original_render", "source_page"}:
        return "original_render"
    if "overlay" in role:
        return "layout_overlay" if "layout" in role else "table_overlay"
    if role in {"ocr_blocks", "ocr_blocks_jsonl"}:
        return "ocr_blocks"
    if role.startswith("table_"):
        return "table_candidates"
    if "markdown" in role:
        return "markdown_ref"
    return "artifact_ref"


def review_page_sort_key(page: dict[str, Any]) -> tuple[int, str]:
    number = page.get("page")
    return (int(number) if isinstance(number, int) else 1_000_000, str(page.get("locator") or ""))

def collect_artifact_paths(artifacts: list[Path], roots: list[Path]) -> list[Path]:
    candidates: list[Path] = list(artifacts)
    for root in roots:
        if root.exists() and root.is_file():
            candidates.append(root)
        elif root.exists() and root.is_dir():
            for pattern in [
                "external-wrapper-result.json",
                "layout-candidates.json",
                "layout_candidates.json",
                "table-candidates.json",
                "table_candidates.json",
                "formula-candidates.json",
                "formula_candidates.json",
                "document-vlm-result.json",
                "document_vlm_result.json",
            ]:
                candidates.extend(root.rglob(pattern))
    seen: set[str] = set()
    unique = []
    for path in candidates:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def summarize_artifact(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {"path": str(path), "status": "missing"}
    artifact_type = infer_artifact_type(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        return {"path": str(path), "artifact_type": artifact_type, "status": "invalid_json", "message": str(exc)}
    if not isinstance(payload, dict):
        return {"path": str(path), "artifact_type": artifact_type, "status": "unsupported_json"}
    summary = summarize_known_artifact_json(payload, artifact_type)
    return {
        "path": str(path),
        "artifact_type": artifact_type,
        "schema_version": payload.get("schema_version"),
        "backend": summary.get("backend") or payload.get("backend"),
        "status": summary.get("status") or payload.get("status") or "ok",
        "summary": summary,
        "review_entries": review_entries_for_payload(path, artifact_type, payload),
    }


def summarize_counts(items: list[dict[str, Any]], promotion_reviews: list[dict[str, Any]] | None = None, benchmark_context: dict[str, Any] | None = None, review_pages: list[dict[str, Any]] | None = None, table_review_matrix: list[dict[str, Any]] | None = None, formula_review_matrix: list[dict[str, Any]] | None = None, quality_evaluations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    counts: dict[str, int] = {}
    gate_counts: dict[str, int] = {}
    backends: set[str] = set()
    total_blocks = 0
    total_tables = 0
    total_formulas = 0
    for item in items:
        artifact_type = str(item.get("artifact_type") or "unknown")
        counts[artifact_type] = counts.get(artifact_type, 0) + 1
        backend = str(item.get("backend") or "")
        if backend:
            backends.add(backend)
        summary = item.get("summary") or {}
        total_blocks += int(summary.get("block_count") or 0)
        total_tables += int(summary.get("table_count") or 0)
        total_formulas += int(summary.get("formula_count") or 0)

    for review in promotion_reviews or []:
        decision = str((review.get("promotion_gate") or {}).get("decision") or "unknown")
        gate_counts[decision] = gate_counts.get(decision, 0) + 1
    return {
        "artifact_count": len(items),
        "artifact_type_counts": counts,
        "backends": sorted(backends),
        "block_count": total_blocks,
        "table_count": total_tables,
        "formula_count": total_formulas,
        "promotion_review_count": len(promotion_reviews or []),
        "promotion_gate_counts": gate_counts,
        "promotion_compare_candidates": [
            review.get("backend")
            for review in promotion_reviews or []
            if (review.get("promotion_gate") or {}).get("decision") == "compare_on_shared_manifest"
        ],
        "benchmark_context_found": bool(benchmark_context),
        "expected_artifact_count": len((benchmark_context or {}).get("expected_artifacts") or []),
        "missing_expected_artifact_count": len(((benchmark_context or {}).get("expected_artifact_coverage") or {}).get("missing") or []),
        "candidate_preview_count": len((benchmark_context or {}).get("candidate_backend_previews") or []),
        "review_page_count": len(review_pages or []),
        "table_review_matrix_count": len(table_review_matrix or []),
        "formula_review_matrix_count": len(formula_review_matrix or []),
    }


def collect_scorecard_backends(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        rows.extend(load_scorecard_backends(path))
    return rows


def load_scorecard_backends(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict) or payload.get("schema_version") != "optional-backend-scorecard-v1":
        return []
    rows = []
    for item in payload.get("backends") or []:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        row["scorecard_path"] = str(path)
        rows.append(row)
    return rows


def promotion_reviews_for_bundle(items: list[dict[str, Any]], scorecard_backends: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bundle_backend_keys = {normalize_backend_key(str(item.get("backend") or "")) for item in items if item.get("backend")}
    reviews: list[dict[str, Any]] = []
    seen: set[str] = set()
    for backend in scorecard_backends:
        keys = scorecard_keys_for_backend(backend)
        if not keys.intersection(bundle_backend_keys):
            continue
        name = str(backend.get("name") or "")
        if name in seen:
            continue
        seen.add(name)
        reviews.append(
            {
                "backend": name,
                "status": backend.get("status"),
                "recommendation_score": backend.get("recommendation_score"),
                "promotion_gate": backend.get("promotion_gate") or {},
                "quality_signals": backend.get("quality_signals") or {},
                "scorecard_path": backend.get("scorecard_path") or "",
            }
        )
    return sorted(reviews, key=promotion_review_sort_key)


def scorecard_keys_for_backend(backend: dict[str, Any]) -> set[str]:
    keys = {normalize_backend_key(str(backend.get("name") or ""))}
    for key in ("health_names", "capability_names"):
        values = backend.get(key) or []
        if isinstance(values, str):
            values = [values]
        for value in values:
            keys.add(normalize_backend_key(str(value or "")))
    return {key for key in keys if key}


def promotion_review_sort_key(review: dict[str, Any]) -> tuple[int, str]:
    decision = str((review.get("promotion_gate") or {}).get("decision") or "unknown")
    order = {
        "plan_or_fix_environment_first": 0,
        "review_only": 1,
        "compare_on_shared_manifest": 2,
        "do_not_promote": 3,
    }
    return (order.get(decision, 9), str(review.get("backend") or ""))


def normalize_backend_key(name: str) -> str:
    lowered = name.lower().replace("-", "_").replace(".", "_").replace(" ", "_").strip()
    aliases = {
        "doclayout_yolo_baseline": "doclayout_yolo",
        "doclayout_yolo": "doclayout_yolo",
        "pdf_table_worker": "pdf_table",
        "pdf_table": "pdf_table",
        "monkeyocr_worker": "monkeyocr",
        "monkeyocr": "monkeyocr",
        "dots_mocr_provider": "dots_mocr",
        "dots_mocr": "dots_mocr",
        "paddleocr_vl_wrapper": "paddleocr_vl",
        "paddleocr_vl": "paddleocr_vl",
        "paddle_ocr_vl": "paddleocr_vl",
        "qwen_vl_wrapper": "qwen_vl",
        "qwen_vl": "qwen_vl",
        "pix2text_wrapper": "pix2text",
        "pix2text": "pix2text",
        "surya_wrapper": "surya",
        "surya": "surya",
        "got_ocr_wrapper": "got_ocr",
        "got_ocr": "got_ocr",
        "deepseek_ocr_wrapper": "deepseek_ocr",
        "deepseek_ocr": "deepseek_ocr",
    }
    return aliases.get(lowered, lowered)


def next_actions_for_bundle(items: list[dict[str, Any]], promotion_reviews: list[dict[str, Any]] | None = None, benchmark_context: dict[str, Any] | None = None, review_pages: list[dict[str, Any]] | None = None, table_review_matrix: list[dict[str, Any]] | None = None, formula_review_matrix: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
    actions = [
        {"action": "read_bundle", "tool": "read_artifact", "artifact_type": "layout_table_review_bundle", "why": "inspect consolidated layout/table/formula evidence"},
        {"action": "update_scorecard", "tool": "generate_backend_scorecard", "why": "fold external wrapper and candidate sidecar evidence into backend scorecard before promotion"},
    ]

    if benchmark_context:
        actions.append({
            "action": "review_expected_artifacts",
            "tool": "manual_review",
            "why": "compare collected artifacts against candidate benchmark plan expected artifacts",
        })
        actions.append({
            "action": "use_candidate_run_previews",
            "tool": "external_wrapper_plan",
            "why": "use candidate-run-preview-v1 entries before any real backend execution",
        })
        coverage = benchmark_context.get("expected_artifact_coverage") or {}
        if coverage.get("missing"):
            actions.append({
                "action": "collect_missing_expected_artifacts",
                "tool": "manual_review",
                "why": "candidate benchmark plan expected artifacts are still missing from the bundle",
                "missing_artifacts": ", ".join(coverage.get("missing") or []),
            })
    for review in promotion_reviews or []:
        backend = str(review.get("backend") or "unknown")
        gate = review.get("promotion_gate") or {}
        decision = str(gate.get("decision") or "unknown")
        if decision == "plan_or_fix_environment_first":
            actions.append({"action": "plan_environment_or_model_fix", "tool": "manual_plan", "backend": backend, "why": "promotion gate says environment/model readiness must be planned before comparison"})
        elif decision == "review_only":
            actions.append({"action": "gather_shared_sample_evidence", "tool": "build_candidate_benchmark_manifest", "backend": backend, "why": "promotion gate needs stronger shared-sample evidence before route changes"})
        elif decision == "compare_on_shared_manifest":
            actions.append({"action": "compare_on_shared_manifest", "tool": "manual_review", "backend": backend, "why": "promotion gate allows comparison against existing route on shared samples"})
        elif decision == "do_not_promote":
            actions.append({"action": "keep_candidate_only", "tool": "manual_review", "backend": backend, "why": "promotion gate has no enough evidence for promotion"})
    if review_pages:
        actions.append({"action": "review_page_index", "tool": "manual_review", "why": "inspect per-page original/overlay/OCR/table/Markdown evidence before promotion"})
    if table_review_matrix:
        actions.append({"action": "review_table_matrix", "tool": "manual_review", "why": "compare same-page table evidence and card-layout false-positive risks across backends"})
    if formula_review_matrix:
        actions.append({"action": "review_formula_matrix", "tool": "manual_review", "why": "compare same-page formula LaTeX/Markdown, bbox, source, and confidence evidence across backends"})
    artifact_types = {str(item.get("artifact_type") or "") for item in items}
    if "table_candidates_json" in artifact_types:
        actions.append({"action": "compare_tables", "tool": "manual_review", "why": "compare table candidates against Camelot/Tabula/pdfplumber/pdf_table outputs"})
    if "layout_candidates_json" in artifact_types:
        actions.append({"action": "review_layout_overlay", "tool": "manual_review", "why": "verify layout boxes explain reading-order risks"})
    if "formula_candidates_json" in artifact_types:
        actions.append({"action": "review_formula_candidates", "tool": "manual_review", "why": "verify formula LaTeX/Markdown candidates against page/image evidence"})
    return actions


def write_bundle(output: Path, payload: dict[str, Any]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "layout-table-review-bundle.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    (output / "layout-table-review-bundle.md").write_text(render_markdown(payload), encoding="utf-8", newline="\n")


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "# Layout/Table Review Bundle",
        "",
        f"- Source: `{payload.get('source') or ''}`",
        f"- Artifact count: {summary.get('artifact_count', 0)}",
        f"- Backends: {', '.join(summary.get('backends') or []) or 'none'}",
        f"- Blocks: {summary.get('block_count', 0)}",
        f"- Tables: {summary.get('table_count', 0)}",
        f"- Formulas: {summary.get('formula_count', 0)}",
        f"- Promotion reviews: {summary.get('promotion_review_count', 0)}",
        f"- Promotion gate counts: {summary.get('promotion_gate_counts', {})}",
        f"- Benchmark context: {'yes' if summary.get('benchmark_context_found') else 'no'}",
        "",
        "## Review Questions",
        "",
    ]
    lines.extend(f"- {question}" for question in payload.get("review_questions") or [])
    benchmark_context = payload.get("benchmark_context") or {}
    if benchmark_context:
        lines.extend([
            "",
            "## Benchmark Context",
            "",
            f"- Sample: `{benchmark_context.get('sample_id') or ''}`",
            f"- Class: `{benchmark_context.get('candidate_class') or ''}`",
            f"- Candidate plan: `{benchmark_context.get('candidate_plan_path') or ''}`",
            f"- Expected artifacts: {', '.join(benchmark_context.get('expected_artifacts') or []) or 'none'}",
            f"- Missing expected artifacts: {', '.join((benchmark_context.get('expected_artifact_coverage') or {}).get('missing') or []) or 'none'}",
        ])
        previews = benchmark_context.get("candidate_backend_previews") or []
        if previews:
            lines.extend([
                "",
                "| Backend | Registry Key | Default Mode | Readiness | Expected Artifacts |",
                "| --- | --- | --- | --- | --- |",
            ])
            for preview in previews:
                run_preview = preview.get("run_preview") or {}
                lines.append(
                    "| "
                    + " | ".join(
                        escape_table(str(value))
                        for value in [
                            preview.get("backend", ""),
                            preview.get("registry_key", ""),
                            run_preview.get("default_mode", ""),
                            ", ".join((run_preview.get("readiness_contract") or {}).get("missing_states") or []),
                            ", ".join(run_preview.get("expected_artifacts") or preview.get("artifact_contract") or []),
                        ]
                    )
                    + " |"
                )
    review_pages = payload.get("review_pages") or []
    if review_pages:
        lines.extend([
            "",
            "## Review Pages",
            "",
            "| Locator | Backends | Counts | Review Targets | Artifact Refs | Markdown Excerpts |",
            "| --- | --- | --- | --- | ---: | ---: |",
        ])
        for page in review_pages:
            counts = f"blocks={page.get('block_count', 0)}, tables={page.get('table_count', 0)}, formulas={page.get('formula_count', 0)}"
            lines.append(
                "| "
                + " | ".join(
                    escape_table(str(value))
                    for value in [
                        page.get("locator", ""),
                        ", ".join(page.get("backends") or []),
                        counts,
                        ", ".join(page.get("review_targets") or []),
                        len(page.get("artifact_refs") or []),
                        len(page.get("markdown_excerpts") or []),
                    ]
                )
                + " |"
            )
    table_review_matrix = payload.get("table_review_matrix") or []
    if table_review_matrix:
        lines.extend([
            "",
            "## Table Review Matrix",
            "",
            "| Locator | Backend | Tables | Score | Missing | HTML | Markdown | Cells | Overlay | Warnings |",
            "| --- | --- | ---: | ---: | --- | --- | --- | --- | --- | --- |",
        ])
        for page_matrix in table_review_matrix:
            for row in page_matrix.get("rows") or []:
                lines.append(
                    "| "
                    + " | ".join(
                        escape_table(str(value))
                        for value in [
                            page_matrix.get("locator", ""),
                            row.get("backend", ""),
                            row.get("table_count", 0),
                            row.get("evidence_completeness_score", 0),
                            ", ".join(row.get("missing_evidence") or []),
                            yes_no(row.get("has_html")),
                            yes_no(row.get("has_markdown")),
                            yes_no(row.get("has_cells_json")),
                            yes_no(row.get("has_overlay")),
                            ", ".join(row.get("warnings") or []),
                        ]
                    )
                    + " |"
                )
    formula_review_matrix = payload.get("formula_review_matrix") or []
    if formula_review_matrix:
        lines.extend([
            "",
            "## Formula Review Matrix",
            "",
            "| Locator | Backend | Formulas | LaTeX/Markdown | BBox | Source/Crop | Confidence | Warnings |",
            "| --- | --- | ---: | ---: | --- | --- | --- | --- | --- | --- |",
        ])
        for page_matrix in formula_review_matrix:
            for row in page_matrix.get("rows") or []:
                lines.append(
                    "| "
                    + " | ".join(
                        escape_table(str(value))
                        for value in [
                            page_matrix.get("locator", ""),
                            row.get("backend", ""),
                            row.get("formula_count", 0),
                            yes_no(row.get("has_latex_or_markdown")),
                            yes_no(row.get("has_bbox")),
                            yes_no(row.get("has_source_ref") or row.get("has_crop")),
                            yes_no(row.get("has_confidence")),
                            ", ".join(row.get("warnings") or []),
                        ]
                    )
                    + " |"
                )
    lines.extend([
        "",
        "## Artifacts",
        "",
        "| Type | Backend | Status | Blocks | Tables | Formulas | Path |",
        "| --- | --- | --- | ---: | ---: | ---: | --- |",
    ])
    for item in payload.get("artifact_summaries") or []:
        summary_item = item.get("summary") or {}
        lines.append(
            "| "
            + " | ".join(
                escape_table(str(value))
                for value in [
                    item.get("artifact_type", ""),
                    item.get("backend", ""),
                    item.get("status", ""),
                    summary_item.get("block_count", ""),
                    summary_item.get("table_count", ""),
                    summary_item.get("formula_count", ""),
                    f"`{item.get('path', '')}`",
                ]
            )
            + " |"
        )
    promotion_reviews = payload.get("promotion_reviews") or []
    if promotion_reviews:
        lines.extend([
            "",
            "## Promotion Gate Reviews",
            "",
            "| Backend | Decision | Gate Status | Evidence | Score | Reasons | Scorecard |",
            "| --- | --- | --- | ---: | ---: | --- | --- |",
        ])
        for review in promotion_reviews:
            gate = review.get("promotion_gate") or {}
            signals = review.get("quality_signals") or {}
            lines.append(
                "| "
                + " | ".join(
                    escape_table(str(value))
                    for value in [
                        review.get("backend", ""),
                        gate.get("decision", ""),
                        gate.get("status", ""),
                        gate.get("evidence_count", signals.get("evidence_count", "")),
                        review.get("recommendation_score", ""),
                        "; ".join(str(reason) for reason in gate.get("reasons") or []),
                        f"`{review.get('scorecard_path', '')}`",
                    ]
                )
                + " |"
            )
    lines.extend(["", "## Next Actions", ""])
    for action in payload.get("next_actions") or []:
        lines.append(f"- {action.get('action')}: {action.get('why')}")
    return "\n".join(lines).rstrip() + "\n"

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


def escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def yes_no(value: Any) -> str:
    return "yes" if bool(value) else "no"


if __name__ == "__main__":
    raise SystemExit(main())
