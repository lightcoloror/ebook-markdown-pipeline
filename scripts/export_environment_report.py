from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline import (  # noqa: E402
    default_options,
    dependency_health_report,
    environment_capability_summary,
    normalize_command_options,
)
from ebook_markdown_pipeline.batch_convert_books import collect_sources  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Export reproducible environment diagnostics for ebook-markdown-pipeline.")
    parser.add_argument("--input", type=Path, default=None, help="Optional input path used to scope required dependencies.")
    parser.add_argument("--output", type=Path, required=True, help="Directory where environment-report.json/md will be written.")
    parser.add_argument("--recursive", action="store_true", help="Scan input recursively when --input is a directory.")
    parser.add_argument("--include-hidden", action="store_true", help="Include hidden files while scanning input.")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    payload = build_environment_report(args.input, recursive=args.recursive, include_hidden=args.include_hidden)
    json_path = args.output / "environment-report.json"
    md_path = args.output / "environment-report.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_environment_report_markdown(payload, json_path), encoding="utf-8")
    print(str(md_path))
    return 0


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
        "## Capability Matrix",
        "",
        "| Status | Capability | Detail | Suggested action |",
        "| --- | --- | --- | --- |",
    ]
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


def format_platform(value: dict[str, Any]) -> str:
    return " ".join(str(value.get(key) or "").strip() for key in ("system", "release", "version", "machine")).strip()


def shorten(value: str, limit: int = 180) -> str:
    value = " ".join(str(value).split())
    return value if len(value) <= limit else value[: limit - 3] + "..."


def escape_md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())
