from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.document_intelligence_blocks import build_document_intelligence_blocks, write_document_intelligence_blocks_artifacts  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize existing layout/table/formula/OCR sidecars into document-intelligence block evidence.")
    parser.add_argument("--source", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build_document_intelligence_blocks(args.source)
    artifacts = write_document_intelligence_blocks_artifacts(args.output, payload)
    print(json.dumps({"status": "ok", "json": artifacts["json"], "markdown": artifacts["markdown"], "summary": payload["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
