from __future__ import annotations

import argparse
import os
from pathlib import Path
from pprint import pformat


TOOL_CACHE = Path(
    os.environ.get(
        "EBOOK_CONVERTER_TOOL_CACHE",
        Path.home() / ".cache" / "ebook-markdown-pipeline",
    )
)
PROJECT_TOOL_CACHE = Path(__file__).resolve().parents[1] / ".cache" / "tools"


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
        return_text=args.file_type not in {"pdf", "page"},
        auto_line_break=True,
        save_debug_res=str(work_dir / "debug") if args.file_type in {"pdf", "page"} else None,
        save_analysis_res=str(work_dir / "analysis.png") if args.file_type not in {"pdf", "page"} else None,
    )
    markdown = result_to_markdown(result, work_dir)
    output.write_text(markdown.rstrip() + "\n", encoding="utf-8", newline="\n")
    print(str(output))
    return 0


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


def result_to_markdown(result, work_dir: Path) -> str:
    if hasattr(result, "to_markdown"):
        try:
            markdown = result.to_markdown(work_dir, markdown_fn="output.md")
        except TypeError:
            markdown = result.to_markdown(work_dir)
        return str(markdown or "").strip()
    if isinstance(result, str):
        return result.strip()
    if isinstance(result, list):
        lines = []
        for item in result:
            if isinstance(item, str):
                lines.append(item)
            else:
                lines.append(pformat(item))
        return "\n\n".join(line.strip() for line in lines if str(line).strip()).strip()
    return pformat(result).strip()


if __name__ == "__main__":
    raise SystemExit(main())
