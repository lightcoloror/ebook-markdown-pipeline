from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ebook-quality-gate-") as tmp:
        root = Path(tmp)
        fixtures = root / "fixtures"
        output = root / "quality-run"
        run("generate_quality_fixtures.py", "--output", str(fixtures))
        minimal = json.loads((fixtures / "quality-minimal.json").read_text(encoding="utf-8"))
        full = json.loads((fixtures / "quality-full.json").read_text(encoding="utf-8"))
        if len(minimal.get("samples") or []) < 5:
            raise AssertionError(f"Expected minimal fixture samples: {minimal}")
        if len(full.get("samples") or []) <= len(minimal.get("samples") or []):
            raise AssertionError(f"Expected full profile to include extra OCR/image samples: {full}")
        required_full_categories = {
            "ebook_epub",
            "ebook_azw3_substitute",
            "pdf_text_layer",
            "pdf_bookmarked_outline",
            "pdf_two_column",
            "pdf_presentation_like",
            "pdf_table",
            "scanned_pdf",
            "image_infographic",
            "image_set_duplicates",
            "image_ocr_english",
            "image_ocr_chinese",
            "image_ocr_lowres",
            "image_ocr_infographic",
        }
        full_categories = {str(item.get("category") or "") for item in full.get("samples") or []}
        missing_categories = required_full_categories.difference(full_categories)
        if missing_categories:
            raise AssertionError(
                f"Full public fixture profile missing required categories {sorted(missing_categories)}: {sorted(full_categories)}"
            )
        minimal_categories = {str(item.get("category") or "") for item in minimal.get("samples") or []}
        if "pdf_bookmarked_outline" not in minimal_categories:
            raise AssertionError(f"Minimal public fixture profile must include PDF bookmark coverage: {minimal_categories}")
        repository_full = json.loads((PROJECT_DIR / "benchmarks" / "fixtures" / "generated" / "quality-full.json").read_text(encoding="utf-8"))
        repository_paths = [str(item.get("path") or "") for item in repository_full.get("samples") or []]
        if any(Path(path).is_absolute() for path in repository_paths):
            raise AssertionError(f"Repository fixture manifests must use repository-relative paths: {repository_paths}")

        run(
            "run_quality_gate.py",
            "--profile",
            "minimal",
            "--fixtures-dir",
            str(fixtures),
            "--output",
            str(output),
            "--reuse-fixtures",
            "--sample-timeout",
            "60",
        )
        payload = json.loads((output / "benchmark-results.json").read_text(encoding="utf-8"))
        gates = ((payload.get("summary") or {}).get("quality_gates") or {})
        if gates.get("status") != "passed":
            raise AssertionError(f"Expected passing quality gate: {gates}")
        bookmarked = next((item for item in payload.get("results") or [] if item.get("category") == "pdf_bookmarked_outline"), None)
        if not bookmarked:
            raise AssertionError(f"Expected PDF bookmark fixture result: {payload}")
        bookmark_ratio = float((bookmarked.get("metrics") or {}).get("toc_match_ratio") or 0)
        if bookmark_ratio <= 0:
            raise AssertionError(f"Expected PDF bookmark fixture to produce TOC/bookmark match signal: {bookmarked}")
        quality_json = output / "quality-regression-summary.json"
        quality_md = output / "quality-regression-summary.md"
        if not quality_md.exists() or not quality_json.exists():
            raise AssertionError("Expected quality-regression-summary.md")
        quality_payload = json.loads(quality_json.read_text(encoding="utf-8"))
        summary = quality_payload.get("summary") or {}
        required_summary_fields = {
            "avg_headings",
            "avg_toc_match_ratio",
            "page_heading_ratio",
            "ocr_characters",
            "table_retention_ratio",
            "expected_table_like_lines",
            "table_like_lines",
            "structure_repair_decisions",
            "structure_repair_promoted",
            "structure_repair_low_confidence",
            "review_or_poor",
            "avg_duration_seconds",
            "max_duration_seconds",
        }
        missing = required_summary_fields.difference(summary)
        if missing:
            raise AssertionError(f"Quality regression summary missing required metrics {sorted(missing)}: {summary}")
        quality_text = quality_md.read_text(encoding="utf-8")
        for needle in ["Average TOC match ratio", "OCR characters", "Table retention ratio", "Structure repair decisions", "Average duration seconds", "Review or poor"]:
            if needle not in quality_text:
                raise AssertionError(f"Quality regression Markdown missing {needle}: {quality_text}")
    print("Quality gate smoke test passed.")
    return 0


def run(script: str, *args: str) -> None:
    subprocess.run([sys.executable, str(PROJECT_DIR / "scripts" / script), *args], cwd=PROJECT_DIR, check=True)


if __name__ == "__main__":
    raise SystemExit(main())
