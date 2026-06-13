from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


OLMOCR_PACKAGE = "olmocr"
DEFAULT_COMMAND = os.environ.get("EBOOK_CONVERTER_OLMOCR_COMMAND", "olmocr")
DEFAULT_MODEL = os.environ.get("EBOOK_CONVERTER_OLMOCR_MODEL", "")


def olmocr_available(command: str | None = None) -> bool:
    command = command or DEFAULT_COMMAND
    args = split_command(command)
    if args:
        executable = args[0]
        if executable in {"python", "python3"} and len(args) >= 3 and args[1] == "-m":
            return importlib.util.find_spec(args[2]) is not None
        if Path(executable).exists() or shutil.which(executable):
            return True
    return importlib.util.find_spec(OLMOCR_PACKAGE) is not None


def olmocr_health(command: str | None = None) -> dict[str, str]:
    command = command or DEFAULT_COMMAND
    if olmocr_available(command):
        return {
            "name": "olmOCR",
            "kind": "vlm",
            "status": "ok",
            "detail": f"command/module available: {command}",
        }
    return {
        "name": "olmOCR",
        "kind": "vlm",
        "status": "missing",
        "detail": f"optional VLM OCR backend not available: {command}",
    }


def convert_with_olmocr(
    source: Path,
    output_path: Path,
    *,
    workspace: Path | None = None,
    command: str | None = None,
    server: str | None = None,
    model: str | None = None,
    api_key_env: str | None = None,
    workers: int | None = None,
    max_concurrent_requests: int | None = None,
    pages_per_group: int | None = None,
    timeout: float | None = None,
    extra_args: list[str] | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    source = source.resolve()
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workspace = (workspace or output_path.parent / ".olmocr" / output_path.stem).resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    cmd = build_olmocr_command(
        source,
        workspace,
        command=command,
        server=server,
        model=model,
        api_key_env=api_key_env,
        workers=workers,
        max_concurrent_requests=max_concurrent_requests,
        pages_per_group=pages_per_group,
        extra_args=extra_args,
    )
    redacted_cmd = redact_command(cmd)
    completed = subprocess.run(
        cmd,
        cwd=str(workspace),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout if timeout and timeout > 0 else None,
        check=False,
    )
    markdown_source = find_olmocr_markdown(workspace, source)
    if completed.returncode != 0:
        raise RuntimeError(f"olmOCR exited with code {completed.returncode}: {completed.stdout[-2000:]}")
    if not markdown_source:
        raise RuntimeError(f"olmOCR did not produce a Markdown file under {workspace / 'markdown'}")
    output_path.write_text(markdown_source.read_text(encoding="utf-8", errors="replace"), encoding="utf-8", newline="\n")
    return {
        "tool": "olmOCR",
        "source": str(source),
        "output": str(output_path),
        "workspace": str(workspace),
        "markdown_source": str(markdown_source),
        "command": redacted_cmd,
        "server": server or "",
        "model": model or "",
        "workers": workers,
        "max_concurrent_requests": max_concurrent_requests,
        "pages_per_group": pages_per_group,
        "stdout_tail": completed.stdout[-4000:],
        "duration_seconds": round(time.monotonic() - started, 3),
    }


def build_olmocr_command(
    source: Path,
    workspace: Path,
    *,
    command: str | None = None,
    server: str | None = None,
    model: str | None = None,
    api_key_env: str | None = None,
    workers: int | None = None,
    max_concurrent_requests: int | None = None,
    pages_per_group: int | None = None,
    extra_args: list[str] | None = None,
) -> list[str]:
    cmd = split_command(command or DEFAULT_COMMAND)
    if not cmd:
        cmd = ["olmocr"]
    cmd.extend([str(workspace), "--markdown", "--pdfs", str(source)])
    if server:
        cmd.extend(["--server", server])
    if model:
        cmd.extend(["--model", model])
    api_key = os.environ.get(api_key_env or "", "").strip() if api_key_env else ""
    if api_key:
        cmd.extend(["--api_key", api_key])
    if workers is not None and workers > 0:
        cmd.extend(["--workers", str(workers)])
    if max_concurrent_requests is not None and max_concurrent_requests > 0:
        cmd.extend(["--max_concurrent_requests", str(max_concurrent_requests)])
    if pages_per_group is not None and pages_per_group > 0:
        cmd.extend(["--pages_per_group", str(pages_per_group)])
    if extra_args:
        cmd.extend(extra_args)
    return cmd


def split_command(command: str) -> list[str]:
    command = str(command or "").strip()
    if not command:
        return []
    return shlex.split(command, posix=os.name != "nt")


def redact_command(cmd: list[str]) -> list[str]:
    redacted: list[str] = []
    skip_next = False
    for item in cmd:
        if skip_next:
            redacted.append("<redacted>")
            skip_next = False
            continue
        redacted.append(item)
        if item in {"--api_key", "--api-key", "--api_key_env"}:
            skip_next = True
    return redacted


def find_olmocr_markdown(workspace: Path, source: Path) -> Path | None:
    markdown_dir = workspace / "markdown"
    if not markdown_dir.exists():
        return None
    exact = markdown_dir / f"{source.stem}.md"
    if exact.exists():
        return exact
    matches = sorted(markdown_dir.glob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Run olmOCR on a PDF/image and write normalized Markdown plus JSON diagnostics.")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--workspace", type=Path, default=None)
    parser.add_argument("--command", default=DEFAULT_COMMAND)
    parser.add_argument("--server", default=os.environ.get("EBOOK_CONVERTER_OLMOCR_SERVER", ""))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-key-env", default=os.environ.get("EBOOK_CONVERTER_OLMOCR_API_KEY_ENV", ""))
    parser.add_argument("--workers", type=int, default=int(os.environ.get("EBOOK_CONVERTER_OLMOCR_WORKERS", "1") or 1))
    parser.add_argument("--max-concurrent-requests", type=int, default=int(os.environ.get("EBOOK_CONVERTER_OLMOCR_MAX_CONCURRENT_REQUESTS", "0") or 0))
    parser.add_argument("--pages-per-group", type=int, default=int(os.environ.get("EBOOK_CONVERTER_OLMOCR_PAGES_PER_GROUP", "0") or 0))
    parser.add_argument("--timeout", type=float, default=float(os.environ.get("EBOOK_CONVERTER_OLMOCR_TIMEOUT", "0") or 0))
    parser.add_argument("--extra-arg", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    if args.dry_run:
        workspace = (args.workspace or args.output.parent / ".olmocr" / args.output.stem).resolve()
        cmd = build_olmocr_command(
            args.source.resolve(),
            workspace,
            command=args.command,
            server=args.server or None,
            model=args.model or None,
            api_key_env=args.api_key_env or None,
            workers=args.workers,
            max_concurrent_requests=args.max_concurrent_requests,
            pages_per_group=args.pages_per_group,
            extra_args=args.extra_arg,
        )
        payload = {
            "ok": True,
            "dry_run": True,
            "source": str(args.source),
            "output": str(args.output),
            "workspace": str(workspace),
            "command": redact_command(cmd),
            "api_key_env": args.api_key_env or "",
        }
        args.output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False), flush=True)
        return 0

    try:
        result = convert_with_olmocr(
            args.source,
            args.output,
            workspace=args.workspace,
            command=args.command,
            server=args.server or None,
            model=args.model or None,
            api_key_env=args.api_key_env or None,
            workers=args.workers,
            max_concurrent_requests=args.max_concurrent_requests,
            pages_per_group=args.pages_per_group,
            timeout=args.timeout,
            extra_args=args.extra_arg,
        )
        payload = {"ok": True, "result": result}
        args.output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(str(args.output), flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001
        payload = {"ok": False, "error": str(exc), "error_type": type(exc).__name__}
        args.output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(str(exc), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
