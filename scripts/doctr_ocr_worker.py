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
    write_result,
    write_text,
)


BACKEND = "doctr"


def build_command(args: argparse.Namespace, tool_output: Path) -> list[str]:
    return [
        args.python_executable or sys.executable,
        "scripts/doctr_ocr_worker.py",
        "--input",
        str(Path(args.input)),
        "--output",
        str(tool_output),
        "--det-arch",
        args.det_arch,
        "--reco-arch",
        args.reco_arch,
        "--mode",
        "execute",
    ]


def health() -> dict[str, object]:
    try:
        import doctr  # type: ignore  # noqa: F401

        return {"status": "needs_model", "checks": [{"name": "doctr", "importable": True, "detail": "model initialization not performed"}]}
    except Exception as exc:  # noqa: BLE001
        return {"status": "planned_only", "checks": [{"name": "doctr", "importable": False, "message": str(exc)}]}


def fake_artifacts(output_dir: Path) -> list[dict[str, object]]:
    blocks = output_dir / "ocr-blocks.jsonl"
    summary = output_dir / "doctr-summary.md"
    write_text(blocks, '{"schema_version":"ocr-blocks-v1","provider":"doctr","image":"fake","blocks":[{"text":"Fake docTR OCR text.","confidence":0.88}]}\n')
    write_text(summary, "# docTR fake OCR summary\n\nDetection + recognition adapter contract only.\n")
    return [
        artifact(blocks, "ocr_blocks_jsonl", "docTR OCR blocks", "application/jsonl"),
        artifact(summary, "markdown", "docTR summary", "text/markdown"),
    ]


def run() -> dict[str, object]:
    parser = argparse.ArgumentParser(description="Plan a docTR OCR detection/recognition worker.")
    add_common_arguments(parser)
    parser.add_argument("--python-executable")
    parser.add_argument("--det-arch", default="db_resnet50")
    parser.add_argument("--reco-arch", default="crnn_vgg16_bn")
    args = parser.parse_args()

    input_path = Path(args.input).expanduser()
    output_dir = ensure_output_dir(Path(args.output).expanduser())
    tool_output = ensure_output_dir(output_dir / "tool-output")
    command = build_command(args, tool_output)
    warnings: list[str] = []
    artifacts: list[dict[str, object]] = []
    if args.mode == "fake":
        artifacts = fake_artifacts(tool_output)
        status = "ok"
    elif args.mode == "execute":
        status = "skipped"
        warnings.append("Execute is deferred until docTR model initialization and ocr-blocks-v1 normalization are implemented.")
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
        next_actions=[
            {"action": "add_adapter", "detail": "Implement docTR detection+recognition normalization to ocr-blocks-v1 before real execution."},
            {"action": "benchmark_only", "detail": "Keep docTR as comparison candidate until quality beats existing local OCR routes."},
        ],
        health=health(),
    )
    write_result(output_dir, payload)
    return payload


if __name__ == "__main__":
    main_entry(run)
