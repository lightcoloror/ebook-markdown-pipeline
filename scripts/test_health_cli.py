from __future__ import annotations

import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.batch_convert_books import build_health_status, parse_args  # noqa: E402


def capability(name: str, status: str) -> dict[str, str]:
    return {"name": name, "status": status, "detail": "test", "action": "test"}


def main() -> int:
    args = parse_args(["--health-check"])
    if args.input is not None or args.output is not None or not args.health_check:
        raise AssertionError(f"Health parsing should not require positional paths: {args}")

    core_ok = build_health_status(
        [],
        capabilities=[capability("structured_ebooks", "ok"), capability("pdf_fast_text", "ok")],
    )
    if core_ok.get("status") != "core_ok" or core_ok.get("minimal_ok") is not True:
        raise AssertionError(f"Expected core_ok health state: {core_ok}")

    degraded_optional = build_health_status(
        [],
        capabilities=[
            capability("structured_ebooks", "ok"),
            capability("pdf_fast_text", "ok"),
            capability("optional_layout_backend", "missing"),
        ],
    )
    if degraded_optional.get("status") != "degraded_optional" or degraded_optional.get("minimal_ok") is not True:
        raise AssertionError(f"Expected degraded_optional health state: {degraded_optional}")

    core_missing = build_health_status(
        [],
        capabilities=[capability("structured_ebooks", "missing"), capability("pdf_fast_text", "ok")],
    )
    if core_missing.get("status") != "core_missing" or core_missing.get("minimal_ok") is not False:
        raise AssertionError(f"Expected core_missing health state: {core_missing}")
    if core_missing.get("missing_minimal_capabilities") != ["structured_ebooks"]:
        raise AssertionError(f"Expected missing core capability evidence: {core_missing}")

    print("Health CLI contract test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
