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


SCHEMA_VERSION = "optional-backend-scorecard-v1"
DEFAULT_OUTPUT = PROJECT_DIR / "benchmarks" / "runs" / "backend-scorecard"


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
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an optional backend availability and recommendation scorecard.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT / time.strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--fast", action="store_true", default=True, help="Skip expensive version/model probes. Enabled by default.")
    args = parser.parse_args()

    options = normalize_command_options(default_options())
    checks = dependency_health_report([], options, fast=bool(args.fast))
    capabilities = environment_capability_summary(checks)
    payload = build_scorecard(checks, capabilities, output=args.output)
    write_scorecard(args.output, payload)
    print(json.dumps({"status": payload["summary"]["status"], "output": str(args.output), "backend_count": len(payload["backends"])}, ensure_ascii=False))
    return 0


def build_scorecard(checks: list[dict[str, str]], capabilities: list[dict[str, str]], *, output: Path | None = None) -> dict[str, Any]:
    check_by_name = {str(item.get("name") or "").lower(): item for item in checks}
    capability_by_name = {str(item.get("name") or "").lower(): item for item in capabilities}
    backends = [score_backend(profile, check_by_name, capability_by_name) for profile in BACKENDS]
    summary = summarize_backends(backends)
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "output": str(output) if output else "",
        "summary": summary,
        "backends": backends,
    }


def score_backend(
    profile: BackendProfile,
    check_by_name: dict[str, dict[str, str]],
    capability_by_name: dict[str, dict[str, str]],
) -> dict[str, Any]:
    health_records = [check_by_name.get(name.lower()) for name in profile.health_names]
    health_records = [item for item in health_records if item]
    capability_records = [capability_by_name.get(name.lower()) for name in profile.capability_names]
    capability_records = [item for item in capability_records if item]
    status = combined_status(health_records + capability_records)
    score = recommendation_score(status, profile.install_cost, profile.default_policy)
    return {
        **asdict(profile),
        "status": status,
        "recommendation_score": score,
        "recommendation": recommendation_text(status, score, profile.default_policy),
        "health": health_records,
        "capabilities": capability_records,
    }


def combined_status(records: list[dict[str, str]]) -> str:
    statuses = {str(item.get("status") or "missing") for item in records}
    if "ok" in statuses:
        return "ok"
    if statuses.intersection({"degraded", "warning", "caution"}):
        return "degraded"
    return "missing"


def recommendation_score(status: str, install_cost: str, policy: str) -> int:
    score = {"ok": 55, "degraded": 35, "missing": 10}.get(status, 10)
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
    if score >= 75:
        return "safe to expose as recommended/manual follow-up when matching risks are detected"
    if score >= 55:
        return "keep as optional comparison or diagnostic backend"
    return f"keep explicit only: {policy}"


def summarize_backends(backends: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for item in backends:
        status = str(item.get("status") or "missing")
        counts[status] = counts.get(status, 0) + 1
    return {
        "status": "ok",
        "backend_count": len(backends),
        "status_counts": counts,
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
        "",
        "| Backend | Status | Score | Role | Best For | Cost | GPU/Model | Default Policy | Recommendation |",
        "| --- | --- | ---: | --- | --- | --- | --- | --- | --- |",
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
    lines.extend(["", "Missing optional backends do not fail the minimal install or release gate. Promote a backend only after fixture evidence shows quality improvement."])
    return "\n".join(lines).rstrip() + "\n"


def escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


if __name__ == "__main__":
    raise SystemExit(main())
