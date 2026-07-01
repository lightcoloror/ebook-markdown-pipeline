from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from ebook_converter_mcp import run_online_enhancement  # noqa: E402
from online_providers import load_provider_registry  # noqa: E402

SUPPORTED_TASKS = {"ocr_layout", "vlm_layout"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate remote OCR/VLM providers on a small manifest without downloading local models.")
    parser.add_argument("--manifest", type=Path, default=PROJECT_DIR / "config" / "remote_ocr_vlm_eval.example.json")
    parser.add_argument("--provider-config", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=PROJECT_DIR / "benchmarks" / "runs" / "remote-ocr-vlm-eval")
    parser.add_argument("--provider", action="append", default=None, help="Provider name from the online provider config. Repeat to select multiple providers.")
    parser.add_argument("--sample", action="append", default=None, help="Sample id from the manifest. Repeat to select multiple samples.")
    parser.add_argument("--execute", action="store_true", help="Actually call providers. Without this flag the script writes a dry-run plan only.")
    parser.add_argument("--allow-remote", action="store_true", help="Required together with --execute for remote OpenAI-compatible provider calls.")
    parser.add_argument("--fake", action="store_true", help="Use fake providers for contract testing; no remote call is made.")
    args = parser.parse_args()

    manifest = load_json(args.manifest)
    providers = select_providers(manifest, args.provider)
    samples = select_samples(manifest, args.sample)
    started = time.monotonic()
    output_dir = args.output
    output_dir.mkdir(parents=True, exist_ok=True)

    provider_health = {}
    if args.provider_config:
        try:
            provider_health = load_provider_registry(args.provider_config).health()
        except Exception as exc:  # noqa: BLE001
            provider_health = {"error": True, "message": str(exc)}

    results: list[dict[str, Any]] = []
    for provider in providers:
        for sample in samples:
            results.append(run_eval_item(provider, sample, manifest, args=args, output_dir=output_dir))

    payload = {
        "schema_version": "remote-ocr-vlm-eval-result-v1",
        "status": summarize_status(results),
        "dry_run": not args.execute,
        "fake": bool(args.fake),
        "remote_call_enabled": bool(args.execute and args.allow_remote and not args.fake),
        "manifest": str(args.manifest),
        "provider_config": str(args.provider_config) if args.provider_config else "",
        "provider_health": provider_health,
        "duration_seconds": round(time.monotonic() - started, 3),
        "result_count": len(results),
        "results": results,
    }
    json_path = output_dir / "remote-ocr-vlm-eval.json"
    md_path = output_dir / "remote-ocr-vlm-eval.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    md_path.write_text(render_markdown(payload), encoding="utf-8", newline="\n")
    print(json.dumps({"status": payload["status"], "json": str(json_path), "markdown": str(md_path), "result_count": len(results)}, ensure_ascii=False, indent=2))
    return 1 if payload["status"] == "failed" else 0


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"Manifest not found: {path}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("Manifest must be a JSON object.")
    return payload


def select_providers(manifest: dict[str, Any], names: list[str] | None) -> list[dict[str, Any]]:
    providers = manifest.get("providers") if isinstance(manifest.get("providers"), list) else []
    selected = [dict(item) for item in providers if isinstance(item, dict)]
    if names:
        wanted = set(names)
        selected = [item for item in selected if str(item.get("name") or "") in wanted]
    if not selected:
        raise SystemExit("No providers selected. Add providers to the manifest or pass --provider with a matching name.")
    return selected


def select_samples(manifest: dict[str, Any], ids: list[str] | None) -> list[dict[str, Any]]:
    samples = manifest.get("samples") if isinstance(manifest.get("samples"), list) else []
    selected = [dict(item) for item in samples if isinstance(item, dict)]
    if ids:
        wanted = set(ids)
        selected = [item for item in selected if str(item.get("id") or "") in wanted]
    if not selected:
        raise SystemExit("No samples selected. Add samples to the manifest or pass --sample with a matching id.")
    return selected


def run_eval_item(provider: dict[str, Any], sample: dict[str, Any], manifest: dict[str, Any], *, args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    provider_name = str(provider.get("name") or "")
    sample_id = str(sample.get("id") or sample.get("path") or "sample")
    task = str(provider.get("task") or manifest.get("default_task") or "vlm_layout")
    if task not in SUPPORTED_TASKS:
        return base_result(provider_name, sample_id, task, "skipped", f"Unsupported task for remote OCR/VLM eval: {task}")
    sample_path = resolve_sample_path(sample, args.manifest)
    if not sample_path.is_file():
        return base_result(provider_name, sample_id, task, "skipped", f"Sample file not found: {sample_path}")

    prompt = str(provider.get("prompt") or sample.get("prompt") or manifest.get("default_prompt") or "")
    mime_type = str(sample.get("mime_type") or guess_mime_type(sample_path))
    item = base_result(provider_name, sample_id, task, "planned" if not args.execute else "running", "")
    item.update(
        {
            "sample_path": str(sample_path),
            "sample_category": sample.get("category") or "",
            "mime_type": mime_type,
            "expected_focus": sample.get("expected_focus") if isinstance(sample.get("expected_focus"), list) else [],
            "remote_call_enabled": bool(args.execute and args.allow_remote and not args.fake),
        }
    )
    if not args.execute:
        item["status"] = "planned"
        item["message"] = "Dry run only. Pass --execute --allow-remote to call a remote provider, or --execute --fake for fake-provider testing."
        return item

    provider_mode = "fake" if args.fake else str(provider.get("provider_mode") or "openai_compatible")
    model_mode = "hybrid" if args.fake else str(provider.get("model_mode") or "hybrid")
    payload = {
        "task": task,
        "input_path": str(sample_path),
        "output": str(output_dir / safe_name(f"{sample_id}-{provider_name}")),
        "mime_type": mime_type,
        "prompt": prompt,
        "context": {
            "sample_id": sample_id,
            "sample_category": sample.get("category") or "",
            "expected_focus": item["expected_focus"],
            "remote_eval": True,
        },
        "model_mode": model_mode,
        "provider_mode": provider_mode,
        "provider": provider_name,
        "config": str(args.provider_config) if args.provider_config else "",
        "allow_remote": bool(args.allow_remote),
    }
    started = time.monotonic()
    response = run_online_enhancement(payload)
    item["duration_seconds"] = round(time.monotonic() - started, 3)
    item["response_status"] = response.get("status") or "error" if response.get("error") else response.get("status") or "ok"
    item["status"] = "failed" if response.get("error") else "ok"
    item["message"] = str(response.get("message") or response.get("error") or "")
    item["artifacts"] = response.get("artifacts") or []
    item["quality_hints"] = quality_hints(response)
    if response.get("error"):
        item["error_payload"] = {key: response.get(key) for key in ("message", "retryable", "status_code", "provider") if key in response}
    return item


def base_result(provider: str, sample_id: str, task: str, status: str, message: str) -> dict[str, Any]:
    return {"provider": provider, "sample_id": sample_id, "task": task, "status": status, "message": message}


def resolve_sample_path(sample: dict[str, Any], manifest_path: Path) -> Path:
    raw = Path(str(sample.get("path") or ""))
    if raw.is_absolute():
        return raw
    candidates = [PROJECT_DIR / raw, manifest_path.resolve().parent / raw]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def guess_mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".pdf":
        return "application/pdf"
    return "image/png"


def quality_hints(response: dict[str, Any]) -> dict[str, Any]:
    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    markdown = str(result.get("markdown") or "")
    blocks = result.get("blocks") if isinstance(result.get("blocks"), list) else []
    tables = result.get("tables") if isinstance(result.get("tables"), list) else []
    warnings = result.get("warnings") if isinstance(result.get("warnings"), list) else []
    return {
        "markdown_chars": len(markdown),
        "heading_count": sum(1 for line in markdown.splitlines() if line.lstrip().startswith("#")),
        "block_count": len(blocks),
        "table_count": len(tables),
        "warning_count": len(warnings),
        "has_markdown_table": "|" in markdown and "---" in markdown,
    }


def summarize_status(results: list[dict[str, Any]]) -> str:
    if any(item.get("status") == "failed" for item in results):
        return "failed"
    if any(item.get("status") == "ok" for item in results):
        return "ok"
    if any(item.get("status") == "planned" for item in results):
        return "planned"
    return "skipped"


def render_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Remote OCR/VLM Evaluation", ""]
    lines.append(f"Status: `{payload.get('status')}`")
    lines.append(f"Dry run: `{payload.get('dry_run')}`")
    lines.append(f"Fake provider: `{payload.get('fake')}`")
    lines.append(f"Remote calls enabled: `{payload.get('remote_call_enabled')}`")
    lines.append("")
    lines.append("| Provider | Sample | Task | Status | Message | Markdown chars | Blocks | Tables |")
    lines.append("| --- | --- | --- | --- | --- | ---: | ---: | ---: |")
    for item in payload.get("results") or []:
        hints = item.get("quality_hints") if isinstance(item.get("quality_hints"), dict) else {}
        lines.append(
            "| "
            + " | ".join(
                [
                    escape_cell(str(item.get("provider") or "")),
                    escape_cell(str(item.get("sample_id") or "")),
                    escape_cell(str(item.get("task") or "")),
                    escape_cell(str(item.get("status") or "")),
                    escape_cell(str(item.get("message") or ""))[:120],
                    str(hints.get("markdown_chars") or 0),
                    str(hints.get("block_count") or 0),
                    str(hints.get("table_count") or 0),
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append("## Safety")
    lines.append("")
    lines.append("- This script does not download model weights.")
    lines.append("- Remote calls require `--execute --allow-remote`; otherwise only a plan is written.")
    lines.append("- Keep private manifests local and ignored. Do not commit private samples or API keys.")
    return "\n".join(lines).rstrip() + "\n"


def escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value).strip("-") or "remote-eval"


if __name__ == "__main__":
    raise SystemExit(main())
