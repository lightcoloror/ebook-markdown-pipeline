from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


class OCRmyPDFPreprocessError(RuntimeError):
    def __init__(self, message: str, diagnostic: dict[str, Any]):
        super().__init__(message)
        self.diagnostic = diagnostic


def ocrmypdf_available(command: str = "ocrmypdf") -> bool:
    return resolve_ocrmypdf_command(command) is not None


def resolve_ocrmypdf_command(command: str = "ocrmypdf") -> str | None:
    value = str(command or "ocrmypdf").strip().strip('"')
    if not value:
        value = "ocrmypdf"
    path = Path(value)
    if path.exists():
        return str(path)
    return shutil.which(value)


def preprocess_pdf_with_ocrmypdf(
    source: Path,
    output_pdf: Path,
    *,
    command: str = "ocrmypdf",
    language: str = "chi_sim+eng",
    timeout: float = 600.0,
    deskew: bool = True,
    rotate_pages: bool = True,
    force_ocr: bool = False,
    skip_text: bool = True,
) -> dict[str, Any]:
    executable = resolve_ocrmypdf_command(command)
    if not executable:
        raise RuntimeError("OCRmyPDF is not installed or not in PATH. Install OCRmyPDF and Tesseract, or configure the command path.")

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    cmd = [executable]
    if language:
        cmd.extend(["-l", language])
    if deskew:
        cmd.append("--deskew")
    if rotate_pages:
        cmd.append("--rotate-pages")
    if force_ocr:
        cmd.append("--force-ocr")
    elif skip_text:
        cmd.append("--skip-text")
    cmd.extend([str(source), str(output_pdf)])

    started = time.monotonic()
    diagnostic: dict[str, Any] = {
        "tool": "OCRmyPDF",
        "command": cmd,
        "source": str(source),
        "output_pdf": str(output_pdf),
        "language": language,
        "timeout_seconds": timeout,
        "status": "running",
    }
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout if timeout and timeout > 0 else None,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        diagnostic.update(
            {
                "status": "timeout",
                "duration_seconds": round(time.monotonic() - started, 3),
                "stdout_tail": str(exc.stdout or "")[-4000:],
                "stderr_tail": str(exc.stderr or "")[-4000:],
            }
        )
        raise OCRmyPDFPreprocessError(f"OCRmyPDF timed out after {timeout:.0f}s", diagnostic) from exc

    diagnostic.update(
        {
            "status": "ok" if completed.returncode == 0 else "failed",
            "exit_code": completed.returncode,
            "duration_seconds": round(time.monotonic() - started, 3),
            "stdout_tail": (completed.stdout or "")[-4000:],
            "stderr_tail": (completed.stderr or "")[-4000:],
            "output_exists": output_pdf.exists(),
            "output_size_bytes": output_pdf.stat().st_size if output_pdf.exists() else 0,
        }
    )
    if completed.returncode != 0:
        raise OCRmyPDFPreprocessError(str(diagnostic["stderr_tail"] or diagnostic["stdout_tail"] or "OCRmyPDF failed."), diagnostic)
    if not output_pdf.exists():
        diagnostic["status"] = "failed"
        raise OCRmyPDFPreprocessError("OCRmyPDF completed but did not create the searchable PDF.", diagnostic)
    return diagnostic


def main() -> int:
    parser = argparse.ArgumentParser(description="Run OCRmyPDF preprocessing and write a JSON diagnostic.")
    parser.add_argument("source", type=Path)
    parser.add_argument("output_pdf", type=Path)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--command", default="ocrmypdf")
    parser.add_argument("--language", default="chi_sim+eng")
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--no-deskew", action="store_true")
    parser.add_argument("--no-rotate-pages", action="store_true")
    parser.add_argument("--force-ocr", action="store_true")
    parser.add_argument("--no-skip-text", action="store_true")
    args = parser.parse_args()
    try:
        payload = preprocess_pdf_with_ocrmypdf(
            args.source,
            args.output_pdf,
            command=args.command,
            language=args.language,
            timeout=args.timeout,
            deskew=not args.no_deskew,
            rotate_pages=not args.no_rotate_pages,
            force_ocr=args.force_ocr,
            skip_text=not args.no_skip_text,
        )
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps({"ok": True, "result": payload}, ensure_ascii=False), encoding="utf-8")
        return 0
    except Exception as exc:  # noqa: BLE001
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps({"ok": False, "error": str(exc), "error_type": type(exc).__name__}, ensure_ascii=False),
            encoding="utf-8",
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
