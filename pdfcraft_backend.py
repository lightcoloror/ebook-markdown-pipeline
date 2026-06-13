from __future__ import annotations

import argparse
import importlib.util
import json
import os
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


PDFCRAFT_PACKAGE = "pdf_craft"
DEFAULT_OCR_SIZE = os.environ.get("PDFCRAFT_OCR_SIZE", "base")
DEFAULT_TOOL_CACHE = Path(
    os.environ.get(
        "EBOOK_CONVERTER_TOOL_CACHE",
        Path(__file__).resolve().parent.parent / "tools",
    )
)


def pdfcraft_available() -> bool:
    return importlib.util.find_spec(PDFCRAFT_PACKAGE) is not None


def convert_with_pdfcraft(
    source: Path,
    output_path: Path,
    *,
    assets_name: str | None = None,
    analysing_dir: Path | None = None,
    models_cache_dir: Path | None = None,
    ocr_size: str = DEFAULT_OCR_SIZE,
    local_only: bool = True,
    dpi: int | None = None,
    max_page_image_file_size: int | None = None,
    includes_cover: bool = False,
    includes_footnotes: bool = True,
    ignore_pdf_errors: bool = False,
    ignore_ocr_errors: bool = False,
    toc_assumed: bool = True,
    generate_plot: bool = False,
) -> dict[str, Any]:
    try:
        from pdf_craft import transform_markdown
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("pdf-craft is not installed. Install optional dependency with: pip install pdf-craft") from exc

    started = time.monotonic()
    source = source.resolve()
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    assets_name = assets_name or f"{output_path.stem}.assets"
    analysing_dir = analysing_dir or output_path.parent / ".pdfcraft" / output_path.stem
    models_cache_dir = models_cache_dir or DEFAULT_TOOL_CACHE / "pdf-craft-models"
    analysing_dir.mkdir(parents=True, exist_ok=True)
    models_cache_dir.mkdir(parents=True, exist_ok=True)

    events: list[dict[str, Any]] = []

    def on_ocr_event(event) -> None:
        payload = serialize_event(event)
        events.append(payload)
        kind = str(payload.get("kind") or "")
        page_index = int(payload.get("page_index") or 0)
        total_pages = int(payload.get("total_pages") or 0)
        cost_time_ms = int(payload.get("cost_time_ms") or 0)
        # Keep this format parseable by the existing PDF tool progress monitor.
        print(f"PDFCRAFT_EVENT Page {page_index}/{total_pages} {kind} {cost_time_ms}ms", flush=True)

    metering = transform_markdown(
        pdf_path=source,
        markdown_path=output_path,
        markdown_assets_path=Path(assets_name),
        analysing_path=analysing_dir,
        ocr_size=ocr_size,
        models_cache_path=models_cache_dir,
        local_only=local_only,
        dpi=dpi,
        max_page_image_file_size=max_page_image_file_size,
        includes_cover=includes_cover,
        includes_footnotes=includes_footnotes,
        ignore_pdf_errors=ignore_pdf_errors,
        ignore_ocr_errors=ignore_ocr_errors,
        generate_plot=generate_plot,
        toc_assumed=toc_assumed,
        on_ocr_event=on_ocr_event,
    )
    return {
        "tool": "pdf-craft",
        "source": str(source),
        "output": str(output_path),
        "assets": str(output_path.parent / assets_name),
        "analysing_dir": str(analysing_dir),
        "models_cache_dir": str(models_cache_dir),
        "ocr_size": ocr_size,
        "local_only": local_only,
        "toc_assumed": toc_assumed,
        "includes_cover": includes_cover,
        "includes_footnotes": includes_footnotes,
        "ignore_pdf_errors": ignore_pdf_errors,
        "ignore_ocr_errors": ignore_ocr_errors,
        "event_count": len(events),
        "events_tail": events[-50:],
        "metering": serialize_value(metering),
        "duration_seconds": round(time.monotonic() - started, 3),
    }


def serialize_event(event) -> dict[str, Any]:
    if is_dataclass(event):
        payload = asdict(event)
    else:
        payload = dict(getattr(event, "__dict__", {}) or {})
    kind = payload.get("kind")
    payload["kind"] = getattr(kind, "name", str(kind))
    error = payload.get("error")
    if error is not None:
        payload["error"] = str(error)
        payload["error_type"] = type(error).__name__
    return payload


def serialize_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if is_dataclass(value):
        return serialize_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): serialize_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize_value(item) for item in value]
    try:
        return json.loads(json.dumps(value, default=str))
    except Exception:
        return str(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run pdf-craft PDF-to-Markdown conversion and write a JSON diagnostic.")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--assets-name", default=None)
    parser.add_argument("--analysing-dir", type=Path, default=None)
    parser.add_argument("--models-cache-dir", type=Path, default=None)
    parser.add_argument("--ocr-size", default=DEFAULT_OCR_SIZE)
    parser.add_argument("--allow-download", action="store_true")
    parser.add_argument("--dpi", type=int, default=None)
    parser.add_argument("--max-page-image-file-size", type=int, default=None)
    parser.add_argument("--include-cover", action="store_true")
    parser.add_argument("--no-footnotes", action="store_true")
    parser.add_argument("--ignore-pdf-errors", action="store_true")
    parser.add_argument("--ignore-ocr-errors", action="store_true")
    parser.add_argument("--no-toc-assumed", action="store_true")
    parser.add_argument("--generate-plot", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        payload = {
            "ok": True,
            "dry_run": True,
            "source": str(args.source),
            "output": str(args.output),
            "output_json": str(args.output_json),
            "ocr_size": args.ocr_size,
            "local_only": not args.allow_download,
        }
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False), flush=True)
        return 0

    try:
        result = convert_with_pdfcraft(
            args.source,
            args.output,
            assets_name=args.assets_name,
            analysing_dir=args.analysing_dir,
            models_cache_dir=args.models_cache_dir,
            ocr_size=args.ocr_size,
            local_only=not args.allow_download,
            dpi=args.dpi,
            max_page_image_file_size=args.max_page_image_file_size,
            includes_cover=args.include_cover,
            includes_footnotes=not args.no_footnotes,
            ignore_pdf_errors=args.ignore_pdf_errors,
            ignore_ocr_errors=args.ignore_ocr_errors,
            toc_assumed=not args.no_toc_assumed,
            generate_plot=args.generate_plot,
        )
        payload = {"ok": True, "result": result}
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(str(args.output), flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001
        payload = {"ok": False, "error": str(exc), "error_type": type(exc).__name__}
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(str(exc), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
