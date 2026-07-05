from __future__ import annotations

import argparse
import csv
import io
import json
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from external_wrapper_utils import (  # noqa: E402
    add_common_arguments,
    artifact,
    ensure_output_dir,
    main_entry,
    make_result,
    run_command,
    write_json,
    write_result,
    write_text,
)


BACKEND = "tesseract"


def build_command(args: argparse.Namespace, tool_output: Path) -> list[str]:
    output_base = tool_output / "tesseract-output"
    command = [args.tesseract_exe, str(Path(args.input)), str(output_base), "-l", args.lang]
    if args.psm:
        command.extend(["--psm", str(args.psm)])
    if args.output_format == "tsv":
        command.append("tsv")
    elif args.output_format == "hocr":
        command.append("hocr")
    return command


def health(args: argparse.Namespace) -> dict[str, object]:
    return {
        "status": "ok" if shutil.which(args.tesseract_exe) else "planned_only",
        "checks": [{"name": "tesseract_exe", "value": args.tesseract_exe, "available": bool(shutil.which(args.tesseract_exe))}],
    }


def fake_artifacts(output_dir: Path) -> list[dict[str, object]]:
    blocks = output_dir / "ocr-blocks.jsonl"
    text = output_dir / "tesseract.txt"
    tsv = output_dir / "tesseract.tsv"
    hocr = output_dir / "tesseract.hocr"
    summary = output_dir / "tesseract-summary.md"
    write_text(text, "Fake Tesseract OCR text.\n")
    write_text(
        tsv,
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        "5\t1\t1\t1\t1\t1\t10\t20\t120\t30\t90\tFake\n",
    )
    write_text(hocr, "<html><body><span class='ocrx_word' title='bbox 10 20 130 50; x_wconf 90'>Fake</span></body></html>\n")
    write_text(
        blocks,
        json.dumps(parse_tesseract_tsv(tsv.read_text(encoding="utf-8"), image="fake"), ensure_ascii=False) + "\n",
    )
    write_text(summary, "# Tesseract fake OCR summary\n\nClassic OCR baseline contract only. Includes fake TSV/hOCR standards outputs.\n")
    return [
        artifact(text, "text", "Tesseract text", "text/plain"),
        artifact(tsv, "tsv", "Tesseract TSV", "text/tab-separated-values"),
        artifact(hocr, "hocr", "Tesseract hOCR", "text/html"),
        artifact(blocks, "ocr_blocks_jsonl", "Tesseract OCR blocks", "application/jsonl"),
        artifact(summary, "markdown", "Tesseract summary", "text/markdown"),
    ]


def output_path_for_format(output_base: Path, output_format: str) -> Path:
    suffix = {"text": ".txt", "tsv": ".tsv", "hocr": ".hocr"}.get(output_format, ".txt")
    return output_base.with_suffix(suffix)


def parse_tesseract_tsv(tsv_text: str, *, image: str | Path) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    reader = csv.DictReader(io.StringIO(tsv_text), delimiter="\t")
    for row in reader:
        text = str(row.get("text") or "").strip()
        if not text or str(row.get("level") or "") != "5":
            continue
        left = int(float(row.get("left") or 0))
        top = int(float(row.get("top") or 0))
        width = int(float(row.get("width") or 0))
        height = int(float(row.get("height") or 0))
        confidence = parse_tesseract_confidence(row.get("conf"))
        block: dict[str, Any] = {
            "text": text,
            "bbox": [left, top, left + width, top + height],
            "provider": BACKEND,
            "page": parse_positive_int(row.get("page_num"), default=1),
            "block": parse_positive_int(row.get("block_num"), default=0),
            "paragraph": parse_positive_int(row.get("par_num"), default=0),
            "line": parse_positive_int(row.get("line_num"), default=0),
            "word": parse_positive_int(row.get("word_num"), default=0),
        }
        if confidence is not None:
            block["confidence"] = confidence
        blocks.append(block)
    return {
        "schema_version": "ocr-blocks-v1",
        "provider": BACKEND,
        "image": str(image),
        "status": "ok",
        "blocks": blocks,
    }


def parse_positive_int(raw: object, *, default: int) -> int:
    try:
        value = int(float(str(raw)))
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


def parse_tesseract_confidence(raw: object) -> float | None:
    try:
        value = float(str(raw))
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return round(value / 100, 4) if value > 1 else round(value, 4)


def collect_execute_artifacts(args: argparse.Namespace, input_path: Path, output_dir: Path, tool_output: Path) -> tuple[list[dict[str, object]], dict[str, object], list[str]]:
    artifacts: list[dict[str, object]] = []
    warnings: list[str] = []
    output_base = tool_output / "tesseract-output"
    produced = output_path_for_format(output_base, args.output_format)
    if not produced.exists():
        warnings.append(f"Expected Tesseract output was not created: {produced}")
        return artifacts, {"artifact_count": 0, "block_count": 0}, warnings
    if args.output_format == "text":
        artifacts.append(artifact(produced, "text", "Tesseract text", "text/plain"))
        char_count = len(produced.read_text(encoding="utf-8", errors="replace"))
        return artifacts, {"artifact_count": len(artifacts), "char_count": char_count}, warnings
    if args.output_format == "hocr":
        artifacts.append(artifact(produced, "hocr", "Tesseract hOCR", "text/html"))
        return artifacts, {"artifact_count": len(artifacts)}, warnings
    artifacts.append(artifact(produced, "tsv", "Tesseract TSV", "text/tab-separated-values"))
    blocks_path = output_dir / "ocr-blocks.jsonl"
    blocks_payload = parse_tesseract_tsv(produced.read_text(encoding="utf-8", errors="replace"), image=input_path)
    write_text(blocks_path, json.dumps(blocks_payload, ensure_ascii=False) + "\n")
    artifacts.append(artifact(blocks_path, "ocr_blocks_jsonl", "Tesseract OCR blocks", "application/jsonl"))
    return artifacts, {"artifact_count": len(artifacts), "block_count": len(blocks_payload.get("blocks") or [])}, warnings


def run() -> dict[str, object]:
    parser = argparse.ArgumentParser(description="Plan or run a Tesseract OCR baseline worker.")
    add_common_arguments(parser)
    parser.add_argument("--tesseract-exe", default="tesseract")
    parser.add_argument("--lang", default="eng")
    parser.add_argument("--psm", default="")
    parser.add_argument("--output-format", choices=["text", "tsv", "hocr"], default="text")
    args = parser.parse_args()

    input_path = Path(args.input).expanduser()
    output_dir = ensure_output_dir(Path(args.output).expanduser())
    tool_output = ensure_output_dir(output_dir / "tool-output")
    command = build_command(args, tool_output)
    warnings: list[str] = []
    metrics: dict[str, object] = {}
    artifacts: list[dict[str, object]] = []
    if args.mode == "fake":
        artifacts = fake_artifacts(tool_output)
        status = "ok"
        metrics = {"artifact_count": len(artifacts), "block_count": 1}
    elif args.mode == "execute":
        if not shutil.which(args.tesseract_exe):
            status = "failed"
            warnings.append("Tesseract executable is not available; keep OCRmyPDF as scanned-PDF path.")
        else:
            completed = run_command(command, cwd=None, timeout_seconds=args.timeout_seconds)
            log = output_dir / "tool.log"
            write_text(log, f"STDOUT\n{completed.stdout}\n\nSTDERR\n{completed.stderr}\n")
            artifacts.append(artifact(log, "tool_log", "Tesseract tool log", "text/plain"))
            produced_artifacts, metrics, collect_warnings = collect_execute_artifacts(args, input_path, output_dir, tool_output)
            artifacts.extend(produced_artifacts)
            warnings.extend(collect_warnings)
            status = "ok" if completed.returncode == 0 and produced_artifacts else "failed"
            metrics["artifact_count"] = len(artifacts)
    else:
        status = "planned"
    payload = make_result(
        backend=BACKEND,
        mode=args.mode,
        status=status,
        input_path=input_path,
        output_dir=output_dir,
        command=command,
        artifacts=artifacts,
        metrics=metrics or {"artifact_count": len(artifacts)},
        warnings=warnings,
        next_actions=[
            {"action": "keep_ocrmypdf_for_scanned_pdf", "detail": "Use direct Tesseract only as a comparison/standards baseline."},
            {"action": "prefer_tsv_for_blocks", "detail": "Use --output-format tsv when normalized ocr-blocks-v1 rows are needed."},
        ],
        health=health(args),
    )
    write_result(output_dir, payload)
    return payload


if __name__ == "__main__":
    main_entry(run)