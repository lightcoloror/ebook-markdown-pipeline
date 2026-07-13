from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from external_wrapper_utils import (  # noqa: E402
    add_common_arguments,
    artifact,
    check_path,
    ensure_output_dir,
    main_entry,
    make_result,
    parse_pages,
    write_json,
    write_placeholder_png,
    write_result,
    write_text,
)


BACKEND = "dots_mocr"


def build_command(args: argparse.Namespace, tool_output: Path) -> list[str]:
    root = Path(args.dots_root).expanduser() if args.dots_root else Path("<dots-mocr-root>")
    command = [
        args.python_executable or sys.executable,
        str(root / "dots_mocr" / "parser.py"),
        str(Path(args.input)),
        "--output",
        str(tool_output),
        "--protocol",
        urlparse(args.server).scheme or "http",
        "--ip",
        urlparse(args.server).hostname or "127.0.0.1",
        "--port",
        str(urlparse(args.server).port or 8000),
        "--model_name",
        args.model,
        "--num_thread",
        str(args.num_thread),
    ]
    if args.use_hf:
        command.extend(["--use_hf", "true"])
    return command


def health(args: argparse.Namespace) -> dict[str, object]:
    root = Path(args.dots_root).expanduser() if args.dots_root else None
    weights = root / "weights" / "DotsMOCR" if root else None
    parsed = urlparse(args.server)
    checks = [
        check_path("dots_root", root, "dir"),
        check_path("parser_py", root / "dots_mocr" / "parser.py" if root else None),
        check_path("weights", weights, "dir"),
        {"name": "server_url", "url": args.server, "ok": bool(parsed.scheme and parsed.netloc)},
    ]
    if args.use_hf and not (weights and weights.exists()):
        status = "needs_weights"
    elif root and not (root / "dots_mocr" / "parser.py").is_file():
        status = "needs_env"
    elif not (parsed.scheme and parsed.netloc):
        status = "planned_only"
    else:
        status = "needs_server"
    return {"status": status, "checks": checks, "server_check": "not_performed"}


def fake_artifacts(output_dir: Path, input_path: Path) -> list[dict[str, object]]:
    stem = input_path.stem or "input"
    layout_json = output_dir / f"{stem}.json"
    md = output_dir / f"{stem}.md"
    nohf = output_dir / f"{stem}_nohf.md"
    overlay = output_dir / f"{stem}.jpg"
    index = output_dir / f"{stem}.jsonl"
    write_json(layout_json, {"schema_version": "dots-layout-fake-v1", "pages": [{"page": 1, "blocks": []}]})
    write_text(md, "# dots.mocr fake Markdown\n")
    write_text(nohf, "# dots.mocr fake Markdown without header/footer\n")
    write_placeholder_png(overlay)
    write_text(index, json_line({"page": 1, "json": str(layout_json), "markdown": str(md)}))
    return [
        artifact(layout_json, "layout_blocks_json", "dots.mocr layout JSON", "application/json"),
        artifact(md, "markdown", "dots.mocr Markdown", "text/markdown"),
        artifact(nohf, "markdown_no_header_footer", "dots.mocr no-header-footer Markdown", "text/markdown"),
        artifact(overlay, "layout_overlay_image", "dots.mocr layout overlay", "image/jpeg"),
        artifact(index, "page_index_jsonl", "dots.mocr page index", "application/jsonl"),
    ]


def json_line(payload: dict[str, object]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False) + "\n"


def run() -> dict[str, object]:
    parser = argparse.ArgumentParser(description="Plan a dots.ocr/dots.mocr provider or worker call.")
    add_common_arguments(parser)
    parser.add_argument("--dots-root")
    parser.add_argument("--python-executable")
    parser.add_argument("--server", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--model", default="model")
    parser.add_argument("--use-hf", action="store_true")
    parser.add_argument("--num-thread", type=int, default=1)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--pages")
    args = parser.parse_args()

    input_path = Path(args.input).expanduser()
    output_dir = ensure_output_dir(Path(args.output).expanduser())
    tool_output = ensure_output_dir(output_dir / "tool-output")
    command = build_command(args, tool_output)
    health_payload = health(args)
    pages = parse_pages(args.pages)
    warnings: list[str] = []
    artifacts: list[dict[str, object]] = []
    if args.mode == "fake":
        artifacts = fake_artifacts(tool_output, input_path)
        status = "ok"
    elif args.mode == "execute":
        status = "skipped"
        warnings.append("Execute is intentionally not implemented until a dots.mocr server or parser command is confirmed.")
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
        metrics={"artifact_count": len(artifacts), "max_pages": args.max_pages, "pages": pages},
        warnings=warnings,
        next_actions=[
            {"action": "check_server", "detail": f"Verify OpenAI-compatible models endpoint at {args.server} before execute."},
            {"action": "limit_pages", "detail": "Use a small page range for first real runs."},
        ],
        health=health_payload,
    )
    write_result(output_dir, payload)
    return payload


if __name__ == "__main__":
    main_entry(run)

