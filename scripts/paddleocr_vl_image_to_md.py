from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PYTHON = Path(r"C:\Users\lightcolor\.conda\envs\pytorch-cuda121\python.exe")
DEFAULT_PADDLEOCR = Path(r"C:\Users\lightcolor\.conda\envs\pytorch-cuda121\Scripts\paddleocr.exe")
TOOL_CACHE = Path(r"D:\used-by-codex\tools")


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
        str(DEFAULT_PADDLEOCR),
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
    if not DEFAULT_PADDLEOCR.exists():
        raise FileNotFoundError(f"paddleocr executable not found: {DEFAULT_PADDLEOCR}")
    completed = subprocess.run(
        command,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=args.timeout if args.timeout > 0 else None,
        check=False,
    )
    candidate = pick_text_artifact(work_dir)
    if candidate:
        shutil.copyfile(candidate, output)
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


if __name__ == "__main__":
    raise SystemExit(main())
