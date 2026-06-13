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
    if results_json and results_json.exists():
        markdown = results_to_markdown(json.loads(results_json.read_text(encoding="utf-8")), args.mode)
    else:
        markdown = (
            "# Surya output unavailable\n\n"
            f"Return code: {completed.returncode}\n\n"
            "```text\n"
            f"{(completed.stdout or '')[-4000:]}\n"
            "```\n"
        )
    output.write_text(markdown.rstrip() + "\n", encoding="utf-8", newline="\n")
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
