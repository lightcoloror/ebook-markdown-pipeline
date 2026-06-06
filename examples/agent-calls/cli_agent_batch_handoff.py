from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_DIR.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_call_helpers import print_json  # noqa: E402
from ebook_markdown_pipeline.ebook_converter_mcp import call_tool as local_call_tool  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect or list agent batch handoff results without starting a server.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Summarize one agent-batch-results.json file.")
    inspect_parser.add_argument("path", help="Path to agent-batch-results.json.")
    inspect_parser.add_argument("--max-review-items", type=int, default=10)

    list_parser = subparsers.add_parser("list", help="Find recent agent-batch-results.json files below a root directory.")
    list_parser.add_argument("root", help="Directory to scan.")
    list_parser.add_argument("--max-results", type=int, default=10)
    list_parser.add_argument("--max-depth", type=int, default=3)
    list_parser.add_argument("--max-review-items", type=int, default=3)

    bundle_parser = subparsers.add_parser("bundle", help="Build agent-handoff-bundle.json/md for a batch result.")
    bundle_parser.add_argument("--batch-results", help="Path to agent-batch-results.json. If omitted, use --root.")
    bundle_parser.add_argument("--root", help="Root directory to search for the newest agent-batch-results.json.")
    bundle_parser.add_argument("--output", required=True, help="Directory where agent-handoff-bundle.json/md will be written.")
    bundle_parser.add_argument("--max-review-items", type=int, default=10)

    args = parser.parse_args()
    if args.command == "inspect":
        print_json(
            local_call_tool(
                "inspect_agent_batch_results",
                {"path": args.path, "max_review_items": args.max_review_items},
            )
        )
        return 0
    if args.command == "list":
        print_json(
            local_call_tool(
                "list_agent_batch_results",
                {
                    "root": args.root,
                    "max_results": args.max_results,
                    "max_depth": args.max_depth,
                    "max_review_items": args.max_review_items,
                },
            )
        )
        return 0
    if args.command == "bundle":
        print_json(
            local_call_tool(
                "build_agent_handoff_bundle",
                {
                    "batch_results": args.batch_results,
                    "root": args.root,
                    "output": args.output,
                    "max_review_items": args.max_review_items,
                },
            )
        )
        return 0
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
