from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT.parent))

from ebook_markdown_pipeline.adaptive_probe import build_adaptive_pdf_probe_plan, execute_adaptive_pdf_probe_plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan or run representative-page adaptive PDF pipeline comparison.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--routing-profile", choices=["fast", "balanced", "best_quality"], default="best_quality")
    parser.add_argument("--pipeline-timeout", type=float, default=120)
    parser.add_argument("--max-pipelines", type=int, default=4)
    parser.add_argument("--pipelines", nargs="+")
    parser.add_argument("--execute", action="store_true", help="Run local candidates. Without this flag only the plan is printed.")
    args = parser.parse_args()

    plan = build_adaptive_pdf_probe_plan(
        args.input,
        args.output,
        routing_profile=args.routing_profile,
        pipeline_timeout=args.pipeline_timeout,
        max_pipelines=args.max_pipelines,
        pipelines=args.pipelines,
    )
    payload = execute_adaptive_pdf_probe_plan(plan) if args.execute and plan.get("status") == "ready" else plan
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if payload.get("status") in {"ready", "ok"}:
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
