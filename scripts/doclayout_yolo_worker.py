from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from external_wrapper_utils import (  # noqa: E402
    add_common_arguments,
    artifact,
    ensure_output_dir,
    main_entry,
    make_result,
    page_metrics,
    parse_pages,
    write_json,
    write_placeholder_png,
    write_result,
    write_text,
)


BACKEND = "doclayout_yolo"


def build_command(args: argparse.Namespace, tool_output: Path) -> list[str]:
    return [
        args.python_executable or sys.executable,
        "scripts/doclayout_yolo_worker.py",
        "--input",
        str(Path(args.input)),
        "--output",
        str(tool_output),
        "--model",
        args.model,
        "--pages",
        args.pages or "1-3",
        "--imgsz",
        str(args.imgsz),
        "--conf",
        str(args.conf),
        "--device",
        args.device,
        "--mode",
        "execute",
    ]


def health(args: argparse.Namespace) -> dict[str, object]:
    model_path = Path(args.model).expanduser() if args.model and not args.model.startswith("hf:") else None
    checks = [
        {"name": "model", "value": args.model, "local_path_exists": bool(model_path and model_path.exists())},
        {"name": "device", "value": args.device},
        {"name": "imports", "value": ["doclayout_yolo", "ultralytics", "fitz"], "checked": False},
    ]
    if not args.model:
        status = "needs_model"
    elif model_path and not model_path.exists():
        status = "needs_model"
    else:
        status = "planned_only"
    return {"status": status, "checks": checks}


def fake_artifacts(output_dir: Path, pages: list[int] | str | None) -> list[dict[str, object]]:
    selected_pages = pages if isinstance(pages, list) and pages else [1]
    blocks = []
    artifacts: list[dict[str, object]] = []
    for page in selected_pages[:3]:
        overlay = output_dir / f"page-{page:03d}-layout.png"
        write_placeholder_png(overlay)
        artifacts.append(artifact(overlay, "layout_overlay_image", f"DocLayout-YOLO page {page} overlay", "image/png"))
        blocks.append(
            {
                "page": page,
                "width": 1240,
                "height": 1754,
                "blocks": [{"label": "table", "confidence": 0.91, "bbox": [100, 220, 900, 600]}],
            }
        )
    layout_json = output_dir / "layout_candidates.json"
    summary = output_dir / "layout-summary.md"
    write_json(layout_json, {"schema_version": "layout-candidates-v1", "backend": BACKEND, "pages": blocks})
    write_text(summary, "# DocLayout-YOLO fake layout summary\n\nGenerated fake layout candidates for contract tests.\n")
    artifacts.insert(0, artifact(layout_json, "layout_candidates_json", "DocLayout-YOLO layout candidates", "application/json"))
    artifacts.append(artifact(summary, "layout_summary", "DocLayout-YOLO layout summary", "text/markdown"))
    return artifacts


def run() -> dict[str, object]:
    parser = argparse.ArgumentParser(description="Plan a DocLayout-YOLO layout baseline run.")
    add_common_arguments(parser)
    parser.add_argument("--python-executable")
    parser.add_argument("--model", default="")
    parser.add_argument("--pages", default="1-3")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--imgsz", type=int, default=1024)
    parser.add_argument("--conf", type=float, default=0.2)
    parser.add_argument("--render-dpi", type=int, default=180)
    args = parser.parse_args()

    input_path = Path(args.input).expanduser()
    output_dir = ensure_output_dir(Path(args.output).expanduser())
    tool_output = ensure_output_dir(output_dir / "tool-output")
    pages = parse_pages(args.pages)
    command = build_command(args, tool_output)
    artifacts: list[dict[str, object]] = []
    warnings: list[str] = []
    if args.mode == "fake":
        artifacts = fake_artifacts(tool_output, pages)
        status = "ok"
    elif args.mode == "execute":
        status = "skipped"
        warnings.append("Execute is intentionally deferred; implement after model path and import environment are confirmed.")
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
            {"action": "confirm_model", "detail": "Confirm a local model path or HF id before the first execute run."},
            {"action": "keep_layout_as_evidence", "detail": "Use bbox output as review evidence, not direct Markdown replacement."},
        ],
        health=health(args),
    )
    write_result(output_dir, payload)
    return payload


if __name__ == "__main__":
    main_entry(run)

