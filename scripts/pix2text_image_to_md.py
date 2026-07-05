from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from pprint import pformat
from typing import Any


TOOL_CACHE = Path(
    os.environ.get(
        "EBOOK_CONVERTER_TOOL_CACHE",
        Path.home() / ".cache" / "ebook-markdown-pipeline",
    )
)
PROJECT_TOOL_CACHE = Path(__file__).resolve().parents[1] / ".cache" / "tools"


FORMULA_CANDIDATES_SCHEMA_VERSION = "formula-candidates-v1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Pix2Text on one image/PDF and write normalized Markdown.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--device", default=os.environ.get("PIX2TEXT_DEVICE", "cpu"))
    parser.add_argument("--languages", default=os.environ.get("PIX2TEXT_LANGUAGES", "en,ch_sim"))
    parser.add_argument("--file-type", default="page", choices=["pdf", "page", "text_formula", "formula", "text"])
    parser.add_argument("--resized-shape", type=int, default=768)
    parser.add_argument("--disable-formula", action="store_true")
    parser.add_argument("--disable-table", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    image = args.input.resolve()
    output = args.output.resolve()
    work_dir = (args.output_dir or output.parent / "pix2text_raw").resolve()

    if args.dry_run:
        configure_local_cache(create_dirs=False)
        print(f"input={image}")
        print(f"output={output}")
        print(f"output_dir={work_dir}")
        print(f"device={args.device}")
        print(f"languages={args.languages}")
        print(f"file_type={args.file_type}")
        print(f"formula_candidates={work_dir / 'formula-candidates.json'}")
        print(f"pix2text_home={os.environ.get('PIX2TEXT_HOME', '')}")
        return 0

    configure_local_cache(create_dirs=True)

    from pix2text import Pix2Text

    output.parent.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    languages = [lang.strip() for lang in str(args.languages).split(",") if lang.strip()]
    p2t = Pix2Text.from_config(
        total_configs={"text_formula": {"languages": languages}},
        enable_formula=not args.disable_formula,
        enable_table=not args.disable_table,
        device=args.device,
    )
    result = p2t.recognize(
        str(image),
        file_type=args.file_type,
        resized_shape=args.resized_shape,
        return_text=return_text_for_file_type(args.file_type),
        auto_line_break=True,
        save_debug_res=str(work_dir / "debug") if args.file_type in {"pdf", "page"} else None,
        save_analysis_res=str(work_dir / "analysis.png") if args.file_type not in {"pdf", "page"} else None,
    )
    markdown = result_to_markdown(result, work_dir)
    output.write_text(markdown.rstrip() + "\n", encoding="utf-8", newline="\n")
    write_formula_candidates(
        work_dir / "formula-candidates.json",
        result,
        input_path=image,
        markdown_path=output,
        file_type=args.file_type,
        markdown=markdown,
        formula_disabled=args.disable_formula,
    )
    print(str(output))
    return 0


def return_text_for_file_type(file_type: str) -> bool:
    if file_type in {"formula", "text_formula"}:
        return False
    return file_type not in {"pdf", "page"}


def configure_local_cache(*, create_dirs: bool) -> None:
    os.environ.setdefault("PIX2TEXT_HOME", str(TOOL_CACHE / "pix2text"))
    os.environ.setdefault("HF_HOME", str(TOOL_CACHE / "huggingface"))
    os.environ.setdefault("TRANSFORMERS_CACHE", str(TOOL_CACHE / "huggingface" / "transformers"))
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    if not create_dirs:
        return
    configured_cache = os.environ.get("EBOOK_CONVERTER_TOOL_CACHE")
    for key in ("PIX2TEXT_HOME", "HF_HOME", "TRANSFORMERS_CACHE"):
        try:
            Path(os.environ[key]).mkdir(parents=True, exist_ok=True)
        except PermissionError:
            if configured_cache:
                raise
            fallback = PROJECT_TOOL_CACHE
            os.environ["PIX2TEXT_HOME"] = str(fallback / "pix2text")
            os.environ["HF_HOME"] = str(fallback / "huggingface")
            os.environ["TRANSFORMERS_CACHE"] = str(fallback / "huggingface" / "transformers")
            for fallback_key in ("PIX2TEXT_HOME", "HF_HOME", "TRANSFORMERS_CACHE"):
                Path(os.environ[fallback_key]).mkdir(parents=True, exist_ok=True)
            return


def result_to_markdown(result: Any, work_dir: Path) -> str:
    if hasattr(result, "to_markdown"):
        try:
            markdown = result.to_markdown(work_dir, markdown_fn="output.md")
        except TypeError:
            markdown = result.to_markdown(work_dir)
        return str(markdown or "").strip()
    if isinstance(result, str):
        return result.strip()
    if isinstance(result, dict):
        text = text_from_formula_like_item(result)
        return text or pformat(to_jsonable(result)).strip()
    if isinstance(result, list):
        pix2text_markdown = pix2text_blocks_to_markdown(result)
        if pix2text_markdown:
            return pix2text_markdown
        lines = []
        for item in result:
            if isinstance(item, str):
                lines.append(item)
            else:
                lines.append(pformat(to_jsonable(item)))
        return "\n\n".join(line.strip() for line in lines if str(line).strip()).strip()
    return pformat(to_jsonable(result)).strip()


def pix2text_blocks_to_markdown(blocks: list[Any]) -> str:
    if not blocks or not all(isinstance(item, dict) for item in blocks):
        return ""
    lines: list[str] = []
    for block in blocks:
        text = str(block.get("text") or block.get("latex") or block.get("formula") or "").strip()
        if not text:
            continue
        block_type = str(block.get("type") or block.get("label") or "").lower()
        if block_type in {"isolated", "formula", "latex", "math"}:
            lines.extend(["$$", text, "$$", ""])
        elif block_type == "embedding":
            lines.append(f"${text}$")
        else:
            lines.extend([text, ""])
    return "\n".join(lines).strip()


def write_formula_candidates(
    path: Path,
    result: Any,
    *,
    input_path: Path,
    markdown_path: Path,
    file_type: str,
    markdown: str,
    formula_disabled: bool = False,
) -> Path:
    payload = formula_candidate_payload(
        result,
        input_path=input_path,
        markdown_path=markdown_path,
        file_type=file_type,
        markdown=markdown,
        formula_disabled=formula_disabled,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    return path


def formula_candidate_payload(
    result: Any,
    *,
    input_path: Path,
    markdown_path: Path,
    file_type: str,
    markdown: str = "",
    formula_disabled: bool = False,
) -> dict[str, Any]:
    formulas = extract_formula_candidates(result, source=str(input_path))
    if not formulas and markdown:
        formulas = formula_candidates_from_markdown(markdown, source=str(input_path))
    formulas = dedupe_formulas(formulas)
    warnings = []
    if formula_disabled:
        warnings.append("formula recognition was disabled for this Pix2Text run")
    if not formulas:
        warnings.append("no formula candidates detected; keep Markdown as primary output")
    return {
        "schema_version": FORMULA_CANDIDATES_SCHEMA_VERSION,
        "backend": "pix2text",
        "status": "review",
        "input": str(input_path),
        "markdown": str(markdown_path),
        "file_type": file_type,
        "pages": [
            {
                "page": 1,
                "source": str(input_path),
                "formulas": formulas,
            }
        ],
        "formula_count": len(formulas),
        "artifacts": [{"type": "markdown", "path": str(markdown_path), "label": "Pix2Text Markdown"}],
        "warnings": warnings,
        "promotion_use": "formula retention review side evidence; do not silently mutate final Markdown",
    }


def extract_formula_candidates(value: Any, *, source: str, page: int = 1) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    visit_formula_value(value, candidates, source=source, page=page, path="result")
    for index, item in enumerate(candidates, start=1):
        item.setdefault("id", f"p{page}-f{index}")
    return candidates


def visit_formula_value(value: Any, candidates: list[dict[str, Any]], *, source: str, page: int, path: str) -> None:
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, str):
        if looks_like_latex(value):
            candidates.append({"page": page, "source": source, "latex": value.strip(), "origin": path})
        return
    if isinstance(value, dict):
        if is_formula_item(value):
            candidate = candidate_from_formula_item(value, source=source, page=page, origin=path)
            if candidate:
                candidates.append(candidate)
                return
        for key, child in value.items():
            visit_formula_value(child, candidates, source=source, page=page, path=f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            visit_formula_value(child, candidates, source=source, page=page, path=f"{path}[{index}]")
        return
    if hasattr(value, "__dict__"):
        visit_formula_value(vars(value), candidates, source=source, page=page, path=f"{path}.{type(value).__name__}")


def is_formula_item(item: dict[str, Any]) -> bool:
    kind = str(item.get("type") or item.get("label") or item.get("category") or item.get("block_type") or "").lower()
    if kind in {"formula", "isolated", "embedding", "latex", "math", "math_formula"}:
        return True
    if any(key in item for key in ("latex", "formula", "latex_text", "formula_text")):
        return True
    text = str(item.get("text") or "").strip()
    return "formula" in kind and bool(text)


def candidate_from_formula_item(item: dict[str, Any], *, source: str, page: int, origin: str) -> dict[str, Any] | None:
    latex = text_from_formula_like_item(item)
    if not latex:
        return None
    candidate: dict[str, Any] = {
        "page": int(item.get("page") or item.get("page_number") or page),
        "source": str(item.get("source") or source),
        "latex": latex,
        "origin": origin,
    }
    kind = str(item.get("type") or item.get("label") or item.get("category") or "").strip()
    if kind:
        candidate["kind"] = kind
    score = item.get("score") or item.get("confidence")
    if isinstance(score, (int, float)):
        candidate["confidence"] = float(score)
    position = normalize_position(item.get("bbox") or item.get("box") or item.get("position"))
    if position is not None:
        candidate["bbox"] = position
    line_number = item.get("line_number")
    if isinstance(line_number, int):
        candidate["line_number"] = line_number
    return candidate


def text_from_formula_like_item(item: dict[str, Any]) -> str:
    for key in ("latex", "formula", "latex_text", "formula_text", "text"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def formula_candidates_from_markdown(markdown: str, *, source: str, page: int = 1) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    consumed: list[tuple[int, int]] = []
    for match in re.finditer(r"\$\$(.+?)\$\$", markdown, flags=re.S):
        latex = " ".join(match.group(1).strip().split())
        if looks_like_latex(latex):
            consumed.append(match.span())
            candidates.append({"page": page, "source": source, "latex": latex, "kind": "isolated", "origin": "markdown"})
    for match in re.finditer(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)", markdown, flags=re.S):
        if any(start <= match.start() < end for start, end in consumed):
            continue
        latex = " ".join(match.group(1).strip().split())
        if looks_like_latex(latex):
            candidates.append({"page": page, "source": source, "latex": latex, "kind": "embedding", "origin": "markdown"})
    for index, item in enumerate(candidates, start=1):
        item.setdefault("id", f"p{page}-mdf{index}")
    return candidates


def looks_like_latex(value: str) -> bool:
    text = str(value or "").strip()
    if len(text) < 2:
        return False
    if text.startswith("$") and text.endswith("$"):
        text = text.strip("$").strip()
    math_markers = ("\\", "_", "^", "=", "{", "}", "\u2211", "\u222b", "\u03b1", "\u03b2", "\u03b3")
    if any(marker in text for marker in math_markers):
        return True
    return bool(re.search(r"[A-Za-z0-9]\s*[+\-*/<>]\s*[A-Za-z0-9]", text))


def normalize_position(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "tolist"):
        value = value.tolist()
    value = to_jsonable(value)
    if isinstance(value, (list, tuple)) and value:
        return value
    return None


def dedupe_formulas(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        latex = str(item.get("latex") or "").strip()
        bbox = json.dumps(item.get("bbox") or [], ensure_ascii=False, sort_keys=True)
        key = (latex, bbox)
        if not latex or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    for index, item in enumerate(unique, start=1):
        item["id"] = item.get("id") or f"p{item.get('page') or 1}-f{index}"
    return unique


def to_jsonable(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return to_jsonable(value.tolist())
    if isinstance(value, dict):
        return {str(key): to_jsonable(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(child) for child in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
