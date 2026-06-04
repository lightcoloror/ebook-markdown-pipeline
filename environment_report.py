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
    lock_json_path = output_dir / "environment-lock.json"
    requirements_lock_path = output_dir / "requirements.lock.txt"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_environment_report_markdown(payload, json_path), encoding="utf-8")
    lock_payload = build_environment_lock(payload)
    lock_json_path.write_text(json.dumps(lock_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    requirements_lock_path.write_text(render_requirements_lock(lock_payload), encoding="utf-8")
    payload["json_report"] = str(json_path)
    payload["markdown_report"] = str(md_path)
    payload["lock_report"] = str(lock_json_path)
    payload["requirements_lock"] = str(requirements_lock_path)
    return payload


def compare_environment_lock(lock_path: Path, output_dir: Path | None = None) -> dict[str, Any]:
    baseline = json.loads(lock_path.read_text(encoding="utf-8"))
    current_report = build_environment_report(None, recursive=False, include_hidden=False)
    current = build_environment_lock(current_report)
    payload = build_lock_comparison(baseline, current, baseline_path=lock_path)
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / "environment-lock-compare.json"
        md_path = output_dir / "environment-lock-compare.md"
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(render_lock_comparison_markdown(payload, json_path), encoding="utf-8")
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


def build_lock_comparison(baseline: dict[str, Any], current: dict[str, Any], *, baseline_path: Path) -> dict[str, Any]:
    differences: list[dict[str, Any]] = []
    differences.extend(compare_named_records("python_package", baseline.get("python_packages") or [], current.get("python_packages") or [], keys=("version", "status", "import_status")))
    differences.extend(compare_named_records("command", baseline.get("commands") or [], current.get("commands") or [], keys=("path", "version", "status")))
    differences.extend(compare_mapping("torch", baseline.get("torch") or {}, current.get("torch") or {}, keys=("version", "cuda_available", "cuda_version", "device_count", "device_name", "status")))
    differences.extend(compare_named_records("capability", baseline.get("capabilities") or [], current.get("capabilities") or [], keys=("status", "detail", "action")))
    severity = comparison_severity(differences)
    return {
        "schema_version": "environment-lock-compare-v1",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "baseline_path": str(baseline_path),
        "baseline_generated_at": baseline.get("generated_at"),
        "current_generated_at": current.get("generated_at"),
        "severity": severity,
        "difference_count": len(differences),
        "differences": differences,
    }


def compare_named_records(kind: str, baseline: list[dict[str, Any]], current: list[dict[str, Any]], *, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    by_name_base = {str(item.get("name") or ""): item for item in baseline if item.get("name")}
    by_name_current = {str(item.get("name") or ""): item for item in current if item.get("name")}
    differences: list[dict[str, Any]] = []
    for name in sorted(set(by_name_base) | set(by_name_current)):
        before = by_name_base.get(name)
        after = by_name_current.get(name)
        if before is None:
            differences.append({"kind": kind, "name": name, "field": "record", "before": None, "after": summarize_record(after), "severity": "warning"})
            continue
        if after is None:
            differences.append({"kind": kind, "name": name, "field": "record", "before": summarize_record(before), "after": None, "severity": "error"})
            continue
        for key in keys:
            before_value = before.get(key)
            after_value = after.get(key)
            if normalize_compare_value(before_value) == normalize_compare_value(after_value):
                continue
            differences.append(
                {
                    "kind": kind,
                    "name": name,
                    "field": key,
                    "before": before_value,
                    "after": after_value,
                    "severity": field_difference_severity(key, before_value, after_value),
                }
            )
    return differences


def compare_mapping(kind: str, baseline: dict[str, Any], current: dict[str, Any], *, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    differences = []
    for key in keys:
        before_value = baseline.get(key)
        after_value = current.get(key)
        if normalize_compare_value(before_value) == normalize_compare_value(after_value):
            continue
        differences.append(
            {
                "kind": kind,
                "name": kind,
                "field": key,
                "before": before_value,
                "after": after_value,
                "severity": field_difference_severity(key, before_value, after_value),
            }
        )
    return differences


def normalize_compare_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value or "").strip()


def summarize_record(record: dict[str, Any] | None) -> dict[str, Any]:
    if not record:
        return {}
    return {key: record.get(key) for key in ("name", "version", "status", "import_status", "path") if key in record}


def field_difference_severity(field: str, before: Any, after: Any) -> str:
    before_text = normalize_compare_value(before).lower()
    after_text = normalize_compare_value(after).lower()
    if field in {"status", "import_status"}:
        if "ok" in before_text and "ok" not in after_text:
            return "error"
        if "ok" not in before_text and "ok" in after_text:
            return "info"
        return "warning"
    if field in {"cuda_available", "device_count"}:
        if before_text in {"true", "1"} and after_text in {"false", "0", ""}:
            return "error"
        return "warning"
    if field in {"version", "cuda_version", "device_name", "path"}:
        return "warning"
    return "info"


def comparison_severity(differences: list[dict[str, Any]]) -> str:
    severities = {item.get("severity") for item in differences}
    if "error" in severities:
        return "error"
    if "warning" in severities:
        return "warning"
    if "info" in severities:
        return "info"
    return "ok"


def render_lock_comparison_markdown(payload: dict[str, Any], json_path: Path) -> str:
    lines = [
        "# Environment Lock Comparison",
        "",
        f"- Generated: {payload.get('generated_at')}",
        f"- Baseline: `{payload.get('baseline_path')}`",
        f"- Baseline generated: {payload.get('baseline_generated_at') or 'unknown'}",
        f"- Severity: {payload.get('severity')}",
        f"- Differences: {payload.get('difference_count')}",
        f"- JSON: `{json_path}`",
        "",
        "| Severity | Kind | Name | Field | Before | After |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    differences = payload.get("differences") or []
    if not differences:
        lines.append("| ok | - | - | - | No differences | - |")
    for item in differences:
        lines.append(
            f"| {escape_md(str(item.get('severity') or ''))} | "
            f"{escape_md(str(item.get('kind') or ''))} | "
            f"{escape_md(str(item.get('name') or ''))} | "
            f"{escape_md(str(item.get('field') or ''))} | "
            f"{escape_md(shorten(str(item.get('before') or ''), 120))} | "
            f"{escape_md(shorten(str(item.get('after') or ''), 120))} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def build_environment_lock(payload: dict[str, Any]) -> dict[str, Any]:
    snapshot = payload.get("version_snapshot") or {}
    packages = [
        {
            "name": item.get("name"),
            "module": item.get("module"),
            "version": item.get("version"),
            "status": item.get("status"),
            "import_status": item.get("import_status"),
        }
        for item in snapshot.get("python_packages") or []
    ]
    commands = [
        {
            "name": item.get("name"),
            "path": item.get("path"),
            "version": item.get("version"),
            "status": item.get("status"),
        }
        for item in snapshot.get("commands") or []
    ]
    return {
        "schema_version": "environment-lock-v1",
        "generated_at": payload.get("generated_at"),
        "project_dir": payload.get("project_dir"),
        "python_executable": (payload.get("python") or {}).get("executable"),
        "python_version": (payload.get("python") or {}).get("version"),
        "platform": payload.get("platform") or {},
        "python_packages": packages,
        "commands": commands,
        "torch": snapshot.get("torch") or {},
        "capabilities": payload.get("capabilities") or [],
    }


def render_requirements_lock(lock_payload: dict[str, Any]) -> str:
    lines = [
        "# Generated by ebook_markdown_pipeline environment report.",
        "# This is a diagnostic lock snapshot, not a universal install recipe.",
        f"# Generated: {lock_payload.get('generated_at')}",
        f"# Python: {shorten(str(lock_payload.get('python_version') or ''), 160)}",
        "",
    ]
    for item in lock_payload.get("python_packages") or []:
        name = str(item.get("name") or "").strip()
        version = str(item.get("version") or "").strip()
        status = str(item.get("status") or "")
        import_status = str(item.get("import_status") or "")
        if status == "ok" and version:
            lines.append(f"{name}=={version}")
        else:
            lines.append(f"# {name or 'unknown'} unavailable; status={status}; import={import_status}")
    lines.extend(["", "# External commands"])
    for item in lock_payload.get("commands") or []:
        lines.append(
            f"# {item.get('name')}: path={item.get('path') or ''}; "
            f"status={item.get('status') or ''}; version={item.get('version') or ''}"
        )
    torch_info = lock_payload.get("torch") or {}
    lines.extend(
        [
            "",
            "# Torch/CUDA",
            f"# torch={torch_info.get('version') or ''}; cuda_available={torch_info.get('cuda_available')}; "
            f"cuda={torch_info.get('cuda_version') or ''}; gpu={torch_info.get('device_name') or ''}",
        ]
    )
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
