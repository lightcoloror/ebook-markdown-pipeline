from __future__ import annotations

import json
import platform
import subprocess
import sys
import time
import importlib
from importlib import metadata
from pathlib import Path
from typing import Any

from . import default_options, dependency_health_report, environment_capability_summary, normalize_command_options
from .batch_convert_books import collect_sources, suggested_command_value


PROJECT_DIR = Path(__file__).resolve().parent


def export_environment_report(input_path: Path | None, output_dir: Path, *, recursive: bool, include_hidden: bool) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = build_environment_report(input_path, recursive=recursive, include_hidden=include_hidden)
    json_path = output_dir / "environment-report.json"
    md_path = output_dir / "environment-report.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_environment_report_markdown(payload, json_path), encoding="utf-8")
    payload["json_report"] = str(json_path)
    payload["markdown_report"] = str(md_path)
    return payload


def build_environment_report(input_path: Path | None, *, recursive: bool, include_hidden: bool) -> dict[str, Any]:
    options = normalize_command_options(default_options(recursive=recursive, include_hidden=include_hidden))
    sources = []
    if input_path:
        try:
            sources = collect_sources(input_path, recursive=recursive, include_hidden=include_hidden)
        except Exception as exc:  # noqa: BLE001
            sources = []
            input_error = str(exc)
        else:
            input_error = ""
    else:
        input_error = ""
    scoped_checks = dependency_health_report(sources, options)
    checks = dependency_health_report([], options)
    capabilities = environment_capability_summary(checks)
    return {
        "schema_version": "environment-report-v1",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "project_dir": str(PROJECT_DIR),
        "input": str(input_path) if input_path else "",
        "input_error": input_error,
        "source_count": len(sources),
        "python": {
            "executable": sys.executable,
            "version": sys.version,
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "version_snapshot": build_version_snapshot(),
        "checks": checks,
        "scoped_checks": scoped_checks,
        "capabilities": capabilities,
        "ready_capabilities": [item["name"] for item in capabilities if item.get("status") == "ok"],
        "degraded_capabilities": [item["name"] for item in capabilities if item.get("status") == "degraded"],
        "missing_capabilities": [item["name"] for item in capabilities if item.get("status") == "missing"],
    }


def render_environment_report_markdown(payload: dict[str, Any], json_path: Path) -> str:
    lines = [
        "# Environment Report",
        "",
        f"- Generated: {payload.get('generated_at')}",
        f"- Project: `{payload.get('project_dir')}`",
        f"- Input: `{payload.get('input') or '(not scoped)'}`",
        f"- Source count: {payload.get('source_count')}",
        f"- JSON: `{json_path}`",
        "",
        "## Runtime",
        "",
        f"- Python: `{(payload.get('python') or {}).get('executable')}`",
        f"- Python version: `{shorten((payload.get('python') or {}).get('version', ''))}`",
        f"- Platform: `{format_platform(payload.get('platform') or {})}`",
        "",
        "## Version Snapshot",
        "",
        "### Python Packages",
        "",
        "| Package | Module | Version | Status | Import |",
        "| --- | --- | --- | --- | --- |",
    ]
    version_snapshot = payload.get("version_snapshot") or {}
    for item in version_snapshot.get("python_packages") or []:
        lines.append(
            f"| {escape_md(str(item.get('name') or ''))} | "
            f"{escape_md(str(item.get('module') or ''))} | "
            f"{escape_md(str(item.get('version') or ''))} | "
            f"{escape_md(str(item.get('status') or ''))} | "
            f"{escape_md(str(item.get('import_status') or ''))} |"
        )
    lines.extend(
        [
            "",
            "### External Commands",
            "",
            "| Command | Path | Version | Status |",
            "| --- | --- | --- | --- |",
        ]
    )
    for item in version_snapshot.get("commands") or []:
        lines.append(
            f"| {escape_md(str(item.get('name') or ''))} | "
            f"{escape_md(str(item.get('path') or ''))} | "
            f"{escape_md(str(item.get('version') or ''))} | "
            f"{escape_md(str(item.get('status') or ''))} |"
        )
    torch_info = version_snapshot.get("torch") or {}
    lines.extend(
        [
            "",
            "### Torch / CUDA",
            "",
            f"- Torch: `{torch_info.get('version') or 'not importable'}`",
            f"- CUDA available: `{torch_info.get('cuda_available')}`",
            f"- CUDA version: `{torch_info.get('cuda_version') or ''}`",
            f"- GPU: `{torch_info.get('device_name') or ''}`",
            "",
        ]
    )
    lines.extend(
        [
        "## Capability Matrix",
        "",
        "| Status | Capability | Detail | Suggested action |",
        "| --- | --- | --- | --- |",
        ]
    )
    for item in payload.get("capabilities") or []:
        lines.append(
            f"| {escape_md(str(item.get('status') or ''))} | "
            f"{escape_md(str(item.get('name') or ''))} | "
            f"{escape_md(str(item.get('detail') or ''))} | "
            f"{escape_md(str(item.get('action') or ''))} |"
        )
    lines.extend(["", "## Raw Checks", "", "| Status | Name | Kind | Detail |", "| --- | --- | --- | --- |"])
    for item in payload.get("checks") or []:
        lines.append(
            f"| {escape_md(str(item.get('status') or ''))} | "
            f"{escape_md(str(item.get('name') or ''))} | "
            f"{escape_md(str(item.get('kind') or ''))} | "
            f"{escape_md(str(item.get('detail') or ''))} |"
        )
    if payload.get("input_error"):
        lines.extend(["", "## Input Error", "", str(payload["input_error"])])
    return "\n".join(lines).rstrip() + "\n"


def build_version_snapshot() -> dict[str, Any]:
    return {
        "python_packages": package_versions(
            {
                "PyMuPDF": "fitz",
                "pymupdf4llm": "pymupdf4llm",
                "tkinterdnd2": "tkinterdnd2",
                "docling": "docling",
                "torch": "torch",
                "marker-pdf": "marker",
                "magic-pdf": "magic_pdf",
            }
        ),
        "commands": command_versions(
            {
                "pandoc": ["--version"],
                "ebook-convert": ["--version"],
                "mineru": ["--version"],
                "marker_single": ["--help"],
                "tesseract": ["--version"],
            }
        ),
        "torch": torch_snapshot(),
    }


def package_versions(names: dict[str, str]) -> list[dict[str, str]]:
    records = []
    for name, module_name in names.items():
        record = {"name": name, "module": module_name, "version": "", "status": "missing", "import_status": "not_checked"}
        try:
            record["version"] = metadata.version(name)
        except metadata.PackageNotFoundError:
            record["status"] = "missing"
        except Exception as exc:  # noqa: BLE001
            record["status"] = f"error: {exc}"
        else:
            record["status"] = "ok"
        if record["status"] != "missing":
            try:
                importlib.import_module(module_name)
            except Exception as exc:  # noqa: BLE001
                record["import_status"] = f"error: {shorten(str(exc), 160)}"
            else:
                record["import_status"] = "ok"
        records.append(record)
    return records


def command_versions(commands: dict[str, list[str]]) -> list[dict[str, str]]:
    records = []
    for name, version_args in commands.items():
        path = suggested_command_value(name)
        if not path:
            records.append({"name": name, "path": "", "version": "", "status": "missing"})
            continue
        try:
            completed = subprocess.run(
                [path, *version_args],
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=8,
                check=False,
            )
        except Exception as exc:  # noqa: BLE001
            records.append({"name": name, "path": path, "version": "", "status": f"error: {shorten(str(exc), 120)}"})
            continue
        output = shorten((completed.stdout or "").strip(), 220)
        status = "ok" if completed.returncode == 0 else f"exit {completed.returncode}"
        records.append({"name": name, "path": path, "version": first_version_line(output), "status": status})
    return records


def torch_snapshot() -> dict[str, Any]:
    try:
        import torch
    except Exception as exc:  # noqa: BLE001
        return {"version": "", "cuda_available": False, "cuda_version": "", "device_name": "", "status": f"error: {exc}"}
    cuda_available = bool(torch.cuda.is_available())
    device_name = ""
    if cuda_available:
        try:
            device_name = str(torch.cuda.get_device_name(0))
        except Exception:
            device_name = ""
    return {
        "version": str(getattr(torch, "__version__", "")),
        "cuda_available": cuda_available,
        "cuda_version": str(getattr(torch.version, "cuda", "") or ""),
        "device_count": int(torch.cuda.device_count()) if hasattr(torch, "cuda") else 0,
        "device_name": device_name,
        "status": "ok" if cuda_available else "cuda_unavailable",
    }


def first_version_line(output: str) -> str:
    for line in output.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def format_platform(value: dict[str, Any]) -> str:
    return " ".join(str(value.get(key) or "").strip() for key in ("system", "release", "version", "machine")).strip()


def shorten(value: str, limit: int = 180) -> str:
    value = " ".join(str(value).split())
    return value if len(value) <= limit else value[: limit - 3] + "..."


def escape_md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
