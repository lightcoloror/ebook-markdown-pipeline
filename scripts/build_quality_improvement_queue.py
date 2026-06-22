from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.quality_improvement_queue import (  # noqa: E402
    build_quality_improvement_queue,
    load_benchmark_results,
    write_quality_queue_artifacts,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a review/poor quality improvement queue from benchmark results.")
    parser.add_argument("--benchmark-results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-paths", action="store_true", help="Include full local source/output/report paths in the queue.")
    args = parser.parse_args()

    payload = build_quality_improvement_queue(load_benchmark_results(args.benchmark_results), include_paths=args.include_paths)
    artifacts = write_quality_queue_artifacts(args.output, payload)
    print(json.dumps({"status": "ok", "queue": artifacts["json"], "markdown": artifacts["markdown"], "count": payload["summary"]["count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
