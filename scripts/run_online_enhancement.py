from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from ebook_converter_mcp import run_online_enhancement  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run explicit fake or OpenAI-compatible online enhancement.")
    parser.add_argument("task", choices=["ocr_layout", "vlm_layout", "text_structure", "table_repair", "embedding"])
    parser.add_argument("--input-text", default="")
    parser.add_argument("--input-texts", nargs="*", default=None)
    parser.add_argument("--input-path", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--mime-type", default="image/png")
    parser.add_argument("--prompt", default="")
    parser.add_argument("--context-json", default="")
    parser.add_argument("--model-mode", choices=["local", "online", "hybrid", "auto"], default="local")
    parser.add_argument("--provider-mode", choices=["fake", "openai_compatible"], default="fake")
    parser.add_argument("--provider", default="")
    parser.add_argument("--config", default="")
    parser.add_argument("--allow-remote", action="store_true")
    args = parser.parse_args()

    context = parse_context(args.context_json)
    payload = {
        "task": args.task,
        "input_text": args.input_text,
        "input_texts": args.input_texts,
        "input_path": str(args.input_path) if args.input_path else "",
        "output": str(args.output) if args.output else "",
        "mime_type": args.mime_type,
        "prompt": args.prompt,
        "context": context,
        "model_mode": args.model_mode,
        "provider_mode": args.provider_mode,
        "provider": args.provider,
        "config": args.config,
        "allow_remote": args.allow_remote,
    }
    result = run_online_enhancement(payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("error") else 0


def parse_context(value: str) -> dict:
    if not value:
        return {}
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise SystemExit("--context-json must be a JSON object")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
