from __future__ import annotations

import argparse
import importlib.util
import json
import re
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
WINDOWS_ABSOLUTE_PATH = re.compile(r"[A-Za-z]:\\[^\s`)]+")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare public-safe GitHub release notes from CHANGELOG and quality-gate evidence.")
    parser.add_argument("--version", default="v0.2.0-rc1", help="Release version/title prefix.")
    parser.add_argument("--title", default="", help="Full release title. Defaults to '<version> - v0.2 release candidate'.")
    parser.add_argument("--quality-gate", type=Path, help="release-summary.json or a release quality-gate directory. Defaults to latest quality gate.")
    parser.add_argument("--output", type=Path, help="Optional Markdown output path. If omitted, print to stdout.")
    parser.add_argument("--include-local-paths", action="store_true", help="Include absolute local artifact paths. Default redacts them for public release text.")
    args = parser.parse_args()

    notes = render_release_notes(
        version=args.version,
        title=args.title or f"{args.version} - v0.2 release candidate",
        changelog=extract_unreleased_changelog(PROJECT_DIR / "CHANGELOG.md"),
        quality_gate=load_quality_gate(args.quality_gate),
        include_local_paths=bool(args.include_local_paths),
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(notes, encoding="utf-8", newline="\n")
    else:
        print(notes, end="")
    return 0


def extract_unreleased_changelog(path: Path) -> dict[str, list[str]]:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^## Unreleased\s*(.*?)(?=^## |\Z)", text, flags=re.M | re.S)
    if not match:
        return {}
    current = ""
    sections: dict[str, list[str]] = {}
    for line in match.group(1).splitlines():
        heading = re.match(r"^###\s+(.+?)\s*$", line)
        if heading:
            current = heading.group(1).strip()
            sections.setdefault(current, [])
            continue
        if current and line.strip().startswith("- "):
            sections.setdefault(current, []).append(line.strip()[2:].strip())
    return sections


def load_quality_gate(source: Path | None) -> dict[str, Any]:
    if source:
        path = source
        if path.is_dir():
            path = path / "release-summary.json"
        if not path.is_file():
            return {"found": False, "message": f"release summary not found: {source}"}
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        return {"found": True, "source": str(path), "payload": payload, "artifact_status": artifact_status(payload)}
    module = load_latest_quality_gate_module()
    return module.load_latest_release()


def load_latest_quality_gate_module():
    path = PROJECT_DIR / "scripts" / "show_latest_quality_gate.py"
    spec = importlib.util.spec_from_file_location("show_latest_quality_gate", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load show_latest_quality_gate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def artifact_status(payload: dict[str, Any]) -> str:
    output = str(payload.get("output") or "")
    if output and not Path(output).exists():
        return "stale"
    for step in payload.get("steps") or []:
        if isinstance(step, dict) and step.get("report") and not Path(str(step["report"])).exists():
            return "stale"
    return "ok"


def render_release_notes(
    *,
    version: str,
    title: str,
    changelog: dict[str, list[str]],
    quality_gate: dict[str, Any],
    include_local_paths: bool,
) -> str:
    payload = quality_gate.get("payload") or {}
    summary = payload.get("summary") or {}
    regression_tags = payload.get("regression_tags") or []
    lines = [
        f"# {title}",
        "",
        "## Highlights",
        "",
    ]
    for section in ("Added", "Changed", "Safety"):
        items = changelog.get(section) or []
        if items:
            lines.append(f"### {section}")
            lines.append("")
            lines.extend(f"- {item}" for item in items)
            lines.append("")

    lines.extend(
        [
            "## Quick Start",
            "",
            "```powershell",
            "git clone https://github.com/lightcoloror/ebook-markdown-pipeline.git",
            "cd ebook-markdown-pipeline",
            "python -m pip install -r requirements.txt",
            "python book_converter_ui.py",
            "```",
            "",
            "## Quality Gate",
            "",
        ]
    )
    if quality_gate.get("found"):
        lines.extend(
            [
                f"- Status: {summary.get('status', 'unknown')}",
                f"- Failed steps: {', '.join(summary.get('failed_steps') or []) or 'none'}",
                f"- Regression tags: {', '.join(regression_tags) or 'none'}",
                f"- Artifact status: {quality_gate.get('artifact_status', 'unknown')}",
            ]
        )
        if include_local_paths:
            lines.append(f"- Local summary: `{quality_gate.get('source', '')}`")
            lines.append(f"- Local output: `{payload.get('output', '')}`")
        else:
            lines.append("- Local summary/output paths are intentionally omitted from public notes; run `python scripts\\show_latest_quality_gate.py` locally for artifact paths.")
        lines.extend(["", "| Step | Status |", "| --- | --- |"])
        for step in payload.get("steps") or []:
            if isinstance(step, dict):
                lines.append(f"| {step.get('name', '')} | {step.get('status', '')} |")
        lines.append("")
    else:
        lines.extend(["- Status: not attached", f"- Message: {quality_gate.get('message', '')}", ""])

    lines.extend(
        [
            "## Compatibility Notes",
            "",
            "- Minimal install supports common ebook/text workflows and text-layer PDF fallback.",
            "- Heavy OCR/VLM/document backends are optional and should be installed only when needed.",
            "- Online model APIs require explicit provider configuration and `allow_remote=true`; no API key is required for the default local workflow.",
            "- `duration_regression` currently means the optional MarkItDown comparison path was slower; it is a review label, not a failed gate, when the release status is passed.",
            "",
            "## Third-Party Notices",
            "",
            "This repository is an orchestration layer. It does not vendor parser/OCR/model code, model weights, private samples, or API keys. Users must follow each optional backend's license and model terms.",
            "",
        ]
    )
    notes = "\n".join(lines).rstrip() + "\n"
    return notes if include_local_paths else redact_local_paths(notes)


def redact_local_paths(text: str) -> str:
    return WINDOWS_ABSOLUTE_PATH.sub("<local path>", text)


if __name__ == "__main__":
    raise SystemExit(main())
