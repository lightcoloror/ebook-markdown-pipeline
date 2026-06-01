from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_DIR.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_call_helpers import print_json, run_material_flow  # noqa: E402
from ebook_markdown_pipeline.ebook_converter_mcp import call_tool as local_call_tool  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Call process_material directly from Python.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--query", default="")
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()

    material_args: dict[str, Any] = {"input": args.input, "output": args.output, "recursive": True}
    if args.query:
        material_args["query"] = args.query
    print_json(run_material_flow(local_call_tool, material_args, timeout=args.timeout))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
