from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable


PANDOC_DIRECT_FORMATS = {".epub", ".fb2", ".odt", ".txt"}
CALIBRE_INTERMEDIATE_FORMATS = {".azw", ".azw3", ".mobi", ".rtf"}
EBOOK_DIRECT_FORMATS = PANDOC_DIRECT_FORMATS
EBOOK_NEEDS_CALIBRE_FORMATS = CALIBRE_INTERMEDIATE_FORMATS
PDF_FORMATS = {".pdf"}
SUPPORTED_FORMATS = PANDOC_DIRECT_FORMATS | CALIBRE_INTERMEDIATE_FORMATS | PDF_FORMATS

OUTPUT_FORMATS = {
    "markdown": {"suffix": ".md", "pandoc_target": "gfm"},
    "html": {"suffix": ".html", "pandoc_target": "html"},
    "text": {"suffix": ".txt", "pandoc_target": "plain"},
}

PDF_PIPELINE_MODES = ("auto", "marker", "mineru", "umi", "pymupdf4llm")

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
        "--calibre-command",
        default="ebook-convert",
        help="Calibre conversion command, default: ebook-convert",
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
        "--health-check",
        action="store_true",
        help="Only print dependency and environment health information, then exit",
    )
    return parser.parse_args()


def default_options(**overrides) -> SimpleNamespace:
    base = {
        "recursive": False,
        "include_hidden": False,
        "output_format": "markdown",
        "markdown_format": "gfm",
        "marker_command": suggested_command_value("marker_single"),
        "marker_extra_args": [],
        "mineru_command": suggested_command_value("mineru"),
        "mineru_extra_args": [],
        "mineru_method": "auto",
        "mineru_backend": "pipeline",
        "mineru_lang": "ch",
        "mineru_model_source": "huggingface",
        "mineru_hf_endpoint": "https://hf-mirror.com",
        "mineru_keep_artifacts": True,
        "calibre_command": suggested_command_value("ebook-convert"),
        "pandoc_command": suggested_command_value("pandoc"),
        "overwrite": False,
        "dry_run": False,
        "manifest": None,
        "resume": False,
        "report_dir": None,
        "no_reports": False,
        "health_check": False,
        "pdf_fallback_to_pymupdf4llm": True,
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
    if getattr(args, "overwrite", False):
        return base_paths

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
    return shorten_output_path_if_needed(output_path, source)


def shorten_output_path_if_needed(output_path: Path, source: Path, max_path_chars: int = 220) -> Path:
    if len(str(output_path)) <= max_path_chars and len(output_path.name) <= 150:
        return output_path

    digest = hashlib.sha1(str(source).encode("utf-8", errors="replace")).hexdigest()[:10]
    safe_stem = sanitize_output_stem(output_path.stem)
    max_stem_len = max(30, 140 - len(output_path.suffix))
    shortened_stem = safe_stem[:max_stem_len].rstrip(" ._-")
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
        checks.append(
            {
                "name": Path(command).name if command else command,
                "kind": "command",
                "status": "ok" if resolved else "missing",
                "detail": resolved or "not found",
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
    return "\n".join(lines)


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
        pipeline=pipeline_name(source, args),
        message="",
    )


def pipeline_name(source: Path, args: argparse.Namespace | None = None) -> str:
    kind = detect_source_kind(source)
    if kind == "pandoc":
        return "pandoc"
    if kind == "calibre":
        return "calibre+pandoc"
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


def run_calibre_intermediate_convert(
    source: Path,
    output_path: Path,
    args: argparse.Namespace,
    progress_callback=None,
    progress_index: int | None = None,
    progress_total: int | None = None,
) -> None:
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


def run_pdf_convert(
    source: Path,
    output_path: Path,
    args: argparse.Namespace,
    progress_callback=None,
    progress_index: int | None = None,
    progress_total: int | None = None,
) -> None:
    selected = selected_pdf_pipeline(source, args)
    if selected == "umi":
        run_umi_pdf_convert(source, output_path, args, progress_callback, progress_index, progress_total)
        return
    if selected == "mineru":
        run_mineru_pdf_convert(source, output_path, args, progress_callback, progress_index, progress_total)
        return
    if selected == "pymupdf4llm":
        run_pymupdf4llm_pdf_convert(source, output_path, args, progress_callback, progress_index, progress_total)
        return

    try:
        run_marker_pdf_convert(source, output_path, args, progress_callback, progress_index, progress_total)
        return
    except Exception as exc:  # noqa: BLE001
        if not should_fallback_from_marker(exc, args):
            raise
        emit_stage(
            progress_callback,
            source,
            progress_index,
            progress_total,
            "fallback",
            "Marker 失败，自动回退到 PyMuPDF4LLM",
        )
        run_pymupdf4llm_pdf_convert(source, output_path, args, progress_callback, progress_index, progress_total)


def run_mineru_pdf_convert(
    source: Path,
    output_path: Path,
    args: argparse.Namespace,
    progress_callback=None,
    progress_index: int | None = None,
    progress_total: int | None = None,
) -> None:
    with tempfile.TemporaryDirectory(prefix="mineru-output-") as tmpdir:
        tmpdir_path = Path(tmpdir)
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
        run_command(cmd, args.dry_run, env=mineru_environment(args), capture_output=False)
        if args.dry_run:
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
            return

        convert_markdown_file(best_md, output_path, args, progress_callback, source, progress_index, progress_total)


def run_marker_pdf_convert(
    source: Path,
    output_path: Path,
    args: argparse.Namespace,
    progress_callback=None,
    progress_index: int | None = None,
    progress_total: int | None = None,
) -> None:
    with tempfile.TemporaryDirectory(prefix="marker-output-") as tmpdir:
        tmpdir_path = Path(tmpdir)
        cmd = [
            args.marker_command,
            str(source),
            "--output_dir",
            str(tmpdir_path),
            *args.marker_extra_args,
        ]
        emit_stage(progress_callback, source, progress_index, progress_total, "marker", "Marker 解析 PDF")
        run_command(cmd, args.dry_run)
        if args.dry_run:
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
            return

        convert_markdown_file(best_md, output_path, args, progress_callback, source, progress_index, progress_total)


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
    import pymupdf4llm

    markdown = pymupdf4llm.to_markdown(
        str(source),
        use_ocr=use_ocr,
        force_text=True,
        show_progress=False,
        ocr_language="eng",
    )
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
                page_title = f"## Page {page_number + 1}"
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
                source_kind="pdf",
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
        emit_stage(progress_callback, stage_source, progress_index, progress_total, "footnotes", "提取脚注与尾注")
        notes = extract_epub_rearnotes(note_source_path) if note_source_path else {}
        if notes:
            text = inject_markdown_footnotes(text, notes)
    else:
        text = clean_generic_markdown(text)
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
        return "\n".join(lines[keep_from:])
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
        return "\n".join(lines[chosen_idx:])

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
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    result.report = str(report_path)


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
    try:
        import pymupdf

        document = pymupdf.open(str(source))
        count = len(document)
        document.close()
        return count
    except Exception:
        return 0


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
    return None


def selected_pdf_pipeline(source: Path, args: argparse.Namespace) -> str:
    mode = getattr(args, "pdf_pipeline_mode", "auto")
    if mode != "auto":
        return mode
    page_count = get_pdf_page_count(source)
    if page_count > int(getattr(args, "marker_default_max_pages", 12)):
        return "mineru"
    return "marker"


def selected_pdf_pipeline_label(source: Path, args: argparse.Namespace) -> str:
    selected = selected_pdf_pipeline(source, args)
    if selected == "marker":
        return "marker(gpu)"
    if selected == "mineru":
        return "mineru(structured)"
    if selected == "umi":
        return "umi-ocr"
    return selected


def plan_note(source: Path, args: argparse.Namespace) -> str:
    if detect_source_kind(source) != "pdf":
        return ""
    page_count = get_pdf_page_count(source)
    if page_count <= 0:
        return ""
    marker_seconds = estimate_marker_seconds(source, args)
    selected = selected_pdf_pipeline(source, args)
    mode = getattr(args, "pdf_pipeline_mode", "auto")
    if selected == "mineru":
        if mode == "auto":
            return f"{page_count} pages; Marker est. {marker_seconds:.0f}s; auto-switch to MinerU structured parser"
        return f"{page_count} pages; Marker est. {marker_seconds:.0f}s; using MinerU structured parser"
    if selected == "umi":
        if mode == "auto":
            return f"{page_count} pages; Marker est. {marker_seconds:.0f}s; auto-switch to Umi-OCR"
        return f"{page_count} pages; Marker est. {marker_seconds:.0f}s; using Umi-OCR"
    return f"{page_count} pages; Marker est. {marker_seconds:.0f}s"


def should_use_ocr_for_pdf(source: Path, sample_pages: int = 6) -> bool:
    doc = None
    try:
        import pymupdf

        doc = pymupdf.open(str(source))
        page_count = len(doc)
        if page_count == 0:
            return False

        sampled = 0
        pages_with_text = 0
        total_text_chars = 0
        for page_number in range(min(sample_pages, page_count)):
            page = doc[page_number]
            text = page.get_text("text").strip()
            sampled += 1
            total_text_chars += len(text)
            if len(text) >= 80:
                pages_with_text += 1

        if sampled == 0:
            return False

        text_page_ratio = pages_with_text / sampled
        avg_chars = total_text_chars / sampled
        return text_page_ratio < 0.5 or avg_chars < 120
    except Exception:
        return False
    finally:
        if doc is not None:
            doc.close()


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
    try:
        if ocr_engine is not None:
            ocr_engine.exit()
    except Exception:
        pass
    if process is None:
        return
    try:
        process.wait(timeout=5)
    except Exception:
        try:
            process.kill()
            process.wait(timeout=5)
        except Exception:
            pass


def should_fallback_from_marker(exc: Exception, args: argparse.Namespace) -> bool:
    if not getattr(args, "pdf_fallback_to_pymupdf4llm", True):
        return False
    if not pymupdf4llm_available():
        return False
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
    return False


if __name__ == "__main__":
    raise SystemExit(main())
