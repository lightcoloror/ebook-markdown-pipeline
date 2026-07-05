from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.review_lifecycle import build_review_lifecycle, write_review_lifecycle_artifacts  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a metadata-only review lifecycle artifact from an existing queue, batch, handoff, bundle, or scorecard JSON.")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-paths", action="store_true", help="Include local source JSON path in the lifecycle artifact.")
    args = parser.parse_args()

    payload = build_review_lifecycle(args.source, include_paths=args.include_paths)
    artifacts = write_review_lifecycle_artifacts(args.output, payload)
    print(json.dumps({"status": "ok", "json": artifacts["json"], "markdown": artifacts["markdown"], "state": payload["lifecycle_state"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
