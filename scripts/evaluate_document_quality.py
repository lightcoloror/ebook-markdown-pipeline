from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "document-quality-evaluation-v1"
DIMENSIONS = ("text", "table", "formula", "layout", "reading_order")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate existing review evidence without running models or converters.")
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    bundle = load_json(args.bundle)
    reference = load_json(args.reference) if args.reference else {}
    payload = build_quality_evaluation(bundle, reference, bundle_path=args.bundle)
    write_quality_evaluation(args.output, payload)
    print(json.dumps({"status": "ok", "output": str(args.output), "backend_count": payload["summary"]["backend_count"]}, ensure_ascii=False))
    return 0


def load_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    return value if isinstance(value, dict) else {}


def build_quality_evaluation(bundle: dict[str, Any], reference: dict[str, Any] | None = None, *, bundle_path: Path | None = None) -> dict[str, Any]:
    reference = reference if isinstance(reference, dict) else {}
    expected = reference.get("dimensions") if isinstance(reference.get("dimensions"), dict) else {}
    evidence = collect_backend_evidence(bundle)
    rows = [evaluate_backend(backend, values, expected) for backend, values in sorted(evidence.items())]
    evaluated = sum(sum(1 for item in row["dimensions"].values() if item["status"] == "evaluated") for row in rows)
    not_evaluated = sum(sum(1 for item in row["dimensions"].values() if item["status"] == "not_evaluated") for row in rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "execution_policy": "offline_evidence_only_no_model_execution_no_service_start",
        "source_bundle": str(bundle_path) if bundle_path else "",
        "reference_schema_version": reference.get("schema_version") or "",
        "overall_score": None,
        "backend_evaluations": rows,
        "summary": {"backend_count": len(rows), "evaluated_dimension_count": evaluated, "not_evaluated_dimension_count": not_evaluated, "overall_score_emitted": False},
    }


def collect_backend_evidence(bundle: dict[str, Any]) -> dict[str, dict[str, int]]:
    evidence: dict[str, dict[str, int]] = {}
    def row(backend: str) -> dict[str, int]:
        return evidence.setdefault(backend, {"markdown_char_count": 0, "table_count": 0, "formula_count": 0, "block_count": 0, "reading_order_count": 0})
    for item in bundle.get("artifact_summaries") or []:
        if not isinstance(item, dict) or not item.get("backend"):
            continue
        summary = item.get("summary") if isinstance(item.get("summary"), dict) else {}
        target = row(str(item["backend"]))
        for key in target:
            target[key] += int(summary.get(key) or 0)
    for matrix_key, signal in (("table_review_matrix", "table_count"), ("formula_review_matrix", "formula_count")):
        for matrix in bundle.get(matrix_key) or []:
            if not isinstance(matrix, dict):
                continue
            for item in matrix.get("rows") or []:
                if isinstance(item, dict) and item.get("backend"):
                    row(str(item["backend"]))[signal] += int(item.get(signal) or 0)
    return evidence


def evaluate_backend(backend: str, values: dict[str, int], expected: dict[str, Any]) -> dict[str, Any]:
    dimensions: dict[str, dict[str, Any]] = {}
    for dimension in DIMENSIONS:
        spec = expected.get(dimension) if isinstance(expected.get(dimension), dict) else None
        metric = {"text": "markdown_char_count", "table": "table_count", "formula": "formula_count", "layout": "block_count", "reading_order": "reading_order_count"}[dimension]
        if not spec or "minimum" not in spec:
            dimensions[dimension] = {"status": "not_evaluated", "reason": "reference_missing", "metric": metric, "actual": values.get(metric, 0)}
            continue
        minimum = int(spec.get("minimum") or 0)
        actual = int(values.get(metric) or 0)
        dimensions[dimension] = {"status": "evaluated", "metric": metric, "actual": actual, "minimum": minimum, "passed": actual >= minimum}
    return {"backend": backend, "status": "review" if any(item["status"] == "evaluated" for item in dimensions.values()) else "not_evaluated", "dimensions": dimensions}


def write_quality_evaluation(output: Path, payload: dict[str, Any]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "document-quality-evaluation.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    lines = ["# Document Quality Evaluation", "", "| Backend | Text | Table | Formula | Layout | Reading order |", "| --- | --- | --- | --- | --- | --- |"]
    for row in payload["backend_evaluations"]:
        lines.append("| " + " | ".join([str(row["backend"]), *(str(row["dimensions"][name]["status"]) for name in DIMENSIONS)]) + " |")
    lines.extend(["", "No overall score is emitted; missing references remain not_evaluated.", ""])
    (output / "document-quality-evaluation.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    raise SystemExit(main())