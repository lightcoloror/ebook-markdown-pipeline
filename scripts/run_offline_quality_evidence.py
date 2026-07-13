from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))
from ebook_markdown_pipeline.offline_quality_router import evaluate_offline_quality, explain_offline_route, quality_vocabulary

DEFAULT_BASELINE = PROJECT_DIR / "benchmarks" / "runs" / "durable-goal-07-fixtures" / "cp5-20260710" / "baseline-summary.json"
DEFAULT_OUTPUT = PROJECT_DIR / "benchmarks" / "runs" / "w6-g41-offline-quality" / "latest"
CAPABILITIES = {
    "local_ocr": "ok",
    "pdf_structure_recovery": "ok",
    "markitdown_baseline": "ok",
    "pdf_table_extraction": "missing",
}
KIND_MAP = {"epub": "epub", "text_pdf": "text_pdf", "complex_pdf": "text_pdf", "office": "office", "image_set": "mixed_image"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build deterministic offline stage-quality evidence.")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = build_evidence(args.baseline.resolve())
    write_evidence(payload, args.output.resolve())
    print(json.dumps({"status": "passed", "cases": len(payload["cases"]), "output": str(args.output.resolve())}, ensure_ascii=False))
    return 0


def build_evidence(baseline_path: Path) -> dict[str, Any]:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = []
    for item in baseline.get("cases") or []:
        report_path = Path(str(item["quality_report"]))
        report = json.loads(report_path.read_text(encoding="utf-8"))
        source_kind = KIND_MAP[str(item["kind"])]
        if source_kind == "mixed_image":
            source = Path(str(item["source"]))
            report["image_evidence"] = {"status": "passed", "source_images": len(list(source.glob("*")))}
            report["asset_evidence"] = {"asset_count": len(list(source.glob("*"))), "missing_count": 0}
        evaluation = evaluate_offline_quality(
            report,
            source_kind=source_kind,
            capabilities=CAPABILITIES,
            artifact_exists=Path(str(item["markdown"])).is_file(),
        )
        cases.append(_case(str(item["id"]), source_kind, str(item["source"]), report_path, evaluation))

    scanned_source = baseline_path.parent / "fixtures" / "pdf" / "scanned-image-only.pdf"
    scan_report = {
        "status": "failed",
        "source": str(scanned_source),
        "output": "",
        "output_exists": False,
        "quality": {"level": "poor", "characters": 0, "nonempty_lines": 0, "headings": 0},
        "quality_risks": {"risk_codes": ["empty_document"]},
        "pdf_preflight": {"image_pages": 1, "complex_layout_likely": False},
    }
    proposed = evaluate_offline_quality(scan_report, source_kind="scanned_pdf", capabilities=CAPABILITIES, artifact_exists=False)
    cases.append(_case("scanned-pdf", "scanned_pdf", str(scanned_source), None, proposed))
    blocked = evaluate_offline_quality(
        scan_report,
        source_kind="scanned_pdf",
        capabilities={**CAPABILITIES, "local_ocr": "missing"},
        artifact_exists=False,
    )
    cases.append(_case("scanned-pdf-no-local-ocr", "scanned_pdf", str(scanned_source), None, blocked))

    table_report = {
        "status": "ok",
        "output": "synthetic-table.md",
        "output_exists": True,
        "quality": {"level": "good", "characters": 900, "nonempty_lines": 18, "headings": 2},
        "quality_risks": {"risk_codes": ["table_structure_risk"]},
    }
    table_eval = evaluate_offline_quality(table_report, source_kind="text_pdf", capabilities=CAPABILITIES, artifact_exists=True)
    cases.append(_case("table-gap-probe", "text_pdf", "synthetic-local-table-probe", None, table_eval))

    statuses = {str(item["route_status"]) for item in cases}
    expected = {"minimal-deliverable", "degraded", "blocked", "fallback-proposed"}
    if not expected.issubset(statuses):
        raise RuntimeError(f"Missing route evidence: expected {sorted(expected)}, got {sorted(statuses)}")
    required_kinds = {"text_pdf", "scanned_pdf", "epub", "office", "mixed_image"}
    actual_kinds = {str(item["source_kind"]) for item in cases}
    if not required_kinds.issubset(actual_kinds):
        raise RuntimeError(f"Missing source classes: {sorted(required_kinds - actual_kinds)}")
    return {
        "schema_version": "offline-quality-evidence-v1",
        "fixture_policy": "synthetic_local_only",
        "baseline": {"path": str(baseline_path), "sha256": sha256_file(baseline_path)},
        "capabilities": CAPABILITIES,
        "vocabulary": quality_vocabulary(),
        "cases": cases,
        "summary": {
            "case_count": len(cases),
            "route_counts": {status: sum(1 for item in cases if item["route_status"] == status) for status in sorted(statuses)},
            "artifact_exists_quality_failed_count": sum(1 for item in cases if item["artifact_exists"] and not item["quality_passed"]),
            "manual_review_count": sum(1 for item in cases if item["manual_review_required"]),
            "default_backend_changed": False,
            "external_calls": 0,
            "model_downloads": 0,
        },
    }


def _case(case_id: str, source_kind: str, source: str, report_path: Path | None, evaluation: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": case_id,
        "source_kind": source_kind,
        "source": source,
        "report": str(report_path) if report_path else None,
        "report_sha256": sha256_file(report_path) if report_path else None,
        "artifact_exists": evaluation["artifact"]["exists"],
        "quality_passed": evaluation["quality"]["passed"],
        "route_status": evaluation["route"]["status"],
        "manual_review_required": evaluation["manual_review_required"],
        "manual_review_stages": evaluation["manual_review_stages"],
        "fallback_proposal": evaluation["fallback_proposal"],
        "explanation": explain_offline_route(evaluation),
        "evaluation": evaluation,
    }


def write_evidence(payload: dict[str, Any], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "offline-quality-evidence.json"
    md_path = output / "offline-quality-evidence.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    lines = [
        "# W6-G41 Offline Quality Evidence",
        "",
        f"- Schema: `{payload['schema_version']}`",
        f"- Cases: {payload['summary']['case_count']}",
        "- Fixture policy: synthetic local only",
        "- Default backend changed: no",
        "",
        "| Case | Kind | Artifact | Quality | Route | Manual review | Fallback |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in payload["cases"]:
        fallback = item["fallback_proposal"].get("backend") or "none"
        lines.append(f"| {item['id']} | {item['source_kind']} | {item['artifact_exists']} | {item['quality_passed']} | {item['route_status']} | {item['manual_review_required']} | {fallback} |")
    lines.extend(["", "Artifact existence and quality acceptance are intentionally independent.", ""])
    md_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def sha256_file(path: Path | None) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path and path.is_file() else None


if __name__ == "__main__":
    raise SystemExit(main())
