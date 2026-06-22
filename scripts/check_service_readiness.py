from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

from ebook_markdown_pipeline.service_readiness import service_readiness_payload  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Check on-demand service readiness without starting the HTTP bridge.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--require-http", action="store_true", help="Report needs_manual_start when HTTP is not listening.")
    args = parser.parse_args()

    payload = service_readiness_payload(require_http=args.require_http)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        http = payload["http"]
        listener = http["listener"]
        print(f"status: {payload['status']}")
        print(f"http: {http['configured_url']}")
        print(f"config: {http['config_path']}")
        print(f"listening: {str(listener['listening']).lower()}")
        print(f"fallback: {payload['fallback']['if_http_unavailable']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

