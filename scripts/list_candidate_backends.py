from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

from ebook_markdown_pipeline.ebook_converter_mcp import list_candidate_backends_tool  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="List candidate-only backend wrappers without executing them.")
    parser.add_argument("--backend", default="", help="Filter by backend key/display/health alias, e.g. dots_mocr.")
    parser.add_argument("--sample-class", default="", help="Filter by benchmark sample class, e.g. scanned_pdf.")
    parser.add_argument("--capability", default="", help="Filter by capability name, e.g. layout_detector_baseline.")
    parser.add_argument("--artifact-type", default="", help="Filter by supported artifact type, e.g. layout_candidates_json.")
    parser.add_argument("--max-results", type=int, default=50)
    parser.add_argument("--include-registry", action="store_true")
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    args = parser.parse_args()

    payload = list_candidate_backends_tool(
        {
            "backend": args.backend,
            "sample_class": args.sample_class,
            "capability": args.capability,
            "artifact_type": args.artifact_type,
            "max_results": args.max_results,
            "include_registry": args.include_registry,
        }
    )
    if args.format == "markdown":
        print(render_markdown(payload))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Candidate Backends",
        "",
        f"- Schema: `{payload.get('schema_version')}`",
        f"- Execution policy: `{payload.get('execution_policy')}`",
        f"- Count: {payload.get('count')} / {payload.get('total_registered')}",
        f"- Remote calls enabled: `{str(payload.get('remote_call_enabled')).lower()}`",
        f"- Model install enabled: `{str(payload.get('model_install_enabled')).lower()}`",
        f"- Service start enabled: `{str(payload.get('service_start_enabled')).lower()}`",
        "",
    ]
    filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else {}
    if filters:
        lines.extend(["## Filters", ""])
        for key, value in filters.items():
            lines.append(f"- `{key}`: `{value}`")
        lines.append("")
    lines.extend(["## Backends", "", "| Backend | Role | Missing states | Artifacts |", "| --- | --- | --- | --- |"])
    for item in payload.get("backends") or []:
        readiness = item.get("readiness_contract") if isinstance(item, dict) else {}
        missing = ", ".join(str(value) for value in (readiness or {}).get("missing_states") or [])
        artifacts = ", ".join(str(value) for value in item.get("artifact_contract") or [])
        lines.append(
            f"| {escape_table(item.get('display_name'))} | {escape_table(item.get('role'))} | {escape_table(missing)} | {escape_table(artifacts)} |"
        )
    next_actions = [item for item in payload.get("next_actions") or [] if isinstance(item, dict)]
    if next_actions:
        lines.extend(["", "## Next Actions", ""])
        for action in next_actions:
            lines.append(f"- `{action.get('action')}` via `{action.get('tool')}`: {action.get('why', '')}")
    return "\n".join(lines).rstrip() + "\n"


def escape_table(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").replace("\r", " ")


if __name__ == "__main__":
    raise SystemExit(main())