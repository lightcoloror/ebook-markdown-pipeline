from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from ebook_converter_mcp import (  # noqa: E402
    build_agent_handoff_bundle_payload,
    newest_agent_batch_results,
    render_agent_handoff_bundle_markdown,
)


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
    return newest_agent_batch_results(str(root) if root else None)


def build_bundle(batch_results: Path, *, max_review_items: int = 10) -> dict[str, object]:
    return build_agent_handoff_bundle_payload(batch_results, max_review_items=max_review_items)


def render_bundle_markdown(payload: dict[str, object]) -> str:
    return render_agent_handoff_bundle_markdown(payload)


if __name__ == "__main__":
    raise SystemExit(main())
