from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from pprint import pformat
from typing import Any


TOOL_CACHE = Path(
    os.environ.get(
        "EBOOK_CONVERTER_TOOL_CACHE",
        Path(__file__).resolve().parents[2] / "tools",
    )
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Surya OCR/layout/table CLI on one image/PDF and normalize output to Markdown.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--mode", choices=["ocr", "layout", "table"], default="ocr")
    parser.add_argument("--command", default=None)
    parser.add_argument("--page-range", default="")
    parser.add_argument("--images", action="store_true")
    parser.add_argument("--timeout", type=float, default=0.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source = args.input.resolve()
    output = args.output.resolve()
    raw_dir = (args.output_dir or output.parent / "surya_raw").resolve()
    command = args.command or default_surya_command(args.mode)
    cmd = [command, str(source), "--output_dir", str(raw_dir)]
    if args.page_range:
        cmd.extend(["--page_range", args.page_range])
    if args.images:
        cmd.append("--images")

    env = os.environ.copy()
    configure_surya_cache(env, create_dirs=not args.dry_run)
    if args.dry_run:
        print(subprocess.list2cmdline(cmd))
        sidecar = candidate_sidecar_path(raw_dir, args.mode)
        if sidecar:
            print(f"{sidecar.stem.replace('-', '_')}={sidecar}")
        return 0

    executable = shutil.which(command) or (command if Path(command).exists() else "")
    if not executable:
        raise FileNotFoundError(f"Surya command not found: {command}")
    cmd[0] = executable
    output.parent.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        cmd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
        timeout=args.timeout if args.timeout > 0 else None,
        check=False,
    )
    results_json = pick_results_json(raw_dir, source)
    data = None
    if results_json and results_json.exists():
        data = json.loads(results_json.read_text(encoding="utf-8"))
        markdown = results_to_markdown(data, args.mode)
    else:
        markdown = (
            "# Surya output unavailable\n\n"
            f"Return code: {completed.returncode}\n\n"
            "```text\n"
            f"{(completed.stdout or '')[-4000:]}\n"
            "```\n"
        )
    output.write_text(markdown.rstrip() + "\n", encoding="utf-8", newline="\n")
    if isinstance(data, dict):
        write_surya_candidate_sidecars(raw_dir, source, output, args.mode, data)
    if completed.returncode != 0:
        print((completed.stdout or "")[-4000:], file=sys.stderr)
        return completed.returncode
    print(str(output))
    return 0


def default_surya_command(mode: str) -> str:
    if mode == "layout":
        return os.environ.get("SURYA_LAYOUT_COMMAND", "surya_layout")
    if mode == "table":
        return os.environ.get("SURYA_TABLE_COMMAND", "surya_table")
    return os.environ.get("SURYA_OCR_COMMAND", "surya_ocr")


def configure_surya_cache(env: dict[str, str], *, create_dirs: bool) -> None:
    env.setdefault("HF_HOME", str(TOOL_CACHE / "huggingface"))
    env.setdefault("TRANSFORMERS_CACHE", str(TOOL_CACHE / "huggingface" / "transformers"))
    env.setdefault("SURYA_CACHE_DIR", str(TOOL_CACHE / "surya"))
    env.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    env.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
    env.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    if create_dirs:
        for key in ("HF_HOME", "TRANSFORMERS_CACHE", "SURYA_CACHE_DIR"):
            Path(env[key]).mkdir(parents=True, exist_ok=True)


def pick_results_json(raw_dir: Path, source: Path) -> Path | None:
    preferred = raw_dir / source.stem / "results.json"
    if preferred.exists():
        return preferred
    matches = sorted(raw_dir.rglob("results.json"))
    return matches[0] if matches else None


def candidate_sidecar_path(raw_dir: Path, mode: str) -> Path | None:
    if mode == "layout":
        return raw_dir / "layout-candidates.json"
    if mode == "table":
        return raw_dir / "table-candidates.json"
    return None


def write_surya_candidate_sidecars(raw_dir: Path, source: Path, output: Path, mode: str, data: dict[str, Any]) -> list[Path]:
    sidecar = candidate_sidecar_path(raw_dir, mode)
    if sidecar is None:
        return []
    if mode == "layout":
        payload = build_layout_candidates_payload(source, output, data)
    elif mode == "table":
        payload = build_table_candidates_payload(source, output, data)
    else:
        return []
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return [sidecar]


def build_layout_candidates_payload(source: Path, output: Path, data: dict[str, Any]) -> dict[str, Any]:
    pages = []
    warnings = []
    for name, index, page in iter_surya_pages(data):
        blocks = layout_blocks_from_page(page)
        if not blocks:
            warnings.append(f"no layout blocks on {name} page {index}")
        pages.append({"page": page_number_from(page, index), "source": str(name), "blocks": blocks})
    return {
        "schema_version": "layout-candidates-v1",
        "backend": "surya",
        "status": "review",
        "mode": "layout",
        "input": str(source),
        "markdown": str(output),
        "pages": pages,
        "artifacts": [{"type": "markdown", "path": str(output)}],
        "warnings": warnings[:20],
    }


def build_table_candidates_payload(source: Path, output: Path, data: dict[str, Any]) -> dict[str, Any]:
    pages = []
    warnings = []
    for name, index, page in iter_surya_pages(data):
        tables = table_candidates_from_page(page)
        if not tables:
            warnings.append(f"no table candidates on {name} page {index}")
        pages.append({"page": page_number_from(page, index), "source": str(name), "tables": tables})
    return {
        "schema_version": "table-candidates-v1",
        "backend": "surya",
        "status": "review",
        "mode": "table",
        "input": str(source),
        "markdown": str(output),
        "pages": pages,
        "artifacts": [{"type": "markdown", "path": str(output)}],
        "warnings": warnings[:20],
    }


def iter_surya_pages(data: Any):
    if isinstance(data, dict):
        for name, pages in data.items():
            if isinstance(pages, list):
                for index, page in enumerate(pages, start=1):
                    yield name, index, page
            else:
                yield name, 1, pages
    elif isinstance(data, list):
        for index, page in enumerate(data, start=1):
            yield "surya", index, page


def page_number_from(page: Any, default: int) -> int:
    if isinstance(page, dict):
        for key in ("page", "page_number", "page_idx", "page_index"):
            value = page.get(key)
            number = int_or_none(value)
            if number is not None:
                return number + 1 if str(value).isdigit() and int(value) == 0 else number
    return default


def layout_blocks_from_page(page: Any) -> list[dict[str, Any]]:
    if not isinstance(page, dict):
        return []
    raw_blocks = first_list(page, "bboxes", "blocks", "layout", "predictions")
    blocks: list[dict[str, Any]] = []
    for position, block in enumerate(raw_blocks, start=1):
        if not isinstance(block, dict):
            continue
        candidate = common_candidate_fields(block, position=position, default_label="block")
        text = block.get("text") or block.get("html")
        if text:
            candidate["text"] = html_fragment_to_markdown(str(text)) or str(text)
        blocks.append(candidate)
    return blocks


def table_candidates_from_page(page: Any) -> list[dict[str, Any]]:
    if isinstance(page, list):
        raw_tables = page
    elif isinstance(page, dict):
        raw_tables = first_list(page, "tables", "table", "bboxes")
        if not raw_tables and isinstance(page.get("cells"), list):
            raw_tables = [{"cells": page.get("cells"), "bbox": page.get("bbox")}]
    else:
        return []
    tables: list[dict[str, Any]] = []
    for position, table in enumerate(raw_tables, start=1):
        if not isinstance(table, dict):
            continue
        candidate = common_candidate_fields(table, position=position, default_label="table")
        for key in ("html", "markdown", "text", "cells", "rows", "cols", "row_count", "col_count", "mode"):
            if key in table:
                candidate[key] = jsonable(table.get(key))
        tables.append(candidate)
    return tables


def first_list(value: dict[str, Any], *keys: str) -> list[Any]:
    for key in keys:
        item = value.get(key)
        if isinstance(item, list):
            return item
        if isinstance(item, dict):
            return [item]
    return []


def common_candidate_fields(item: dict[str, Any], *, position: int, default_label: str) -> dict[str, Any]:
    candidate: dict[str, Any] = {
        "label": str(item.get("label") or item.get("class_name") or item.get("type") or default_label),
        "position": int_or_none(item.get("position")) or position,
    }
    bbox = normalize_bbox(item.get("bbox") or item.get("box") or item.get("polygon") or item.get("poly"))
    if bbox is not None:
        candidate["bbox"] = bbox
    confidence = float_or_none(item.get("confidence") or item.get("score") or item.get("probability"))
    if confidence is not None:
        candidate["confidence"] = confidence
    reading_order = int_or_none(item.get("reading_order") or item.get("order"))
    if reading_order is not None:
        candidate["reading_order"] = reading_order
    return candidate


def normalize_bbox(value: Any) -> Any | None:
    if value is None:
        return None
    if hasattr(value, "tolist"):
        value = value.tolist()
    return jsonable(value)


def jsonable(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None

def results_to_markdown(data, mode: str) -> str:
    lines = [f"# Surya {mode} result", ""]
    if not isinstance(data, dict):
        return pformat(data)
    for name, pages in data.items():
        lines.extend([f"## {name}", ""])
        if not isinstance(pages, list):
            lines.extend(["```json", json.dumps(pages, ensure_ascii=False, indent=2), "```", ""])
            continue
        for index, page in enumerate(pages, start=1):
            page_number = page.get("page") if isinstance(page, dict) else index
            lines.extend([f"### Page {page_number}", ""])
            if mode == "ocr":
                lines.extend(render_ocr_page(page))
            elif mode == "layout":
                lines.extend(render_layout_page(page))
            else:
                lines.extend(render_table_page(page))
            lines.append("")
    return "\n".join(lines).strip()


def render_ocr_page(page) -> list[str]:
    if not isinstance(page, dict):
        return ["```json", json.dumps(page, ensure_ascii=False, indent=2), "```"]
    blocks = page.get("blocks") or []
    lines: list[str] = []
    for block in sorted(blocks, key=lambda item: int(item.get("reading_order") or item.get("position") or 0) if isinstance(item, dict) else 0):
        if not isinstance(block, dict):
            continue
        label = str(block.get("label") or "Text")
        html_text = str(block.get("html") or "").strip()
        text = html_fragment_to_markdown(html_text)
        if not text:
            text = f"[{label} skipped]"
        if label == "SectionHeader":
            lines.extend([f"#### {text}", ""])
        elif label in {"PageHeader", "PageFooter"}:
            lines.append(f"> {label}: {text}")
        elif label == "Table" and "<table" in html_text.lower():
            lines.extend([html_text, ""])
        else:
            lines.extend([text, ""])
    return lines or ["[No OCR blocks]"]


def render_layout_page(page) -> list[str]:
    if not isinstance(page, dict):
        return ["```json", json.dumps(page, ensure_ascii=False, indent=2), "```"]
    rows = []
    for box in page.get("bboxes") or []:
        if not isinstance(box, dict):
            continue
        rows.append(
            f"- {box.get('position', '')}: {box.get('label', '')} "
            f"confidence={box.get('confidence', '')} bbox={box.get('bbox', '')}"
        )
    return rows or ["[No layout boxes]"]


def render_table_page(page) -> list[str]:
    if not isinstance(page, (dict, list)):
        return ["```json", json.dumps(page, ensure_ascii=False, indent=2), "```"]
    rows = []
    tables = page if isinstance(page, list) else page.get("tables") or page.get("bboxes") or page.get("cells") or []
    if isinstance(tables, dict):
        tables = [tables]
    for table in tables:
        if not isinstance(table, dict):
            continue
        html_table = table.get("html")
        if html_table:
            rows.extend([str(html_table), ""])
            continue
        rows.append(
            f"- table mode={table.get('mode', '')} rows={len(table.get('rows') or [])} "
            f"cols={len(table.get('cols') or [])} cells={len(table.get('cells') or [])}"
        )
    return rows or ["[No table blocks]"]


def html_fragment_to_markdown(value: str) -> str:
    if not value:
        return ""
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"</p\s*>", "\n\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", "", value)
    value = html.unescape(value)
    value = re.sub(r"[ \t]+\n", "\n", value)
    return "\n".join(line.strip() for line in value.splitlines()).strip()


if __name__ == "__main__":
    raise SystemExit(main())
