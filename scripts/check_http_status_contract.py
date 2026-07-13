from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))
from ebook_markdown_pipeline.http_status_contract import build_http_status_contract, explain_http_status

def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate an offline ebook HTTP status fixture.")
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--case-id")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.fixture.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if cases is not None:
        selected = next((item for item in cases if item.get("id") == args.case_id), None)
        if selected is None:
            raise SystemExit("--case-id must select a fixture case")
        observation = selected["observation"]
    else:
        observation = payload
    result = build_http_status_contract(observation)
    result["explanation"] = explain_http_status(result)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
