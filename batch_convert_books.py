from __future__ import annotations

import argparse
import contextlib
import hashlib
import html
import importlib.util
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable

try:
    from ebook_markdown_pipeline.docling_backend import DOCLING_FORMATS, convert_with_docling, docling_available
except ModuleNotFoundError:  # Allows running this file directly by absolute path.
    from docling_backend import DOCLING_FORMATS, convert_with_docling, docling_available


PANDOC_DIRECT_FORMATS = {".epub", ".fb2", ".odt", ".txt"}
CALIBRE_INTERMEDIATE_FORMATS = {".azw", ".azw3", ".mobi", ".rtf"}
CALIBRE_FALLBACK_FORMATS = {".epub", ".fb2", ".odt"}
EBOOK_DIRECT_FORMATS = PANDOC_DIRECT_FORMATS
EBOOK_NEEDS_CALIBRE_FORMATS = CALIBRE_INTERMEDIATE_FORMATS
PDF_FORMATS = {".pdf"}
DOCLING_PANDOC_FALLBACK_FORMATS = {".docx", ".html", ".htm", ".md"}
DOCLING_TEXT_FALLBACK_FORMATS = {".csv"}
SUPPORTED_FORMATS = PANDOC_DIRECT_FORMATS | CALIBRE_INTERMEDIATE_FORMATS | PDF_FORMATS | DOCLING_FORMATS

OUTPUT_FORMATS = {
    "markdown": {"suffix": ".md", "pandoc_target": "gfm"},
    "html": {"suffix": ".html", "pandoc_target": "html"},
    "text": {"suffix": ".txt", "pandoc_target": "plain"},
}

PDF_PIPELINE_MODES = ("auto", "marker", "mineru", "umi", "pymupdf4llm", "docling")

COMMON_WINDOWS_COMMAND_PATHS = {
    "pandoc": [
        Path(r"C:\Program Files\Pandoc\pandoc.exe"),
        Path(r"D:\ProgramData\anaconda3\Scripts\pandoc.exe"),
    ],
    "ebook-convert": [
        Path(r"C:\Program Files\Calibre2\ebook-convert.exe"),
        Path(r"C:\Program Files\Calibre\ebook-convert.exe"),
        Path(r"C:\Program Files (x86)\Calibre2\ebook-convert.exe"),
    ],
    "marker_single": [],
    "mineru": [],
}

DEFAULT_UMI_PLUGIN_DIR = Path(r"D:\Umi-OCR\Umi-OCR_Paddle_v2.1.5\UmiOCR-data\plugins\win7_x64_PaddleOCR-json")


@dataclass
class SourcePlan:
    source: str
    detected_format: str
    pipeline: str
    output: str
    output_format: str
    note: str = ""


@dataclass
class ConversionResult:
    source: str
    output: str | None
    status: str
    pipeline: str
    message: str
    detected_format: str = ""
    duration_seconds: float = 0.0
    started_at: str = ""
    finished_at: str = ""
    report: str | None = None


@dataclass
class MarkdownQuality:
    score: int
    level: str
    headings: int
    page_headings: int
    lines: int
    nonempty_lines: int
    characters: int
    page_number_lines: int
    footnote_like_lines: int
    html_tag_lines: int
    replacement_chars: int
    short_line_ratio: float
    repeated_noise_lines: int
    reasons: list[str]


@dataclass
class PdfPreflight:
    page_count: int
    sampled_pages: int
    bookmark_count: int
    text_page_ratio: float
    avg_text_chars: float
    avg_text_blocks: float
    image_page_ratio: float
    avg_image_area_ratio: float
    toc_like_pages: int
    table_like_pages: int
    two_column_like_pages: int
    scanned_likely: bool
    complex_layout_likely: bool
    recommended_pipeline: str
    reasons: list[str]


class PdfToolTimeoutError(RuntimeError):
    def __init__(self, message: str, diagnostic: dict[str, object]):
        super().__init__(message)
        self.diagnostic = diagnostic


class DoclingTimeoutError(RuntimeError):
    def __init__(self, message: str, diagnostic: dict[str, object]):
        super().__init__(message)
        self.diagnostic = diagnostic


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Batch convert EPUB/FB2/TXT/ODT/AZW/AZW3/MOBI/RTF/PDF with automatic format detection. "
            "Stable split pipeline: pandoc for structured ebooks/docs, calibre + pandoc for Kindle/RTF, MinerU for PDFs."
        )
    )
    parser.add_argument("input", type=Path, help="Input file or directory")
    parser.add_argument("output", type=Path, help="Output directory")
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Recursively scan the input directory",
    )
    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help="Include hidden files while scanning directories",
    )
    parser.add_argument(
        "--output-format",
        choices=sorted(OUTPUT_FORMATS),
        default="markdown",
        help="Target output format, default: markdown",
    )
    parser.add_argument(
        "--output-name-suffix",
        default="",
        help="Append a safe suffix to generated output filenames before the extension, for versioned reruns.",
    )
    parser.add_argument(
        "--pdf-pipeline-mode",
        choices=PDF_PIPELINE_MODES,
        default="auto",
        help="PDF conversion mode, default: auto",
    )
    parser.add_argument(
        "--markdown-format",
        default="gfm",
        help="Pandoc markdown target used when output-format=markdown, default: gfm",
    )
    parser.add_argument(
        "--marker-command",
        default="marker_single",
        help="PDF converter command for Marker, default: marker_single",
    )
    parser.add_argument(
        "--marker-extra-args",
        nargs="*",
        default=[],
        help="Extra arguments passed to the Marker command",
    )
    parser.add_argument(
        "--mineru-command",
        default="mineru",
        help="MinerU converter command, default: mineru",
    )
    parser.add_argument(
        "--mineru-extra-args",
        nargs="*",
        default=[],
        help="Extra arguments passed to the MinerU command",
    )
    parser.add_argument(
        "--mineru-method",
        choices=["auto", "txt", "ocr"],
        default="auto",
        help="MinerU PDF parse method, default: auto",
    )
    parser.add_argument(
        "--mineru-backend",
        default="pipeline",
        help="MinerU backend, default: pipeline",
    )
    parser.add_argument(
        "--mineru-lang",
        default="ch",
        help="MinerU OCR language, default: ch",
    )
    parser.add_argument(
        "--mineru-segment-min-pages",
        type=int,
        default=200,
        help="Use segmented MinerU processing for PDFs with at least this many pages; 0 disables. Default: 200.",
    )
    parser.add_argument(
        "--mineru-segment-pages",
        type=int,
        default=50,
        help="Pages per MinerU segment for long PDFs; 0 disables. Default: 50.",
    )
    parser.add_argument(
        "--calibre-command",
        default="ebook-convert",
        help="Calibre conversion command, default: ebook-convert",
    )
    parser.add_argument(
        "--no-calibre-fallback",
        action="store_true",
        help="Disable Calibre EPUB preprocessing fallback for weak Pandoc ebook output.",
    )
    parser.add_argument(
        "--pandoc-command",
        default="pandoc",
        help="Pandoc command, default: pandoc",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing files in the output directory",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan without running external tools",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Optional path to write a JSON conversion manifest",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Use an existing manifest to skip files that were already converted successfully",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=None,
        help="Directory for per-book conversion reports, default: <output>/.reports",
    )
    parser.add_argument(
        "--no-reports",
        action="store_true",
        help="Disable per-book conversion reports",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=None,
        help="Optional path for a Markdown batch summary, default: <output>/.reports/summary.md",
    )
    parser.add_argument(
        "--health-check",
        action="store_true",
        help="Only print dependency and environment health information, then exit",
    )
    parser.add_argument(
        "--pdf-tool-idle-timeout",
        type=float,
        default=1800.0,
        help="Abort Marker/MinerU after this many seconds without output; 0 disables. Default: 1800.",
    )
    parser.add_argument(
        "--pdf-tool-finalize-timeout",
        type=float,
        default=480.0,
        help="Abort Marker/MinerU after this many seconds stuck after all pages are reported done; 0 disables. Default: 480.",
    )
    parser.add_argument(
        "--no-pdf-auto-fallback",
        action="store_true",
        help="Disable automatic fallback to PyMuPDF4LLM when Marker/MinerU fails or times out.",
    )
    parser.add_argument(
        "--docling-timeout",
        type=float,
        default=45.0,
        help="Abort Docling document conversion after this many seconds; 0 disables isolation/timeout. Default: 45.",
    )
    parser.add_argument(
        "--no-docling-fallback",
        action="store_true",
        help="Disable automatic fallback to Pandoc/lightweight text output when Docling fails or times out.",
    )
    return parser.parse_args()


def default_options(**overrides) -> SimpleNamespace:
    base = {
        "recursive": False,
        "include_hidden": False,
        "output_format": "markdown",
        "output_name_suffix": "",
        "markdown_format": "gfm",
        "marker_command": suggested_command_value("marker_single"),
        "marker_extra_args": [],
        "mineru_command": suggested_command_value("mineru"),
        "mineru_extra_args": [],
        "mineru_method": "auto",
        "mineru_backend": "pipeline",
        "mineru_lang": "ch",
        "mineru_segment_min_pages": 200,
        "mineru_segment_pages": 50,
        "mineru_model_source": "huggingface",
        "mineru_hf_endpoint": "https://hf-mirror.com",
        "mineru_keep_artifacts": True,
        "calibre_command": suggested_command_value("ebook-convert"),
        "calibre_fallback_to_epub": True,
        "pandoc_command": suggested_command_value("pandoc"),
        "overwrite": False,
        "dry_run": False,
        "manifest": None,
        "resume": False,
        "report_dir": None,
        "no_reports": False,
        "summary": None,
        "health_check": False,
        "pdf_fallback_to_pymupdf4llm": True,
        "pdf_tool_idle_timeout": 1800.0,
        "pdf_tool_finalize_timeout": 480.0,
        "docling_timeout": 45.0,
        "docling_fallback_to_pandoc": True,
        "pdf_pipeline_mode": "auto",
        "marker_default_max_pages": 12,
        "marker_seconds_per_page_estimate": 10.0,
        "umi_ocr_command": suggested_umi_ocr_command(),
        "umi_ocr_port": 1224,
        "umi_render_dpi": 200,
        "umi_paddle_exe": suggested_umi_paddle_exe(),
        "umi_paddle_module": suggested_umi_paddle_module(),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def main() -> int:
    args = parse_args()
    return run_batch(args)


def run_batch(args: argparse.Namespace) -> int:
    if getattr(args, "no_pdf_auto_fallback", False):
        args.pdf_fallback_to_pymupdf4llm = False
    if getattr(args, "no_docling_fallback", False):
        args.docling_fallback_to_pandoc = False
    if getattr(args, "no_calibre_fallback", False):
        args.calibre_fallback_to_epub = False
    normalize_command_options(args)
    sources = collect_sources(
        args.input,
        recursive=args.recursive,
        include_hidden=args.include_hidden,
    )
    if not sources and not getattr(args, "health_check", False):
        print("No supported files found.", file=sys.stderr)
        return 1

    args.output.mkdir(parents=True, exist_ok=True)
    if getattr(args, "resume", False) and getattr(args, "manifest", None) is None:
        args.manifest = args.output / "manifest.json"

    if getattr(args, "health_check", False):
        checks = dependency_health_report(sources, args)
        print(format_health_report(checks))
        return 0 if all(item["status"] != "missing" for item in checks) else 2

    missing = find_missing_dependencies(sources, args)
    if missing:
        for message in missing:
            print(message, file=sys.stderr)
        return 2

    results = convert_sources(sources, args.input, args.output, args)

    for result in results:
        print(f"[{result.status}] {result.source} -> {result.output or '-'}")
        if result.message:
            print(f"  {result.message}")

    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(
            json.dumps([asdict(item) for item in results], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    write_batch_summary(results, args)

    failures = [item for item in results if item.status == "failed"]
    return 0 if not failures else 3


def convert_sources(
    sources: Iterable[Path],
    input_root: Path,
    output_root: Path,
    args: argparse.Namespace,
    progress_callback=None,
) -> list[ConversionResult]:
    results: list[ConversionResult] = []
    source_list = list(sources)
    output_paths = build_output_paths(source_list, input_root, output_root, args)
    completed_outputs = load_completed_outputs(getattr(args, "manifest", None)) if getattr(args, "resume", False) else {}
    total = len(source_list)
    for index, source in enumerate(source_list, start=1):
        if progress_callback:
            progress_callback("start", source, index, total, {"estimate_seconds": estimate_conversion_seconds(source, args)})
        output_path = output_paths[source]
        completed_output = completed_outputs.get(str(source))
        if completed_output and Path(completed_output).exists():
            result = ConversionResult(
                source=str(source),
                output=completed_output,
                status="skipped",
                pipeline=pipeline_name(source, args),
                message="Previously completed in manifest; skipped by --resume.",
                detected_format=detect_format_label(source),
            )
            write_conversion_report(result, args, output_path)
            results.append(result)
            if progress_callback:
                progress_callback("done", source, index, total, result)
            continue

        started = time.monotonic()
        started_at = timestamp_now()
        result = convert_one(
            source,
            input_root,
            output_root,
            args,
            progress_callback,
            index,
            total,
            output_path=output_path,
        )
        result.detected_format = detect_format_label(source)
        result.duration_seconds = round(time.monotonic() - started, 3)
        result.started_at = started_at
        result.finished_at = timestamp_now()
        write_conversion_report(result, args, output_path)
        results.append(result)
        if progress_callback:
            progress_callback("done", source, index, total, result)
    return results


def load_completed_outputs(manifest_path: Path | None) -> dict[str, str]:
    if not manifest_path or not manifest_path.exists():
        return {}
    try:
        items = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    completed: dict[str, str] = {}
    if not isinstance(items, list):
        return completed
    for item in items:
        if not isinstance(item, dict):
            continue
        source = item.get("source")
        output = item.get("output")
        if item.get("status") in {"ok", "skipped"} and source and output:
            completed[str(source)] = str(output)
    return completed


def collect_sources(
    input_path: Path,
    *,
    recursive: bool,
    include_hidden: bool,
) -> list[Path]:
    if input_path.is_file():
        return [input_path] if detect_source_kind(input_path) != "unsupported" else []

    if not input_path.exists():
        return []

    pattern = "**/*" if recursive else "*"
    items = []
    for path in input_path.glob(pattern):
        if not path.is_file():
            continue
        if detect_source_kind(path) == "unsupported":
            continue
        if not include_hidden and is_hidden(path):
            continue
        items.append(path)
    return sorted(items)


def detect_source_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in PANDOC_DIRECT_FORMATS:
        return "pandoc"
    if suffix in CALIBRE_INTERMEDIATE_FORMATS:
        return "calibre"
    if suffix in PDF_FORMATS:
        return "pdf"
    if suffix in DOCLING_FORMATS:
        return "docling"
    return "unsupported"


def detect_format_label(path: Path) -> str:
    suffix = path.suffix.lower()
    return suffix.lstrip(".").upper() if suffix else "UNKNOWN"


def is_hidden(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts)


def analyze_sources(
    sources: Iterable[Path],
    input_root: Path,
    output_root: Path,
    args: argparse.Namespace,
) -> list[SourcePlan]:
    source_list = list(sources)
    output_paths = build_output_paths(source_list, input_root, output_root, args)
    return [
        SourcePlan(
            source=str(source),
            detected_format=detect_format_label(source),
            pipeline=pipeline_name(source, args),
            output=str(output_paths[source]),
            output_format=args.output_format,
            note=plan_note(source, args),
        )
        for source in source_list
    ]


def build_output_paths(
    sources: Iterable[Path],
    input_root: Path,
    output_root: Path,
    args: argparse.Namespace,
) -> dict[Path, Path]:
    source_list = list(sources)
    base_paths = {
        source: build_output_path(source, input_root, output_root, args)
        for source in source_list
    }

    assigned: dict[Path, Path] = {}
    used: set[str] = set()
    seen_base_count: dict[str, int] = {}
    for source in source_list:
        base_path = base_paths[source]
        key = normalized_output_key(base_path)
        seen = seen_base_count.get(key, 0)
        candidate = base_path if seen == 0 else disambiguated_output_path(base_path, source.suffix, seen + 1)
        while normalized_output_key(candidate) in used:
            seen += 1
            candidate = disambiguated_output_path(base_path, source.suffix, seen + 1)
        seen_base_count[key] = seen + 1
        used.add(normalized_output_key(candidate))
        assigned[source] = candidate
    return assigned


def build_output_path(
    source: Path,
    input_root: Path,
    output_root: Path,
    args: argparse.Namespace,
) -> Path:
    try:
        relative = source.name if input_root.is_file() else source.relative_to(input_root)
    except ValueError:
        relative = Path(source.name)
    suffix = output_suffix(args.output_format)
    output_path = output_root / Path(relative).with_suffix(suffix)
    output_path = shorten_output_path_if_needed(output_path, source)
    name_suffix = safe_output_name_suffix(getattr(args, "output_name_suffix", ""))
    if name_suffix:
        output_path = output_path.with_name(f"{output_path.stem}{name_suffix}{output_path.suffix}")
        output_path = shorten_output_path_if_needed(output_path, source, protected_stem_suffix=name_suffix)
    return output_path


def safe_output_name_suffix(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    if not value.startswith(("-", "_", ".")):
        value = f"-{value}"
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    value = re.sub(r"\s+", "-", value)
    return value[:60].rstrip(" ._-")


def shorten_output_path_if_needed(
    output_path: Path,
    source: Path,
    max_path_chars: int = 220,
    protected_stem_suffix: str = "",
) -> Path:
    if len(str(output_path)) <= max_path_chars and len(output_path.name) <= 150:
        return output_path

    digest = hashlib.sha1(str(source).encode("utf-8", errors="replace")).hexdigest()[:10]
    safe_stem = sanitize_output_stem(output_path.stem)
    protected_stem_suffix = protected_stem_suffix.strip()
    if protected_stem_suffix and safe_stem.endswith(protected_stem_suffix):
        safe_stem = safe_stem[: -len(protected_stem_suffix)].rstrip(" ._-")
    max_stem_len = max(30, 140 - len(output_path.suffix) - len(protected_stem_suffix))
    shortened_stem = safe_stem[:max_stem_len].rstrip(" ._-")
    if protected_stem_suffix:
        shortened_stem = f"{shortened_stem}{protected_stem_suffix}"
    return output_path.with_name(f"{shortened_stem}-{digest}{output_path.suffix}")


def sanitize_output_stem(stem: str) -> str:
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem or "converted-book"


def normalized_output_key(path: Path) -> str:
    return str(path).casefold()


def disambiguated_output_path(base_path: Path, source_suffix: str, index: int) -> Path:
    source_tag = source_suffix.lower().lstrip(".") or "source"
    index_tag = "" if index == 2 else f"-{index}"
    return base_path.with_name(f"{base_path.stem}.{source_tag}{index_tag}{base_path.suffix}")


def output_suffix(output_format: str) -> str:
    if output_format not in OUTPUT_FORMATS:
        raise ValueError(f"Unsupported output format: {output_format}")
    return OUTPUT_FORMATS[output_format]["suffix"]


def pandoc_target(args: argparse.Namespace) -> str:
    if args.output_format == "markdown":
        return args.markdown_format
    return OUTPUT_FORMATS[args.output_format]["pandoc_target"]


def find_missing_dependencies(sources: Iterable[Path], args: argparse.Namespace) -> list[str]:
    required = required_dependencies(sources, args)
    missing = []
    for command in sorted(required):
        if command == "docling":
            if not docling_available():
                missing.append("Missing optional Python dependency: docling. Install with: pip install docling")
            continue
        if resolve_command_path(command):
            continue
        missing.append(
            f"Missing dependency: '{command}' is not in PATH. "
            "Install it or pass a custom command path."
        )
    return missing


def required_dependencies(sources: Iterable[Path], args: argparse.Namespace) -> set[str]:
    required = set()
    for source in sources:
        kind = detect_source_kind(source)
        if kind == "pandoc":
            required.add(args.pandoc_command)
        elif kind == "calibre":
            required.add(args.calibre_command)
            required.add(args.pandoc_command)
        elif kind == "pdf":
            selected = selected_pdf_pipeline(source, args)
            if selected == "marker":
                required.add(args.marker_command)
            elif selected == "mineru":
                required.add(getattr(args, "mineru_command", "mineru"))
            elif selected == "umi":
                required.add(getattr(args, "umi_paddle_exe", suggested_umi_paddle_exe()))
            elif selected == "pymupdf4llm" and not pymupdf4llm_available():
                required.add("pymupdf4llm")
            elif selected == "docling" and not docling_available():
                required.add("docling")
            if args.output_format != "markdown":
                required.add(args.pandoc_command)
        elif kind == "docling":
            if not docling_available():
                required.add("docling")
            if args.output_format != "markdown":
                required.add(args.pandoc_command)
    return required


def dependency_health_report(sources: Iterable[Path], args: argparse.Namespace) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    source_list = list(sources)
    required = required_dependencies(source_list, args)
    if not source_list:
        required.update(
            {
                getattr(args, "pandoc_command", "pandoc"),
                getattr(args, "calibre_command", "ebook-convert"),
                getattr(args, "marker_command", "marker_single"),
                getattr(args, "mineru_command", "mineru"),
                getattr(args, "umi_paddle_exe", suggested_umi_paddle_exe()),
            }
        )
    for command in sorted(required):
        resolved = resolve_command_path(command)
        detail = resolved or "not found"
        version = command_version(resolved or command) if resolved else ""
        if version:
            detail = f"{detail}; {version}"
        checks.append(
            {
                "name": Path(command).name if command else command,
                "kind": "command",
                "status": "ok" if resolved else "missing",
                "detail": detail,
            }
        )

    checks.append(
        {
            "name": "pymupdf4llm",
            "kind": "python",
            "status": "ok" if pymupdf4llm_available() else "missing",
            "detail": "importable" if pymupdf4llm_available() else "not importable",
        }
    )
    checks.append(
        {
            "name": "docling",
            "kind": "python",
            "status": "ok" if docling_available() else "missing",
            "detail": "importable" if docling_available() else "optional backend not installed",
        }
    )
    checks.append(
        {
            "name": "PyMuPDF",
            "kind": "python",
            "status": "ok" if pymupdf_available() else "missing",
            "detail": "importable" if pymupdf_available() else "not importable",
        }
    )
    checks.append(
        {
            "name": "Umi PaddleOCR module",
            "kind": "file",
            "status": "ok" if Path(getattr(args, "umi_paddle_module", suggested_umi_paddle_module())).exists() else "missing",
            "detail": getattr(args, "umi_paddle_module", suggested_umi_paddle_module()),
        }
    )
    cache_status, cache_detail = mineru_model_cache_status()
    checks.append(
        {
            "name": "MinerU model cache",
            "kind": "model",
            "status": cache_status,
            "detail": cache_detail,
        }
    )
    checks.append(
        {
            "name": "CUDA for torch",
            "kind": "gpu",
            "status": torch_cuda_status(),
            "detail": torch_cuda_detail(),
        }
    )
    return checks


def format_health_report(checks: list[dict[str, str]]) -> str:
    lines = ["Dependency health check:"]
    for item in checks:
        lines.append(f"- [{item['status']}] {item['name']} ({item['kind']}): {item['detail']}")
    capabilities = environment_capability_summary(checks)
    if capabilities:
        lines.extend(["", "Capability matrix:"])
        for item in capabilities:
            lines.append(f"- [{item['status']}] {item['name']}: {item['detail']} Action: {item['action']}")
    return "\n".join(lines)


def environment_capability_summary(checks: list[dict[str, str]]) -> list[dict[str, str]]:
    by_name = {str(item.get("name", "")).lower(): item for item in checks}
    names = set(by_name)

    def command_ok(candidates: tuple[str, ...]) -> bool:
        return any(
            any(candidate in name for name in names)
            and by_name[name].get("status") == "ok"
            for candidate in candidates
            for name in names
        )

    def check_ok(name: str) -> bool:
        return by_name.get(name.lower(), {}).get("status") == "ok"

    def check_status(name: str) -> str:
        return str(by_name.get(name.lower(), {}).get("status") or "missing")

    pandoc_ok = command_ok(("pandoc",))
    calibre_ok = command_ok(("ebook-convert",))
    mineru_ok = command_ok(("mineru",))
    marker_ok = command_ok(("marker", "marker_single"))
    pymupdf_ok = check_ok("PyMuPDF")
    pymupdf4llm_ok = check_ok("pymupdf4llm")
    docling_ok = check_ok("docling")
    umi_ok = check_ok("Umi PaddleOCR module")
    mineru_cache = check_status("MinerU model cache")
    cuda_status = check_status("CUDA for torch")

    capabilities: list[dict[str, str]] = []

    structured_ok = pandoc_ok and calibre_ok
    capabilities.append(
        capability_item(
            "structured_ebooks",
            "ok" if structured_ok else "missing",
            "EPUB/TXT/RTF/ODT via Pandoc; AZW/AZW3/MOBI via Calibre+Pandoc"
            if structured_ok
            else "Pandoc and Calibre are both needed for broad ebook coverage.",
            "Use normal conversion." if structured_ok else "Install/fix Pandoc and Calibre before large ebook batches.",
        )
    )

    fast_pdf_ok = pymupdf_ok and pymupdf4llm_ok
    capabilities.append(
        capability_item(
            "pdf_fast_text",
            "ok" if fast_pdf_ok else "missing",
            "Fast text-layer extraction with PyMuPDF/PyMuPDF4LLM." if fast_pdf_ok else "Fast PDF fallback is incomplete.",
            "Use pymupdf4llm for text-layer PDFs." if fast_pdf_ok else "Install PyMuPDF and pymupdf4llm for safe PDF fallback.",
        )
    )

    structured_pdf_status = "ok" if mineru_ok and mineru_cache == "ok" else "degraded" if mineru_ok else "missing"
    capabilities.append(
        capability_item(
            "pdf_structure_recovery",
            structured_pdf_status,
            "MinerU available with model cache." if structured_pdf_status == "ok" else "MinerU command/model cache is incomplete.",
            "Use MinerU for complex PDFs." if structured_pdf_status == "ok" else "Run health details, download models, or fall back to PyMuPDF4LLM/Umi-OCR.",
        )
    )

    capabilities.append(
        capability_item(
            "pdf_marker_layout",
            "ok" if marker_ok else "missing",
            "Marker is available for short layout-heavy PDFs." if marker_ok else "Marker command is not available.",
            "Use Marker only for short selected PDFs." if marker_ok else "Install Marker or keep using MinerU/PyMuPDF4LLM.",
        )
    )

    capabilities.append(
        capability_item(
            "local_ocr",
            "ok" if umi_ok else "missing",
            "Umi-OCR Paddle module is available." if umi_ok else "Umi-OCR Paddle module is not configured.",
            "Use Umi-OCR for long scanned documents or image batches." if umi_ok else "Configure Umi-OCR path for scanned PDFs/images.",
        )
    )

    capabilities.append(
        capability_item(
            "docling_documents",
            "ok" if docling_ok else "missing",
            "Docling backend is importable." if docling_ok else "Docling optional backend is not installed.",
            "Use Docling for office-like documents and selected PDFs." if docling_ok else "Install optional Docling deps only if needed.",
        )
    )

    capabilities.append(
        capability_item(
            "gpu_acceleration",
            "ok" if cuda_status == "ok" else "degraded",
            "Torch CUDA is available." if cuda_status == "ok" else "Torch CUDA is unavailable; model pipelines may run on CPU.",
            "Prefer GPU MinerU/VLM workloads." if cuda_status == "ok" else "Use lighter/fallback pipelines or install CUDA-enabled torch.",
        )
    )
    return capabilities


def capability_item(name: str, status: str, detail: str, action: str) -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail, "action": action}


def command_version(command: str) -> str:
    command_name = Path(command).name.lower()
    if command_name not in {"pandoc.exe", "pandoc", "mineru.exe", "mineru", "ebook-convert.exe", "ebook-convert"}:
        return ""
    candidates = [
        [command, "--version"],
        [command, "-V"],
        [command, "-v"],
    ]
    for cmd in candidates:
        try:
            completed = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
            )
        except Exception:
            continue
        output = (completed.stdout or "").strip().splitlines()
        first_line = next((line.strip() for line in output if line.strip()), "")
        if first_line and not looks_like_version_probe_error(first_line):
            return first_line[:180]
    return ""


def looks_like_version_probe_error(line: str) -> bool:
    lowered = line.lower()
    return (
        lowered.startswith("traceback")
        or lowered.startswith("error")
        or "not recognized" in lowered
        or "exception" in lowered
    )


def convert_one(
    source: Path,
    input_root: Path,
    output_root: Path,
    args: argparse.Namespace,
    progress_callback=None,
    progress_index: int | None = None,
    progress_total: int | None = None,
    output_path: Path | None = None,
) -> ConversionResult:
    output_path = output_path or build_output_path(source, input_root, output_root, args)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    args._pdf_tool_diagnostics = []
    args._pdf_fallback_diagnostics = []
    args._docling_diagnostics = []
    args._calibre_fallback_diagnostics = []
    args._last_pdf_pipeline = None
    args._last_docling_pipeline = None
    args._last_ebook_pipeline = None

    if output_path.exists() and not args.overwrite:
        return ConversionResult(
            source=str(source),
            output=str(output_path),
            status="skipped",
            pipeline=pipeline_name(source, args),
            message="Output exists. Use --overwrite to replace it.",
        )

    kind = detect_source_kind(source)
    try:
        emit_stage(progress_callback, source, progress_index, progress_total, "prepare", f"输出到 {output_path}")
        if kind == "pandoc":
            run_pandoc_direct_convert(source, output_path, args, progress_callback, progress_index, progress_total)
        elif kind == "calibre":
            run_calibre_intermediate_convert(source, output_path, args, progress_callback, progress_index, progress_total)
        elif kind == "pdf":
            run_pdf_convert(source, output_path, args, progress_callback, progress_index, progress_total)
        elif kind == "docling":
            run_docling_convert(source, output_path, args, progress_callback, progress_index, progress_total)
        else:
            return ConversionResult(
                source=str(source),
                output=None,
                status="failed",
                pipeline="unknown",
                message=f"Unsupported format: {source.suffix.lower()}",
            )
    except subprocess.CalledProcessError as exc:
        return ConversionResult(
            source=str(source),
            output=str(output_path),
            status="failed",
            pipeline=pipeline_name(source, args),
            message=format_subprocess_error(exc),
        )
    except Exception as exc:  # noqa: BLE001
        return ConversionResult(
            source=str(source),
            output=str(output_path),
            status="failed",
            pipeline=pipeline_name(source, args),
            message=str(exc),
        )

    return ConversionResult(
        source=str(source),
        output=str(output_path),
        status="ok",
        pipeline=final_pipeline_name(source, kind, args),
        message="",
    )


def final_pipeline_name(source: Path, kind: str, args: argparse.Namespace) -> str:
    if kind == "pdf":
        return getattr(args, "_last_pdf_pipeline", None) or pipeline_name(source, args)
    if kind == "docling":
        return getattr(args, "_last_docling_pipeline", None) or pipeline_name(source, args)
    if kind in {"pandoc", "calibre"}:
        return getattr(args, "_last_ebook_pipeline", None) or pipeline_name(source, args)
    return pipeline_name(source, args)


def pipeline_name(source: Path, args: argparse.Namespace | None = None) -> str:
    kind = detect_source_kind(source)
    if kind == "pandoc":
        return "pandoc"
    if kind == "calibre":
        return "calibre+pandoc"
    if kind == "docling":
        return "docling"
    if kind == "pdf":
        if args:
            return selected_pdf_pipeline_label(source, args)
        return "pdf"
    return "unknown"


def run_pandoc_direct_convert(
    source: Path,
    output_path: Path,
    args: argparse.Namespace,
    progress_callback=None,
    progress_index: int | None = None,
    progress_total: int | None = None,
) -> None:
    direct_failed: Exception | None = None
    try:
        run_pandoc_direct_convert_once(source, output_path, args, progress_callback, progress_index, progress_total)
        args._last_ebook_pipeline = "pandoc"
    except Exception as exc:  # noqa: BLE001
        direct_failed = exc

    if should_try_calibre_fallback(source, output_path, args, direct_failed):
        if try_calibre_fallback_after_pandoc(
            source,
            output_path,
            args,
            direct_failed,
            progress_callback,
            progress_index,
            progress_total,
        ):
            return

    if direct_failed:
        raise direct_failed


def run_pandoc_direct_convert_once(
    source: Path,
    output_path: Path,
    args: argparse.Namespace,
    progress_callback=None,
    progress_index: int | None = None,
    progress_total: int | None = None,
) -> None:
    if source.suffix.lower() == ".txt" and not args.dry_run:
        with tempfile.TemporaryDirectory(prefix="txt-normalized-") as tmpdir:
            temp_source = Path(tmpdir) / f"{source.stem}.txt"
            encoding = normalize_text_file_for_pandoc(source, temp_source)
            emit_stage(
                progress_callback,
                source,
                progress_index,
                progress_total,
                "encoding",
                f"文本编码识别为 {encoding}，转为 UTF-8",
            )
            run_pandoc_command(temp_source, output_path, args, progress_callback, source, progress_index, progress_total)
    else:
        run_pandoc_command(source, output_path, args, progress_callback, source, progress_index, progress_total)

    postprocess_text_output(
        output_path,
        args,
        source_kind="epub" if source.suffix.lower() == ".epub" else "pandoc",
        note_source_path=source,
        progress_callback=progress_callback,
        progress_source=source,
        progress_index=progress_index,
        progress_total=progress_total,
    )


def run_pandoc_command(
    source: Path,
    output_path: Path,
    args: argparse.Namespace,
    progress_callback=None,
    progress_source: Path | None = None,
    progress_index: int | None = None,
    progress_total: int | None = None,
) -> None:
    cmd = [
        args.pandoc_command,
        str(source),
        "-t",
        pandoc_target(args),
        "-o",
        str(output_path),
    ]
    emit_stage(progress_callback, progress_source or source, progress_index, progress_total, "pandoc", "Pandoc 转换")
    run_command(cmd, args.dry_run)


def normalize_text_file_for_pandoc(source: Path, target: Path) -> str:
    data = source.read_bytes()
    encoding, text = decode_text_bytes(data)
    target.write_text(text, encoding="utf-8", newline="\n")
    return encoding


def decode_text_bytes(data: bytes) -> tuple[str, str]:
    bom_encodings = [
        (b"\xef\xbb\xbf", "utf-8-sig"),
        (b"\xff\xfe", "utf-16"),
        (b"\xfe\xff", "utf-16"),
    ]
    for bom, encoding in bom_encodings:
        if data.startswith(bom):
            return encoding, data.decode(encoding, errors="replace")

    for encoding in ("utf-8", "gb18030", "big5", "utf-16"):
        try:
            return encoding, data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return "utf-8-replace", data.decode("utf-8", errors="replace")


def should_try_calibre_fallback(
    source: Path,
    output_path: Path,
    args: argparse.Namespace,
    direct_failed: Exception | None,
) -> bool:
    if not getattr(args, "calibre_fallback_to_epub", True):
        return False
    if source.suffix.lower() not in CALIBRE_FALLBACK_FORMATS:
        return False
    if args.output_format != "markdown":
        return direct_failed is not None
    if not resolve_command_path(getattr(args, "calibre_command", "ebook-convert")):
        return False
    if direct_failed is not None:
        return True
    quality = analyze_markdown_quality(output_path)
    if not quality:
        return False
    return quality.level == "poor" or any("没有 Markdown 标题" in reason for reason in quality.reasons)


def try_calibre_fallback_after_pandoc(
    source: Path,
    output_path: Path,
    args: argparse.Namespace,
    direct_failed: Exception | None,
    progress_callback=None,
    progress_index: int | None = None,
    progress_total: int | None = None,
) -> bool:
    direct_quality = analyze_markdown_quality(output_path) if output_path.exists() else None
    diagnostic: dict[str, object] = {
        "source": str(source),
        "output": str(output_path),
        "started_at": timestamp_now(),
        "from_pipeline": "pandoc",
        "to_pipeline": "calibre+epub+pandoc",
        "trigger": "pandoc_failed" if direct_failed else "weak_pandoc_quality",
        "status": "running",
    }
    if direct_failed:
        diagnostic["direct_error"] = str(direct_failed)
        diagnostic["direct_error_type"] = type(direct_failed).__name__
    if direct_quality:
        diagnostic["direct_quality"] = asdict(direct_quality)
    getattr(args, "_calibre_fallback_diagnostics", []).append(diagnostic)

    started = time.monotonic()
    emit_stage(progress_callback, source, progress_index, progress_total, "calibre", "Pandoc 结果较弱，尝试 Calibre 预处理")
    with tempfile.TemporaryDirectory(prefix="calibre-fallback-") as tmpdir:
        tmpdir_path = Path(tmpdir)
        fallback_output = tmpdir_path / output_path.name
        direct_backup = tmpdir_path / f"direct-{output_path.name}"
        if output_path.exists():
            shutil.copyfile(output_path, direct_backup)
        try:
            run_calibre_intermediate_convert(source, fallback_output, args, progress_callback, progress_index, progress_total)
            fallback_quality = analyze_markdown_quality(fallback_output)
            if fallback_quality:
                diagnostic["fallback_quality"] = asdict(fallback_quality)
            use_fallback = direct_failed is not None or quality_score(fallback_quality) > quality_score(direct_quality)
            if use_fallback:
                shutil.copyfile(fallback_output, output_path)
                args._last_ebook_pipeline = "calibre+epub+pandoc(fallback from pandoc)"
                diagnostic["status"] = "ok"
                diagnostic["decision"] = "used_fallback"
                return True
            if direct_backup.exists():
                shutil.copyfile(direct_backup, output_path)
            args._last_ebook_pipeline = "pandoc"
            diagnostic["status"] = "skipped"
            diagnostic["decision"] = "kept_direct_output"
            return False
        except Exception as exc:  # noqa: BLE001
            if direct_backup.exists():
                shutil.copyfile(direct_backup, output_path)
            diagnostic["status"] = "failed"
            diagnostic["fallback_error"] = str(exc)
            diagnostic["fallback_error_type"] = type(exc).__name__
            if direct_failed is not None:
                raise RuntimeError(f"Pandoc failed and Calibre fallback also failed: {exc}") from exc
            return False
        finally:
            diagnostic["duration_seconds"] = round(time.monotonic() - started, 3)
            diagnostic["finished_at"] = timestamp_now()


def quality_score(quality: MarkdownQuality | None) -> int:
    return int(quality.score) if quality else -1


def run_calibre_intermediate_convert(
    source: Path,
    output_path: Path,
    args: argparse.Namespace,
    progress_callback=None,
    progress_index: int | None = None,
    progress_total: int | None = None,
) -> None:
    args._last_ebook_pipeline = "calibre+pandoc"
    with tempfile.TemporaryDirectory(prefix="ebook-pipeline-") as tmpdir:
        temp_epub = Path(tmpdir) / f"{source.stem}.epub"
        calibre_env = calibre_environment()
        calibre_cmd = [args.calibre_command, str(source), str(temp_epub)]
        emit_stage(progress_callback, source, progress_index, progress_total, "calibre", "Calibre 转 EPUB")
        run_command(calibre_cmd, args.dry_run, env=calibre_env)

        pandoc_cmd = [
            args.pandoc_command,
            str(temp_epub),
            "-t",
            pandoc_target(args),
            "-o",
            str(output_path),
        ]
        emit_stage(progress_callback, source, progress_index, progress_total, "pandoc", "Pandoc 转换")
        run_command(pandoc_cmd, args.dry_run)
        postprocess_text_output(
            output_path,
            args,
            source_kind="epub",
            note_source_path=temp_epub,
            progress_callback=progress_callback,
            progress_source=source,
            progress_index=progress_index,
            progress_total=progress_total,
        )


def run_docling_convert(
    source: Path,
    output_path: Path,
    args: argparse.Namespace,
    progress_callback=None,
    progress_index: int | None = None,
    progress_total: int | None = None,
) -> None:
    emit_stage(progress_callback, source, progress_index, progress_total, "docling", "Docling 文档解析")
    if args.dry_run:
        return
    try:
        result = run_docling_backend(source, output_path, args)
        args._last_docling_pipeline = "docling"
    except Exception as exc:  # noqa: BLE001
        if not should_fallback_from_docling(source, args):
            raise
        args._last_docling_pipeline = "docling(fallback)"
        emit_stage(
            progress_callback,
            source,
            progress_index,
            progress_total,
            "fallback",
            f"Docling 失败/超时，自动回退到轻量转换: {exc}",
        )
        run_docling_fallback_convert(source, output_path, args, progress_callback, progress_index, progress_total)
        return
    markdown = result["markdown"]
    if args.output_format == "markdown":
        output_path.write_text(markdown, encoding="utf-8", newline="\n")
        postprocess_text_output(
            output_path,
            args,
            source_kind="docling",
            note_source_path=source,
            progress_callback=progress_callback,
            progress_source=source,
            progress_index=progress_index,
            progress_total=progress_total,
        )
        return

    with tempfile.TemporaryDirectory(prefix="docling-markdown-") as tmpdir:
        temp_md = Path(tmpdir) / f"{source.stem}.md"
        temp_md.write_text(markdown, encoding="utf-8", newline="\n")
        convert_markdown_file(temp_md, output_path, args, progress_callback, source, progress_index, progress_total)


def run_docling_backend(source: Path, output_path: Path, args: argparse.Namespace) -> dict:
    timeout = float(getattr(args, "docling_timeout", 60.0) or 0.0)
    diagnostic: dict[str, object] = {
        "tool": "Docling",
        "source": str(source),
        "output": str(output_path),
        "started_at": timestamp_now(),
        "timeout_seconds": timeout,
        "duration_seconds": None,
        "status": "running",
    }
    getattr(args, "_docling_diagnostics", []).append(diagnostic)
    started = time.monotonic()
    if timeout <= 0:
        try:
            result = convert_with_docling(source)
            diagnostic["status"] = "ok"
            return result
        except Exception as exc:  # noqa: BLE001
            diagnostic["status"] = "failed"
            diagnostic["error"] = str(exc)
            raise
        finally:
            diagnostic["duration_seconds"] = round(time.monotonic() - started, 3)
            diagnostic["finished_at"] = timestamp_now()

    with tempfile.TemporaryDirectory(prefix="docling-worker-") as tmpdir:
        result_json = Path(tmpdir) / "result.json"
        backend_script = Path(__file__).resolve().parent / "docling_backend.py"
        cmd = [sys.executable, str(backend_script), str(source), "--output-json", str(result_json)]
        diagnostic["command"] = cmd
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        diagnostic["pid"] = process.pid
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            terminate_process_tree(process)
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            diagnostic["status"] = "timeout"
            diagnostic["duration_seconds"] = round(time.monotonic() - started, 3)
            diagnostic["finished_at"] = timestamp_now()
            diagnostic["stdout_tail"] = str(stdout)[-4000:]
            diagnostic["stderr_tail"] = str(stderr)[-4000:]
            raise DoclingTimeoutError(f"Docling timed out after {format_duration(timeout)}", diagnostic) from exc
        diagnostic["duration_seconds"] = round(time.monotonic() - started, 3)
        diagnostic["finished_at"] = timestamp_now()
        diagnostic["exit_code"] = process.returncode
        diagnostic["stdout_tail"] = (stdout or "")[-4000:]
        diagnostic["stderr_tail"] = (stderr or "")[-4000:]
        payload = load_docling_worker_result(result_json)
        if process.returncode != 0 or not payload.get("ok"):
            diagnostic["status"] = "failed"
            diagnostic["error"] = str(payload.get("error") or diagnostic.get("stderr_tail") or "Docling failed")
            raise RuntimeError(str(diagnostic["error"]))
        diagnostic["status"] = "ok"
        result = payload.get("result")
        if not isinstance(result, dict):
            diagnostic["status"] = "failed"
            diagnostic["error"] = "Docling worker returned an invalid result."
            raise RuntimeError(str(diagnostic["error"]))
        return result


def load_docling_worker_result(result_json: Path) -> dict:
    if not result_json.exists():
        return {"ok": False, "error": "Docling worker produced no result JSON."}
    try:
        payload = json.loads(result_json.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Could not read Docling worker result: {exc}"}
    return payload if isinstance(payload, dict) else {"ok": False, "error": "Invalid Docling worker result JSON."}


def should_fallback_from_docling(source: Path, args: argparse.Namespace) -> bool:
    if not getattr(args, "docling_fallback_to_pandoc", True):
        return False
    suffix = source.suffix.lower()
    return suffix in DOCLING_PANDOC_FALLBACK_FORMATS or suffix in DOCLING_TEXT_FALLBACK_FORMATS


def run_docling_fallback_convert(
    source: Path,
    output_path: Path,
    args: argparse.Namespace,
    progress_callback=None,
    progress_index: int | None = None,
    progress_total: int | None = None,
) -> None:
    suffix = source.suffix.lower()
    getattr(args, "_docling_diagnostics", []).append(
        {
            "tool": "Docling fallback",
            "source": str(source),
            "output": str(output_path),
            "started_at": timestamp_now(),
            "status": "running",
            "fallback": "text" if suffix in DOCLING_TEXT_FALLBACK_FORMATS else "pandoc",
        }
    )
    fallback_diagnostic = getattr(args, "_docling_diagnostics", [])[-1]
    started = time.monotonic()
    if suffix in DOCLING_TEXT_FALLBACK_FORMATS:
        emit_stage(progress_callback, source, progress_index, progress_total, "fallback", "CSV 轻量文本兜底")
        text = source.read_text(encoding="utf-8-sig", errors="replace")
        if args.output_format == "markdown":
            output_path.write_text(f"# {source.stem}\n\n```csv\n{text.rstrip()}\n```\n", encoding="utf-8", newline="\n")
            finish_docling_fallback_diagnostic(fallback_diagnostic, started, "ok")
            return
        with tempfile.TemporaryDirectory(prefix="docling-fallback-") as tmpdir:
            temp_md = Path(tmpdir) / f"{source.stem}.md"
            temp_md.write_text(f"# {source.stem}\n\n```csv\n{text.rstrip()}\n```\n", encoding="utf-8", newline="\n")
            convert_markdown_file(temp_md, output_path, args, progress_callback, source, progress_index, progress_total)
            finish_docling_fallback_diagnostic(fallback_diagnostic, started, "ok")
            return

    if suffix == ".md":
        emit_stage(progress_callback, source, progress_index, progress_total, "fallback", "Markdown 轻量兜底")
        if args.output_format == "markdown":
            shutil.copyfile(source, output_path)
            postprocess_text_output(
                output_path,
                args,
                source_kind="docling-fallback",
                note_source_path=source,
                progress_callback=progress_callback,
                progress_source=source,
                progress_index=progress_index,
                progress_total=progress_total,
            )
            finish_docling_fallback_diagnostic(fallback_diagnostic, started, "ok")
            return
        convert_markdown_file(source, output_path, args, progress_callback, source, progress_index, progress_total)
        finish_docling_fallback_diagnostic(fallback_diagnostic, started, "ok")
        return

    if suffix in DOCLING_PANDOC_FALLBACK_FORMATS:
        emit_stage(progress_callback, source, progress_index, progress_total, "fallback", "Pandoc 文档兜底")
        pandoc_cmd = [
            args.pandoc_command,
            str(source),
            "-t",
            pandoc_target(args),
            "-o",
            str(output_path),
        ]
        run_command(pandoc_cmd, args.dry_run)
        if args.output_format == "markdown":
            postprocess_text_output(
                output_path,
                args,
                source_kind="docling-fallback",
                note_source_path=source,
                progress_callback=progress_callback,
                progress_source=source,
                progress_index=progress_index,
                progress_total=progress_total,
            )
        finish_docling_fallback_diagnostic(fallback_diagnostic, started, "ok")
        return
    finish_docling_fallback_diagnostic(
        fallback_diagnostic,
        started,
        "failed",
        f"No lightweight fallback is available for {source.suffix.lower()}",
    )
    raise RuntimeError(f"No lightweight fallback is available for {source.suffix.lower()}")


def finish_docling_fallback_diagnostic(
    diagnostic: dict[str, object],
    started: float,
    status: str,
    error: str | None = None,
) -> None:
    diagnostic["status"] = status
    diagnostic["duration_seconds"] = round(time.monotonic() - started, 3)
    diagnostic["finished_at"] = timestamp_now()
    if error:
        diagnostic["error"] = error


def run_pdf_convert(
    source: Path,
    output_path: Path,
    args: argparse.Namespace,
    progress_callback=None,
    progress_index: int | None = None,
    progress_total: int | None = None,
) -> None:
    selected = selected_pdf_pipeline(source, args)
    args._last_pdf_pipeline = selected_pdf_pipeline_label(source, args)
    try:
        if selected == "umi":
            run_umi_pdf_convert(source, output_path, args, progress_callback, progress_index, progress_total)
        elif selected == "mineru":
            run_mineru_pdf_convert(source, output_path, args, progress_callback, progress_index, progress_total)
        elif selected == "pymupdf4llm":
            run_pymupdf4llm_pdf_convert(source, output_path, args, progress_callback, progress_index, progress_total)
        elif selected == "docling":
            run_docling_convert(source, output_path, args, progress_callback, progress_index, progress_total)
        else:
            run_marker_pdf_convert(source, output_path, args, progress_callback, progress_index, progress_total)
        return
    except Exception as exc:  # noqa: BLE001
        if not should_fallback_from_pdf_tool(exc, selected, args):
            raise
        fallback_diagnostic: dict[str, object] = {
            "source": str(source),
            "output": str(output_path),
            "started_at": timestamp_now(),
            "from_pipeline": selected,
            "to_pipeline": "pymupdf4llm",
            "reason": str(exc),
            "reason_type": type(exc).__name__,
            "status": "running",
        }
        if isinstance(exc, PdfToolTimeoutError):
            fallback_diagnostic["timeout_diagnostic"] = exc.diagnostic
        getattr(args, "_pdf_fallback_diagnostics", []).append(fallback_diagnostic)
        fallback_started = time.monotonic()
        emit_stage(
            progress_callback,
            source,
            progress_index,
            progress_total,
            "fallback",
            f"{selected} 失败/超时，自动回退到 PyMuPDF4LLM",
        )
        try:
            run_pymupdf4llm_pdf_convert(source, output_path, args, progress_callback, progress_index, progress_total)
        except Exception as fallback_exc:  # noqa: BLE001
            fallback_diagnostic["status"] = "failed"
            fallback_diagnostic["fallback_error"] = str(fallback_exc)
            fallback_diagnostic["fallback_error_type"] = type(fallback_exc).__name__
            fallback_diagnostic["duration_seconds"] = round(time.monotonic() - fallback_started, 3)
            fallback_diagnostic["finished_at"] = timestamp_now()
            raise RuntimeError(f"{selected} failed and PyMuPDF4LLM fallback also failed: {fallback_exc}") from fallback_exc
        fallback_diagnostic["status"] = "ok"
        fallback_diagnostic["duration_seconds"] = round(time.monotonic() - fallback_started, 3)
        fallback_diagnostic["finished_at"] = timestamp_now()
        args._last_pdf_pipeline = f"pymupdf4llm(fallback from {selected})"


def run_mineru_pdf_convert(
    source: Path,
    output_path: Path,
    args: argparse.Namespace,
    progress_callback=None,
    progress_index: int | None = None,
    progress_total: int | None = None,
) -> None:
    page_count = pdf_preflight(source, args).page_count
    segment_min_pages = int(getattr(args, "mineru_segment_min_pages", 200) or 0)
    segment_pages = int(getattr(args, "mineru_segment_pages", 50) or 0)
    if segment_min_pages > 0 and segment_pages > 0 and page_count >= segment_min_pages:
        args._last_pdf_pipeline = "mineru(segmented)"
        run_segmented_mineru_pdf_convert(
            source,
            output_path,
            args,
            page_count,
            segment_pages,
            progress_callback,
            progress_index,
            progress_total,
        )
        return
    run_single_mineru_pdf_convert(source, output_path, args, progress_callback, progress_index, progress_total)


def run_single_mineru_pdf_convert(
    source: Path,
    output_path: Path,
    args: argparse.Namespace,
    progress_callback=None,
    progress_index: int | None = None,
    progress_total: int | None = None,
) -> None:
    tmpdir_path = Path(tempfile.mkdtemp(prefix="mineru-output-"))
    success = False
    try:
        cmd = [
            args.mineru_command,
            "-p",
            str(source),
            "-o",
            str(tmpdir_path),
            "-m",
            getattr(args, "mineru_method", "auto"),
            "-b",
            getattr(args, "mineru_backend", "pipeline"),
            "-l",
            getattr(args, "mineru_lang", "ch"),
            *getattr(args, "mineru_extra_args", []),
        ]
        emit_stage(progress_callback, source, progress_index, progress_total, "mineru", "MinerU 结构化解析 PDF")
        run_pdf_tool_command(
            cmd,
            args,
            source,
            output_path,
            progress_callback,
            progress_index,
            progress_total,
            stage="mineru_progress",
            label="MinerU",
            env=mineru_environment(args),
        )
        if args.dry_run:
            success = True
            return

        emit_stage(progress_callback, source, progress_index, progress_total, "collect", "收集 MinerU 输出")
        md_candidates = sorted(tmpdir_path.rglob("*.md"))
        if not md_candidates:
            raise FileNotFoundError("MinerU completed but no markdown file was produced.")

        best_md = pick_mineru_markdown(md_candidates, source.stem)
        artifact_root = None
        if getattr(args, "mineru_keep_artifacts", True):
            artifact_root = save_mineru_artifacts(tmpdir_path, output_path)
            emit_stage(progress_callback, source, progress_index, progress_total, "quality", "生成 PDF 质量报告")
            write_mineru_quality_report(artifact_root, output_path)
        if args.output_format == "markdown":
            emit_stage(progress_callback, source, progress_index, progress_total, "copy", "复制 MinerU Markdown 输出")
            shutil.copyfile(best_md, output_path)
            postprocess_text_output(
                output_path,
                args,
                source_kind="pdf",
                progress_callback=progress_callback,
                progress_source=source,
                progress_index=progress_index,
                progress_total=progress_total,
            )
            success = True
            return

        convert_markdown_file(best_md, output_path, args, progress_callback, source, progress_index, progress_total)
        success = True
    except Exception:
        preserve_pdf_tool_temp_dir(args, tmpdir_path, output_path, "MinerU")
        raise
    finally:
        if success and tmpdir_path.exists():
            shutil.rmtree(tmpdir_path, ignore_errors=True)


def run_segmented_mineru_pdf_convert(
    source: Path,
    output_path: Path,
    args: argparse.Namespace,
    page_count: int,
    segment_pages: int,
    progress_callback=None,
    progress_index: int | None = None,
    progress_total: int | None = None,
) -> None:
    tmpdir_path = Path(tempfile.mkdtemp(prefix="mineru-segments-"))
    merged_md = tmpdir_path / "merged.md"
    chunk_paths: list[Path] = []
    success = False
    try:
        ranges = [(start, min(start + segment_pages, page_count)) for start in range(0, page_count, segment_pages)]
        emit_stage(
            progress_callback,
            source,
            progress_index,
            progress_total,
            "mineru",
            f"长 PDF 分段解析：{len(ranges)} 段，每段最多 {segment_pages} 页",
        )
        for idx, (start, end) in enumerate(ranges, start=1):
            segment_pdf = tmpdir_path / f"segment-{idx:03d}-pages-{start + 1}-{end}.pdf"
            segment_output = tmpdir_path / f"segment-{idx:03d}.md"
            write_pdf_segment(source, segment_pdf, start, end)
            emit_stage(
                progress_callback,
                source,
                progress_index,
                progress_total,
                "mineru_progress",
                f"MinerU 分段 {idx}/{len(ranges)}，页 {start + 1}-{end}",
            )
            run_single_mineru_pdf_convert(
                segment_pdf,
                segment_output,
                args,
                progress_callback,
                progress_index,
                progress_total,
            )
            chunk_paths.append(segment_output)

        merge_markdown_segments(chunk_paths, merged_md, ranges)
        if args.output_format == "markdown":
            shutil.copyfile(merged_md, output_path)
            postprocess_text_output(
                output_path,
                args,
                source_kind="pdf",
                progress_callback=progress_callback,
                progress_source=source,
                progress_index=progress_index,
                progress_total=progress_total,
            )
        else:
            convert_markdown_file(merged_md, output_path, args, progress_callback, source, progress_index, progress_total)
        success = True
    except Exception:
        preserve_pdf_tool_temp_dir(args, tmpdir_path, output_path, "MinerU-segments")
        raise
    finally:
        if success and tmpdir_path.exists():
            shutil.rmtree(tmpdir_path, ignore_errors=True)


def write_pdf_segment(source: Path, target: Path, start_page: int, end_page: int) -> None:
    import pymupdf

    with pymupdf.open(str(source)) as src_doc:
        with pymupdf.open() as out_doc:
            out_doc.insert_pdf(src_doc, from_page=start_page, to_page=end_page - 1)
            out_doc.save(str(target))


def merge_markdown_segments(chunk_paths: list[Path], target: Path, ranges: list[tuple[int, int]]) -> None:
    parts = []
    for path, (start, end) in zip(chunk_paths, ranges):
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        parts.append(f"<!-- MinerU segment pages {start + 1}-{end} -->\n\n{text}")
    target.write_text("\n\n".join(parts).rstrip() + "\n", encoding="utf-8")


def run_marker_pdf_convert(
    source: Path,
    output_path: Path,
    args: argparse.Namespace,
    progress_callback=None,
    progress_index: int | None = None,
    progress_total: int | None = None,
) -> None:
    tmpdir_path = Path(tempfile.mkdtemp(prefix="marker-output-"))
    success = False
    try:
        cmd = [
            args.marker_command,
            str(source),
            "--output_dir",
            str(tmpdir_path),
            *args.marker_extra_args,
        ]
        emit_stage(progress_callback, source, progress_index, progress_total, "marker", "Marker 解析 PDF")
        run_pdf_tool_command(
            cmd,
            args,
            source,
            output_path,
            progress_callback,
            progress_index,
            progress_total,
            stage="marker_progress",
            label="Marker",
        )
        if args.dry_run:
            success = True
            return

        emit_stage(progress_callback, source, progress_index, progress_total, "collect", "收集 Marker 输出")
        md_candidates = sorted(tmpdir_path.rglob("*.md"))
        if not md_candidates:
            raise FileNotFoundError("Marker completed but no markdown file was produced.")

        best_md = pick_marker_markdown(md_candidates, source.stem)
        if args.output_format == "markdown":
            emit_stage(progress_callback, source, progress_index, progress_total, "copy", "复制 Markdown 输出")
            shutil.copyfile(best_md, output_path)
            postprocess_text_output(
                output_path,
                args,
                source_kind="pdf",
                progress_callback=progress_callback,
                progress_source=source,
                progress_index=progress_index,
                progress_total=progress_total,
            )
            success = True
            return

        convert_markdown_file(best_md, output_path, args, progress_callback, source, progress_index, progress_total)
        success = True
    except Exception:
        preserve_pdf_tool_temp_dir(args, tmpdir_path, output_path, "Marker")
        raise
    finally:
        if success and tmpdir_path.exists():
            shutil.rmtree(tmpdir_path, ignore_errors=True)


def run_pymupdf4llm_pdf_convert(
    source: Path,
    output_path: Path,
    args: argparse.Namespace,
    progress_callback=None,
    progress_index: int | None = None,
    progress_total: int | None = None,
) -> None:
    use_ocr = should_use_ocr_for_pdf(source)
    ocr_detail = "启用 OCR" if use_ocr else "直接使用文字层"
    emit_stage(progress_callback, source, progress_index, progress_total, "pymupdf", f"PyMuPDF4LLM 解析 PDF - {ocr_detail}")
    try:
        import pymupdf4llm

        with contextlib.redirect_stdout(sys.stderr):
            markdown = pymupdf4llm.to_markdown(
                str(source),
                use_ocr=use_ocr,
                force_text=True,
                show_progress=False,
                ocr_language="eng",
            )
    except Exception as exc:  # noqa: BLE001
        emit_stage(progress_callback, source, progress_index, progress_total, "pymupdf", "PyMuPDF4LLM 失败，改用 PyMuPDF 文本层兜底")
        getattr(args, "_pdf_fallback_diagnostics", []).append(
            {
                "source": str(source),
                "output": str(output_path),
                "started_at": timestamp_now(),
                "from_pipeline": "pymupdf4llm",
                "to_pipeline": "pymupdf-text",
                "reason": str(exc),
                "reason_type": type(exc).__name__,
                "status": "ok",
                "finished_at": timestamp_now(),
            }
        )
        args._last_pdf_pipeline = "pymupdf-text(fallback from pymupdf4llm)"
        markdown = extract_pdf_text_layer_markdown(source)
    with tempfile.TemporaryDirectory(prefix="pymupdf4llm-output-") as tmpdir:
        temp_md = Path(tmpdir) / f"{source.stem}.md"
        temp_md.write_text(markdown, encoding="utf-8")

        if args.output_format == "markdown":
            emit_stage(progress_callback, source, progress_index, progress_total, "copy", "写入回退 Markdown 输出")
            shutil.copyfile(temp_md, output_path)
            postprocess_text_output(
                output_path,
                args,
                source_kind="pdf",
                progress_callback=progress_callback,
                progress_source=source,
                progress_index=progress_index,
                progress_total=progress_total,
            )
            return

        convert_markdown_file(temp_md, output_path, args, progress_callback, source, progress_index, progress_total)


def extract_pdf_text_layer_markdown(source: Path) -> str:
    import pymupdf

    parts = [f"# {source.stem}", ""]
    with pymupdf.open(str(source)) as document:
        for page_index, page in enumerate(document, start=1):
            text = page.get_text("text").strip()
            if not text:
                continue
            parts.append(f"## Page {page_index}")
            parts.append("")
            parts.append(text)
            parts.append("")
    markdown = "\n".join(parts).rstrip() + "\n"
    if markdown.strip() == f"# {source.stem}":
        raise RuntimeError("PyMuPDF text-layer fallback produced no text.")
    return markdown


def run_umi_pdf_convert(
    source: Path,
    output_path: Path,
    args: argparse.Namespace,
    progress_callback=None,
    progress_index: int | None = None,
    progress_total: int | None = None,
) -> None:
    emit_stage(progress_callback, source, progress_index, progress_total, "umi", "Umi-OCR 解析 PDF")
    ocr_engine = create_umi_paddle_engine(args)
    ocr_process = getattr(ocr_engine, "ret", None)
    if ocr_process is not None:
        emit_stage(
            progress_callback,
            source,
            progress_index,
            progress_total,
            "umi",
            f"Umi-OCR 解析 PDF，本次引擎 PID {getattr(ocr_process, 'pid', 'unknown')}",
        )

    import pymupdf

    document = pymupdf.open(str(source))
    try:
        page_count = len(document)
        markdown_pages: list[str] = []
        with tempfile.TemporaryDirectory(prefix="umi-pdf-render-") as tmpdir:
            tmpdir_path = Path(tmpdir)
            for page_number in range(page_count):
                emit_stage(
                    progress_callback,
                    source,
                    progress_index,
                    progress_total,
                    "umi_page",
                    f"Umi-OCR 识别第 {page_number + 1}/{page_count} 页",
                )
                pixmap = document[page_number].get_pixmap(dpi=args.umi_render_dpi)
                image_path = tmpdir_path / f"page-{page_number + 1:04d}.png"
                pixmap.save(str(image_path))
                text = umi_ocr_image(image_path, ocr_engine)
                page_title = f"<!-- Page {page_number + 1} -->"
                page_body = text.strip() if text.strip() else "[No text recognized]"
                markdown_pages.append(f"{page_title}\n\n{page_body}")
    finally:
        document.close()
        close_umi_paddle_engine(ocr_engine)

    markdown = f"# {source.stem}\n\n" + "\n\n".join(markdown_pages) + "\n"
    with tempfile.TemporaryDirectory(prefix="umi-markdown-") as tmpdir:
        temp_md = Path(tmpdir) / f"{source.stem}.md"
        temp_md.write_text(markdown, encoding="utf-8")
        if args.output_format == "markdown":
            emit_stage(progress_callback, source, progress_index, progress_total, "copy", "写入 Umi-OCR Markdown 输出")
            shutil.copyfile(temp_md, output_path)
            postprocess_text_output(
                output_path,
                args,
                source_kind="umi_pdf",
                progress_callback=progress_callback,
                progress_source=source,
                progress_index=progress_index,
                progress_total=progress_total,
            )
            return
        convert_markdown_file(temp_md, output_path, args, progress_callback, source, progress_index, progress_total)


def convert_markdown_file(
    source_md: Path,
    output_path: Path,
    args: argparse.Namespace,
    progress_callback=None,
    progress_source: Path | None = None,
    progress_index: int | None = None,
    progress_total: int | None = None,
) -> None:
    cmd = [
        args.pandoc_command,
        str(source_md),
        "-f",
        "gfm",
        "-t",
        pandoc_target(args),
        "-o",
        str(output_path),
    ]
    emit_stage(
        progress_callback,
        progress_source or source_md,
        progress_index,
        progress_total,
        "pandoc",
        "Pandoc 转换输出格式",
    )
    run_command(cmd, args.dry_run)


def postprocess_text_output(
    output_path: Path,
    args: argparse.Namespace,
    source_kind: str,
    note_source_path: Path | None = None,
    progress_callback=None,
    progress_source: Path | None = None,
    progress_index: int | None = None,
    progress_total: int | None = None,
) -> None:
    if args.dry_run or not output_path.exists():
        return
    if args.output_format != "markdown":
        return

    stage_source = progress_source or output_path
    emit_stage(progress_callback, stage_source, progress_index, progress_total, "postprocess", "Markdown 清洗")
    text = output_path.read_text(encoding="utf-8", errors="replace")
    if source_kind in {"epub", "kindle"}:
        text = clean_epub_markdown(text)
        toc_titles = extract_epub_toc_titles(note_source_path)
        if toc_titles:
            text = apply_toc_headings(text, toc_titles)
        emit_stage(progress_callback, stage_source, progress_index, progress_total, "footnotes", "提取脚注与尾注")
        notes = extract_epub_rearnotes(note_source_path) if note_source_path else {}
        if notes:
            text = inject_markdown_footnotes(text, notes)
    else:
        text = clean_generic_markdown(text)
        if source_kind == "umi_pdf":
            text = clean_umi_ocr_markdown(text)
    output_path.write_text(text, encoding="utf-8")


def clean_epub_markdown(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    text = strip_st_tags(text)

    # Drop EPUB nav landmarks blocks before line-based cleanup.
    text = re.sub(
        r"<nav\b[^>]*epub:type=\"landmarks\"[^>]*>.*?</nav>",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # Drop invisible anchors and noisy block wrappers commonly preserved from EPUB HTML.
    text = re.sub(r'^\s*<span id="[^"]+"></span>\s*$\n?', "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*</?(div|svg)[^>]*>\s*$\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*<image[^>]*>\s*</image>\s*$\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*<img [^>]*>\s*$\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*</?(nav|ol|ul|li)[^>]*>\s*$\n?", "", text, flags=re.MULTILINE)

    # Remove link wrappers around plain TOC blocks while keeping the visible link text.
    text = re.sub(r'^\s*<a [^>]*>(.*?)</a>\s*$',
                  lambda m: m.group(1).strip(),
                  text,
                  flags=re.MULTILINE)

    # Remove navigation headings and boilerplate lines that are not useful in Markdown output.
    lines_to_drop = {
        "# Landmarks",
        "# 总目录",
        "目录",
        "总目录",
        "[返回总目录](#part0000.html#aid-1)",
        "[返回总目录](#aid-1)",
    }
    cleaned_lines: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped in lines_to_drop:
            continue
        if stripped.startswith("[返回总目录]("):
            continue
        cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)

    # Remove the common EPUB cover/titlepage artifact at the very top.
    text = re.sub(r"\A\s*!\[\]\([^)]+\)\s*\n+", "", text, flags=re.MULTILINE)

    # Turn leftover TOC-ish link lines into bullets so structure stays readable.
    text = re.sub(r"^(?![#*-])(\[[^\]]+\]\([^)]+\))\s*$", r"- \1", text, flags=re.MULTILINE)

    # Remove common inline wrapper tags while preserving their text content.
    text = re.sub(r"</?span[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</?font[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</?small[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</?nav[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(ol|ul|li)[^>]*>", "", text, flags=re.IGNORECASE)

    # Normalize emphasis tags to Markdown.
    text = re.sub(r"<\s*(b|strong)[^>]*>(.*?)</\s*(b|strong)\s*>", r"**\2**", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<\s*(i|em)[^>]*>(.*?)</\s*(i|em)\s*>", r"*\2*", text, flags=re.IGNORECASE | re.DOTALL)

    # Turn HTML footnote links into plain visible note markers.
    text = re.sub(
        r"<sup>\s*<a [^>]*>\[(\d+)\]</a>\s*</sup>",
        r"[\1]",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(
        r"<a [^>]*>\[(\d+)\]</a>",
        r"[\1]",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(r"<sup>\s*(.*?)\s*</sup>", r"[\1]", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"</?a[^>]*>", "", text, flags=re.IGNORECASE)

    # Strip the remaining trivial HTML blocks that usually only add visual layout noise.
    text = re.sub(r"</?p[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)

    # Remove empty formatting leftovers introduced by the substitutions above.
    text = re.sub(r"\*\*\s*\*\*", "", text)
    text = re.sub(r"\*\s*\*", "", text)

    # Re-attach note markers that got split onto standalone lines between body lines.
    text = re.sub(r"([^\n])\n{2}\[(\^?\d+)\](?=\n)", r"\1[\2]\n", text)
    text = re.sub(r"([^\n])\n\[(\^?\d+)\](?=\n)", r"\1[\2]", text)
    text = re.sub(r"([^\n])\n\[(\^?\d+)\]\n([^\n])", r"\1[\2]\3", text)

    # Remove pure image lines which are usually cover/title decoration rather than content.
    text = re.sub(r"(?m)^\s*!\[[^\]]*\]\([^)]+\)\s*$\n?", "", text)

    # Drop a leading TOC-style list block before the first real heading/body section.
    text = strip_leading_toc_block(text)

    # Drop leading publication / CIP metadata pages once we reach the first real heading.
    text = strip_leading_front_matter(text)

    # Compact stray blank lines around headings and list items.
    text = re.sub(r"\n{2,}(?=#)", "\n\n", text)
    text = re.sub(r"(?m)^[ \t]+", "", text)
    text = re.sub(r"(?m)^\d+\.\s+\[(.*?)\]\((.*?)\)\s*$", r"- [\1](\2)", text)
    text = re.sub(r"\[\s*(\d+)\s*\]", r"[\1]", text)

    text = promote_plain_chinese_book_headings(text)

    return clean_generic_markdown(text)


def strip_st_tags(text: str) -> str:
    # Some EPUBs generated from PDF/OCR wrap nearly every text span in
    # non-standard <st c="..."> tags. Pandoc preserves them as raw HTML,
    # which makes otherwise valid headings look broken.
    text = re.sub(r"<st\b[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</st>", "", text, flags=re.IGNORECASE)
    return text


def extract_epub_toc_titles(epub_path: Path | None) -> list[str]:
    if epub_path is None or not epub_path.exists():
        return []
    titles: list[str] = []
    try:
        with zipfile.ZipFile(epub_path) as archive:
            for name in archive.namelist():
                lower = name.lower()
                if lower.endswith("toc.ncx"):
                    raw = archive.read(name).decode("utf-8", errors="replace")
                    titles.extend(extract_ncx_titles(raw))
                elif lower.endswith(("nav.xhtml", "nav.html")):
                    raw = archive.read(name).decode("utf-8", errors="replace")
                    titles.extend(extract_nav_titles(raw))
    except Exception:
        return []
    return dedupe_toc_titles(titles)


def extract_ncx_titles(raw: str) -> list[str]:
    titles = []
    for match in re.finditer(r"<navLabel\b[^>]*>.*?<text\b[^>]*>(.*?)</text>.*?</navLabel>", raw, re.I | re.S):
        title = html.unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip()
        if title:
            titles.append(title)
    return titles


def extract_nav_titles(raw: str) -> list[str]:
    titles = []
    nav_match = re.search(r"<nav\b[^>]*(?:epub:type|type)=[\"']toc[\"'][^>]*>(.*?)</nav>", raw, re.I | re.S)
    scope = nav_match.group(1) if nav_match else raw
    for match in re.finditer(r"<a\b[^>]*>(.*?)</a>", scope, re.I | re.S):
        title = html.unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip()
        if title:
            titles.append(title)
    return titles


def dedupe_toc_titles(titles: list[str]) -> list[str]:
    seen: set[str] = set()
    cleaned = []
    for title in titles:
        title = normalize_toc_title(title)
        if not title or len(title) > 120:
            continue
        key = normalize_heading_key(title)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(title)
    return cleaned


def apply_toc_headings(text: str, toc_titles: list[str]) -> str:
    title_keys = {normalize_heading_key(title) for title in toc_titles}
    title_keys.discard("")
    if not title_keys:
        return text
    lines = text.split("\n")
    updated: list[str] = []
    for line in lines:
        stripped = line.strip()
        key = normalize_heading_key(stripped)
        previous_blank = not updated or not updated[-1].strip()
        if (
            key in title_keys
            and stripped
            and not stripped.startswith("#")
            and not stripped.startswith(("-", "*", ">"))
            and len(stripped) <= 120
            and previous_blank
        ):
            updated.append(f"## {stripped}")
        else:
            updated.append(line)
    return "\n".join(updated)


def normalize_toc_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip()
    return title.strip("·•-—– ")


def normalize_heading_key(title: str) -> str:
    title = html.unescape(title)
    title = re.sub(r"^#+\s*", "", title.strip())
    title = re.sub(r"\[[^\]]+\]\([^)]+\)", "", title)
    title = re.sub(r"[\s　]+", "", title)
    title = re.sub(r"[《》“”\"'‘’：:，,。.!！?？、（）()\[\]【】\-—–_·•]", "", title)
    return title.casefold()


def promote_plain_chinese_book_headings(text: str) -> str:
    lines = text.split("\n")
    promoted: list[str] = []
    index = 0
    chapter_re = re.compile(r"^第[一二三四五六七八九十百零〇\d]+章[\s　]*(.+)?$")
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        previous_blank = not promoted or not promoted[-1].strip()
        next_line = lines[index + 1].strip() if index + 1 < len(lines) else ""
        next_next_blank = index + 2 >= len(lines) or not lines[index + 2].strip()

        if not stripped or stripped.startswith("#"):
            promoted.append(line)
            index += 1
            continue

        if chapter_re.match(stripped) and (previous_blank or next_line == "" or len(stripped) <= 80):
            heading = stripped
            if next_line and len(next_line) <= 48 and next_next_blank and not next_line.startswith(("-", ">", "#")):
                heading = f"{heading}　{next_line}"
                index += 1
            promoted.append(f"## {heading}")
            index += 1
            continue

        if stripped in {"致谢", "结语", "后记"} and (previous_blank or next_line == ""):
            promoted.append(f"## {stripped}")
            index += 1
            continue

        if stripped.startswith("附录") and len(stripped) <= 80 and (previous_blank or next_line == ""):
            promoted.append(f"## {stripped}")
            index += 1
            continue

        if stripped == "学习要点" and (previous_blank or next_line == ""):
            promoted.append("### 学习要点")
            index += 1
            continue

        promoted.append(line)
        index += 1

    return "\n".join(promoted)


def clean_generic_markdown(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = normalize_footnote_references(text)
    text = unwrap_hard_wrapped_paragraphs(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return text.strip() + "\n"


def clean_umi_ocr_markdown(text: str) -> str:
    """Keep page boundaries without treating every page as a document heading."""
    lines = text.split("\n")
    cleaned: list[str] = []
    pending_page = False
    promoted_on_page = False
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r"^##\s+Page\s+\d+\s*$", stripped, re.I):
            page_number = re.search(r"\d+", stripped)
            cleaned.append(f"<!-- Page {page_number.group(0) if page_number else ''} -->")
            pending_page = True
            promoted_on_page = False
            continue
        if re.match(r"^<!--\s*Page\s+\d+\s*-->\s*$", stripped, re.I):
            cleaned.append(stripped)
            pending_page = True
            promoted_on_page = False
            continue
        if pending_page and is_umi_ocr_noise_header(stripped):
            cleaned.append(line)
            continue
        if (
            pending_page
            and not promoted_on_page
            and should_promote_umi_ocr_heading(stripped, next_nonempty_line(lines, idx + 1))
        ):
            cleaned.append(f"## {stripped}")
            pending_page = False
            promoted_on_page = True
            continue
        if stripped:
            pending_page = False
        cleaned.append(line)
    text = "\n".join(cleaned)
    text = remove_repeated_ocr_noise_lines(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def remove_repeated_ocr_noise_lines(text: str) -> str:
    """Conservatively drop repeated short OCR headers/footers.

    This targets scanned book artifacts such as a running title repeated on
    many pages. It intentionally avoids Markdown headings and numbered section
    titles so real structure is not silently removed.
    """
    lines = text.split("\n")
    counts: dict[str, int] = {}
    for line in lines:
        stripped = normalize_repeated_noise_key(line)
        if stripped:
            counts[stripped] = counts.get(stripped, 0) + 1
    noisy = {
        key
        for key, count in counts.items()
        if count >= 4 and (len(key) <= 12 or count >= 6)
    }
    if not noisy:
        return text
    kept = []
    for line in lines:
        key = normalize_repeated_noise_key(line)
        if key and key in noisy:
            kept.append(f"<!-- removed repeated OCR header/footer: {line.strip()} -->")
            continue
        kept.append(line)
    return "\n".join(kept)


def normalize_repeated_noise_key(line: str) -> str:
    stripped = re.sub(r"\s+", "", line.strip())
    if not stripped:
        return ""
    if line.lstrip().startswith("#"):
        return ""
    if re.match(r"^<!--\s*Page\s+\d+\s*-->\s*$", line.strip(), re.I):
        return ""
    if re.match(r"^(第[一二三四五六七八九十百千万\d]+[章节篇部卷]|Chapter\d+|Part\w+)", stripped, re.I):
        return ""
    if re.match(r"^\d{1,4}$", stripped):
        return ""
    if len(stripped) > 24:
        return ""
    if re.search(r"[。！？!?；;：:，,、]$", stripped):
        return ""
    return stripped


def next_nonempty_line(lines: list[str], start: int) -> str:
    for line in lines[start:]:
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def should_promote_umi_ocr_heading(line: str, next_line: str) -> bool:
    if not line or line.startswith(("#", "-", "*", ">", "|", "<!--")):
        return False
    if len(line) > 24:
        return False
    if re.match(r"^[\d\s().（）\-—–]+$", line):
        return False
    if re.match(r"^[A-Za-z]{1,8}$", line):
        return False
    if is_umi_ocr_noise_header(line):
        return False
    if line in {"目", "录", "MULU"}:
        return False
    if not next_line:
        return True
    if len(next_line) >= 18:
        return True
    if line in {"目录", "序", "编者的话", "出版者的话"}:
        return True
    return False


def is_umi_ocr_noise_header(line: str) -> bool:
    if not line:
        return False
    noisy_headers = {"高中医", "名老中医走路", "多老中医建露", "老中医", "·老中匠"}
    if line in noisy_headers:
        return True
    if line.startswith(("·", "•")) and len(line) <= 12:
        return True
    return False


def strip_leading_toc_block(text: str) -> str:
    lines = text.split("\n")
    if not lines:
        return text

    keep_from = 0
    toc_like_count = 0
    body_seen = False
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# "):
            if toc_like_count >= 3 and not body_seen:
                keep_from = idx
            break
        if re.match(r"^- \[[^\]]+\]\([^)]+\)$", stripped):
            toc_like_count += 1
            continue
        if re.match(r"^\d+\.\s+\[[^\]]+\]\([^)]+\)$", stripped):
            toc_like_count += 1
            continue
        if toc_like_count and not body_seen:
            body_seen = True
            continue
        break

    if keep_from > 0:
        candidate = "\n".join(lines[keep_from:])
        if is_safe_markdown_trim(text, candidate):
            return candidate
    return text


def extract_epub_rearnotes(epub_path: Path | None) -> dict[int, str]:
    if epub_path is None or not epub_path.exists():
        return {}

    notes: dict[int, str] = {}
    with zipfile.ZipFile(epub_path) as archive:
        candidates = sorted(
            name
            for name in archive.namelist()
            if name.lower().endswith((".html", ".xhtml"))
        )
        for name in candidates:
            raw = archive.read(name).decode("utf-8", errors="replace")
            if "epub:type=\"rearnote\"" not in raw and "id=\"footnote_" not in raw:
                continue
            for match in re.finditer(
                r"<aside\b[^>]*id=\"footnote_(\d+)\"[^>]*>.*?<p\b[^>]*>(.*?)</p>.*?</aside>",
                raw,
                flags=re.IGNORECASE | re.DOTALL,
            ):
                number = int(match.group(1))
                body = match.group(2)
                body = re.sub(r"<a\b[^>]*>\[(\d+)\]</a>", "", body, flags=re.IGNORECASE)
                body = re.sub(r"<br\s*/?>", "\n", body, flags=re.IGNORECASE)
                body = re.sub(r"</?[^>]+>", "", body)
                body = html.unescape(body)
                body = re.sub(r"[ \t]+\n", "\n", body)
                body = re.sub(r"\n{2,}", "\n", body)
                body = re.sub(r"[ \t]{2,}", " ", body)
                body = body.strip()
                if body:
                    notes[number] = body
    return notes


def inject_markdown_footnotes(text: str, notes: dict[int, str]) -> str:
    if not notes:
        return text

    note_block = "\n".join(f"[^{number}]: {notes[number]}" for number in sorted(notes))

    section_pattern = re.compile(
        r"(^## 注释\s*$)(.*?)(?=^## |\Z)",
        flags=re.MULTILINE | re.DOTALL,
    )
    match = section_pattern.search(text)
    if match:
        replacement = f"{match.group(1)}\n\n{note_block}\n\n"
        return text[:match.start()] + replacement + text[match.end():]

    appendix_pattern = re.compile(r"(^# APPENDIX .*?$)", flags=re.MULTILINE)
    appendix_match = appendix_pattern.search(text)
    if appendix_match:
        insertion = f"## 注释\n\n{note_block}\n\n"
        return text[:appendix_match.end()] + "\n\n" + insertion + text[appendix_match.end():]

    return text.rstrip() + "\n\n## 注释\n\n" + note_block + "\n"


def normalize_footnote_references(text: str) -> str:
    return re.sub(r"\[(\d+)\]", r"[^\1]", text)


def unwrap_hard_wrapped_paragraphs(text: str) -> str:
    lines = text.split("\n")
    if not lines:
        return text

    merged: list[str] = []
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        stripped = line.strip()
        if not stripped:
            merged.append("")
            idx += 1
            continue

        current = stripped
        while idx + 1 < len(lines):
            next_line = lines[idx + 1].strip()
            if not next_line:
                break
            if not is_plain_paragraph_line(current) or not is_plain_paragraph_line(next_line):
                break
            if len(current) <= 8 or len(next_line) <= 8:
                break
            if re.search(r"[。！？!?；;：:：”’」』】》]$", current):
                break
            current += next_line
            idx += 1

        merged.append(current)
        idx += 1

    return "\n".join(merged)


def is_plain_paragraph_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    markdown_prefixes = ("#", "-", "*", ">", "|", "```")
    if stripped.startswith(markdown_prefixes):
        return False
    if re.match(r"^\d+\.\s", stripped):
        return False
    if re.match(r"^\[[^\]]+\]:", stripped):
        return False
    if re.match(r"^!\[[^\]]*\]\([^)]+\)$", stripped):
        return False
    return True


def is_safe_markdown_trim(original: str, candidate: str) -> bool:
    original_len = len(original.strip())
    candidate_len = len(candidate.strip())
    if original_len < 5000:
        return True
    if candidate_len < 1000:
        return False
    if candidate_len < original_len * 0.2:
        return False

    original_lines = [line for line in original.splitlines() if line.strip()]
    candidate_lines = [line for line in candidate.splitlines() if line.strip()]
    if len(original_lines) >= 200 and len(candidate_lines) < 25:
        return False
    return True


def strip_leading_front_matter(text: str) -> str:
    lines = text.split("\n")
    if not lines:
        return text

    metadata_markers = (
        "图书在版编目",
        "cip",
        "isbn",
        "copyright",
        "all rights reserved",
        "书名原文",
        "著作权合同登记号",
        "出版",
        "出版人",
        "责任编辑",
        "特约编辑",
        "产品经理",
        "封面设计",
        "制版印刷",
        "经销",
        "发行",
        "地址",
        "邮政编码",
        "邮购电话",
        "网址",
        "电子信箱",
        "开本",
        "印张",
        "印数",
        "字数",
        "版次印次",
        "定价",
        "版权所有",
        "侵权必究",
        "published by arrangement",
        "simplified chinese translation copyright",
    )

    heading_indexes = [idx for idx, line in enumerate(lines) if line.strip().startswith("# ")]
    if not heading_indexes:
        return text

    front_matter_titles = {"扉页", "版权页", "书名页", "封面"}

    def count_marker_hits(chunk: list[str]) -> int:
        hits = 0
        for line in chunk:
            lower = line.strip().lower()
            if any(marker in lower for marker in metadata_markers):
                hits += 1
        return hits

    chosen_idx: int | None = None
    for idx in heading_indexes:
        heading_title = lines[idx].strip()[2:].strip()
        window = [line for line in lines[idx:min(len(lines), idx + 30)] if line.strip()]
        window_hits = count_marker_hits(window)
        if heading_title in front_matter_titles and window_hits >= 3:
            continue
        if window_hits >= 5:
            continue
        chosen_idx = idx
        break

    if chosen_idx is None or chosen_idx == 0:
        return text

    prefix_lines = [line for line in lines[:chosen_idx] if line.strip()]
    prefix_hits = count_marker_hits(prefix_lines)
    if prefix_hits >= 3 or len(prefix_lines) <= 5:
        candidate = "\n".join(lines[chosen_idx:])
        if is_safe_markdown_trim(text, candidate):
            return candidate

    return text


def pick_marker_markdown(candidates: list[Path], stem: str) -> Path:
    exact = [path for path in candidates if path.stem == stem]
    if exact:
        return exact[0]
    return candidates[0]


def pick_mineru_markdown(candidates: list[Path], stem: str) -> Path:
    exact = [path for path in candidates if path.stem == stem]
    if exact:
        return exact[0]

    stem_lower = stem.lower()
    named = [path for path in candidates if stem_lower in path.stem.lower()]
    if named:
        return max(named, key=lambda path: path.stat().st_size)

    return max(candidates, key=lambda path: path.stat().st_size)


def save_mineru_artifacts(mineru_output_dir: Path, output_path: Path) -> Path:
    artifact_root = output_path.parent / ".mineru" / output_path.stem
    if artifact_root.exists():
        shutil.rmtree(artifact_root)
    artifact_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        mineru_output_dir,
        artifact_root,
        ignore=shutil.ignore_patterns("*.pdf", "images", "*.jpg", "*.jpeg", "*.png"),
    )
    return artifact_root


def preserve_pdf_tool_temp_dir(args: argparse.Namespace, tmpdir_path: Path, output_path: Path, label: str) -> Path | None:
    if not tmpdir_path.exists():
        return None
    report_dir = getattr(args, "report_dir", None)
    if report_dir is None:
        report_dir = output_path.parent / ".reports"
    else:
        report_dir = Path(report_dir)
    artifact_root = report_dir / "pdf-tool-artifacts"
    artifact_root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(str(tmpdir_path).encode("utf-8", errors="replace")).hexdigest()[:8]
    target = artifact_root / f"{time.strftime('%Y%m%d-%H%M%S')}-{label.lower()}-{safe_report_name(output_path.stem)[:80]}-{digest}"
    try:
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        shutil.move(str(tmpdir_path), str(target))
    except Exception:
        return tmpdir_path
    diagnostics = getattr(args, "_pdf_tool_diagnostics", [])
    if diagnostics:
        diagnostics[-1]["preserved_temp_dir"] = str(target)
    return target


def write_mineru_quality_report(artifact_root: Path, output_path: Path) -> None:
    try:
        from ebook_markdown_pipeline.analyze_mineru_difficult_pages import find_middle_json, score_middle_json
    except Exception:
        from analyze_mineru_difficult_pages import find_middle_json, score_middle_json

    try:
        middle_json = find_middle_json(artifact_root)
        scores = score_middle_json(middle_json)
    except Exception as exc:  # noqa: BLE001
        report = f"# PDF Quality Report\n\nFailed to analyze MinerU artifacts: {exc}\n"
        quality_report_path(output_path).write_text(report, encoding="utf-8")
        return

    candidates = [item for item in scores if item.score >= 6]
    top_items = sorted(scores, key=lambda row: (-row.score, row.page))[:60]
    lines = [
        "# PDF Quality Report",
        "",
        f"- Source Markdown: `{output_path.name}`",
        f"- Pages analyzed: {len(scores)}",
        f"- Difficult page candidates: {len(candidates)}",
        f"- MinerU middle JSON: `{middle_json}`",
        "",
        "## Difficult Pages",
        "",
    ]
    if not candidates:
        lines.append("No high-risk pages were detected with the current threshold.")
    else:
        lines.append("| PDF page | Score | Text chars | Reasons |")
        lines.append("| --- | ---: | ---: | --- |")
        for item in top_items:
            if item.score < 1:
                continue
            reason_text = "; ".join(item.reasons) if item.reasons else "normal"
            lines.append(f"| {item.page + 1} | {item.score} | {item.text_chars} | {reason_text} |")

    report_path = quality_report_path(output_path)
    report_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def quality_report_path(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.stem}.quality.md")


def pdf_tool_log_path(args: argparse.Namespace, source: Path, output_path: Path, label: str) -> Path:
    report_dir = getattr(args, "report_dir", None)
    if report_dir is None:
        report_dir = output_path.parent / ".reports"
    else:
        report_dir = Path(report_dir)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    digest = hashlib.sha1(str(source).encode("utf-8", errors="replace")).hexdigest()[:8]
    tool = re.sub(r"[^A-Za-z0-9_.-]+", "-", label.lower()).strip("-") or "pdf-tool"
    safe_stem = safe_report_name(output_path.stem)[:90].rstrip(" ._-") or "converted-book"
    return report_dir / "pdf-tool-logs" / f"{timestamp}-{tool}-{safe_stem}-{digest}.log"


def write_conversion_report(result: ConversionResult, args: argparse.Namespace, output_path: Path) -> None:
    if getattr(args, "no_reports", False):
        return
    report_dir = getattr(args, "report_dir", None)
    if report_dir is None:
        report_dir = output_path.parent / ".reports"
    else:
        report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{safe_report_name(output_path.stem)}.report.json"
    payload = asdict(result)
    payload["report"] = str(report_path)
    payload["source_exists"] = Path(result.source).exists()
    payload["output_exists"] = bool(result.output and Path(result.output).exists())
    payload["output_size_bytes"] = Path(result.output).stat().st_size if result.output and Path(result.output).exists() else 0
    if result.output and Path(result.output).exists():
        quality = analyze_markdown_quality(Path(result.output))
        if quality:
            payload["quality"] = asdict(quality)
    if Path(result.source).suffix.lower() == ".pdf":
        payload["pdf_preflight"] = asdict(pdf_preflight(Path(result.source), args))
        payload["pdf_outline"] = extract_pdf_outline(Path(result.source))
        diagnostics = getattr(args, "_pdf_tool_diagnostics", [])
        if diagnostics:
            payload["pdf_tool_diagnostics"] = diagnostics
        fallback_diagnostics = getattr(args, "_pdf_fallback_diagnostics", [])
        if fallback_diagnostics:
            payload["pdf_fallback_diagnostics"] = fallback_diagnostics
    docling_diagnostics = getattr(args, "_docling_diagnostics", [])
    if docling_diagnostics:
        payload["docling_diagnostics"] = docling_diagnostics
    calibre_fallback_diagnostics = getattr(args, "_calibre_fallback_diagnostics", [])
    if calibre_fallback_diagnostics:
        payload["calibre_fallback_diagnostics"] = calibre_fallback_diagnostics
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    result.report = str(report_path)


def write_batch_summary(results: list[ConversionResult], args: argparse.Namespace) -> None:
    if getattr(args, "no_reports", False):
        return
    summary_path = getattr(args, "summary", None)
    report_dir = getattr(args, "report_dir", None)
    if summary_path is None:
        if report_dir is None:
            output_root = getattr(args, "output", None)
            if output_root is None:
                return
            report_root = Path(output_root) / ".reports"
        else:
            report_root = Path(report_dir)
        summary_path = report_root / "summary.md"
    else:
        summary_path = Path(summary_path)
        report_root = summary_path.parent
    report_root.mkdir(parents=True, exist_ok=True)

    entries = [load_report_snapshot(result) for result in results]
    summary_json = summary_path.with_suffix(".json")
    summary_json.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path.write_text(render_batch_summary_markdown(entries, summary_json), encoding="utf-8")
    checklist_entries = build_review_checklist_entries(entries)
    checklist_json = report_root / "review-checklist.json"
    checklist_md = report_root / "review-checklist.md"
    checklist_json.write_text(json.dumps(checklist_entries, ensure_ascii=False, indent=2), encoding="utf-8")
    checklist_md.write_text(render_review_checklist_markdown(checklist_entries, checklist_json), encoding="utf-8")


def load_report_snapshot(result: ConversionResult) -> dict:
    payload = asdict(result)
    if result.report and Path(result.report).exists():
        try:
            payload.update(json.loads(Path(result.report).read_text(encoding="utf-8")))
        except Exception:
            pass
    return payload


def render_batch_summary_markdown(entries: list[dict], summary_json: Path) -> str:
    total = len(entries)
    status_counts = count_by(entries, "status")
    pipeline_counts = count_by(entries, "pipeline")
    quality_counts = count_nested(entries, "quality", "level")
    pdf_risk_count = sum(1 for item in entries if (item.get("pdf_preflight") or {}).get("scanned_likely"))
    failed = [item for item in entries if item.get("status") == "failed"]
    review_items = [
        item
        for item in entries
        if (item.get("quality") or {}).get("level") in {"review", "poor"} or item.get("status") == "failed"
    ]

    lines = [
        "# Conversion Summary",
        "",
        f"- Generated: {timestamp_now()}",
        f"- Total files: {total}",
        f"- Status: {format_counts(status_counts)}",
        f"- Pipelines: {format_counts(pipeline_counts)}",
        f"- Quality: {format_counts(quality_counts) if quality_counts else 'n/a'}",
        f"- PDF scanned-like: {pdf_risk_count}",
        f"- JSON summary: `{summary_json}`",
        "",
    ]

    if failed:
        lines.extend(["## Failed", "", "| Source | Pipeline | Message |", "| --- | --- | --- |"])
        for item in failed:
            lines.append(
                f"| {escape_table(Path(str(item.get('source', ''))).name)} | "
                f"{escape_table(str(item.get('pipeline', '')))} | "
                f"{escape_table(str(item.get('message', ''))[:240])} |"
            )
        lines.append("")

    lines.extend(["## Review Queue", "", "| Level | Score | Source | Pipeline | Reasons |", "| --- | ---: | --- | --- | --- |"])
    if not review_items:
        lines.append("| good | 100 | No review candidates | - | - |")
    else:
        for item in sorted(review_items, key=summary_sort_key):
            quality = item.get("quality") or {}
            reasons = "; ".join(quality.get("reasons") or [])
            if not reasons and item.get("status") == "failed":
                reasons = item.get("message", "")
            lines.append(
                f"| {escape_table(str(quality.get('level', item.get('status', ''))))} | "
                f"{quality.get('score', '')} | "
                f"{escape_table(Path(str(item.get('source', ''))).name)} | "
                f"{escape_table(str(item.get('pipeline', '')))} | "
                f"{escape_table(str(reasons)[:260])} |"
            )

    return "\n".join(lines).rstrip() + "\n"


def build_review_checklist_entries(entries: list[dict]) -> list[dict]:
    checklist = []
    for item in entries:
        quality = item.get("quality") or {}
        preflight = item.get("pdf_preflight") or {}
        outline = item.get("pdf_outline") or {}
        status = item.get("status")
        level = quality.get("level")
        if status != "failed" and level not in {"review", "poor"} and not preflight.get("scanned_likely"):
            continue
        checklist.append(
            {
                "source": item.get("source"),
                "output": item.get("output"),
                "report": item.get("report"),
                "status": status,
                "pipeline": item.get("pipeline"),
                "quality_level": level,
                "quality_score": quality.get("score"),
                "quality_reasons": quality.get("reasons") or [],
                "pdf_scanned_likely": preflight.get("scanned_likely"),
                "pdf_complex_layout_likely": preflight.get("complex_layout_likely"),
                "pdf_outline_count": outline.get("count"),
                "pdf_outline_items": (outline.get("items") or [])[:10],
                "pdf_reasons": preflight.get("reasons") or [],
                "suggested_action": suggest_review_action(item),
                "next_actions": suggest_review_next_actions(item),
            }
        )
    return sorted(checklist, key=review_checklist_sort_key)


def render_review_checklist_markdown(entries: list[dict], checklist_json: Path) -> str:
    lines = [
        "# Review Checklist",
        "",
        f"- Generated: {timestamp_now()}",
        f"- Review candidates: {len(entries)}",
        f"- JSON checklist: `{checklist_json}`",
        "",
        "| Status | Quality | Source | Suggested action | Reasons |",
        "| --- | --- | --- | --- | --- |",
    ]
    if not entries:
        lines.append("| ok | good | No review candidates | - | - |")
    for item in entries:
        reasons = "; ".join((item.get("quality_reasons") or []) + (item.get("pdf_reasons") or []))
        next_actions = ", ".join(action.get("action", "") for action in item.get("next_actions") or [])
        lines.append(
            f"| {escape_table(str(item.get('status') or ''))} | "
            f"{escape_table(str(item.get('quality_level') or 'n/a'))} {item.get('quality_score') or ''} | "
            f"{escape_table(Path(str(item.get('source') or '')).name)} | "
            f"{escape_table(str(item.get('suggested_action') or '') + ('; next: ' + next_actions if next_actions else ''))} | "
            f"{escape_table(reasons[:300])} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def suggest_review_action(item: dict) -> str:
    status = item.get("status")
    pipeline = str(item.get("pipeline") or "")
    quality = item.get("quality") or {}
    preflight = item.get("pdf_preflight") or {}
    reasons = "；".join(quality.get("reasons") or [])
    if status == "failed":
        return "先打开 report 查看 message；若是 PDF 工具失败，按顺序尝试 --pdf-pipeline-mode pymupdf4llm、mineru、umi"
    if preflight.get("scanned_likely") and "mineru" not in pipeline.lower():
        return "疑似扫描 PDF：优先用 --pdf-pipeline-mode mineru 重跑；如果只需文字或页级定位，用 umi 或定位索引"
    if preflight.get("complex_layout_likely") and "mineru" not in pipeline.lower():
        return "复杂版面/表格/多栏：建议用 --pdf-pipeline-mode mineru 或 docling 对比结构"
    if quality.get("level") == "poor":
        if "没有 Markdown 标题" in reasons or "章节层级" in reasons:
            return "标题层级差：电子书优先检查 TOC；PDF 建议用 mineru/docling 重跑并对比 review-checklist"
        if "页码" in reasons:
            return "页码噪声高：检查是否按页切分；PDF 建议 mineru/docling，电子书检查目录增强结果"
        if "OCR" in reasons or "短行" in reasons:
            return "疑似 OCR 断行：抽查原图/PDF；必要时提高 OCR DPI 或改用 Umi-OCR/MinerU"
        return "质量 poor：先打开输出和 report 人工复查，再换管道重跑对比"
    if quality.get("reasons"):
        return "按 reasons 抽查对应问题；重点看标题层级、页码噪声、脚注、乱码和 HTML 残留"
    return "人工抽查"


def suggest_review_next_actions(item: dict) -> list[dict[str, str]]:
    status = item.get("status")
    source = str(item.get("source") or "")
    output = str(item.get("output") or "")
    report = str(item.get("report") or "")
    pipeline = str(item.get("pipeline") or "").lower()
    quality = item.get("quality") or {}
    reasons = "；".join(quality.get("reasons") or [])
    preflight = item.get("pdf_preflight") or {}
    outline = item.get("pdf_outline") or {}
    source_suffix = Path(source).suffix.lower()

    actions: list[dict[str, str]] = []
    if report:
        actions.append({"action": "read_report", "path": report, "why": "inspect converter diagnostics and quality reasons"})
    if output:
        actions.append({"action": "open_output", "path": output, "why": "spot-check visible structure before replacing any existing file"})
    if status == "failed":
        fallback = "pymupdf4llm" if source_suffix == ".pdf" else "auto"
        actions.append({"action": "rerun", "pipeline": fallback, "why": "recover a failed conversion with a lightweight fallback"})
        return actions
    if source_suffix == ".pdf":
        if int(outline.get("count") or 0) > 0 and quality.get("level") in {"review", "poor"}:
            actions.append({"action": "inspect_pdf_outline", "why": "compare generated Markdown headings with built-in PDF bookmarks"})
        if preflight.get("scanned_likely"):
            actions.append({"action": "rerun", "pipeline": "umi", "why": "long or scanned PDF may need OCR-first extraction"})
            actions.append({"action": "export_location_review_pack", "why": "verify representative OCR pages/images before accepting output"})
        elif preflight.get("complex_layout_likely") or "没有 Markdown 标题" in reasons or "章节层级" in reasons:
            preferred = "docling" if "mineru" in pipeline else "mineru"
            actions.append({"action": "compare_pdf_pipelines", "pipelines": "mineru,docling,pymupdf4llm", "why": "compare structure recovery rather than trusting one parser"})
            actions.append({"action": "rerun", "pipeline": preferred, "why": "try a structure-aware PDF backend"})
        elif "页码" in reasons:
            actions.append({"action": "rerun", "pipeline": "docling", "why": "reduce page-heading style output when structure is weak"})
    elif source_suffix in CALIBRE_INTERMEDIATE_FORMATS | PANDOC_DIRECT_FORMATS:
        if "没有 Markdown 标题" in reasons or "章节层级" in reasons:
            actions.append({"action": "inspect_toc", "why": "align EPUB/Calibre TOC titles with body text before manual cleanup"})
        if "输出文本很短" in reasons:
            actions.append({"action": "rerun", "pipeline": "calibre+pandoc", "why": "verify source conversion before post-processing"})
    if quality.get("level") in {"review", "poor"}:
        actions.append({"action": "manual_accept_or_score", "why": "record human judgment so future batches can be filtered"})
    return actions


def review_checklist_sort_key(item: dict) -> tuple[int, int]:
    if item.get("status") == "failed":
        return (0, 0)
    score = item.get("quality_score")
    return (1, int(score) if score is not None else 999)


def count_by(entries: list[dict], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in entries:
        value = str(item.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


def count_nested(entries: list[dict], parent: str, key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in entries:
        nested = item.get(parent) or {}
        value = nested.get(key)
        if not value:
            continue
        counts[str(value)] = counts.get(str(value), 0) + 1
    return counts


def format_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) if counts else "n/a"


def summary_sort_key(item: dict) -> tuple[int, int]:
    quality = item.get("quality") or {}
    status_rank = 0 if item.get("status") == "failed" else 1
    return (status_rank, int(quality.get("score") or 999))


def escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def analyze_markdown_quality(path: Path) -> MarkdownQuality | None:
    if path.suffix.lower() not in {".md", ".markdown", ".txt"}:
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    lines = text.splitlines()
    nonempty = [line.strip() for line in lines if line.strip()]
    headings = [line for line in nonempty if re.match(r"^#{1,6}\s+\S", line)]
    page_headings = [line for line in headings if re.match(r"^#{1,6}\s+(page|第?\s*\d+\s*页|p\.?\s*\d+)\b", line, re.I)]
    page_number_lines = [line for line in nonempty if re.match(r"^(第\s*)?\d{1,4}\s*(页)?$", line)]
    footnote_like_lines = [
        line
        for line in nonempty
        if re.match(r"^(\[\^?\d+\]|\(\d+\)|\d+[\.、])\s*", line) or "脚注" in line or "注释" in line
    ]
    html_tag_lines = [line for line in nonempty if re.search(r"</?(div|span|p|br|html|body|section|aside|st)\b", line, re.I)]
    replacement_chars = text.count("\ufffd")
    short_lines = [line for line in nonempty if 0 < len(line) <= 8 and not re.match(r"^#{1,6}\s+", line)]
    short_line_ratio = round(len(short_lines) / max(len(nonempty), 1), 3)
    repeated_noise_keys: dict[str, int] = {}
    for line in nonempty:
        key = normalize_repeated_noise_key(line)
        if key:
            repeated_noise_keys[key] = repeated_noise_keys.get(key, 0) + 1
    repeated_noise_lines = sum(count for count in repeated_noise_keys.values() if count >= 4)

    score = 100
    reasons: list[str] = []
    if len(text) < 500:
        score -= 45
        reasons.append("输出文本很短，可能没有完整转换")
    if not headings and len(text) >= 1000:
        score -= 25
        reasons.append("没有 Markdown 标题，章节层级可能缺失")
    if headings and len(page_headings) / max(len(headings), 1) > 0.7:
        score -= 25
        reasons.append("大部分标题像页码，可能按页面而非原书目录分层")
    if len(page_number_lines) / max(len(nonempty), 1) > 0.08:
        score -= 12
        reasons.append("疑似页码行较多")
    if len(footnote_like_lines) / max(len(nonempty), 1) > 0.18:
        score -= 10
        reasons.append("疑似脚注/尾注密度偏高")
    if html_tag_lines:
        score -= min(15, len(html_tag_lines))
        reasons.append("存在 HTML 标签残留")
    if replacement_chars:
        score -= min(20, replacement_chars)
        reasons.append("存在乱码替换字符")
    if short_line_ratio > 0.45 and len(nonempty) > 30:
        score -= 10
        reasons.append("短行比例偏高，可能存在 OCR 断行或目录/页眉页脚噪声")
    if repeated_noise_lines >= 4:
        score -= min(12, repeated_noise_lines // 2)
        reasons.append("检测到重复短行，可能存在页眉/页脚噪声")

    score = max(0, min(100, score))
    if score >= 85:
        level = "good"
    elif score >= 65:
        level = "review"
    else:
        level = "poor"

    return MarkdownQuality(
        score=score,
        level=level,
        headings=len(headings),
        page_headings=len(page_headings),
        lines=len(lines),
        nonempty_lines=len(nonempty),
        characters=len(text),
        page_number_lines=len(page_number_lines),
        footnote_like_lines=len(footnote_like_lines),
        html_tag_lines=len(html_tag_lines),
        replacement_chars=replacement_chars,
        short_line_ratio=short_line_ratio,
        repeated_noise_lines=repeated_noise_lines,
        reasons=reasons,
    )


def safe_report_name(stem: str) -> str:
    safe = sanitize_output_stem(stem)
    return safe[:140].rstrip(" ._-") or "converted-book"


def timestamp_now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def run_command(
    cmd: list[str],
    dry_run: bool,
    env: dict[str, str] | None = None,
    *,
    capture_output: bool = True,
) -> None:
    if dry_run:
        print("DRY RUN:", format_cmd(cmd))
        return
    kwargs = {
        "check": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "env": env,
    }
    if capture_output:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    subprocess.run(cmd, **kwargs)


def run_pdf_tool_command(
    cmd: list[str],
    args: argparse.Namespace,
    source: Path,
    output_path: Path,
    progress_callback,
    progress_index: int | None,
    progress_total: int | None,
    *,
    stage: str,
    label: str,
    env: dict[str, str] | None = None,
) -> None:
    if args.dry_run:
        print("DRY RUN:", format_cmd(cmd))
        return

    page_count = max(pdf_preflight(source, args).page_count, 0)
    log_path = pdf_tool_log_path(args, source, output_path, label)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostic: dict[str, object] = {
        "tool": label,
        "stage": stage,
        "source": str(source),
        "output": str(output_path),
        "log": str(log_path),
        "command": cmd,
        "started_at": timestamp_now(),
        "page_count": page_count,
        "last_page": None,
        "last_output_at": None,
        "finalizing_started_at": None,
        "duration_seconds": None,
        "exit_code": None,
        "status": "running",
        "last_lines": [],
    }
    getattr(args, "_pdf_tool_diagnostics", []).append(diagnostic)
    log_file = log_path.open("w", encoding="utf-8", errors="replace")

    def log_event(kind: str, message: str | dict[str, object]) -> None:
        payload = message if isinstance(message, dict) else {"message": message}
        log_file.write(json.dumps({"time": timestamp_now(), "kind": kind, **payload}, ensure_ascii=False) + "\n")
        log_file.flush()

    log_event(
        "start",
        {
            "tool": label,
            "stage": stage,
            "source": str(source),
            "output": str(output_path),
            "command": cmd,
            "page_count": page_count,
        },
    )
    emit_stage(
        progress_callback,
        source,
        progress_index,
        progress_total,
        stage,
        f"{label} 日志写入 {log_path}",
    )
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    except Exception as exc:
        diagnostic["status"] = "spawn_failed"
        diagnostic["error"] = str(exc)
        log_event("spawn_failed", {"error": str(exc)})
        log_file.close()
        raise
    diagnostic["pid"] = process.pid
    log_event("process", {"pid": process.pid})
    lines: list[str] = []
    output_queue: queue.Queue[str | None] = queue.Queue()

    def reader() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            output_queue.put(line)
        output_queue.put(None)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()

    started = time.monotonic()
    last_emit = 0.0
    last_output_at = started
    finalizing_since: float | None = None
    last_page: int | None = None
    while True:
        try:
            line = output_queue.get(timeout=1.0)
        except queue.Empty:
            line = ""

        now = time.monotonic()
        if line is None:
            break
        if line:
            clean = line.strip()
            if clean:
                last_output_at = now
                diagnostic["last_output_at"] = timestamp_now()
                lines.append(clean)
                log_event("stdout", clean)
                parsed = parse_pdf_tool_progress(clean, page_count)
                if parsed:
                    last_page = parsed
                    diagnostic["last_page"] = parsed
                    if page_count and parsed >= page_count and finalizing_since is None:
                        finalizing_since = now
                        diagnostic["finalizing_started_at"] = timestamp_now()
                        log_event("finalizing", {"last_page": parsed, "page_count": page_count})
                    emit_pdf_tool_progress(
                        progress_callback,
                        source,
                        progress_index,
                        progress_total,
                        stage,
                        label,
                        started,
                        page_count,
                        last_page,
                        finalizing_since=finalizing_since,
                        no_output_seconds=0.0,
                    )
                    last_emit = now
                    continue

        if now - last_emit >= 5.0:
            if page_count and last_page and last_page >= page_count and finalizing_since is None:
                finalizing_since = now
                diagnostic["finalizing_started_at"] = timestamp_now()
                log_event("finalizing", {"last_page": last_page, "page_count": page_count})
            idle_seconds = now - last_output_at
            finalizing_seconds = now - finalizing_since if finalizing_since else 0.0
            timeout_reason = pdf_tool_timeout_reason(args, idle_seconds, finalizing_seconds)
            if timeout_reason:
                diagnostic["status"] = "timeout"
                diagnostic["timeout_reason"] = timeout_reason
                diagnostic["last_page"] = last_page
                diagnostic["duration_seconds"] = round(now - started, 3)
                diagnostic["finished_at"] = timestamp_now()
                diagnostic["last_lines"] = lines[-20:]
                log_event(
                    "timeout",
                    {
                        "reason": timeout_reason,
                        "elapsed_seconds": round(now - started, 3),
                        "last_page": last_page,
                        "page_count": page_count,
                        "idle_seconds": round(idle_seconds, 3),
                        "finalizing_seconds": round(finalizing_seconds, 3) if finalizing_since else None,
                    },
                )
                terminate_process_tree(process)
                log_file.close()
                raise PdfToolTimeoutError(f"{label} timed out: {timeout_reason}", diagnostic)
            log_event(
                "heartbeat",
                {
                    "elapsed_seconds": round(now - started, 3),
                    "last_page": last_page,
                    "page_count": page_count,
                    "no_output_seconds": round(idle_seconds, 3),
                    "finalizing_seconds": round(finalizing_seconds, 3) if finalizing_since else None,
                },
            )
            emit_pdf_tool_progress(
                progress_callback,
                source,
                progress_index,
                progress_total,
                stage,
                label,
                started,
                page_count,
                last_page,
                finalizing_since=finalizing_since,
                no_output_seconds=now - last_output_at,
            )
            last_emit = now

    return_code = process.wait()
    thread.join(timeout=1.0)
    duration_seconds = time.monotonic() - started
    diagnostic["duration_seconds"] = round(duration_seconds, 3)
    diagnostic["exit_code"] = return_code
    diagnostic["status"] = "ok" if return_code == 0 else "failed"
    diagnostic["finished_at"] = timestamp_now()
    diagnostic["last_lines"] = lines[-20:]
    log_event(
        "exit",
        {
            "exit_code": return_code,
            "duration_seconds": round(duration_seconds, 3),
            "last_page": last_page,
            "page_count": page_count,
            "line_count": len(lines),
        },
    )
    log_file.close()
    if return_code != 0:
        output = "\n".join(lines[-80:])
        raise subprocess.CalledProcessError(return_code, cmd, output=output, stderr=output)


def parse_pdf_tool_progress(line: str, page_count: int) -> int | None:
    lowered = line.lower()
    patterns = [
        r"(?:page|pages|页)\s*[:#]?\s*(\d{1,5})\s*(?:/|of|共)\s*(\d{1,5})",
        r"(\d{1,5})\s*/\s*(\d{1,5})\s*(?:page|pages|页)?",
        r"第\s*(\d{1,5})\s*页",
        r"(?:processing|processed|parse|ocr).*?(?:page|页)\s*[:#]?\s*(\d{1,5})",
    ]
    for pattern in patterns:
        match = re.search(pattern, lowered, re.I)
        if not match:
            continue
        current = int(match.group(1))
        total = int(match.group(2)) if len(match.groups()) >= 2 and match.group(2) else page_count
        if page_count and total and abs(total - page_count) > max(5, page_count * 0.2):
            continue
        if current <= 0:
            continue
        if page_count and current > page_count:
            continue
        return current
    return None


def pdf_tool_timeout_reason(args: argparse.Namespace, idle_seconds: float, finalizing_seconds: float) -> str | None:
    finalize_timeout = float(getattr(args, "pdf_tool_finalize_timeout", 0.0) or 0.0)
    idle_timeout = float(getattr(args, "pdf_tool_idle_timeout", 0.0) or 0.0)
    if finalize_timeout > 0 and finalizing_seconds >= finalize_timeout:
        return f"finalize timeout after {format_duration(finalizing_seconds)}"
    if idle_timeout > 0 and idle_seconds >= idle_timeout:
        return f"idle timeout after {format_duration(idle_seconds)} without output"
    return None


def terminate_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            process.wait(timeout=10)
            return
        except Exception:
            pass
    try:
        process.terminate()
        process.wait(timeout=10)
    except Exception:
        try:
            process.kill()
            process.wait(timeout=10)
        except Exception:
            pass


def emit_pdf_tool_progress(
    progress_callback,
    source: Path,
    index: int | None,
    total: int | None,
    stage: str,
    label: str,
    started: float,
    page_count: int,
    current_page: int | None,
    *,
    finalizing_since: float | None = None,
    no_output_seconds: float = 0.0,
) -> None:
    elapsed = time.monotonic() - started
    elapsed_text = format_duration(elapsed)
    remaining_text = ""
    suffixes: list[str] = []
    if current_page and page_count and current_page >= page_count:
        page_text = f"{page_count}/{page_count} 页，页处理完成，正在收尾/写文件"
        if finalizing_since is not None:
            finalizing_elapsed = max(time.monotonic() - finalizing_since, 0.0)
            if finalizing_elapsed >= 30:
                suffixes.append(f"收尾已用 {format_duration(finalizing_elapsed)}")
            if finalizing_elapsed >= 120:
                suffixes.append("可能在合并版面、复制图片或等待子进程退出")
        if no_output_seconds >= 60:
            suffixes.append(f"最近 {format_duration(no_output_seconds)} 无新输出")
    elif current_page and page_count and current_page > 0:
        estimated_total = elapsed * page_count / current_page
        remaining_text = f"; 预计剩余 {format_duration(max(estimated_total - elapsed, 0))}"
        page_text = f"{current_page}/{page_count} 页"
    else:
        page_text = f"总页数 {page_count}" if page_count else "页数未知"
        if no_output_seconds >= 60:
            suffixes.append(f"最近 {format_duration(no_output_seconds)} 无新输出")
    suffix_text = f"; {'; '.join(suffixes)}" if suffixes else ""
    emit_stage(
        progress_callback,
        source,
        index,
        total,
        stage,
        f"{label} 运行中 - {page_text}; 已用 {elapsed_text}{remaining_text}{suffix_text}",
    )


def format_duration(seconds: float) -> str:
    seconds = max(int(seconds), 0)
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def format_cmd(cmd: list[str]) -> str:
    return subprocess.list2cmdline(cmd)


def emit_stage(
    progress_callback,
    source: Path,
    index: int | None,
    total: int | None,
    stage: str,
    detail: str,
) -> None:
    if not progress_callback or index is None or total is None:
        return
    progress_callback("stage", source, index, total, {"stage": stage, "detail": detail})


def calibre_environment() -> dict[str, str]:
    env = os.environ.copy()
    tools_dir = Path(__file__).resolve().parent.parent / "tools"
    config_dir = tools_dir / "calibre-config"
    cache_dir = tools_dir / "calibre-cache"
    config_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    env["CALIBRE_CONFIG_DIRECTORY"] = str(config_dir)
    env["CALIBRE_CACHE_DIRECTORY"] = str(cache_dir)
    return env


def mineru_environment(args: argparse.Namespace) -> dict[str, str]:
    env = os.environ.copy()
    model_source = getattr(args, "mineru_model_source", "modelscope")
    if model_source:
        env["MINERU_MODEL_SOURCE"] = model_source
    hf_endpoint = getattr(args, "mineru_hf_endpoint", "")
    if hf_endpoint:
        env["HF_ENDPOINT"] = hf_endpoint
    env.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
    env.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    return env


def normalize_command_options(args: argparse.Namespace) -> argparse.Namespace:
    args.pandoc_command = resolve_command_path(getattr(args, "pandoc_command", "pandoc")) or getattr(
        args, "pandoc_command", "pandoc"
    )
    args.calibre_command = resolve_command_path(
        getattr(args, "calibre_command", "ebook-convert")
    ) or getattr(args, "calibre_command", "ebook-convert")
    args.marker_command = resolve_command_path(
        getattr(args, "marker_command", "marker_single")
    ) or getattr(args, "marker_command", "marker_single")
    args.mineru_command = resolve_command_path(
        getattr(args, "mineru_command", "mineru")
    ) or getattr(args, "mineru_command", "mineru")
    return args


def suggested_command_value(command: str) -> str:
    return resolve_command_path(command) or command


def resolve_command_path(command: str) -> str | None:
    normalized = (command or "").strip().strip('"')
    if not normalized:
        return None

    candidate_path = Path(normalized)
    if candidate_path.exists():
        return str(candidate_path)

    found = shutil.which(normalized)
    if found:
        return found

    for candidate in iter_fallback_command_paths(normalized):
        if candidate.exists():
            return str(candidate)
    return None


def iter_fallback_command_paths(command: str) -> Iterable[Path]:
    normalized = command.lower().removesuffix(".exe")
    if normalized in COMMON_WINDOWS_COMMAND_PATHS:
        yield from COMMON_WINDOWS_COMMAND_PATHS[normalized]

    workspace_tools = Path(__file__).resolve().parent.parent / "tools"
    if normalized == "mineru":
        yield workspace_tools / "mineru-venv" / "Scripts" / "mineru.exe"

    if workspace_tools.exists():
        for match in sorted(
            workspace_tools.glob(f"**/{normalized}.exe"),
            reverse=True,
        ):
            yield match

    if normalized == "marker_single":
        appdata = os.environ.get("APPDATA")
        if appdata:
            roaming_scripts = Path(appdata) / "Python"
            for script in sorted(
                roaming_scripts.glob("Python*/Scripts/marker_single.exe"),
                reverse=True,
            ):
                yield script

        for script in sorted(
            Path.home().glob("AppData/Roaming/Python/Python*/Scripts/marker_single.exe"),
            reverse=True,
        ):
            yield script


def format_subprocess_error(exc: subprocess.CalledProcessError) -> str:
    stderr = (exc.stderr or "").strip()
    stdout = (exc.stdout or "").strip()
    details = stderr or stdout or f"Command failed with exit code {exc.returncode}"
    details = explain_known_tool_error(details)
    return f"{format_cmd(list(exc.cmd))}: {details}"


def explain_known_tool_error(details: str) -> str:
    lowered = details.lower()
    if "requestsdependencywarning" in lowered:
        return (
            "Marker 的 Python 环境存在 requests/urllib3/chardet 版本不匹配警告，"
            "可能导致模型下载或网络请求不稳定。建议修复 Marker 所在 Python 环境，"
            "或在 PDF 模式中改用 MinerU / Umi-OCR。原始信息："
            f"{details}"
        )
    if "models.datalab.to" in lowered and (
        "failed to establish a new connection" in lowered
        or "connectionerror" in lowered
        or "max retries exceeded" in lowered
    ):
        return (
            "Marker 首次运行需要从 models.datalab.to 下载模型，但当前网络无法访问该地址，"
            "所以 PDF 转换没有真正开始。请先放通该站点，或改用不依赖在线模型下载的 PDF 方案。"
        )
    return details


def pymupdf4llm_available() -> bool:
    return importlib.util.find_spec("pymupdf4llm") is not None


def pymupdf_available() -> bool:
    return importlib.util.find_spec("pymupdf") is not None or importlib.util.find_spec("fitz") is not None


def torch_cuda_status() -> str:
    try:
        import torch

        return "ok" if torch.cuda.is_available() else "warning"
    except Exception:
        return "warning"


def torch_cuda_detail() -> str:
    try:
        import torch

        if not torch.cuda.is_available():
            return f"torch {getattr(torch, '__version__', 'unknown')}; CUDA unavailable"
        return f"torch {getattr(torch, '__version__', 'unknown')}; {torch.cuda.get_device_name(0)}"
    except Exception as exc:  # noqa: BLE001
        return f"torch not importable: {exc}"


def mineru_model_cache_status() -> tuple[str, str]:
    cache_root = Path.home() / ".cache" / "huggingface" / "hub"
    expected = [
        cache_root / "models--opendatalab--PDF-Extract-Kit-1.0",
        cache_root / "models--opendatalab--MinerU2.5-Pro-2604-1.2B",
    ]
    existing = [path for path in expected if path.exists()]
    if len(existing) == len(expected):
        return "ok", "; ".join(f"{path.name} ({format_bytes(directory_size(path))})" for path in existing)
    if existing:
        return "warning", "partial cache: " + "; ".join(path.name for path in existing)
    return "warning", f"not found under {cache_root}; MinerU may download models on first run"


def directory_size(path: Path) -> int:
    total = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                total += item.stat().st_size
    except Exception:
        return total
    return total


def format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def suggested_umi_ocr_command() -> str:
    candidate = Path(r"D:\Umi-OCR\Umi-OCR_Paddle_v2.1.5\Umi-OCR.exe")
    return str(candidate) if candidate.exists() else "Umi-OCR.exe"


def suggested_umi_paddle_exe() -> str:
    candidate = DEFAULT_UMI_PLUGIN_DIR / "PaddleOCR-json.exe"
    return str(candidate) if candidate.exists() else "PaddleOCR-json.exe"


def suggested_umi_paddle_module() -> str:
    candidate = DEFAULT_UMI_PLUGIN_DIR / "PPOCR_api.py"
    return str(candidate) if candidate.exists() else "PPOCR_api.py"


def get_pdf_page_count(source: Path) -> int:
    return pdf_preflight(source, default_options()).page_count


def pdf_preflight(source: Path, args: argparse.Namespace, sample_pages: int = 8) -> PdfPreflight:
    cache = getattr(args, "_pdf_preflight_cache", None)
    if cache is None:
        cache = {}
        setattr(args, "_pdf_preflight_cache", cache)
    cache_key = str(source)
    if cache_key in cache:
        return cache[cache_key]

    result = inspect_pdf_preflight(source, args, sample_pages=sample_pages)
    cache[cache_key] = result
    return result


def inspect_pdf_preflight(source: Path, args: argparse.Namespace, sample_pages: int = 8) -> PdfPreflight:
    doc = None
    try:
        import pymupdf

        doc = pymupdf.open(str(source))
        page_count = len(doc)
        if page_count == 0:
            return empty_pdf_preflight()

        sample_indexes = pdf_sample_indexes(page_count, sample_pages)
        try:
            bookmark_count = len(doc.get_toc(simple=True))
        except Exception:
            bookmark_count = 0
        text_pages = 0
        image_pages = 0
        text_chars = 0
        text_blocks = 0
        image_area_ratios: list[float] = []
        toc_like_pages = 0
        table_like_pages = 0
        two_column_like_pages = 0
        for page_number in sample_indexes:
            page = doc[page_number]
            text = page.get_text("text").strip()
            text_chars += len(text)
            blocks = page_text_blocks(page)
            text_blocks += len(blocks)
            if len(text) >= 80:
                text_pages += 1
            if looks_like_toc_page(text):
                toc_like_pages += 1
            if looks_like_table_page(text):
                table_like_pages += 1
            if looks_like_two_column_page(page, blocks):
                two_column_like_pages += 1

            image_area_ratio = page_image_area_ratio(page)
            image_area_ratios.append(image_area_ratio)
            if image_area_ratio >= 0.25:
                image_pages += 1

        sampled = len(sample_indexes)
        text_page_ratio = round(text_pages / max(sampled, 1), 3)
        avg_text_chars = round(text_chars / max(sampled, 1), 1)
        avg_text_blocks = round(text_blocks / max(sampled, 1), 1)
        image_page_ratio = round(image_pages / max(sampled, 1), 3)
        avg_image_area_ratio = round(sum(image_area_ratios) / max(sampled, 1), 3)
        scanned_likely = text_page_ratio < 0.5 or avg_text_chars < 120
        complex_layout_likely = (
            image_page_ratio >= 0.35
            or avg_image_area_ratio >= 0.25
            or table_like_pages > 0
            or two_column_like_pages > 0
        )
        recommended, reasons = recommend_pdf_pipeline(
            page_count=page_count,
            scanned_likely=scanned_likely,
            complex_layout_likely=complex_layout_likely,
            toc_like_pages=toc_like_pages,
            table_like_pages=table_like_pages,
            two_column_like_pages=two_column_like_pages,
            bookmark_count=bookmark_count,
            args=args,
        )
        return PdfPreflight(
            page_count=page_count,
            sampled_pages=sampled,
            bookmark_count=bookmark_count,
            text_page_ratio=text_page_ratio,
            avg_text_chars=avg_text_chars,
            avg_text_blocks=avg_text_blocks,
            image_page_ratio=image_page_ratio,
            avg_image_area_ratio=avg_image_area_ratio,
            toc_like_pages=toc_like_pages,
            table_like_pages=table_like_pages,
            two_column_like_pages=two_column_like_pages,
            scanned_likely=scanned_likely,
            complex_layout_likely=complex_layout_likely,
            recommended_pipeline=recommended,
            reasons=reasons,
        )
    except Exception as exc:  # noqa: BLE001
        result = empty_pdf_preflight()
        result.reasons.append(f"PDF preflight failed: {exc}")
        return result
    finally:
        if doc is not None:
            doc.close()


def extract_pdf_outline(source: Path, limit: int = 80) -> dict[str, object]:
    try:
        import pymupdf

        with pymupdf.open(str(source)) as doc:
            toc = doc.get_toc(simple=True)
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "count": 0, "truncated": False, "items": [], "message": str(exc)}

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


def empty_pdf_preflight() -> PdfPreflight:
    return PdfPreflight(
        page_count=0,
        sampled_pages=0,
        bookmark_count=0,
        text_page_ratio=0.0,
        avg_text_chars=0.0,
        avg_text_blocks=0.0,
        image_page_ratio=0.0,
        avg_image_area_ratio=0.0,
        toc_like_pages=0,
        table_like_pages=0,
        two_column_like_pages=0,
        scanned_likely=False,
        complex_layout_likely=False,
        recommended_pipeline="marker",
        reasons=[],
    )


def pdf_sample_indexes(page_count: int, sample_pages: int) -> list[int]:
    if page_count <= sample_pages:
        return list(range(page_count))
    candidates = {0, 1, page_count - 1}
    step = max(1, page_count // max(sample_pages - len(candidates), 1))
    for index in range(2, page_count - 1, step):
        candidates.add(index)
        if len(candidates) >= sample_pages:
            break
    return sorted(index for index in candidates if 0 <= index < page_count)


def page_image_area_ratio(page) -> float:
    page_area = max(float(page.rect.width * page.rect.height), 1.0)
    total = 0.0
    try:
        drawings = page.get_image_info(xrefs=False)
    except Exception:
        drawings = []
    for image in drawings:
        bbox = image.get("bbox")
        if not bbox or len(bbox) != 4:
            continue
        width = max(float(bbox[2]) - float(bbox[0]), 0.0)
        height = max(float(bbox[3]) - float(bbox[1]), 0.0)
        total += width * height
    return round(min(total / page_area, 1.0), 3)


def page_text_blocks(page) -> list[tuple[float, float, float, float]]:
    try:
        raw_blocks = page.get_text("blocks")
    except Exception:
        return []
    blocks: list[tuple[float, float, float, float]] = []
    for block in raw_blocks:
        if len(block) < 5:
            continue
        text = str(block[4]).strip()
        if not text:
            continue
        try:
            blocks.append((float(block[0]), float(block[1]), float(block[2]), float(block[3])))
        except Exception:
            continue
    return blocks


def looks_like_two_column_page(page, blocks: list[tuple[float, float, float, float]]) -> bool:
    if len(blocks) < 8:
        return False
    midpoint = float(page.rect.width) / 2.0
    left = [block for block in blocks if (block[0] + block[2]) / 2.0 < midpoint * 0.9]
    right = [block for block in blocks if (block[0] + block[2]) / 2.0 > midpoint * 1.1]
    if len(left) < 3 or len(right) < 3:
        return False
    left_max = max(block[2] for block in left)
    right_min = min(block[0] for block in right)
    return right_min - left_max > page.rect.width * 0.04


def looks_like_toc_page(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    toc_markers = ("目录", "contents", "table of contents")
    dot_leaders = len(re.findall(r"\.{3,}\s*\d{1,4}", text))
    numbered_lines = len(re.findall(r"(?m)^\s*(第.+章|chapter\s+\d+|[一二三四五六七八九十]+[、.])", lowered))
    return any(marker in lowered for marker in toc_markers) or dot_leaders >= 3 or numbered_lines >= 5


def looks_like_table_page(text: str) -> bool:
    if not text:
        return False
    lines = [line for line in text.splitlines() if line.strip()]
    tabular_lines = [line for line in lines if "\t" in line or len(re.findall(r"\s{2,}", line)) >= 3]
    numeric_dense = [line for line in lines if len(re.findall(r"\d+(?:[.,]\d+)?", line)) >= 4]
    return len(tabular_lines) >= 4 or len(numeric_dense) >= 4


def recommend_pdf_pipeline(
    *,
    page_count: int,
    scanned_likely: bool,
    complex_layout_likely: bool,
    toc_like_pages: int,
    table_like_pages: int,
    two_column_like_pages: int,
    bookmark_count: int,
    args: argparse.Namespace,
) -> tuple[str, list[str]]:
    max_marker_pages = int(getattr(args, "marker_default_max_pages", 12))
    reasons: list[str] = []
    if page_count > max_marker_pages:
        reasons.append(f"页数 {page_count} 超过 Marker 默认阈值 {max_marker_pages}")
    if scanned_likely:
        reasons.append("文本层较少，疑似扫描版或 OCR 质量风险")
    if complex_layout_likely:
        reasons.append("图片/表格/复杂版式迹象较多")
    if toc_like_pages:
        reasons.append("检测到目录页迹象")
    if table_like_pages:
        reasons.append("检测到表格页迹象")
    if two_column_like_pages:
        reasons.append("检测到双栏/多栏版式迹象")
    if bookmark_count:
        reasons.append(f"PDF 内置书签 {bookmark_count} 条，可辅助章节结构")

    if page_count <= max_marker_pages and not complex_layout_likely:
        return "marker", reasons or ["短 PDF 且版式不复杂，优先 Marker"]
    return "mineru", reasons or ["默认使用 MinerU 结构化解析"]


def estimate_marker_seconds(source: Path, args: argparse.Namespace) -> float:
    page_count = max(get_pdf_page_count(source), 1)
    return page_count * float(getattr(args, "marker_seconds_per_page_estimate", 10.0))


def estimate_conversion_seconds(source: Path, args: argparse.Namespace) -> float | None:
    kind = detect_source_kind(source)
    if kind in {"pandoc", "calibre"}:
        return None
    if kind != "pdf":
        return None

    page_count = max(get_pdf_page_count(source), 1)
    selected = selected_pdf_pipeline(source, args)
    if selected == "marker":
        return estimate_marker_seconds(source, args)
    if selected == "mineru":
        return page_count * 3.0
    if selected == "umi":
        return page_count * 2.0
    if selected == "pymupdf4llm":
        return page_count * 0.5
    if selected == "docling":
        return page_count * 2.0
    return None


def selected_pdf_pipeline(source: Path, args: argparse.Namespace) -> str:
    mode = getattr(args, "pdf_pipeline_mode", "auto")
    if mode != "auto":
        return mode
    return pdf_preflight(source, args).recommended_pipeline


def selected_pdf_pipeline_label(source: Path, args: argparse.Namespace) -> str:
    selected = selected_pdf_pipeline(source, args)
    if selected == "marker":
        return "marker(gpu)"
    if selected == "mineru":
        return "mineru(structured)"
    if selected == "umi":
        return "umi-ocr"
    if selected == "docling":
        return "docling"
    return selected


def plan_note(source: Path, args: argparse.Namespace) -> str:
    if detect_source_kind(source) != "pdf":
        return ""
    preflight = pdf_preflight(source, args)
    page_count = preflight.page_count
    if page_count <= 0:
        return ""
    marker_seconds = estimate_marker_seconds(source, args)
    selected = selected_pdf_pipeline(source, args)
    mode = getattr(args, "pdf_pipeline_mode", "auto")
    metrics = (
        f"text {preflight.text_page_ratio:.0%}; "
        f"image {preflight.avg_image_area_ratio:.0%}; "
        f"blocks {preflight.avg_text_blocks:.1f}/page; "
        f"bookmarks {preflight.bookmark_count}; "
        f"sample {preflight.sampled_pages}/{page_count}"
    )
    reason = "; ".join(preflight.reasons[:2])
    if selected == "mineru":
        if mode == "auto":
            return f"{page_count} pages; {metrics}; Marker est. {marker_seconds:.0f}s; auto-switch to MinerU ({reason})"
        return f"{page_count} pages; {metrics}; Marker est. {marker_seconds:.0f}s; using MinerU structured parser"
    if selected == "umi":
        if mode == "auto":
            return f"{page_count} pages; {metrics}; Marker est. {marker_seconds:.0f}s; auto-switch to Umi-OCR ({reason})"
        return f"{page_count} pages; {metrics}; Marker est. {marker_seconds:.0f}s; using Umi-OCR"
    if selected == "pymupdf4llm":
        return f"{page_count} pages; {metrics}; using PyMuPDF4LLM"
    if selected == "docling":
        return f"{page_count} pages; {metrics}; using Docling document converter"
    if mode == "auto":
        return f"{page_count} pages; {metrics}; Marker est. {marker_seconds:.0f}s; auto-use Marker ({reason})"
    return f"{page_count} pages; {metrics}; Marker est. {marker_seconds:.0f}s"


def should_use_ocr_for_pdf(source: Path, sample_pages: int = 6) -> bool:
    return inspect_pdf_preflight(source, default_options(), sample_pages=sample_pages).scanned_likely


def create_umi_paddle_engine(args: argparse.Namespace):
    module_path = Path(getattr(args, "umi_paddle_module", suggested_umi_paddle_module()))
    exe_path = Path(getattr(args, "umi_paddle_exe", suggested_umi_paddle_exe()))
    if not module_path.exists():
        raise FileNotFoundError(f"Umi-OCR module not found: {module_path}")
    if not exe_path.exists():
        raise FileNotFoundError(f"Umi-OCR engine not found: {exe_path}")

    import importlib.util as importlib_util

    spec = importlib_util.spec_from_file_location("umi_ppocr_api", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load Umi-OCR module: {module_path}")
    module = importlib_util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PPOCR_pipe(str(exe_path))


def umi_ocr_image(image_path: Path, ocr_engine) -> str:
    result = ocr_engine.run(str(image_path))
    code = result.get("code")
    if code == 101:
        # Umi-OCR uses 101 for pages where no text is detected. Treat these
        # as empty/image-only pages instead of failing the whole document.
        return ""
    if code != 100:
        raise RuntimeError(f"Umi-OCR failed: {result}")
    lines = []
    for item in result.get("data", []):
        text = (item.get("text") or "").strip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def close_umi_paddle_engine(ocr_engine) -> None:
    process = getattr(ocr_engine, "ret", None)
    # Do not call PPOCR_pipe.exit(): the bundled Umi-OCR API prints to
    # stdout on shutdown, which corrupts MCP stdio JSON-RPC streams.
    try:
        import atexit

        atexit.unregister(ocr_engine.exit)
    except Exception:
        pass
    try:
        if ocr_engine is not None:
            ocr_engine.ret = None
    except Exception:
        pass
    if process is None:
        return
    try:
        process.terminate()
        process.wait(timeout=5)
    except Exception:
        try:
            process.kill()
            process.wait(timeout=5)
        except Exception:
            pass


def should_fallback_from_pdf_tool(exc: Exception, selected: str, args: argparse.Namespace) -> bool:
    if not getattr(args, "pdf_fallback_to_pymupdf4llm", True):
        return False
    if selected == "pymupdf4llm":
        return False
    if not pymupdf4llm_available():
        return False
    if isinstance(exc, PdfToolTimeoutError):
        return True
    if isinstance(exc, FileNotFoundError):
        return True
    if isinstance(exc, subprocess.CalledProcessError):
        details = f"{exc.stderr or ''}\n{exc.stdout or ''}".lower()
        retryable_markers = (
            "models.datalab.to",
            "failed to establish a new connection",
            "max retries exceeded",
            "connectionerror",
            "marker completed but no markdown file was produced",
        )
        return any(token in details for token in retryable_markers)
    return selected in {"marker", "mineru", "docling"}


if __name__ == "__main__":
    raise SystemExit(main())
