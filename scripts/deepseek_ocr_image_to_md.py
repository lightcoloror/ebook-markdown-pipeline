from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

from document_vlm_artifact_utils import write_document_vlm_result


DEFAULT_PYTHON = os.environ.get("DEEPSEEK_OCR_PYTHON", sys.executable)
DEFAULT_MODEL = os.environ.get("DEEPSEEK_OCR_MODEL", "deepseek-ai/DeepSeek-OCR")
DEFAULT_PROMPT_MODE = os.environ.get("DEEPSEEK_OCR_PROMPT_MODE", "markdown")
TOOL_CACHE = Path(
    os.environ.get(
        "EBOOK_CONVERTER_TOOL_CACHE",
        Path(__file__).resolve().parents[2] / "tools",
    )
)

PROMPT_PRESETS = {
    "markdown": "<image>\n<|grounding|>Convert the document to markdown.",
    "ocr": "<image>\n<|grounding|>OCR this image.",
    "free": "<image>\nFree OCR.",
    "describe": "<image>\nDescribe this image in detail.",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run DeepSeek-OCR Transformers inference on one image/PDF page and normalize output to Markdown.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--python", default=DEFAULT_PYTHON)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--prompt-mode", choices=sorted(PROMPT_PRESETS), default=DEFAULT_PROMPT_MODE if DEFAULT_PROMPT_MODE in PROMPT_PRESETS else "markdown")
    parser.add_argument("--prompt", default=os.environ.get("DEEPSEEK_OCR_PROMPT", ""))
    parser.add_argument("--base-size", type=int, default=int(os.environ.get("DEEPSEEK_OCR_BASE_SIZE", "1024")))
    parser.add_argument("--image-size", type=int, default=int(os.environ.get("DEEPSEEK_OCR_IMAGE_SIZE", "640")))
    parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default=os.environ.get("DEEPSEEK_OCR_DEVICE", "auto"))
    parser.add_argument("--attention", choices=["auto", "flash_attention_2", "eager", "sdpa"], default=os.environ.get("DEEPSEEK_OCR_ATTENTION", "auto"))
    parser.add_argument("--no-crop", action="store_true")
    parser.add_argument("--no-test-compress", action="store_true")
    parser.add_argument("--timeout", type=float, default=float(os.environ.get("DEEPSEEK_OCR_TIMEOUT", "0") or 0))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source = args.input.resolve()
    output = args.output.resolve()
    raw_dir = (args.output_dir or output.parent / "deepseek_ocr_raw").resolve()
    command = build_deepseek_command(args, source, raw_dir)
    env = os.environ.copy()
    configure_cache(env, create_dirs=not args.dry_run)
    if args.dry_run:
        print(subprocess.list2cmdline(command))
        print(f"document_vlm_result={raw_dir / 'document-vlm-result.json'}")
        return 0

    validate_runtime(args, source)
    output.parent.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        command,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
        timeout=args.timeout if args.timeout > 0 else None,
        check=False,
    )
    markdown = stdout_to_markdown(completed.stdout or "", source=source, raw_dir=raw_dir, mode=args.prompt_mode)
    output.write_text(markdown.rstrip() + "\n", encoding="utf-8", newline="\n")
    write_document_vlm_result(
        raw_dir / "document-vlm-result.json",
        backend="deepseek_ocr",
        source=source,
        markdown_path=output,
        markdown=markdown,
        mode=args.prompt_mode,
        raw_dir=raw_dir,
        command=command,
        status="review" if completed.returncode == 0 else "failed",
    )
    if completed.returncode != 0:
        print((completed.stdout or "")[-4000:], file=sys.stderr)
        return completed.returncode
    print(str(output))
    return 0


def build_deepseek_command(args: argparse.Namespace, source: Path, raw_dir: Path) -> list[str]:
    runner = Path(__file__).with_name("deepseek_ocr_transformers_runner.py")
    command = [
        str(args.python),
        str(runner),
        "--input",
        str(source),
        "--output-dir",
        str(raw_dir),
        "--model",
        str(args.model),
        "--prompt",
        prompt_from_args(args),
        "--base-size",
        str(args.base_size),
        "--image-size",
        str(args.image_size),
        "--device",
        str(args.device),
        "--attention",
        str(args.attention),
    ]
    if args.no_crop:
        command.append("--no-crop")
    if args.no_test_compress:
        command.append("--no-test-compress")
    return command


def prompt_from_args(args: argparse.Namespace) -> str:
    custom = str(getattr(args, "prompt", "") or "").strip()
    if custom:
        return custom
    return PROMPT_PRESETS.get(str(args.prompt_mode), PROMPT_PRESETS["markdown"])


def validate_runtime(args: argparse.Namespace, source: Path) -> None:
    python = Path(str(args.python))
    if not python.exists() and not str(args.python).lower().startswith("python"):
        raise FileNotFoundError(f"DeepSeek-OCR python executable not found: {args.python}")
    runner = Path(__file__).with_name("deepseek_ocr_transformers_runner.py")
    if not runner.exists():
        raise FileNotFoundError(f"DeepSeek-OCR runner not found: {runner}")
    if not source.exists():
        raise FileNotFoundError(f"Input file not found: {source}")
    if not str(args.model).strip():
        raise FileNotFoundError("DeepSeek-OCR model path/id is empty. Set DEEPSEEK_OCR_MODEL or pass --model.")


def configure_cache(env: dict[str, str], *, create_dirs: bool) -> None:
    env.setdefault("HF_HOME", str(TOOL_CACHE / "huggingface"))
    env.setdefault("TRANSFORMERS_CACHE", str(TOOL_CACHE / "huggingface" / "transformers"))
    env.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    env.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
    env.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    if create_dirs:
        for key in ("HF_HOME", "TRANSFORMERS_CACHE"):
            Path(env[key]).mkdir(parents=True, exist_ok=True)


def stdout_to_markdown(stdout: str, *, source: Path, raw_dir: Path, mode: str) -> str:
    text = collect_output_text(raw_dir) or clean_stdout(stdout)
    if not text:
        text = "[No DeepSeek-OCR text captured from stdout or output files.]"
    return "\n".join(
        [
            f"# DeepSeek-OCR {mode} result",
            "",
            f"- Source: `{source}`",
            f"- Raw output: `{raw_dir}`",
            "",
            text,
            "",
        ]
    )


def collect_output_text(raw_dir: Path) -> str:
    if not raw_dir.exists():
        return ""
    candidates: list[Path] = []
    for pattern in ("*.md", "*.txt"):
        candidates.extend(raw_dir.rglob(pattern))
    candidates = sorted((path for path in candidates if path.is_file()), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in candidates:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if text:
            return text
    return ""


def clean_stdout(stdout: str) -> str:
    lines = []
    for line in str(stdout or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.search(r"^(loading|using|model|cuda|device|torch|transformers|time cost|image:|output_dir)", stripped, re.I):
            continue
        lines.append(stripped)
    return "\n".join(lines).strip()


if __name__ == "__main__":
    raise SystemExit(main())
