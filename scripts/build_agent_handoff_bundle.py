from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from ebook_converter_mcp import inspect_agent_batch_results, list_agent_batch_results  # noqa: E402
from validate_agent_batch_contract import validate_payload  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a lightweight handoff bundle for an agent batch result.")
    parser.add_argument("--batch-results", type=Path, help="Path to agent-batch-results.json. If omitted, use --root to find the newest result.")
    parser.add_argument("--root", type=Path, help="Root directory to search for agent-batch-results.json when --batch-results is omitted.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-review-items", type=int, default=10)
    args = parser.parse_args()

    batch_results = args.batch_results or newest_batch_results(args.root)
    if not batch_results:
        raise SystemExit("--batch-results or --root with an agent-batch-results.json is required")
    payload = build_bundle(batch_results, max_review_items=args.max_review_items)
    args.output.mkdir(parents=True, exist_ok=True)
    json_path = args.output / "agent-handoff-bundle.json"
    md_path = args.output / "agent-handoff-bundle.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_bundle_markdown(payload), encoding="utf-8")
    print(json.dumps({"ok": True, "json": str(json_path), "markdown": str(md_path)}, ensure_ascii=False, indent=2))
    return 0


def newest_batch_results(root: Path | None) -> Path | None:
    if not root:
        return None
    listed = list_agent_batch_results({"root": str(root), "max_results": 1})
    items = listed.get("items") or []
    if not items:
        return None
    return Path(items[0]["path"])


def build_bundle(batch_results: Path, *, max_review_items: int = 10) -> dict[str, Any]:
    raw = json.loads(batch_results.read_text(encoding="utf-8-sig"))
    validation = validate_payload(raw, batch_results)
    inspection = inspect_agent_batch_results({"path": str(batch_results), "max_review_items": max_review_items})
    bundle = {
        "schema_version": "agent-handoff-bundle-v1",
        "source": str(batch_results),
        "contract_validation": validation,
        "inspection": inspection,
        "attention": inspection.get("attention") or {},
        "summary": inspection.get("summary") or {},
        "selection": inspection.get("selection") or {},
        "artifact_summary": inspection.get("artifact_summary") or {},
        "next_actions": inspection.get("next_actions") or [],
        "artifacts": inspection.get("artifacts") or [],
        "review_items": inspection.get("review_items") or [],
    }
    bundle["handoff_ready"] = bool(validation.get("ok")) and not bool((inspection.get("attention") or {}).get("needs_attention"))
    return bundle


def render_bundle_markdown(payload: dict[str, Any]) -> str:
    validation = payload.get("contract_validation") or {}
    attention = payload.get("attention") or {}
    summary = payload.get("summary") or {}
    selection = payload.get("selection") or {}
    artifact_summary = payload.get("artifact_summary") or {}
    lines = [
        "# Agent Handoff Bundle",
        "",
        f"- Source: `{payload.get('source', '')}`",
        f"- Handoff ready: {payload.get('handoff_ready')}",
        f"- Contract validation: {'ok' if validation.get('ok') else 'failed'}",
        f"- Needs attention: {attention.get('needs_attention', False)}",
        f"- Attention reasons: {', '.join(attention.get('reasons') or []) or '(none)'}",
        f"- Select: {selection.get('select', '')}",
        f"- Selected jobs: {selection.get('selected_count', 0)}/{selection.get('manifest_job_count', 0)}",
        f"- Total: {summary.get('total', 0)}",
        f"- OK: {summary.get('ok', 0)}",
        f"- Review: {summary.get('review', 0)}",
        f"- Hard failed: {summary.get('hard_failed', 0)}",
        f"- Artifact failures: {artifact_summary.get('failed', 0)}",
        "",
        "## Next Actions",
        "",
    ]
    actions = payload.get("next_actions") or []
    if actions:
        for action in actions:
            lines.append(f"- `{action.get('action') or action.get('tool')}`")
    else:
        lines.append("- (none)")
    review_items = payload.get("review_items") or []
    if review_items:
        lines.extend(["", "## Review Items", ""])
        for item in review_items[:10]:
            lines.append(f"- `{item.get('id')}` {item.get('quality_level', '')}: {item.get('suggested_action', '')}")
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
