from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from external_wrapper_utils import add_common_arguments, artifact, ensure_output_dir, main_entry, make_result, page_metrics, parse_pages, write_json, write_result, write_text


BACKEND = "opendataloader_pdf_fast"


def health(args: argparse.Namespace) -> dict[str, object]:
    root = Path(args.opendataloader_root).expanduser() if args.opendataloader_root else None
    return {
        "status": "needs_env",
        "checks": [
            {"name": "java", "available": shutil.which("java") is not None, "required_version": "11+"},
            {"name": "opendataloader_root", "path": str(root) if root else "", "exists": bool(root and root.exists())},
            {"name": "mode", "value": "fast", "hybrid_forbidden": True, "ocr_forbidden": True},
        ],
    }


def fake_artifacts(output_dir: Path, pages: list[int] | str | None) -> list[dict[str, object]]:
    page = pages[0] if isinstance(pages, list) and pages else 1
    markdown = output_dir / "document.md"
    html = output_dir / "document.html"
    provenance = output_dir / "document-provenance.json"
    write_text(markdown, "# Fake OpenDataLoader fast output\n\nThis is contract-only provenance evidence.\n")
    write_text(html, "<h1>Fake OpenDataLoader fast output</h1><p>Contract-only provenance evidence.</p>\n")
    write_json(provenance, {"schema_version": "document-provenance-v1", "backend": BACKEND, "mode": "fake", "pages": [{"page": page, "elements": [{"type": "text", "bbox": [0, 0, 100, 20], "reading_order": 1}]}], "warnings": ["Fake output is not a parser result."]})
    return [artifact(markdown, "markdown", "OpenDataLoader fake Markdown", "text/markdown"), artifact(html, "html", "OpenDataLoader fake HTML", "text/html"), artifact(provenance, "document_provenance_json", "OpenDataLoader fake provenance", "application/json")]


def run() -> dict[str, object]:
    parser = argparse.ArgumentParser(description="Plan/fake-only OpenDataLoader PDF fast-mode comparison.")
    add_common_arguments(parser)
    parser.add_argument("--pages", default="1")
    parser.add_argument("--opendataloader-root", default="")
    args = parser.parse_args()
    output_dir = ensure_output_dir(Path(args.output).expanduser())
    pages = parse_pages(args.pages)
    artifacts: list[dict[str, object]] = []
    warnings = ["Hybrid, OCR, model download, and service start are forbidden by this worker."]
    if args.mode == "fake":
        artifacts = fake_artifacts(ensure_output_dir(output_dir / "tool-output"), pages)
        status = "ok"
    elif args.mode == "execute":
        status = "skipped"
        warnings.append("Execute is intentionally refused; only an approved fast-mode experiment may add a real runner later.")
    else:
        status = "planned"
    payload = make_result(
        backend=BACKEND, mode=args.mode, status=status, input_path=Path(args.input).expanduser(), output_dir=output_dir,
        command=["opendataloader-pdf", "fast", "--input", str(Path(args.input)), "--no-hybrid", "--no-ocr"], artifacts=artifacts,
        metrics={"artifact_count": len(artifacts), **page_metrics(pages), "model_downloads": 0, "service_starts": 0}, warnings=warnings,
        next_actions=[{"action": "verify_java_11", "detail": "Check Java 11+ and a manually managed runtime before any approved experiment."}, {"action": "compare_provenance", "detail": "Compare page/bbox/reading-order evidence without starting hybrid mode."}], health=health(args),
    )
    write_result(output_dir, payload)
    return payload


if __name__ == "__main__":
    main_entry(run)