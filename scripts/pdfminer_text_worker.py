from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from external_wrapper_utils import (  # noqa: E402
    add_common_arguments,
    artifact,
    ensure_output_dir,
    main_entry,
    make_result,
    write_json,
    write_result,
    write_text,
)


BACKEND = "pdfminer_six"


def build_command(args: argparse.Namespace, tool_output: Path) -> list[str]:
    return [
        args.python_executable or sys.executable,
        "scripts/pdfminer_text_worker.py",
        "--input",
        str(Path(args.input)),
        "--output",
        str(tool_output),
        "--max-chars",
        str(args.max_chars),
        "--mode",
        "execute",
    ]


def health() -> dict[str, object]:
    try:
        import pdfminer.high_level  # type: ignore  # noqa: F401

        return {"status": "ok", "checks": [{"name": "pdfminer.six", "importable": True}]}
    except Exception as exc:  # noqa: BLE001
        return {"status": "needs_env", "checks": [{"name": "pdfminer.six", "importable": False, "message": str(exc)}]}


def fake_artifacts(output_dir: Path) -> list[dict[str, object]]:
    text_path = output_dir / "pdfminer-text.txt"
    pages_path = output_dir / "pdfminer-pages.jsonl"
    evidence_path = output_dir / "pdfminer-layout-evidence.json"
    summary = output_dir / "pdfminer-summary.md"
    text_sample = "Fake pdfminer text-layer fallback."
    evidence = build_layout_evidence([text_sample], backend=BACKEND, status="fake")
    write_text(text_path, text_sample + "\n")
    write_text(pages_path, json.dumps({"schema_version": "pdfminer-text-page-v1", "page": 1, "text_preview": text_sample}, ensure_ascii=False) + "\n")
    write_json(evidence_path, evidence)
    write_text(summary, "# pdfminer.six fake text diagnostics\n\nText-layer fallback contract only. Includes pdf-layout-evidence-v1.\n")
    return [
        artifact(text_path, "text", "pdfminer text sample", "text/plain"),
        artifact(pages_path, "pages_jsonl", "pdfminer page text JSONL", "application/jsonl"),
        artifact(evidence_path, "pdf_layout_evidence_json", "pdfminer layout/text evidence", "application/json"),
        artifact(summary, "markdown", "pdfminer diagnostic summary", "text/markdown"),
    ]


def execute_artifacts(input_path: Path, output_dir: Path, max_chars: int) -> tuple[list[dict[str, object]], dict[str, object], list[str]]:
    warnings: list[str] = []
    try:
        from pdfminer.high_level import extract_text  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return [], {}, [f"pdfminer.six is not importable: {exc}"]
    text = extract_text(str(input_path)) or ""
    truncated = text[:max_chars] if max_chars > 0 else text
    text_path = output_dir / "pdfminer-text.txt"
    pages_path = output_dir / "pdfminer-pages.jsonl"
    summary = output_dir / "pdfminer-summary.md"
    evidence_path = output_dir / "pdfminer-layout-evidence.json"
    page_texts = split_pdfminer_pages(text)
    write_text(text_path, truncated)
    write_text(pages_path, "".join(json.dumps({"schema_version": "pdfminer-text-page-v1", "page": index, "text_preview": page_text[:300]}, ensure_ascii=False) + "\n" for index, page_text in enumerate(page_texts, start=1)))
    write_json(evidence_path, build_layout_evidence(page_texts, backend=BACKEND, status="ok"))
    write_text(summary, f"# pdfminer.six text diagnostics\n\n- Characters: {len(text)}\n- Returned: {len(truncated)}\n- Evidence: pdf-layout-evidence-v1\n")
    if max_chars > 0 and len(text) > max_chars:
        warnings.append(f"Text truncated to {max_chars} characters.")
    artifacts = [
        artifact(text_path, "text", "pdfminer text sample", "text/plain"),
        artifact(pages_path, "pages_jsonl", "pdfminer page text JSONL", "application/jsonl"),
        artifact(evidence_path, "pdf_layout_evidence_json", "pdfminer layout/text evidence", "application/json"),
        artifact(summary, "markdown", "pdfminer diagnostic summary", "text/markdown"),
    ]
    return artifacts, {"char_count": len(text), "returned_char_count": len(truncated), "evidence_schema": "pdf-layout-evidence-v1"}, warnings


def split_pdfminer_pages(text: str) -> list[str]:
    pages = [page.strip() for page in text.split("\f")]
    pages = [page for page in pages if page]
    return pages or [text]


def build_layout_evidence(page_texts: list[str], *, backend: str, status: str) -> dict[str, object]:
    pages = []
    total_chars = 0
    total_lines = 0
    for index, page_text in enumerate(page_texts, start=1):
        lines = [line for line in page_text.splitlines() if line.strip()]
        text_chars = len(page_text)
        line_count = len(lines)
        total_chars += text_chars
        total_lines += line_count
        pages.append(
            {
                "page": index,
                "text_chars": text_chars,
                "line_count": line_count,
                "avg_line_chars": round(text_chars / line_count, 2) if line_count else 0,
                "text_preview": page_text[:300],
            }
        )
    page_count = len(pages)
    avg_chars = round(total_chars / page_count, 2) if page_count else 0
    return {
        "schema_version": "pdf-layout-evidence-v1",
        "backend": backend,
        "status": status,
        "page_count": page_count,
        "text_char_count": total_chars,
        "line_count": total_lines,
        "flags": {
            "text_layer_present": total_chars > 0,
            "low_text_density": avg_chars < 80,
            "layout_heavy_suspected": False,
            "table_heavy_suspected": False,
        },
        "pages": pages,
    }


def run() -> dict[str, object]:
    parser = argparse.ArgumentParser(description="Plan or run pdfminer.six text-layer diagnostics.")
    add_common_arguments(parser)
    parser.add_argument("--python-executable")
    parser.add_argument("--max-chars", type=int, default=20000)
    args = parser.parse_args()

    input_path = Path(args.input).expanduser()
    output_dir = ensure_output_dir(Path(args.output).expanduser())
    tool_output = ensure_output_dir(output_dir / "tool-output")
    command = build_command(args, tool_output)
    warnings: list[str] = []
    metrics: dict[str, object] = {}
    artifacts: list[dict[str, object]] = []
    if args.mode == "fake":
        artifacts = fake_artifacts(tool_output)
        status = "ok"
        metrics = {"artifact_count": len(artifacts), "char_count": 35, "evidence_schema": "pdf-layout-evidence-v1"}
    elif args.mode == "execute":
        artifacts, metrics, warnings = execute_artifacts(input_path, tool_output, args.max_chars)
        status = "ok" if artifacts else "failed"
        metrics["artifact_count"] = len(artifacts)
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
        metrics=metrics or {"artifact_count": len(artifacts)},
        warnings=warnings,
        next_actions=[
            {"action": "use_as_text_debug_fallback", "detail": "Use pdfminer.six as text-layer evidence when PyMuPDF output looks suspicious."},
            {"action": "do_not_replace_markdown_router", "detail": "This worker emits diagnostics/text samples, not final book Markdown."},
        ],
        health=health(),
    )
    write_result(output_dir, payload)
    return payload


if __name__ == "__main__":
    main_entry(run)
