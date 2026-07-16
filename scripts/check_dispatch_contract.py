from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.batch_convert_books import build_health_status, default_options, dependency_health_report  # noqa: E402
from ebook_markdown_pipeline.candidate_backend_registry import candidate_backend_registry_payload  # noqa: E402
from ebook_markdown_pipeline.dispatch_contract_runtime import build_dispatch_contract  # noqa: E402
from ebook_markdown_pipeline.mineru_api_config import load_mineru_api_config  # noqa: E402
from ebook_markdown_pipeline.service_readiness import service_readiness_payload  # noqa: E402
from ebook_markdown_pipeline.scripts.mineru_api_service import status_payload as mineru_status_payload  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Print read-only service, module, route, and fallback discovery JSON.")
    parser.add_argument("--require-http", action="store_true", help="Report needs_manual_start when configured HTTP is absent.")
    parser.add_argument("--no-listener-check", action="store_true", help="Skip the configured HTTP TCP probe.")
    parser.add_argument("--skip-health", action="store_true", help="Skip dependency health collection.")
    parser.add_argument("--skip-mineru-status", action="store_true", help="Skip the fixed MinerU API health probe.")
    args = parser.parse_args()

    service = service_readiness_payload(require_http=args.require_http, check_listener=not args.no_listener_check)
    health: dict[str, object] = {}
    if not args.skip_health:
        health = build_health_status(dependency_health_report([], default_options(), fast=True))
    mineru_service: dict[str, object] = {"status": "not_checked"}
    if not args.skip_mineru_status:
        mineru_service = mineru_status_payload(load_mineru_api_config())
    payload = build_dispatch_contract(
        service=service,
        health=health,
        mineru_service=mineru_service,
        candidate_registry=candidate_backend_registry_payload(),
        require_http=args.require_http,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
