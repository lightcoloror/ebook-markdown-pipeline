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


BACKEND = "pypdf"


def build_command(args: argparse.Namespace, tool_output: Path) -> list[str]:
    return [
        args.python_executable or sys.executable,
        "scripts/pypdf_diagnostics_worker.py",
        "--input",
        str(Path(args.input)),
        "--output",
        str(tool_output),
        "--mode",
        "execute",
    ]


def health() -> dict[str, object]:
    try:
        import pypdf  # type: ignore  # noqa: F401

        return {"status": "ok", "checks": [{"name": "pypdf", "importable": True}]}
    except Exception as exc:  # noqa: BLE001
        return {"status": "needs_env", "checks": [{"name": "pypdf", "importable": False, "message": str(exc)}]}


def fake_artifacts(output_dir: Path) -> list[dict[str, object]]:
    metadata = output_dir / "pypdf-metadata.json"
    outline = output_dir / "pypdf-outline.json"
    summary = output_dir / "pypdf-summary.md"
    write_json(metadata, {"schema_version": "pypdf-diagnostics-v1", "backend": BACKEND, "page_count": 1, "metadata": {"title": "fake"}})
    write_json(outline, {"schema_version": "pypdf-outline-v1", "backend": BACKEND, "items": []})
    write_text(summary, "# pypdf fake diagnostics\n\nMetadata and outline fallback contract only.\n")
    return [
        artifact(metadata, "pdf_metadata_json", "pypdf metadata diagnostics", "application/json"),
        artifact(outline, "pdf_outline_json", "pypdf outline diagnostics", "application/json"),
        artifact(summary, "markdown", "pypdf diagnostic summary", "text/markdown"),
    ]


def execute_artifacts(input_path: Path, output_dir: Path) -> tuple[list[dict[str, object]], dict[str, object], list[str]]:
    warnings: list[str] = []
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return [], {}, [f"pypdf is not importable: {exc}"]
    reader = PdfReader(str(input_path))
    metadata_payload = {str(key).lstrip("/"): str(value) for key, value in dict(reader.metadata or {}).items()}
    outlines = []
    try:
        raw_outline = reader.outline
        outlines = flatten_outline(raw_outline)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"Could not read PDF outline: {exc}")
    metadata = output_dir / "pypdf-metadata.json"
    outline = output_dir / "pypdf-outline.json"
    summary = output_dir / "pypdf-summary.md"
    write_json(metadata, {"schema_version": "pypdf-diagnostics-v1", "backend": BACKEND, "page_count": len(reader.pages), "metadata": metadata_payload})
    write_json(outline, {"schema_version": "pypdf-outline-v1", "backend": BACKEND, "items": outlines})
    write_text(summary, f"# pypdf diagnostics\n\n- Pages: {len(reader.pages)}\n- Outline items: {len(outlines)}\n")
    artifacts = [
        artifact(metadata, "pdf_metadata_json", "pypdf metadata diagnostics", "application/json"),
        artifact(outline, "pdf_outline_json", "pypdf outline diagnostics", "application/json"),
        artifact(summary, "markdown", "pypdf diagnostic summary", "text/markdown"),
    ]
    return artifacts, {"page_count": len(reader.pages), "outline_count": len(outlines)}, warnings


def flatten_outline(items, *, depth: int = 0, limit: int = 120) -> list[dict[str, object]]:
    flattened: list[dict[str, object]] = []
    for item in items or []:
        if len(flattened) >= limit:
            break
        if isinstance(item, list):
            flattened.extend(flatten_outline(item, depth=depth + 1, limit=limit - len(flattened)))
            continue
        title = getattr(item, "title", "") or str(item)
        flattened.append({"title": str(title), "level": depth + 1})
    return flattened[:limit]


def run() -> dict[str, object]:
    parser = argparse.ArgumentParser(description="Plan or run pypdf metadata/outline diagnostics.")
    add_common_arguments(parser)
    parser.add_argument("--python-executable")
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
        metrics = {"artifact_count": len(artifacts), "page_count": 1}
    elif args.mode == "execute":
        artifacts, metrics, warnings = execute_artifacts(input_path, tool_output)
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
            {"action": "use_as_metadata_fallback", "detail": "Use pypdf only for metadata/outline/split utility evidence, not Markdown conversion."},
            {"action": "compare_with_pymupdf", "detail": "Prefer PyMuPDF/PyMuPDF4LLM for text-layer extraction unless pypdf evidence fills a gap."},
        ],
        health=health(),
    )
    write_result(output_dir, payload)
    return payload


if __name__ == "__main__":
    main_entry(run)
