from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from external_wrapper_utils import (  # noqa: E402
    add_common_arguments,
    artifact,
    command_available,
    ensure_output_dir,
    main_entry,
    make_result,
    page_metrics,
    parse_pages,
    run_command,
    write_json,
    write_placeholder_png,
    write_result,
    write_text,
)


BACKEND = "pdf_table"


def build_command(args: argparse.Namespace, tool_output: Path) -> list[str]:
    command = [
        args.pdftable_exe,
        "--output_dir",
        str(tool_output),
        "--file_path_or_url",
        str(Path(args.input)),
    ]
    if args.pages:
        command.extend(["--pages", args.pages])
    if args.use_modelscope:
        command.append("--use_modelscope")
    return command


def health(args: argparse.Namespace) -> dict[str, object]:
    return {
        "status": "ready" if command_available(args.pdftable_exe) else "needs_env",
        "checks": [
            {"name": "pdftable_exe", "value": args.pdftable_exe, "available": command_available(args.pdftable_exe)},
            {"name": "model_cache", "checked": False, "detail": "Model cache is not inspected in plan mode."},
        ],
    }


def fake_artifacts(output_dir: Path, pages: list[int] | str | None) -> list[dict[str, object]]:
    selected_pages = pages if isinstance(pages, list) and pages else [1]
    table_md = output_dir / "tables.md"
    table_html = output_dir / "tables.html"
    cells_json = output_dir / "table-cells.json"
    overlay = output_dir / "page-001-table.png"
    candidates = output_dir / "table-candidates.json"
    summary = output_dir / "table-worker-summary.json"
    write_text(table_md, "| A | B |\n|---|---|\n| fake | table |\n")
    write_text(table_html, "<table><tr><th>A</th><th>B</th></tr><tr><td>fake</td><td>table</td></tr></table>\n")
    write_json(cells_json, {"schema_version": "table-cells-fake-v1", "pages": [{"page": selected_pages[0], "tables": []}]})
    write_placeholder_png(overlay)
    write_table_candidates(candidates, selected_pages, table_md=table_md, table_html=table_html, cells_json=cells_json, overlay=overlay, status="review")
    write_json(
        summary,
        {
            "schema_version": "table-worker-result-v1",
            "backend": BACKEND,
            "pages": [{"page": selected_pages[0], "table_count": 1, "cell_count": 2, "output_artifacts": []}],
            "table_candidates": str(candidates),
            "warnings": [],
        },
    )
    return [
        artifact(table_md, "table_markdown", "pdf_table Markdown table", "text/markdown"),
        artifact(table_html, "table_html", "pdf_table HTML table", "text/html"),
        artifact(cells_json, "table_cells_json", "pdf_table cell JSON", "application/json"),
        artifact(overlay, "table_overlay_image", "pdf_table table overlay", "image/png"),
        artifact(candidates, "table_candidates_json", "pdf_table normalized table candidates", "application/json"),
        artifact(summary, "table_comparison_summary", "pdf_table summary", "application/json"),
    ]



def write_table_candidates(
    path: Path,
    pages: list[int],
    *,
    table_md: Path | None = None,
    table_html: Path | None = None,
    cells_json: Path | None = None,
    overlay: Path | None = None,
    status: str = "review",
) -> Path:
    page = pages[0] if pages else 1
    table: dict[str, object] = {
        "backend": BACKEND,
        "page": page,
        "table_number": 1,
        "confidence": None,
    }
    if table_md:
        table["markdown"] = str(table_md)
    if table_html:
        table["html"] = str(table_html)
    if cells_json:
        table["cells_json"] = str(cells_json)
    if overlay:
        table["overlay_image"] = str(overlay)
    artifacts = []
    for kind, candidate_path in [("markdown", table_md), ("html", table_html), ("cells_json", cells_json), ("overlay_image", overlay)]:
        if candidate_path:
            artifacts.append({"type": kind, "path": str(candidate_path), "backend": BACKEND, "page": page})
    write_json(
        path,
        {
            "schema_version": "table-candidates-v1",
            "backend": BACKEND,
            "status": status,
            "pages": [{"page": page, "tables": [table]}],
            "artifacts": artifacts,
            "warnings": ["pdf_table candidates are side evidence; compare against pdfplumber/Camelot/Tabula and final Markdown before promotion."],
        },
    )
    return path


def write_execute_table_candidates(output_dir: Path, pages: list[int], *, status: str) -> Path:
    table_md = first_existing(output_dir, ["*.md", "*.markdown"])
    table_html = first_existing(output_dir, ["*.html", "*.htm"])
    cells_json = first_existing(output_dir, ["*.json"])
    overlay = first_existing(output_dir, ["*.png", "*.jpg", "*.jpeg"])
    return write_table_candidates(
        output_dir / "table-candidates.json",
        pages or [1],
        table_md=table_md,
        table_html=table_html,
        cells_json=cells_json,
        overlay=overlay,
        status=status,
    )


def first_existing(root: Path, patterns: list[str]) -> Path | None:
    for pattern in patterns:
        for path in sorted(root.rglob(pattern)):
            if path.name in {"external-wrapper-result.json", "table-candidates.json"}:
                continue
            if path.is_file():
                return path
    return None

def run() -> dict[str, object]:
    parser = argparse.ArgumentParser(description="Plan or run a pdf_table table worker.")
    add_common_arguments(parser)
    parser.add_argument("--pages")
    parser.add_argument("--pdftable-exe", default="pdftable")
    parser.add_argument("--use-modelscope", action="store_true")
    args = parser.parse_args()

    input_path = Path(args.input).expanduser()
    output_dir = ensure_output_dir(Path(args.output).expanduser())
    tool_output = ensure_output_dir(output_dir / "tool-output")
    pages = parse_pages(args.pages)
    command = build_command(args, tool_output)
    health_payload = health(args)
    artifacts: list[dict[str, object]] = []
    warnings: list[str] = []
    if args.mode == "fake":
        artifacts = fake_artifacts(tool_output, pages)
        status = "ok"
    elif args.mode == "execute":
        if not command_available(args.pdftable_exe):
            status = "failed"
            warnings.append("pdftable executable is not available.")
        else:
            completed = run_command(command, cwd=None, timeout_seconds=args.timeout_seconds)
            log = output_dir / "tool.log"
            write_text(log, f"STDOUT\n{completed.stdout}\n\nSTDERR\n{completed.stderr}\n")
            artifacts.append(artifact(log, "tool_log", "pdf_table tool log", "text/plain"))
            status = "ok" if completed.returncode == 0 else "failed"
            candidates = write_execute_table_candidates(tool_output, pages or [1], status="review" if status == "ok" else "failed")
            artifacts.append(artifact(candidates, "table_candidates_json", "pdf_table normalized table candidates", "application/json"))
    else:
        status = "planned"
    payload = make_result(
        backend=BACKEND,
        mode=args.mode,
        status=status,
        input_path=input_path,
        output_dir=output_dir,
        command=command,
        artifacts=artifacts,
        metrics={"artifact_count": len(artifacts), **page_metrics(pages)},
        warnings=warnings,
        next_actions=[
            {"action": "limit_pages", "detail": "Only run pdf_table on detected table-heavy pages."},
            {"action": "compare_backends", "detail": "Compare against Camelot, Tabula, pdfplumber, and PaddleOCR-VL before promotion."},
        ],
        health=health_payload,
    )
    write_result(output_dir, payload)
    return payload


if __name__ == "__main__":
    main_entry(run)

