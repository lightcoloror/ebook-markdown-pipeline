from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.batch_convert_books import (  # noqa: E402
    close_umi_paddle_engine,
    create_umi_paddle_engine,
    default_options,
    normalize_command_options,
    suggested_umi_paddle_exe,
    suggested_umi_paddle_module,
)
from ebook_markdown_pipeline.document_locator import IMAGE_EXTENSIONS  # noqa: E402
from ebook_markdown_pipeline.image_book_rebuilder import umi_ocr_image_with_blocks  # noqa: E402
from ebook_markdown_pipeline.ocr_providers import (  # noqa: E402
    OCR_BLOCK_SCHEMA_VERSION,
    create_rapidocr_engine,
    rapidocr_available,
    rapidocr_package_name,
    recognize_image_with_rapidocr,
)


PROVIDERS = ("rapidocr", "umi")
REPORT_SCHEMA_VERSION = "ocr-provider-comparison-v1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare lightweight OCR providers on small image samples.")
    parser.add_argument("inputs", nargs="+", type=Path, help="Image files or folders.")
    parser.add_argument("--output", type=Path, default=PROJECT_DIR / "benchmarks" / "runs" / "ocr-provider-comparison" / time.strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--providers", nargs="+", choices=PROVIDERS, default=list(PROVIDERS))
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--umi-paddle-exe", default=suggested_umi_paddle_exe())
    parser.add_argument("--umi-paddle-module", default=suggested_umi_paddle_module())
    args = parser.parse_args()

    images = collect_images(args.inputs, recursive=args.recursive)
    if args.limit:
        images = images[: args.limit]
    payload = compare_ocr_providers(
        images,
        output_dir=args.output,
        providers=args.providers,
        umi_paddle_exe=args.umi_paddle_exe,
        umi_paddle_module=args.umi_paddle_module,
    )
    print(json.dumps({"status": payload["status"], "output": payload["output"], "image_count": payload["image_count"]}, ensure_ascii=False))
    return 0 if payload["status"] in {"ok", "partial", "skipped"} else 2


def collect_images(inputs: list[Path], *, recursive: bool) -> list[Path]:
    images: list[Path] = []
    for input_path in inputs:
        if input_path.is_file() and input_path.suffix.lower() in IMAGE_EXTENSIONS:
            images.append(input_path.resolve())
            continue
        if input_path.is_dir():
            pattern = "**/*" if recursive else "*"
            for path in input_path.glob(pattern):
                if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
                    images.append(path.resolve())
    return sorted(dict.fromkeys(images), key=lambda path: str(path).lower())


def compare_ocr_providers(
    images: list[Path],
    *,
    output_dir: Path,
    providers: list[str],
    umi_paddle_exe: str | None = None,
    umi_paddle_module: str | None = None,
    rapidocr_engine_factory: Callable[[], Any] | None = None,
    umi_engine_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    provider_results = []
    for provider in providers:
        provider_results.append(
            run_provider(
                provider,
                images,
                umi_paddle_exe=umi_paddle_exe,
                umi_paddle_module=umi_paddle_module,
                rapidocr_engine_factory=rapidocr_engine_factory,
                umi_engine_factory=umi_engine_factory,
            )
        )
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "ocr_block_schema_version": OCR_BLOCK_SCHEMA_VERSION,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "output": str(output_dir),
        "image_count": len(images),
        "images": [str(path) for path in images],
        "providers": provider_results,
    }
    payload["summary"] = summarize_provider_results(provider_results, image_count=len(images))
    payload["status"] = payload["summary"]["status"]
    json_path = output_dir / "ocr-provider-comparison.json"
    md_path = output_dir / "ocr-provider-comparison.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    md_path.write_text(render_markdown(payload), encoding="utf-8", newline="\n")
    payload["json_report"] = str(json_path)
    payload["markdown_report"] = str(md_path)
    return payload


def run_provider(
    provider: str,
    images: list[Path],
    *,
    umi_paddle_exe: str | None,
    umi_paddle_module: str | None,
    rapidocr_engine_factory: Callable[[], Any] | None = None,
    umi_engine_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    items = []
    engine = None
    status = "ok"
    message = ""
    try:
        if provider == "rapidocr":
            if rapidocr_engine_factory is None and not rapidocr_available():
                raise FileNotFoundError("RapidOCR is not installed.")
            engine = rapidocr_engine_factory() if rapidocr_engine_factory else create_rapidocr_engine()
            message = f"package={rapidocr_package_name() or 'test/fake'}"
            for image in images:
                items.append(run_rapidocr_item(image, engine))
        elif provider == "umi":
            engine = umi_engine_factory() if umi_engine_factory else create_default_umi_engine(umi_paddle_exe, umi_paddle_module)
            for image in images:
                items.append(run_umi_item(image, engine))
        else:
            raise ValueError(f"Unsupported OCR provider: {provider}")
    except Exception as exc:  # noqa: BLE001
        status = "missing" if provider_unavailable_exception(exc) else "failed"
        message = str(exc)
    finally:
        if provider == "umi" and engine is not None and umi_engine_factory is None:
            close_umi_paddle_engine(engine)
    duration = round(time.monotonic() - started, 4)
    metrics = summarize_items(items)
    if status == "ok" and metrics["failed_count"]:
        status = "partial"
    if status == "ok" and not images:
        status = "skipped"
        message = "No image samples."
    return {
        "provider": provider,
        "status": status,
        "message": message,
        "duration_seconds": duration,
        "metrics": metrics,
        "items": items,
    }


def create_default_umi_engine(umi_paddle_exe: str | None, umi_paddle_module: str | None):
    options = normalize_command_options(
        default_options(
            umi_paddle_exe=umi_paddle_exe or suggested_umi_paddle_exe(),
            umi_paddle_module=umi_paddle_module or suggested_umi_paddle_module(),
        )
    )
    return create_umi_paddle_engine(options)


def run_rapidocr_item(image: Path, engine: Any) -> dict[str, Any]:
    started = time.monotonic()
    try:
        result = recognize_image_with_rapidocr(image, engine)
        return item_result(image, result.get("text") or "", result.get("blocks") or [], started=started)
    except Exception as exc:  # noqa: BLE001
        return item_result(image, "", [], started=started, status="failed", message=str(exc))


def run_umi_item(image: Path, engine: Any) -> dict[str, Any]:
    started = time.monotonic()
    try:
        text, blocks = umi_ocr_image_with_blocks(image, engine)
        for block in blocks:
            block.setdefault("provider", "umi")
        return item_result(image, text, blocks, started=started)
    except Exception as exc:  # noqa: BLE001
        return item_result(image, "", [], started=started, status="failed", message=str(exc))


def item_result(
    image: Path,
    text: str,
    blocks: list[dict[str, Any]],
    *,
    started: float,
    status: str = "ok",
    message: str = "",
) -> dict[str, Any]:
    text = str(text or "").strip()
    blocks = list(blocks or [])
    return {
        "image": str(image),
        "status": status,
        "message": message,
        "duration_seconds": round(time.monotonic() - started, 4),
        "char_count": len(text),
        "line_count": len([line for line in text.splitlines() if line.strip()]),
        "block_count": len(blocks),
        "bbox_count": sum(1 for block in blocks if block.get("bbox")),
        "empty": not bool(text),
        "text_preview": text[:120],
    }


def summarize_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(items)
    failed = sum(1 for item in items if item.get("status") == "failed")
    empty = sum(1 for item in items if item.get("empty"))
    duration = sum(float(item.get("duration_seconds") or 0) for item in items)
    chars = sum(int(item.get("char_count") or 0) for item in items)
    blocks = sum(int(item.get("block_count") or 0) for item in items)
    bbox = sum(int(item.get("bbox_count") or 0) for item in items)
    return {
        "sample_count": total,
        "failed_count": failed,
        "empty_count": empty,
        "empty_rate": round(empty / total, 4) if total else 0.0,
        "total_duration_seconds": round(duration, 4),
        "avg_duration_seconds": round(duration / total, 4) if total else 0.0,
        "total_char_count": chars,
        "avg_char_count": round(chars / total, 2) if total else 0.0,
        "total_block_count": blocks,
        "avg_block_count": round(blocks / total, 2) if total else 0.0,
        "total_bbox_count": bbox,
        "bbox_coverage": round(bbox / blocks, 4) if blocks else 0.0,
    }


def summarize_provider_results(provider_results: list[dict[str, Any]], *, image_count: int) -> dict[str, Any]:
    ok = [item for item in provider_results if item.get("status") in {"ok", "partial", "skipped"}]
    missing = [item for item in provider_results if item.get("status") == "missing"]
    failed = [item for item in provider_results if item.get("status") == "failed"]
    if not image_count:
        status = "skipped"
    elif missing and len(missing) == len(provider_results):
        status = "skipped"
    elif ok and not failed:
        status = "ok" if not missing else "partial"
    elif ok:
        status = "partial"
    else:
        status = "failed"
    return {
        "status": status,
        "provider_count": len(provider_results),
        "ok_or_partial_count": len(ok),
        "missing_count": len(missing),
        "failed_count": len(failed),
    }


def provider_unavailable_exception(exc: Exception) -> bool:
    if isinstance(exc, (FileNotFoundError, ModuleNotFoundError, ImportError, PermissionError)):
        return True
    message = str(exc).lower()
    return "permission denied" in message or "not installed" in message or "not found" in message


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# OCR Provider Comparison",
        "",
        f"- Generated: {payload.get('created_at')}",
        f"- Status: {payload.get('status')}",
        f"- Images: {payload.get('image_count')}",
        f"- JSON: `{payload.get('json_report', 'ocr-provider-comparison.json')}`",
        "",
        "| Provider | Status | Samples | Empty | Chars | Blocks | BBox coverage | Avg sec | Message |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for provider in payload.get("providers") or []:
        metrics = provider.get("metrics") or {}
        lines.append(
            f"| {provider.get('provider')} | {provider.get('status')} | "
            f"{metrics.get('sample_count', 0)} | {metrics.get('empty_count', 0)} | "
            f"{metrics.get('total_char_count', 0)} | {metrics.get('total_block_count', 0)} | "
            f"{metrics.get('bbox_coverage', 0)} | {metrics.get('avg_duration_seconds', 0)} | "
            f"{markdown_cell(str(provider.get('message') or ''))} |"
        )
    lines.append("")
    lines.append("## Per Image")
    lines.append("")
    for provider in payload.get("providers") or []:
        lines.append(f"### {provider.get('provider')} ({provider.get('status')})")
        lines.append("")
        lines.append("| Image | Status | Chars | Blocks | BBox | Sec | Preview |")
        lines.append("| --- | --- | ---: | ---: | ---: | ---: | --- |")
        for item in provider.get("items") or []:
            lines.append(
                f"| {markdown_cell(Path(str(item.get('image') or '')).name)} | {item.get('status')} | "
                f"{item.get('char_count', 0)} | {item.get('block_count', 0)} | {item.get('bbox_count', 0)} | "
                f"{item.get('duration_seconds', 0)} | {markdown_cell(str(item.get('text_preview') or item.get('message') or ''))} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")[:240]


if __name__ == "__main__":
    raise SystemExit(main())
