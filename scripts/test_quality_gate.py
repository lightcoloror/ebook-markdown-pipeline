from __future__ import annotations

import argparse
import importlib.util
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

        quality_gate_module = load_run_quality_gate()
        existing_manifest = fixtures / "quality-minimal.json"
        missing_manifest = root / "missing-fixtures" / "quality-minimal.json"
        if quality_gate_module.should_generate_fixtures(argparse.Namespace(regenerate_fixtures=False, reuse_fixtures=False), existing_manifest):
            raise AssertionError("Existing public fixtures should be reused by default.")
        if not quality_gate_module.should_generate_fixtures(argparse.Namespace(regenerate_fixtures=False, reuse_fixtures=False), missing_manifest):
            raise AssertionError("Missing public fixtures should be generated by default.")
        if not quality_gate_module.should_generate_fixtures(argparse.Namespace(regenerate_fixtures=True, reuse_fixtures=True), existing_manifest):
            raise AssertionError("--regenerate-fixtures should force fixture generation.")
        backend_output = root / "backend-compare"
        manifest = fixtures / "quality-minimal.json"
        seen_modes: list[tuple[str, str, Path]] = []
        original_run = quality_gate_module.run

        def fake_run(command: list[str], *, check: bool = True):
            script = Path(command[1]).name if len(command) > 1 else ""
            if script == "run_benchmarks.py":
                output_dir = Path(command[command.index("--output") + 1])
                pdf_mode = command[command.index("--pdf-mode-for-benchmark") + 1]
                document_mode = command[command.index("--document-mode-for-benchmark") + 1]
                seen_modes.append((pdf_mode, document_mode, output_dir))
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "quality-regression-summary.json").write_text(
                    json.dumps(
                        {
                            "schema_version": "quality-regression-summary-v1",
                            "summary": {"total": 1, "scored": 1, "status_counts": {"ok": 1}, "review_or_poor": 0},
                        }
                    ),
                    encoding="utf-8",
                )
                (output_dir / "quality-regression-summary.md").write_text("# Quality\n", encoding="utf-8")
            elif script == "compare_benchmark_quality.py":
                output_dir = Path(command[command.index("--output") + 1])
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "benchmark-quality-comparison.json").write_text("{}", encoding="utf-8")
                (output_dir / "benchmark-quality-comparison.md").write_text("# Compare\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0)

        quality_gate_module.run = fake_run
        try:
            exit_code = quality_gate_module.run_backend_compare(
                argparse.Namespace(
                    profile="backend-compare",
                    sample_timeout=60.0,
                    pdf_mode_for_benchmark="fast",
                    document_mode_for_benchmark="auto",
                    min_success_rate=0.95,
                    min_good_rate=0.30,
                    max_review_poor_rate=0.70,
                    max_timeout_rate=0.0,
                    max_failed_rate=0.0,
                    no_fail_on_quality_gate=True,
                ),
                manifest,
                backend_output,
            )
        finally:
            quality_gate_module.run = original_run
        if exit_code != 0:
            raise AssertionError(f"Expected backend compare fake run to pass: {exit_code}")
        expected_modes = [("fast", "auto", backend_output / "baseline"), ("markitdown", "markitdown", backend_output / "markitdown")]
        if seen_modes != expected_modes:
            raise AssertionError(f"Backend compare should run baseline then MarkItDown candidate: {seen_modes}")
        if not (backend_output / "backend-comparison" / "benchmark-quality-comparison.md").exists():
            raise AssertionError("Backend compare should write benchmark-quality-comparison.md")

        release_output = root / "release"
        release_calls: list[str] = []

        def fake_release_run(command: list[str], *, check: bool = True):
            script = Path(command[1]).name if len(command) > 1 else ""
            release_calls.append(script)
            if script == "run_benchmarks.py":
                output_dir = Path(command[command.index("--output") + 1])
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "quality-regression-summary.json").write_text(
                    json.dumps(
                        {
                            "schema_version": "quality-regression-summary-v1",
                            "summary": {"total": 1, "scored": 1, "status_counts": {"ok": 1}, "review_or_poor": 0},
                        }
                    ),
                    encoding="utf-8",
                )
                (output_dir / "quality-regression-summary.md").write_text("# Quality\n", encoding="utf-8")
            elif script == "compare_benchmark_quality.py":
                output_dir = Path(command[command.index("--output") + 1])
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "benchmark-quality-comparison.json").write_text(
                    json.dumps({"summary": {"status": "failed", "regression_tags": ["duration_regression"], "deltas": {}}}),
                    encoding="utf-8",
                )
                (output_dir / "benchmark-quality-comparison.md").write_text("# Compare\n", encoding="utf-8")
            elif script == "compare_ocr_providers.py":
                output_dir = Path(command[command.index("--output") + 1])
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "ocr-provider-comparison.md").write_text("# OCR\n", encoding="utf-8")
            elif script == "test_docs_contract.py":
                pass
            elif script == "check_public_release.py":
                if "--run-smoke" not in command:
                    raise AssertionError(f"Release public check should run minimal smoke: {command}")
                output_dir = Path(command[command.index("--output") + 1])
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "public-release-check.md").write_text("# Public\n", encoding="utf-8")
            else:
                raise AssertionError(f"Unexpected release command: {command}")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        quality_gate_module.run = fake_release_run
        try:
            release_code = quality_gate_module.run_release_profile(
                argparse.Namespace(
                    profile="release",
                    sample_timeout=60.0,
                    pdf_mode_for_benchmark="fast",
                    document_mode_for_benchmark="auto",
                    min_success_rate=0.95,
                    min_good_rate=0.30,
                    max_review_poor_rate=0.70,
                    max_timeout_rate=0.0,
                    max_failed_rate=0.0,
                    no_fail_on_quality_gate=True,
                ),
                fixtures,
                release_output,
            )
        finally:
            quality_gate_module.run = original_run
        if release_code != 0:
            raise AssertionError(f"Expected release fake run to pass: {release_code}")
        for expected in ["run_benchmarks.py", "compare_benchmark_quality.py", "compare_ocr_providers.py", "test_docs_contract.py", "check_public_release.py"]:
            if expected not in release_calls:
                raise AssertionError(f"Release profile did not call {expected}: {release_calls}")
        if not (release_output / "release-summary.json").exists() or not (release_output / "release-summary.md").exists():
            raise AssertionError("Release profile should write release-summary.json/md")
        release_payload = json.loads((release_output / "release-summary.json").read_text(encoding="utf-8"))
        if release_payload.get("regression_tags") != ["duration_regression"]:
            raise AssertionError(f"Release profile should surface regression tags: {release_payload}")
        release_markdown = (release_output / "release-summary.md").read_text(encoding="utf-8")
        if "Regression tags: duration_regression" not in release_markdown:
            raise AssertionError(f"Release Markdown should surface regression tags: {release_markdown}")
    print("Quality gate smoke test passed.")
    return 0


def run(script: str, *args: str) -> None:
    subprocess.run([sys.executable, str(PROJECT_DIR / "scripts" / script), *args], cwd=PROJECT_DIR, check=True)


def load_run_quality_gate():
    path = PROJECT_DIR / "scripts" / "run_quality_gate.py"
    spec = importlib.util.spec_from_file_location("run_quality_gate", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    raise SystemExit(main())
