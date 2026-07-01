from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL_CACHE = Path(
    os.environ.get(
        "EBOOK_CONVERTER_TOOL_CACHE",
        Path.home() / ".cache" / "ebook-markdown-pipeline",
    )
)


def default_paddleocr_command() -> str:
    configured = os.environ.get("EBOOK_CONVERTER_PADDLEOCR_COMMAND", "").strip().strip('"')
    if configured:
        return configured
    return shutil.which("paddleocr") or "paddleocr"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PaddleOCR-VL doc_parser for one image and normalize output to Markdown.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--pipeline-version", default="v1.6", choices=["v1", "v1.5", "v1.6"])
    parser.add_argument("--timeout", type=float, default=0.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    image = args.input.resolve()
    output = args.output.resolve()
    work_dir = (args.output_dir or output.parent / "paddleocr_vl_raw").resolve()

    env = os.environ.copy()
    configure_local_cache(env)
    command = [
        default_paddleocr_command(),
        "doc_parser",
        "--input",
        str(image),
        "--save_path",
        str(work_dir),
        "--pipeline_version",
        args.pipeline_version,
        "--device",
        args.device,
        "--engine",
        "transformers",
        "--use_chart_recognition",
        "True",
        "--use_ocr_for_image_block",
        "True",
        "--format_block_content",
        "True",
        "--merge_layout_blocks",
        "True",
        "--max_new_tokens",
        "2048",
    ]
    if args.dry_run:
        print(subprocess.list2cmdline(command))
        return 0
    work_dir.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not shutil.which(command[0]) and not Path(command[0]).exists():
        raise FileNotFoundError(f"paddleocr executable not found: {command[0]}")
    completed = subprocess.run(
        command,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=args.timeout if args.timeout > 0 else None,
        check=False,
    )
    candidate = pick_text_artifact(work_dir)
    if candidate:
        write_normalized_markdown(candidate, output, work_dir)
    else:
        output.write_text(
            "# PaddleOCR-VL output unavailable\n\n"
            f"Return code: {completed.returncode}\n\n"
            "```text\n"
            f"{completed.stdout[-4000:]}\n"
            "```\n",
            encoding="utf-8",
            newline="\n",
        )
    if completed.returncode != 0:
        print(completed.stdout[-4000:], file=sys.stderr)
        return completed.returncode
    print(str(output))
    return 0


def configure_local_cache(env: dict[str, str]) -> None:
    env.setdefault("HOME", str(TOOL_CACHE / "vlm-home"))
    env.setdefault("USERPROFILE", str(TOOL_CACHE / "vlm-home"))
    env.setdefault("XDG_CACHE_HOME", str(TOOL_CACHE / "vlm-cache"))
    env.setdefault("PADDLE_HOME", str(TOOL_CACHE / "paddle-cache"))
    env.setdefault("PADDLE_PDX_CACHE_HOME", str(TOOL_CACHE / "paddlex-cache"))
    env.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    env.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
    env.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    for key in ("HOME", "USERPROFILE", "XDG_CACHE_HOME", "PADDLE_HOME", "PADDLE_PDX_CACHE_HOME"):
        Path(env[key]).mkdir(parents=True, exist_ok=True)


def pick_text_artifact(root: Path) -> Path | None:
    preferred = sorted(root.rglob("*.md")) + sorted(root.rglob("*.markdown")) + sorted(root.rglob("*.txt"))
    for path in preferred:
        try:
            if path.read_text(encoding="utf-8", errors="replace").strip():
                return path
        except Exception:
            continue
    return None


def write_normalized_markdown(candidate: Path, output: Path, raw_root: Path) -> None:
    markdown = candidate.read_text(encoding="utf-8", errors="replace").strip()
    tables = extract_actual_tables(raw_root)
    if tables:
        markdown = markdown.rstrip() + "\n\n## 真实表格 / Extracted Tables\n\n" + "\n\n".join(tables).strip()
    output.write_text(markdown.rstrip() + "\n", encoding="utf-8", newline="\n")


def extract_actual_tables(root: Path) -> list[str]:
    tables: list[str] = []
    tables.extend(extract_json_table_blocks(root))
    tables.extend(extract_docx_tables(root))
    return unique_markdown_blocks(tables)


def extract_json_table_blocks(root: Path) -> list[str]:
    tables: list[str] = []
    for path in sorted(root.rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        tables.extend(table_blocks_from_json_value(data))
    return tables


def table_blocks_from_json_value(value) -> list[str]:
    tables: list[str] = []
    if isinstance(value, dict):
        label = str(value.get("block_label") or value.get("label") or value.get("type") or "").lower()
        content = str(value.get("block_content") or value.get("content") or value.get("html") or "").strip()
        if "table" in label and content:
            tables.append(normalize_table_content(content))
        for child in value.values():
            tables.extend(table_blocks_from_json_value(child))
    elif isinstance(value, list):
        for child in value:
            tables.extend(table_blocks_from_json_value(child))
    return tables


def extract_docx_tables(root: Path) -> list[str]:
    try:
        from docx import Document
    except Exception:
        return []
    tables: list[str] = []
    for path in sorted(root.rglob("*.docx")):
        try:
            document = Document(str(path))
        except Exception:
            continue
        for table in document.tables:
            rows = [[clean_cell_text(cell.text) for cell in row.cells] for row in table.rows]
            markdown = table_rows_to_markdown(rows)
            if markdown:
                tables.append(markdown)
    return tables


def table_rows_to_markdown(rows: list[list[str]]) -> str:
    rows = [[cell for cell in row] for row in rows if any(cell.strip() for cell in row)]
    if not rows:
        return ""
    col_count = max(len(row) for row in rows)
    normalized = [row + [""] * (col_count - len(row)) for row in rows]
    if col_count < 2:
        return ""
    header = normalized[0]
    body = normalized[1:] or [[""] * col_count]
    lines = [
        "| " + " | ".join(markdown_cell(cell) for cell in header) + " |",
        "| " + " | ".join("---" for _ in range(col_count)) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(markdown_cell(cell) for cell in row) + " |")
    return "\n".join(lines)


def normalize_table_content(content: str) -> str:
    content = content.strip()
    if not content:
        return ""
    return content


def clean_cell_text(value: str) -> str:
    return " ".join(str(value).replace("\r", "\n").split())


def markdown_cell(value: str) -> str:
    return clean_cell_text(value).replace("|", r"\|")


def unique_markdown_blocks(blocks: list[str]) -> list[str]:
    seen = set()
    unique = []
    for block in blocks:
        normalized = "\n".join(line.rstrip() for line in str(block).strip().splitlines()).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


if __name__ == "__main__":
    raise SystemExit(main())
