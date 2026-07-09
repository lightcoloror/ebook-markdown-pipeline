from __future__ import annotations

import argparse
import csv
import html
import importlib.util
import json
import re
import subprocess
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from external_wrapper_utils import (  # noqa: E402
    add_common_arguments,
    artifact,
    ensure_output_dir,
    main_entry,
    make_result,
    command_available,
    write_json,
    write_result,
)


BACKEND = "table_to_xlsx"
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def cv2_ximgproc_available() -> bool:
    if not module_available("cv2"):
        return False
    try:
        import cv2  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001
        return False
    return hasattr(cv2, "ximgproc")


def tesseract_languages() -> list[str]:
    executable = shutil.which("tesseract")
    if not executable:
        return []
    command: list[str] | str = [executable, "--list-langs"]
    shell = False
    if Path(executable).suffix.lower() in {".bat", ".cmd"}:
        command = f'"{executable}" --list-langs'
        shell = True
    try:
        completed = subprocess.run(command, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False, shell=shell)
    except OSError:
        return []
    languages: list[str] = []
    for line in (completed.stdout + "\n" + completed.stderr).splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("list of available languages"):
            continue
        languages.append(stripped)
    return sorted(set(languages))


def build_command(args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--input",
        str(args.input),
        "--output",
        str(args.output),
        "--backend",
        args.backend,
        "--mode",
        args.mode,
    ]
    if args.csv:
        command.extend(["--csv", args.csv])
    if args.markdown:
        command.extend(["--markdown", args.markdown])
    if args.table_candidates:
        command.extend(["--table-candidates", args.table_candidates])
    if args.ocr != "none":
        command.extend(["--ocr", args.ocr])
    for flag, enabled in [("--detect-rotation", args.detect_rotation), ("--implicit-rows", args.implicit_rows), ("--implicit-columns", args.implicit_columns), ("--borderless-tables", args.borderless_tables)]:
        if enabled:
            command.append(flag)
    return command


def health(args: argparse.Namespace) -> dict[str, object]:
    available_tesseract_languages = tesseract_languages()
    return {
        "status": "planned",
        "selected_backend": args.backend,
        "checks": [
            {"name": "paddleocr", "available": module_available("paddleocr"), "role": "preferred heavy table recognition backend"},
            {"name": "img2table", "available": module_available("img2table"), "role": "lightweight table-to-xlsx baseline"},
            {"name": "cv2_ximgproc", "available": cv2_ximgproc_available(), "role": "OpenCV contrib module required by img2table table detection"},
            {"name": "rapid_table", "available": module_available("rapid_table") or module_available("rapidtable"), "role": "table structure recognition fallback"},
            {
                "name": "tesseract",
                "available": command_available("tesseract"),
                "role": "img2table OCR option",
                "languages": available_tesseract_languages,
                "selected_language_available": args.ocr_lang in available_tesseract_languages,
            },
        ],
        "note": "Plan/fake mode never installs models or runs recognition. Execute mode only uses already-installed optional dependencies; img2table also needs cv2.ximgproc from OpenCV contrib.",
    }


def write_minimal_xlsx(path: Path, rows: list[list[Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = normalize_rows(rows)
    sheet_rows = []
    for row_index, row in enumerate(normalized, start=1):
        cells = []
        for col_index, value in enumerate(row, start=1):
            ref = f"{column_name(col_index)}{row_index}"
            text = html.escape(str(value), quote=False)
            cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>')
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    dimension = f"A1:{column_name(max((len(row) for row in normalized), default=1))}{max(len(normalized), 1)}"
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="{dimension}"/><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
    )
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
            "</Relationships>"
        ),
        "docProps/core.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>ebook_markdown_pipeline</dc:creator></cp:coreProperties>'
        ),
        "docProps/app.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
            '<Application>ebook_markdown_pipeline</Application></Properties>'
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Table 1" sheetId="1" r:id="rId1"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>"
        ),
        "xl/worksheets/sheet1.xml": sheet_xml,
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return path


def column_name(index: int) -> str:
    name = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name or "A"


def normalize_rows(rows: list[list[Any]]) -> list[list[str]]:
    if not rows:
        return [[""]]
    width = max(len(row) for row in rows) or 1
    return [["" if cell is None else str(cell) for cell in row + [""] * (width - len(row))] for row in rows]


def read_csv_rows(path: Path) -> list[list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [row for row in csv.reader(handle)]


def read_markdown_table(path: Path) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if cells and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells):
            continue
        rows.append(cells)
    return rows


def rows_from_args(args: argparse.Namespace) -> tuple[list[list[str]], list[str]]:
    warnings: list[str] = []
    if args.csv:
        return read_csv_rows(Path(args.csv).expanduser()), warnings
    if args.markdown:
        return read_markdown_table(Path(args.markdown).expanduser()), warnings
    warnings.append("No structured table source was provided; real image recognition is environment-gated and not run by this worker yet.")
    return [], warnings



def create_img2table_document(input_path: Path, args: argparse.Namespace) -> Any:
    from img2table.document import Image, PDF

    if input_path.suffix.lower() == ".pdf":
        pages = None
        if args.pages:
            pages = [max(0, page - 1) for page in parse_page_list(args.pages)]
        return PDF(src=input_path, pages=pages, detect_rotation=args.detect_rotation, pdf_text_extraction=True)
    return Image(src=input_path, detect_rotation=args.detect_rotation)


def create_img2table_ocr(args: argparse.Namespace) -> Any | None:
    if args.ocr == "none":
        return None
    if args.ocr == "tesseract":
        from img2table.ocr import TesseractOCR

        return TesseractOCR(n_threads=1, lang=args.ocr_lang)
    if args.ocr == "rapidocr":
        from img2table.ocr import RapidOCR

        return RapidOCR(params={"Rec.lang_type": args.ocr_lang})
    if args.ocr == "paddle":
        from img2table.ocr import PaddleOCR

        return PaddleOCR(lang=args.ocr_lang)
    raise ValueError(f"Unsupported img2table OCR backend: {args.ocr}")


def parse_page_list(raw: str) -> list[int]:
    pages: set[int] = set()
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            start_raw, end_raw = chunk.split("-", 1)
            start = int(start_raw)
            end = int(end_raw)
            pages.update(range(min(start, end), max(start, end) + 1))
        else:
            pages.add(int(chunk))
    return sorted(page for page in pages if page > 0)


def run_img2table_export(args: argparse.Namespace, input_path: Path, output_dir: Path) -> tuple[str, list[dict[str, object]], dict[str, object], list[str]]:
    warnings: list[str] = []
    if not module_available("img2table"):
        return "failed", [], {}, ["img2table is not installed; install/configure it manually before execute mode."]
    if not cv2_ximgproc_available():
        return "failed", [], {}, ["img2table requires cv2.ximgproc; ensure OpenCV contrib is the cv2 module loaded by this Python environment."]
    if args.ocr == "tesseract" and not command_available("tesseract"):
        return "failed", [], {}, ["Tesseract executable is not available; choose --ocr none or configure Tesseract."]
    try:
        document = create_img2table_document(input_path, args)
        ocr = create_img2table_ocr(args)
        xlsx_path = output_dir / args.xlsx_name
        document.to_xlsx(
            dest=xlsx_path,
            ocr=ocr,
            implicit_rows=args.implicit_rows,
            implicit_columns=args.implicit_columns,
            borderless_tables=args.borderless_tables,
            min_confidence=args.min_confidence,
            max_workers=args.max_workers,
        )
    except Exception as exc:  # noqa: BLE001
        return "failed", [], {}, [f"img2table execution failed: {exc}"]
    if not xlsx_path.exists():
        return "failed", [], {}, ["img2table completed but did not create the expected XLSX artifact."]
    summary_path = output_dir / "table-to-xlsx-result.json"
    write_json(
        summary_path,
        {
            "schema_version": "table-to-xlsx-result-v1",
            "backend": BACKEND,
            "selected_backend": "img2table",
            "xlsx": str(xlsx_path),
            "ocr": args.ocr,
            "warnings": warnings,
        },
    )
    artifacts = [
        artifact(xlsx_path, "table_xlsx", "Editable XLSX table draft from img2table", XLSX_MEDIA_TYPE),
        artifact(summary_path, "table_to_xlsx_summary", "table_to_xlsx summary", "application/json"),
    ]
    return "ok", artifacts, {"artifact_count": len(artifacts), "recognized_by": "img2table"}, warnings


def run_paddle_table_v2_export(args: argparse.Namespace, input_path: Path, output_dir: Path) -> tuple[str, list[dict[str, object]], dict[str, object], list[str]]:
    if not module_available("paddleocr"):
        return "failed", [], {}, ["paddleocr is not installed; configure PaddleOCR manually before execute mode."]
    if not args.allow_model_download and not args.paddlex_config:
        return "failed", [], {}, ["PaddleOCR TableRecognitionPipelineV2 may download default models; pass --allow-model-download or --paddlex-config to execute explicitly."]
    try:
        from paddleocr import TableRecognitionPipelineV2

        kwargs: dict[str, Any] = {}
        if args.paddlex_config:
            kwargs["paddlex_config"] = args.paddlex_config
        if args.paddle_device:
            kwargs["device"] = args.paddle_device
        if args.paddle_engine:
            kwargs["engine"] = args.paddle_engine
        pipeline = TableRecognitionPipelineV2(**kwargs)
        results = pipeline.predict(str(input_path))
        for result in results:
            result.save_to_xlsx(str(output_dir))
            result.save_to_html(str(output_dir))
            result.save_to_json(str(output_dir))
    except Exception as exc:  # noqa: BLE001
        return "failed", [], {}, [f"PaddleOCR TableRecognitionPipelineV2 execution failed: {exc}"]
    xlsx_files = sorted(output_dir.glob("*.xlsx"))
    json_files = sorted(output_dir.glob("*.json"))
    html_files = sorted(output_dir.glob("*.html"))
    if not xlsx_files:
        return "failed", [], {}, ["PaddleOCR completed but did not create an XLSX artifact."]
    summary_path = output_dir / "table-to-xlsx-result.json"
    write_json(
        summary_path,
        {
            "schema_version": "table-to-xlsx-result-v1",
            "backend": BACKEND,
            "selected_backend": "paddle_table_v2",
            "xlsx": [str(path) for path in xlsx_files],
            "json": [str(path) for path in json_files if path.name != summary_path.name],
            "html": [str(path) for path in html_files],
            "warnings": ["XLSX is an editable draft; formulas and original formatting are not recovered."],
        },
    )
    artifacts: list[dict[str, object]] = [artifact(path, "table_xlsx", "Editable XLSX table draft from PaddleOCR", XLSX_MEDIA_TYPE) for path in xlsx_files]
    artifacts.extend(artifact(path, "table_html", "PaddleOCR table HTML", "text/html") for path in html_files)
    artifacts.extend(artifact(path, "table_raw_json", "PaddleOCR table JSON", "application/json") for path in json_files if path.name != summary_path.name)
    artifacts.append(artifact(summary_path, "table_to_xlsx_summary", "table_to_xlsx summary", "application/json"))
    return "ok", artifacts, {"artifact_count": len(artifacts), "recognized_by": "paddle_table_v2"}, []


def run() -> dict[str, object]:
    parser = argparse.ArgumentParser(description="Plan or export editable XLSX drafts from table evidence.")
    add_common_arguments(parser)
    parser.add_argument("--backend", choices=["paddle_table_v2", "img2table", "rapidtable", "existing_artifact"], default="existing_artifact")
    parser.add_argument("--csv", help="Existing CSV table evidence to export.")
    parser.add_argument("--markdown", help="Existing Markdown table evidence to export.")
    parser.add_argument("--table-candidates", help="Reserved for table-candidates-v1 JSON export.")
    parser.add_argument("--xlsx-name", default="table.xlsx")
    parser.add_argument("--ocr", choices=["none", "tesseract", "rapidocr", "paddle"], default="none")
    parser.add_argument("--ocr-lang", default="eng")
    parser.add_argument("--pages", help="1-based PDF pages for img2table, for example 1,3-4.")
    parser.add_argument("--detect-rotation", action="store_true")
    parser.add_argument("--implicit-rows", action="store_true")
    parser.add_argument("--implicit-columns", action="store_true")
    parser.add_argument("--borderless-tables", action="store_true")
    parser.add_argument("--min-confidence", type=int, default=50)
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--paddlex-config")
    parser.add_argument("--paddle-device")
    parser.add_argument("--paddle-engine")
    parser.add_argument("--allow-model-download", action="store_true")
    args = parser.parse_args()

    input_path = Path(args.input).expanduser()
    output_dir = ensure_output_dir(Path(args.output).expanduser())
    command = build_command(args)
    health_payload = health(args)
    artifacts: list[dict[str, object]] = []
    warnings: list[str] = []
    metrics: dict[str, object] = {}

    if args.mode == "plan":
        status = "planned"
    else:
        handled_by_backend = False
        if args.mode == "fake":
            rows = [["A", "B"], ["fake", "table"]]
        elif args.backend == "img2table" and not any([args.csv, args.markdown, args.table_candidates]):
            status, artifacts, metrics, warnings = run_img2table_export(args, input_path, output_dir)
            handled_by_backend = True
            rows = []
        elif args.backend == "paddle_table_v2" and not any([args.csv, args.markdown, args.table_candidates]):
            status, artifacts, metrics, warnings = run_paddle_table_v2_export(args, input_path, output_dir)
            handled_by_backend = True
            rows = []
        elif args.backend == "rapidtable" and not any([args.csv, args.markdown, args.table_candidates]):
            status = "failed"
            warnings = ["RapidTable execute mode is reserved for a later adapter; use img2table or PaddleOCR first."]
            handled_by_backend = True
            rows = []
        else:
            rows, warnings = rows_from_args(args)
        if rows:
            xlsx_path = write_minimal_xlsx(output_dir / args.xlsx_name, rows)
            summary_path = output_dir / "table-to-xlsx-result.json"
            candidates_path = output_dir / "table-candidates.json"
            write_json(
                candidates_path,
                {
                    "schema_version": "table-candidates-v1",
                    "backend": BACKEND,
                    "status": "review",
                    "pages": [{"page": 1, "tables": [{"page": 1, "table_number": 1, "cells": rows, "xlsx": str(xlsx_path)}]}],
                    "artifacts": [{"type": "xlsx", "path": str(xlsx_path), "backend": BACKEND, "page": 1}],
                    "warnings": ["XLSX is an editable draft; formulas and original formatting are not recovered."],
                },
            )
            write_json(
                summary_path,
                {
                    "schema_version": "table-to-xlsx-result-v1",
                    "backend": BACKEND,
                    "selected_backend": args.backend,
                    "xlsx": str(xlsx_path),
                    "row_count": len(rows),
                    "column_count": max((len(row) for row in rows), default=0),
                    "warnings": warnings,
                },
            )
            artifacts.extend(
                [
                    artifact(xlsx_path, "table_xlsx", "Editable XLSX table draft", XLSX_MEDIA_TYPE),
                    artifact(candidates_path, "table_candidates_json", "Normalized table candidates with XLSX artifact", "application/json"),
                    artifact(summary_path, "table_to_xlsx_summary", "table_to_xlsx summary", "application/json"),
                ]
            )
            metrics = {"row_count": len(rows), "column_count": max((len(row) for row in rows), default=0), "artifact_count": len(artifacts)}
            status = "ok"
        elif not handled_by_backend:
            status = "failed"

    payload = make_result(
        backend=BACKEND,
        mode=args.mode,
        status=status,
        input_path=input_path,
        output_dir=output_dir,
        command=command,
        artifacts=artifacts,
        metrics=metrics,
        warnings=warnings,
        next_actions=[
            {"action": "use_paddle_table_v2_for_real_recognition", "detail": "Preferred future backend for photographed/scanned table recognition."},
            {"action": "compare_img2table_baseline", "detail": "Run img2table on bordered table samples before promotion."},
            {"action": "review_xlsx_draft", "detail": "Open XLSX and verify cell grid, OCR errors, and merged-cell needs before trusting output."},
        ],
        health=health_payload,
    )
    write_result(output_dir, payload)
    return payload


if __name__ == "__main__":
    main_entry(run)
