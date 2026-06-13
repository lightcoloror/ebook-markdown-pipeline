from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "project-readiness-v1"


@dataclass(frozen=True)
class Check:
    stage: str
    name: str
    ok: bool
    evidence: str
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "name": self.name,
            "ok": self.ok,
            "evidence": self.evidence,
            "details": self.details,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check evidence for the five-stage project readiness goal.")
    parser.add_argument("--output", type=Path, help="Optional directory for project-readiness.json/md.")
    args = parser.parse_args()

    checks = collect_checks()
    payload = build_payload(checks)
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    if args.output:
        write_reports(args.output, payload)
    return 0 if payload["summary"]["status"] == "passed" else 3


def collect_checks() -> list[Check]:
    return [
        *stage1_checks(),
        *stage2_checks(),
        *stage3_checks(),
        *stage4_checks(),
        *stage5_checks(),
    ]


def stage1_checks() -> list[Check]:
    readme = read_text("README.md")
    install = read_text("docs/INSTALLATION.md")
    env = read_text("config.example.env")
    minimal_test = read_text("scripts/test_minimal_entrypoints.py")
    local_env_test = read_text("scripts/test_local_env.py")
    public_release = read_text("scripts/check_public_release.py")
    return [
        contains_all(
            "stage1_open_source_usability",
            "minimal README path",
            readme,
            ["git clone", "python -m pip install -r requirements.txt", "python book_converter_ui.py", "python batch_convert_books.py"],
            "README.md",
        ),
        contains_all(
            "stage1_open_source_usability",
            "four install levels",
            install,
            ["## 1. Minimal Setup", "## 2. PDF Enhanced Setup", "## 3. Local VLM / Image Layout Setup", "## 4. Agent / API Setup"],
            "docs/INSTALLATION.md",
        ),
        contains_all(
            "stage1_open_source_usability",
            "example environment paths",
            env + "\n" + local_env_test,
            [
                "EBOOK_CONVERTER_UMI_DIR",
                "EBOOK_CONVERTER_TOOL_CACHE",
                "EBOOK_CONVERTER_VLM_PYTHON",
                "EBOOK_CONVERTER_PADDLEOCR_COMMAND",
                "load_project_env",
                "Existing environment values must win by default",
            ],
            "config.example.env; scripts/test_local_env.py",
        ),
        contains_all(
            "stage1_open_source_usability",
            "README flow diagram",
            readme,
            ["```mermaid", "Input materials", "Desktop UI / CLI / HTTP API / MCP", "Outputs"],
            "README.md",
        ),
        contains_all(
            "stage1_open_source_usability",
            "minimal entrypoint smoke",
            minimal_test,
            ["book_converter_ui.py", "batch_convert_books.py", "--help", "Minimal TXT conversion"],
            "scripts/test_minimal_entrypoints.py",
        ),
        contains_all(
            "stage1_open_source_usability",
            "portable homepage guard",
            public_release,
            ["check_homepage_paths_are_portable", "homepage paths are portable", "README.md", "docs", "QUICKSTART.md"],
            "scripts/check_public_release.py",
        ),
        contains_all(
            "stage1_open_source_usability",
            "portable examples guard",
            public_release,
            ["check_example_paths_are_portable", "example paths are portable", "tracked examples/"],
            "scripts/check_public_release.py",
        ),
    ]


def stage2_checks() -> list[Check]:
    full_manifest = load_json("benchmarks/fixtures/generated/quality-full.json")
    categories = {str(item.get("category") or "") for item in full_manifest.get("samples") or []}
    required_categories = {
        "ebook_epub",
        "ebook_azw3_substitute",
        "pdf_text_layer",
        "pdf_bookmarked_outline",
        "scanned_pdf",
        "pdf_two_column",
        "image_infographic",
        "pdf_presentation_like",
    }
    run_benchmarks = read_text("scripts/run_benchmarks.py")
    gitignore = read_text(".gitignore")
    quality_test = read_text("scripts/test_quality_gate.py")
    run_quality_gate = read_text("scripts/run_quality_gate.py")
    readme = read_text("README.md")
    tracked_private_manifest_check = private_manifest_tracking_check()
    return [
        Check(
            "stage2_quality_regression",
            "public fixture coverage",
            required_categories.issubset(categories),
            "benchmarks/fixtures/generated/quality-full.json",
            f"required={sorted(required_categories)} actual={sorted(categories)}",
        ),
        contains_all(
            "stage2_quality_regression",
            "quality gate command",
            run_quality_gate,
            ["Run the public quality regression gate", "quality-regression-summary.md", "--fail-on-quality-gate"],
            "scripts/run_quality_gate.py",
        ),
        contains_all(
            "stage2_quality_regression",
            "fixed regression metrics",
            run_benchmarks,
            [
                "success_rate",
                "avg_headings",
                "avg_toc_match_ratio",
                "page_heading_ratio",
                "ocr_characters",
                "structure_repair_decisions",
                "review_or_poor",
                "avg_duration_seconds",
            ],
            "scripts/run_benchmarks.py",
        ),
        contains_all(
            "stage2_quality_regression",
            "quality metric test coverage",
            quality_test,
            ["required_full_categories", "pdf_bookmarked_outline", "image_set_duplicates", "avg_toc_match_ratio", "ocr_characters", "structure_repair_decisions", "avg_duration_seconds", "Review or poor"],
            "scripts/test_quality_gate.py",
        ),
        contains_all(
            "stage2_quality_regression",
            "quality comparison docs include fixed metrics",
            readme,
            ["benchmark-quality-comparison.json/md", "目录/书签匹配率", "OCR 字符量", "运行时间"],
            "README.md",
        ),
        contains_all(
            "stage2_quality_regression",
            "private manifests ignored",
            gitignore,
            ["benchmarks/*.local.json", "benchmarks/runs/"],
            ".gitignore",
        ),
        contains_all(
            "stage2_quality_regression",
            "quality gate run outputs do not pollute tracked fixtures or latest",
            run_quality_gate + "\n" + quality_test,
            ["should_generate_fixtures", "--regenerate-fixtures", "--no-update-latest", "write_latest_release_index", "Release test runs should not update latest"],
            "scripts/run_quality_gate.py; scripts/test_quality_gate.py",
        ),
        tracked_private_manifest_check,
    ]


def private_manifest_tracking_check() -> Check:
    try:
        completed = subprocess.run(
            ["git", "ls-files", "benchmarks/*.local.json", "benchmarks/runs"],
            cwd=PROJECT_DIR,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception as exc:  # pragma: no cover - defensive diagnostic path
        return Check(
            "stage2_quality_regression",
            "private manifests not tracked",
            False,
            "git ls-files benchmarks/*.local.json benchmarks/runs",
            f"unable to run git ls-files: {exc}",
        )
    tracked = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    return Check(
        "stage2_quality_regression",
        "private manifests not tracked",
        completed.returncode == 0 and not tracked,
        "git ls-files benchmarks/*.local.json benchmarks/runs",
        f"tracked={tracked}" if tracked else "no tracked private benchmark manifests or run outputs",
    )


def stage3_checks() -> list[Check]:
    batch = read_text("batch_convert_books.py")
    structure_test = read_text("scripts/test_structure_repair.py")
    image_test = read_text("scripts/test_image_book_rebuilder.py")
    agent_test = read_text("scripts/test_agent_fast_contract.py")
    return [
        contains_all(
            "stage3_pdf_image_quality",
            "PDF structural evidence sources",
            batch,
            ["pdf_outline_heading_candidates", "pymupdf_font_heading_candidates", "mineru_heading_candidates_from_artifacts"],
            "batch_convert_books.py",
        ),
        contains_all(
            "stage3_pdf_image_quality",
            "explainable structure repair",
            structure_test,
            ["decisions", "promoted_to_heading", "confidence", "Expected PyMuPDF font heading candidate"],
            "scripts/test_structure_repair.py",
        ),
        contains_all(
            "stage3_pdf_image_quality",
            "layer-heavy image strategy",
            image_test,
            ["layout-heavy", "paddleocr-vl", "qwen-vl", "mineru-vlm"],
            "scripts/test_image_book_rebuilder.py",
        ),
        contains_all(
            "stage3_pdf_image_quality",
            "recognition default over location index",
            agent_test,
            [
                "Unexpected process_material route",
                "Explicit rebuild intent should use image-book recognition",
                "Explicit locate intent should use location index",
                "Query process_material route should still use location index",
            ],
            "scripts/test_agent_fast_contract.py",
        ),
    ]


def stage4_checks() -> list[Check]:
    contract = read_text("docs/TOOL_CONTRACT.md")
    mcp = read_text("ebook_converter_mcp.py")
    latest_viewer = read_text("scripts/show_latest_quality_gate.py")
    latest_test = read_text("scripts/test_show_latest_quality_gate.py")
    recipes = {item.name for item in (PROJECT_DIR / "examples" / "agent-recipes").glob("*.md")}
    required_recipes = {
        "single-file-recognition.md",
        "batch-folder.md",
        "rerun-failed-or-review.md",
        "review-checklist.md",
        "docker-http-agent.md",
    }
    return [
        Check(
            "stage4_agent_productization",
            "agent recipe coverage",
            required_recipes.issubset(recipes),
            "examples/agent-recipes/",
            f"required={sorted(required_recipes)} actual={sorted(recipes)}",
        ),
        contains_all(
            "stage4_agent_productization",
            "three stable entrypoints",
            contract,
            ["CLI", "HTTP", "MCP", "process_material", "get_job_status", "read_artifact"],
            "docs/TOOL_CONTRACT.md",
        ),
        contains_all(
            "stage4_agent_productization",
            "health and contract context",
            mcp,
            ["config_sources", "local_env_exists", "local_env_loaded_keys", "pipeline_capabilities", "risk_status", "long_task_guidance", "online_provider_health"],
            "ebook_converter_mcp.py",
        ),
        contains_all(
            "stage4_agent_productization",
            "machine executable next actions",
            contract,
            ["next_actions", "tool", "arguments", "powershell_command", "overwrite=false"],
            "docs/TOOL_CONTRACT.md",
        ),
        contains_all(
            "stage4_agent_productization",
            "latest quality gate stale detection",
            mcp + "\n" + latest_viewer + "\n" + latest_test + "\n" + contract,
            ["artifact_status", "missing_artifacts", "stale", "missing_quality_gate_artifacts", "Expected stale artifact detection"],
            "ebook_converter_mcp.py; scripts/show_latest_quality_gate.py; scripts/test_show_latest_quality_gate.py; docs/TOOL_CONTRACT.md",
        ),
    ]


def stage5_checks() -> list[Check]:
    providers = read_text("online_providers.py")
    provider_test = read_text("scripts/test_online_providers.py")
    provider_evidence = providers + "\n" + provider_test
    config = read_text("config/online_providers.example.json")
    online_doc = read_text("docs/ONLINE_MODEL_API_INTEGRATION.md")
    return [
        contains_all(
            "stage5_online_api_abstraction",
            "provider interfaces",
            providers,
            ["OcrLayoutProvider", "VlmLayoutProvider", "TextStructureProvider", "EmbeddingProvider", "TableRepairProvider"],
            "online_providers.py",
        ),
        contains_all(
            "stage5_online_api_abstraction",
            "provider example config",
            config,
            ["openai_compatible_vlm", "openai_compatible_ocr", "openai_compatible_text", "openai_compatible_embedding", "openai_compatible_table"],
            "config/online_providers.example.json",
        ),
        contains_all(
            "stage5_online_api_abstraction",
            "fake provider tests",
            provider_evidence,
            ["fake_provider_for_type", "Fake OCR", "fake_embedding", "fake table", "assert_online_health_redacts_secrets"],
            "online_providers.py; scripts/test_online_providers.py",
        ),
        contains_all(
            "stage5_online_api_abstraction",
            "OpenAI-compatible remote safety",
            providers + "\n" + online_doc,
            ["OpenAI-compatible", "allow_remote", "model_mode=local", "api_key_env", "不会自动调用远程 API"],
            "online_providers.py; docs/ONLINE_MODEL_API_INTEGRATION.md",
        ),
    ]


def contains_all(stage: str, name: str, text: str, needles: list[str], evidence: str) -> Check:
    missing = [needle for needle in needles if needle not in text]
    return Check(stage, name, not missing, evidence, f"missing={missing}" if missing else f"matched={len(needles)}")


def build_payload(checks: list[Check]) -> dict[str, Any]:
    items = [check.to_dict() for check in checks]
    by_stage: dict[str, dict[str, int]] = {}
    for check in checks:
        stage = by_stage.setdefault(check.stage, {"passed": 0, "failed": 0, "total": 0})
        stage["total"] += 1
        if check.ok:
            stage["passed"] += 1
        else:
            stage["failed"] += 1
    failed = [item for item in items if not item["ok"]]
    return {
        "schema_version": SCHEMA_VERSION,
        "summary": {
            "status": "passed" if not failed else "failed",
            "passed": len(items) - len(failed),
            "failed": len(failed),
            "total": len(items),
            "by_stage": by_stage,
        },
        "checks": items,
        "next_actions": readiness_next_actions(failed),
    }


def readiness_next_actions(failed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not failed:
        return []
    return [
        {
            "action": "inspect_failed_readiness_checks",
            "failed_checks": [{"stage": item["stage"], "name": item["name"], "evidence": item["evidence"], "details": item["details"]} for item in failed],
            "reason": "Read the evidence files for failed readiness checks before claiming the five-stage goal is complete.",
        }
    ]


def write_reports(output: Path, payload: dict[str, Any]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "project-readiness.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "project-readiness.md").write_text(render_markdown(payload), encoding="utf-8")


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Project Readiness",
        "",
        f"- Schema: `{payload['schema_version']}`",
        f"- Status: {summary['status']}",
        f"- Passed: {summary['passed']}",
        f"- Failed: {summary['failed']}",
        f"- Total: {summary['total']}",
        "",
        "## Stages",
        "",
        "| Stage | Passed | Failed | Total |",
        "| --- | ---: | ---: | ---: |",
    ]
    for stage, counts in summary["by_stage"].items():
        lines.append(f"| {stage} | {counts['passed']} | {counts['failed']} | {counts['total']} |")
    lines.extend(["", "## Checks", "", "| Status | Stage | Check | Evidence | Details |", "| --- | --- | --- | --- | --- |"])
    for item in payload["checks"]:
        status = "ok" if item["ok"] else "failed"
        lines.append(f"| {status} | {item['stage']} | {item['name']} | `{item['evidence']}` | {escape_table(item.get('details') or '')} |")
    return "\n".join(lines).rstrip() + "\n"


def read_text(relative: str) -> str:
    return (PROJECT_DIR / relative).read_text(encoding="utf-8", errors="replace")


def load_json(relative: str) -> dict[str, Any]:
    return json.loads(read_text(relative))


def escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").replace("\r", " ")


if __name__ == "__main__":
    raise SystemExit(main())
