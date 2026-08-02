from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.online_document_pipeline import (  # noqa: E402
    OnlinePipelineOptions,
    run_online_document_pipeline,
)
from ebook_markdown_pipeline.shared_vkp_gateway import redacted_json  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Plan or execute an online-only material conversion. VKP shared mode reuses "
            "VKP's LiteLLM routes and DPAPI-protected supplier keys."
        )
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--provider-mode", choices=("fake", "vkp_shared"), default="vkp_shared")
    parser.add_argument("--execute", action="store_true", help="Execute instead of writing a no-network plan.")
    parser.add_argument(
        "--confirm-data-export",
        action="store_true",
        help="Confirm that exact source text or rendered pages may be sent to remote providers.",
    )
    parser.add_argument("--max-estimated-cost-usd", type=float, default=0.0)
    parser.add_argument("--start-shared-gateway", action="store_true")
    parser.add_argument("--vkp-root", type=Path)
    parser.add_argument("--resume-manifest", type=Path)
    parser.add_argument("--no-recursive", action="store_true")
    parser.add_argument("--include-hidden", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--no-structure-pass", action="store_true")
    parser.add_argument("--no-embedded-image-ocr", action="store_true")
    parser.add_argument(
        "--vlm-mode",
        choices=("auto", "always", "never"),
        default="auto",
        help="Use VKP shared VLM for selected visual pages, every page, or no page.",
    )
    parser.add_argument("--vlm-max-pages", type=int, default=12)
    parser.add_argument("--vlm-min-ocr-chars", type=int, default=80)
    parser.add_argument("--max-chunk-chars", type=int, default=12000)
    parser.add_argument("--render-dpi", type=int, default=160)
    parser.add_argument("--request-interval-seconds", type=float, default=0.25)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    options = OnlinePipelineOptions(
        provider_mode=args.provider_mode,
        execute=bool(args.execute),
        confirm_data_export=bool(args.confirm_data_export),
        max_estimated_cost_usd=float(args.max_estimated_cost_usd),
        start_shared_gateway=bool(args.start_shared_gateway),
        vkp_root=str(args.vkp_root or ""),
        recursive=not bool(args.no_recursive),
        include_hidden=bool(args.include_hidden),
        overwrite=bool(args.overwrite),
        structure_pass=not bool(args.no_structure_pass),
        embedded_image_ocr=not bool(args.no_embedded_image_ocr),
        vlm_mode=str(args.vlm_mode),
        vlm_max_pages=max(0, int(args.vlm_max_pages)),
        vlm_min_ocr_chars=max(1, int(args.vlm_min_ocr_chars)),
        max_chunk_chars=max(1000, int(args.max_chunk_chars)),
        render_dpi=max(72, int(args.render_dpi)),
        request_interval_seconds=max(0.0, float(args.request_interval_seconds)),
        resume_manifest=str(args.resume_manifest or ""),
    )

    def progress(event: str, source: Path, index: int, total: int, payload: dict) -> None:
        stage = str(payload.get("stage") or payload.get("status") or "")
        print(f"[{index}/{total}] {event}: {source.name} {stage}".rstrip(), file=sys.stderr, flush=True)

    result = run_online_document_pipeline(args.input, args.output, options=options, progress_callback=progress)
    print(redacted_json(result))
    return 1 if result.get("error") or result.get("status") == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
