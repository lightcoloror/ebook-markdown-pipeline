from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from external_wrapper_utils import add_common_arguments, artifact, ensure_output_dir, main_entry, make_result, page_metrics, parse_pages, write_json, write_placeholder_png, write_result, write_text


BACKEND = "gmft_table"


def health(args: argparse.Namespace) -> dict[str, object]:
    cache = Path(args.model_cache).expanduser() if args.model_cache else None
    return {
        "status": "needs_model",
        "checks": [
            {"name": "gmft_import", "checked": False, "detail": "Plan/fake worker never imports gmft or torch."},
            {"name": "model_cache", "path": str(cache) if cache else "", "exists": bool(cache and cache.exists())},
            {"name": "text_layer", "checked": False, "detail": "Execute requires an explicit pdfplumber text-layer preflight."},
        ],
    }


def fake_artifacts(output_dir: Path, pages: list[int] | str | None) -> list[dict[str, object]]:
    page = pages[0] if isinstance(pages, list) and pages else 1
    markdown = output_dir / "tables.md"
    html = output_dir / "tables.html"
    cells = output_dir / "table-cells.json"
    overlay = output_dir / f"page-{page:03d}-table.png"
    candidates = output_dir / "table-candidates.json"
    write_text(markdown, "| Header A | Header B |\n| --- | --- |\n| fake | gmft |\n")
    write_text(html, "<table><thead><tr><th>Header A</th><th>Header B</th></tr></thead><tbody><tr><td>fake</td><td>gmft</td></tr></tbody></table>\n")
    write_json(cells, {"schema_version": "table-cells-fake-v1", "backend": BACKEND, "pages": [{"page": page, "tables": []}]})
    write_placeholder_png(overlay)
    write_json(
        candidates,
        {
            "schema_version": "table-candidates-v1",
            "backend": BACKEND,
            "mode": "fake",
            "status": "review",
            "pages": [{"page": page, "tables": [{"table_number": 1, "markdown": str(markdown), "html": str(html), "cells_json": str(cells), "overlay_image": str(overlay)}]}],
            "artifacts": [{"type": "markdown", "path": str(markdown)}, {"type": "html", "path": str(html)}, {"type": "cells_json", "path": str(cells)}, {"type": "overlay_image", "path": str(overlay)}],
            "warnings": ["Fake output is contract evidence only; it is not a gmft extraction result."],
        },
    )
    return [
        artifact(markdown, "table_markdown", "gmft fake Markdown table", "text/markdown"),
        artifact(html, "table_html", "gmft fake HTML table", "text/html"),
        artifact(cells, "table_cells_json", "gmft fake cells", "application/json"),
        artifact(overlay, "table_overlay_image", "gmft fake overlay", "image/png"),
        artifact(candidates, "table_candidates_json", "gmft normalized candidates", "application/json"),
    ]


def run() -> dict[str, object]:
    parser = argparse.ArgumentParser(description="Plan/fake-only gmft text-layer table baseline.")
    add_common_arguments(parser)
    parser.add_argument("--pages", default="1")
    parser.add_argument("--model-cache", default="")
    args = parser.parse_args()
    output_dir = ensure_output_dir(Path(args.output).expanduser())
    pages = parse_pages(args.pages)
    artifacts: list[dict[str, object]] = []
    warnings = ["No model download, import, or table extraction is performed by this scaffold."]
    if args.mode == "fake":
        artifacts = fake_artifacts(ensure_output_dir(output_dir / "tool-output"), pages)
        status = "ok"
    elif args.mode == "execute":
        status = "skipped"
        warnings.append("Execute is intentionally refused until a human prepares gmft, weights, and text-layer preflight outside this project.")
    else:
        status = "planned"
    payload = make_result(
        backend=BACKEND, mode=args.mode, status=status, input_path=Path(args.input).expanduser(), output_dir=output_dir,
        command=["gmft", "<manual-runtime>", "--input", str(Path(args.input)), "--pages", args.pages], artifacts=artifacts,
        metrics={"artifact_count": len(artifacts), **page_metrics(pages), "model_downloads": 0, "service_starts": 0}, warnings=warnings,
        next_actions=[{"action": "verify_text_layer", "detail": "Use pdfplumber preflight before any approved execute experiment."}, {"action": "compare_tables", "detail": "Compare deterministic HTML, Markdown, cells, and overlay evidence with existing table diagnostics."}], health=health(args),
    )
    write_result(output_dir, payload)
    return payload


if __name__ == "__main__":
    main_entry(run)