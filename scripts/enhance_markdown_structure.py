from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from ebook_converter_mcp import enhance_markdown_structure  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely repair an existing Markdown file's heading hierarchy.")
    parser.add_argument("input", type=Path, help="Markdown file to enhance.")
    parser.add_argument("output", type=Path, help="Output directory for versioned Markdown and reports.")
    parser.add_argument("--source-kind", default="markdown")
    parser.add_argument("--model-mode", choices=["local", "online", "hybrid", "auto"], default="local")
    parser.add_argument("--provider-mode", choices=["fake", "openai_compatible"], default="fake")
    parser.add_argument("--provider", default="")
    parser.add_argument("--config", default="")
    parser.add_argument("--allow-remote", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    payload = enhance_markdown_structure(
        {
            "input": str(args.input),
            "output": str(args.output),
            "source_kind": args.source_kind,
            "model_mode": args.model_mode,
            "provider_mode": args.provider_mode,
            "provider": args.provider,
            "config": args.config,
            "allow_remote": args.allow_remote,
            "overwrite": args.overwrite,
        }
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if payload.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
