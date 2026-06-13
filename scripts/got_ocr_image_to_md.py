from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


DEFAULT_PYTHON = os.environ.get("GOT_OCR_PYTHON", sys.executable)
DEFAULT_SCRIPT = os.environ.get("GOT_OCR_SCRIPT", "")
DEFAULT_CROP_SCRIPT = os.environ.get("GOT_OCR_CROP_SCRIPT", "")
DEFAULT_MODEL = os.environ.get("GOT_OCR_MODEL", "")
TOOL_CACHE = Path(
    os.environ.get(
        "EBOOK_CONVERTER_TOOL_CACHE",
        Path(__file__).resolve().parents[2] / "tools",
    )
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run GOT-OCR 2.0 demo scripts on one image/folder and normalize stdout to Markdown.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--script", default=DEFAULT_SCRIPT, help="Path to GOT/demo/run_ocr_2.0.py.")
    parser.add_argument("--crop-script", default=DEFAULT_CROP_SCRIPT, help="Path to GOT/demo/run_ocr_2.0_crop.py for crop/multi-page mode.")
    parser.add_argument("--python", default=DEFAULT_PYTHON)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="GOT model directory or model id.")
    parser.add_argument("--type", choices=["ocr", "format"], default=os.environ.get("GOT_OCR_TYPE", "format"))
    parser.add_argument("--box", default="")
    parser.add_argument("--color", default="")
    parser.add_argument("--crop", action="store_true")
    parser.add_argument("--multi-page", action="store_true")
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--timeout", type=float, default=float(os.environ.get("GOT_OCR_TIMEOUT", "0") or 0))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source = args.input.resolve()
    output = args.output.resolve()
    command = build_got_command(args, source)
    env = os.environ.copy()
    configure_cache(env, create_dirs=not args.dry_run)
    if args.dry_run:
        print(subprocess.list2cmdline(command))
        return 0

    validate_runtime(args)
    output.parent.mkdir(parents=True, exist_ok=True)
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
    markdown = stdout_to_markdown(completed.stdout or "", source=source, mode="crop" if args.crop else args.type)
    output.write_text(markdown.rstrip() + "\n", encoding="utf-8", newline="\n")
    if completed.returncode != 0:
        print((completed.stdout or "")[-4000:], file=sys.stderr)
        return completed.returncode
    print(str(output))
    return 0


def build_got_command(args: argparse.Namespace, source: Path) -> list[str]:
    script = args.crop_script if args.crop else args.script
    cmd = [str(args.python), str(script), "--model-name", str(args.model), "--image-file", str(source)]
    if args.crop:
        if args.multi_page:
            cmd.append("--multi-page")
        return cmd
    cmd.extend(["--type", str(args.type)])
    if args.box:
        cmd.extend(["--box", str(args.box)])
    if args.color:
        cmd.extend(["--color", str(args.color)])
    if args.render:
        cmd.append("--render")
    return cmd


def validate_runtime(args: argparse.Namespace) -> None:
    python = Path(str(args.python))
    if not python.exists() and not str(args.python).lower().startswith("python"):
        raise FileNotFoundError(f"GOT-OCR python executable not found: {args.python}")
    script = Path(str(args.crop_script if args.crop else args.script))
    if not script.exists():
        raise FileNotFoundError(f"GOT-OCR demo script not found: {script}")
    if not str(args.model).strip():
        raise FileNotFoundError("GOT-OCR model path/id is empty. Set GOT_OCR_MODEL or pass --model.")


def configure_cache(env: dict[str, str], *, create_dirs: bool) -> None:
    env.setdefault("HF_HOME", str(TOOL_CACHE / "huggingface"))
    env.setdefault("TRANSFORMERS_CACHE", str(TOOL_CACHE / "huggingface" / "transformers"))
    env.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    env.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
    env.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    if create_dirs:
        for key in ("HF_HOME", "TRANSFORMERS_CACHE"):
            Path(env[key]).mkdir(parents=True, exist_ok=True)


def stdout_to_markdown(stdout: str, *, source: Path, mode: str) -> str:
    text = clean_stdout(stdout)
    if not text:
        text = "[No GOT-OCR text captured from stdout.]"
    return "\n".join(
        [
            f"# GOT-OCR {mode} result",
            "",
            f"- Source: `{source}`",
            "",
            text,
            "",
        ]
    )


def clean_stdout(stdout: str) -> str:
    lines = []
    for line in str(stdout or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.search(r"^(loading|using|model|cuda|device|time cost|image:)", stripped, re.I):
            continue
        lines.append(stripped)
    return "\n".join(lines).strip()


if __name__ == "__main__":
    raise SystemExit(main())
