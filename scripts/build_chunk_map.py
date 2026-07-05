from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.chunk_map import build_chunk_map, write_chunk_map_artifacts  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build metadata-only chunk-map artifacts from an existing Markdown output.")
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--structure-json", type=Path)
    parser.add_argument("--max-chunk-chars", type=int, default=1800)
    parser.add_argument("--include-text-preview", action="store_true")
    args = parser.parse_args()

    payload = build_chunk_map(
        args.markdown,
        structure_json=args.structure_json,
        max_chunk_chars=args.max_chunk_chars,
        include_text_preview=args.include_text_preview,
    )
    artifacts = write_chunk_map_artifacts(args.output, payload)
    print(json.dumps({"status": "ok", "json": artifacts["json"], "markdown": artifacts["markdown"], "chunks": payload["summary"]["chunk_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
