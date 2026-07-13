from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.batch_convert_books import analyze_markdown_quality, deterministic_quality_risks  # noqa: E402
from ebook_markdown_pipeline.image_book_rebuilder import rebuild_image_book  # noqa: E402
from ebook_markdown_pipeline.artifact_schema import material_consumer_contract  # noqa: E402


SCHEMA_VERSION = "durable-fixture-baseline-v1"


def baseline_case_specs(fixtures: Path) -> list[dict[str, object]]:
    return [
        {
            "id": "epub",
            "kind": "epub",
            "source": fixtures / "ebooks" / "sample.epub",
            "arguments": ["--no-calibre-fallback"],
        },
        {
            "id": "text-pdf",
            "kind": "text_pdf",
            "source": fixtures / "pdf" / "text-layer.pdf",
            "arguments": ["--pdf-pipeline-mode", "pymupdf4llm"],
        },
        {
            "id": "complex-pdf",
            "kind": "complex_pdf",
            "source": fixtures / "pdf" / "two-column.pdf",
            "arguments": ["--pdf-pipeline-mode", "pymupdf4llm"],
        },
        {
            "id": "office-docx",
            "kind": "office",
            "source": fixtures / "office" / "sample.docx",
            "arguments": ["--document-pipeline-mode", "markitdown"],
        },
        {
            "id": "image-set",
            "kind": "image_set",
            "source": fixtures / "images" / "screenshots",
            "arguments": [],
        },
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the five non-sensitive durable-goal fixture baselines.")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_DIR / "benchmarks" / "runs" / "durable-goal-07-fixtures" / "latest",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    run_root = args.output.resolve()
    fixtures = run_root / "fixtures"
    run_root.mkdir(parents=True, exist_ok=True)
    generate_fixtures(fixtures, timeout_seconds=args.timeout)

    records: list[dict[str, object]] = []
    for spec in baseline_case_specs(fixtures):
        if spec["kind"] == "image_set":
            records.append(run_image_case(spec, run_root))
        else:
            records.append(run_batch_case(spec, run_root, timeout_seconds=args.timeout))

    validate_records(records)
    handoff = build_material_handoff(records)
    handoff_json = run_root / "handoff-bundle.json"
    handoff_markdown = run_root / "handoff-bundle.md"
    handoff_json.write_text(json.dumps(handoff, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    handoff_markdown.write_text(render_handoff_markdown(handoff), encoding="utf-8", newline="\n")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "fixture_policy": "synthetic_local_only",
        "model_downloads_allowed": False,
        "external_api_calls_allowed": False,
        "cases": records,
        "handoff": {"json": str(handoff_json), "markdown": str(handoff_markdown), "consumer_contract": handoff["consumer_contract"]},
        "summary": {
            "case_count": len(records),
            "passed": sum(1 for item in records if item.get("status") == "passed"),
            "kinds": [item["kind"] for item in records],
        },
    }
    json_path = run_root / "baseline-summary.json"
    markdown_path = run_root / "baseline-summary.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8", newline="\n")
    print(json.dumps({"status": "passed", "summary": str(json_path), "markdown": str(markdown_path), "handoff_json": str(handoff_json), "handoff_markdown": str(handoff_markdown)}, ensure_ascii=False))
    return 0


def generate_fixtures(fixtures: Path, *, timeout_seconds: float) -> None:
    command = [
        sys.executable,
        "-B",
        str(PROJECT_DIR / "scripts" / "generate_quality_fixtures.py"),
        "--output",
        str(fixtures),
    ]
    completed = subprocess.run(
        command,
        cwd=PROJECT_DIR,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Fixture generation failed:\n{completed.stdout}\n{completed.stderr}")


def run_batch_case(spec: dict[str, object], run_root: Path, *, timeout_seconds: float) -> dict[str, object]:
    case_id = str(spec["id"])
    source = Path(spec["source"])
    output = run_root / case_id
    manifest = output / "manifest.json"
    summary = output / ".reports" / "summary.md"
    command = [
        sys.executable,
        "-B",
        str(PROJECT_DIR / "batch_convert_books.py"),
        str(source),
        str(output),
        "--manifest",
        str(manifest),
        "--summary",
        str(summary),
        "--overwrite",
        *[str(item) for item in spec.get("arguments") or []],
    ]
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=PROJECT_DIR,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    elapsed = round(time.monotonic() - started, 3)
    if completed.returncode != 0:
        raise RuntimeError(f"{case_id} failed:\n{completed.stdout}\n{completed.stderr}")
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    if len(manifest_payload) != 1:
        raise RuntimeError(f"Expected one manifest result for {case_id}: {manifest_payload}")
    result = manifest_payload[0]
    markdown = Path(str(result.get("output") or ""))
    report = Path(str(result.get("report") or ""))
    if not report.is_file():
        candidates = sorted((output / ".reports").glob("*.report.json"))
        report = candidates[0] if candidates else report
    report_payload = json.loads(report.read_text(encoding="utf-8")) if report.is_file() else {}
    return record_for_case(
        spec,
        source=source,
        output_root=output,
        markdown=markdown,
        manifest=manifest,
        report=report,
        backend=str(result.get("pipeline") or "unknown"),
        duration_seconds=float(result.get("duration_seconds") or elapsed),
        quality=report_payload.get("quality") or {},
        warnings=warning_evidence(result, report_payload),
    )


def run_image_case(spec: dict[str, object], run_root: Path) -> dict[str, object]:
    source = Path(spec["source"])
    output = run_root / str(spec["id"])
    started = time.monotonic()
    result = rebuild_image_book(
        source,
        output,
        ocr_mode="never",
        auto_split_long_images=False,
        enhance_layout_heavy="never",
    )
    elapsed = round(time.monotonic() - started, 3)
    markdown = Path(str(result["book"]))
    manifest = output / "manifest.json"
    report_dir = output / ".reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report = report_dir / "image-set.report.json"
    quality = analyze_markdown_quality(markdown)
    quality_payload = asdict(quality) if quality is not None else {}
    manifest_payload = [
        {
            "source": str(source),
            "output": str(markdown),
            "status": "converted",
            "pipeline": "image_book_rebuilder_no_ocr",
            "duration_seconds": elapsed,
            "message": "OCR and layout enhancement disabled by durable-goal boundary.",
        }
    ]
    manifest.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    report.write_text(
        json.dumps(
            {
                "schema_version": "image-book-quality-report-v1",
                "source": str(source),
                "output": str(markdown),
                "quality": quality_payload,
                "quality_risks": deterministic_quality_risks(quality_payload),
                "source_count": result.get("source_count"),
                "page_count": result.get("page_count"),
                "warnings": ["ocr_disabled_by_contract", "layout_enhancement_disabled_by_contract"],
                "artifacts": result.get("artifacts") or [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
        newline="\n",
    )
    return record_for_case(
        spec,
        source=source,
        output_root=output,
        markdown=markdown,
        manifest=manifest,
        report=report,
        backend="image_book_rebuilder_no_ocr",
        duration_seconds=elapsed,
        quality=quality_payload,
        warnings=["ocr_disabled_by_contract", "layout_enhancement_disabled_by_contract"],
    )


def record_for_case(
    spec: dict[str, object],
    *,
    source: Path,
    output_root: Path,
    markdown: Path,
    manifest: Path,
    report: Path,
    backend: str,
    duration_seconds: float,
    quality: dict[str, object],
    warnings: list[str],
) -> dict[str, object]:
    return {
        "id": spec["id"],
        "kind": spec["kind"],
        "status": "passed" if markdown.is_file() and manifest.is_file() and report.is_file() else "failed",
        "source": str(source),
        "source_sha256": sha256_path(source),
        "backend": backend,
        "duration_seconds": duration_seconds,
        "file_count": sum(1 for item in output_root.rglob("*") if item.is_file()),
        "warnings": warnings,
        "quality": quality,
        "markdown": str(markdown),
        "manifest": str(manifest),
        "quality_report": str(report),
    }


def warning_evidence(result: dict[str, object], report: dict[str, object]) -> list[str]:
    warnings: list[str] = []
    message = str(result.get("message") or "").strip()
    if message and message.lower() not in {"converted", "ok"}:
        warnings.append(message)
    for key in ("pdf_fallback_diagnostics", "docling_diagnostics", "markitdown_diagnostics", "calibre_fallback_diagnostics"):
        if report.get(key):
            warnings.append(f"{key}={len(report[key])}")
    return warnings


def build_material_handoff(records: list[dict[str, object]]) -> dict[str, object]:
    cases = []
    for item in records:
        cases.append(
            {
                "id": item.get("id"),
                "kind": item.get("kind"),
                "status": item.get("status"),
                "backend": item.get("backend"),
                "source_sha256": item.get("source_sha256"),
                "artifacts": [
                    {"type": "markdown", "path": item.get("markdown")},
                    {"type": "json", "path": item.get("manifest")},
                    {"type": "conversion_report", "path": item.get("quality_report")},
                ],
            }
        )
    return {
        "schema_version": "material-handoff-bundle-v1",
        "status": "ready" if all(item.get("status") == "passed" for item in records) else "needs_review",
        "consumer_contract": material_consumer_contract(),
        "cases": cases,
    }


def render_handoff_markdown(payload: dict[str, object]) -> str:
    consumer = payload.get("consumer_contract") or {}
    lines = [
        "# Material Handoff Bundle",
        "",
        f"- Status: `{payload.get('status')}`",
        f"- Consumers: {', '.join(consumer.get('supported_consumers') or [])}",
        "- Transfer: local artifact refs only; no network transfer",
        "",
    ]
    for item in payload.get("cases") or []:
        lines.append(f"## {item.get('kind')}")
        lines.append("")
        lines.append(f"- Backend: `{item.get('backend')}`")
        for artifact_item in item.get("artifacts") or []:
            lines.append(f"- {artifact_item.get('type')}: `{artifact_item.get('path')}`")
        lines.append("")
    return "\n".join(lines)

def validate_records(records: list[dict[str, object]]) -> None:
    expected = {"epub", "text_pdf", "complex_pdf", "office", "image_set"}
    actual = {str(item.get("kind")) for item in records}
    if actual != expected:
        raise RuntimeError(f"Expected five fixture kinds {sorted(expected)}, got {sorted(actual)}")
    failed = [item for item in records if item.get("status") != "passed"]
    if failed:
        raise RuntimeError(f"Fixture baseline missing required artifacts: {failed}")


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_file():
        digest.update(path.read_bytes())
    else:
        for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
            digest.update(str(item.relative_to(path)).replace("/", "/").encode("utf-8"))
            digest.update(item.read_bytes())
    return digest.hexdigest()


def render_markdown(payload: dict[str, object]) -> str:
    lines = [
        "# Durable Goal 07 Fixture Baseline",
        "",
        f"- Status: `{payload['status']}`",
        f"- Policy: `{payload['fixture_policy']}`",
        "- Model downloads: disabled",
        "- External API calls: disabled",
        "",
        "| Kind | Backend | Seconds | Files | Quality | Warnings |",
        "| --- | --- | ---: | ---: | --- | --- |",
    ]
    for item in payload.get("cases") or []:
        quality = item.get("quality") or {}
        warnings = "; ".join(str(value) for value in item.get("warnings") or [])
        lines.append(
            f"| {item.get('kind')} | {item.get('backend')} | {item.get('duration_seconds')} | "
            f"{item.get('file_count')} | {quality.get('level', 'unknown')} ({quality.get('score', 'n/a')}) | {warnings} |"
        )
    lines.extend(["", "Each row links to a Markdown output, manifest, and quality report in `baseline-summary.json`.", ""])
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
