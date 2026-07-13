from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))
from ebook_markdown_pipeline.offline_quality_router import evaluate_offline_quality, explain_offline_route

def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only offline quality evaluation and route explanation.")
    parser.add_argument("report", type=Path)
    parser.add_argument("--source-kind", required=True)
    parser.add_argument("--capabilities", type=Path)
    parser.add_argument("--artifact-exists", choices=("auto", "true", "false"), default="auto")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    capabilities = json.loads(args.capabilities.read_text(encoding="utf-8")) if args.capabilities else {}
    override = None if args.artifact_exists == "auto" else args.artifact_exists == "true"
    result = evaluate_offline_quality(report, source_kind=args.source_kind, capabilities=capabilities, artifact_exists=override)
    result["explanation"] = explain_offline_route(result)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
