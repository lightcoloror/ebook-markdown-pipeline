from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from external_wrapper_utils import (  # noqa: E402
    add_common_arguments,
    artifact,
    check_path,
    ensure_output_dir,
    main_entry,
    make_result,
    run_command,
    write_json,
    write_placeholder_pdf,
    write_result,
    write_text,
)


BACKEND = "monkeyocr"


def build_command(args: argparse.Namespace, tool_output: Path) -> list[str]:
    python_exe = args.python_executable or sys.executable
    root = Path(args.monkeyocr_root).expanduser() if args.monkeyocr_root else Path("<monkeyocr-root>")
    command = [python_exe, str(root / "parse.py"), str(Path(args.input)), "-o", str(tool_output)]
    if args.split_pages:
        command.append("--split_pages")
    if args.group_size:
        command.extend(["--group-size", str(args.group_size)])
    if args.task:
        command.extend(["--task", args.task])
    if args.skip_processed:
        command.append("--skip-processed")
    if args.pred_abandon:
        command.append("--pred-abandon")
    return command


def health(args: argparse.Namespace) -> dict[str, object]:
    root = Path(args.monkeyocr_root).expanduser() if args.monkeyocr_root else None
    model_root = root / "model_weight" if root else None
    checks = [
        check_path("monkeyocr_root", root, "dir"),
        check_path("parse_py", root / "parse.py" if root else None),
        check_path("model_configs", root / "model_configs.yaml" if root else None),
        check_path("model_weight", model_root, "dir"),
    ]
    if not root:
        status = "planned_only"
    elif not (root / "parse.py").is_file():
        status = "needs_env"
    elif not model_root.exists():
        status = "needs_model"
    else:
        status = "ready"
    return {"status": status, "checks": checks}


def fake_artifacts(output_dir: Path, input_path: Path) -> list[dict[str, object]]:
    stem = input_path.stem or "input"
    md = output_dir / f"{stem}.md"
    middle = output_dir / f"{stem}_middle.json"
    content = output_dir / f"{stem}_content_list.json"
    layout = output_dir / f"{stem}_layout.pdf"
    spans = output_dir / f"{stem}_spans.pdf"
    model = output_dir / f"{stem}_model.pdf"
    images = output_dir / "images"
    images.mkdir(parents=True, exist_ok=True)
    write_text(md, "# MonkeyOCR fake output\n\nThis is a dry artifact for contract tests.\n")
    write_json(middle, {"schema_version": "monkeyocr-middle-fake-v1", "pages": []})
    write_json(content, [{"type": "text", "text": "MonkeyOCR fake output"}])
    write_placeholder_pdf(layout, "layout")
    write_placeholder_pdf(spans, "spans")
    write_placeholder_pdf(model, "model")
    return [
        artifact(md, "markdown", "MonkeyOCR Markdown", "text/markdown"),
        artifact(middle, "middle_json", "MonkeyOCR middle JSON", "application/json"),
        artifact(content, "content_list_json", "MonkeyOCR content list", "application/json"),
        artifact(layout, "layout_review_pdf", "MonkeyOCR layout review PDF", "application/pdf"),
        artifact(spans, "span_review_pdf", "MonkeyOCR spans review PDF", "application/pdf"),
        artifact(model, "model_debug_pdf", "MonkeyOCR model debug PDF", "application/pdf"),
        artifact(images, "image_assets_dir", "MonkeyOCR image assets"),
    ]


def run() -> dict[str, object]:
    parser = argparse.ArgumentParser(description="Plan or run a MonkeyOCR external worker.")
    add_common_arguments(parser)
    parser.add_argument("--monkeyocr-root")
    parser.add_argument("--python-executable")
    parser.add_argument("--split-pages", action="store_true")
    parser.add_argument("--group-size", type=int)
    parser.add_argument("--task", choices=["text", "formula", "table"])
    parser.add_argument("--skip-processed", action="store_true")
    parser.add_argument("--pred-abandon", action="store_true")
    args = parser.parse_args()

    input_path = Path(args.input).expanduser()
    output_dir = ensure_output_dir(Path(args.output).expanduser())
    tool_output = ensure_output_dir(output_dir / "tool-output")
    command = build_command(args, tool_output)
    health_payload = health(args)
    artifacts: list[dict[str, object]] = []
    warnings: list[str] = []
    next_actions = [
        {"action": "review_plan", "detail": "Verify MonkeyOCR root, isolated Python, model_weight, and a small page range before execute."}
    ]

    if args.mode == "fake":
        artifacts = fake_artifacts(tool_output, input_path)
        status = "ok"
    elif args.mode == "execute":
        if health_payload.get("status") not in {"ready"}:
            status = "failed"
            warnings.append("MonkeyOCR is not ready; refusing execute without parse.py and model_weight.")
        else:
            completed = run_command(command, cwd=Path(args.monkeyocr_root).expanduser(), timeout_seconds=args.timeout_seconds)
            log = output_dir / "tool.log"
            write_text(log, f"STDOUT\n{completed.stdout}\n\nSTDERR\n{completed.stderr}\n")
            artifacts.append(artifact(log, "tool_log", "MonkeyOCR tool log", "text/plain"))
            status = "ok" if completed.returncode == 0 else "failed"
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
        metrics={"artifact_count": len(artifacts)},
        warnings=warnings,
        next_actions=next_actions,
        health=health_payload,
    )
    write_result(output_dir, payload)
    return payload


if __name__ == "__main__":
    main_entry(run)

