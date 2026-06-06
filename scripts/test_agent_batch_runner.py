from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
RUNNER_PATH = PROJECT_DIR / "examples" / "agent-batch" / "agent_batch_http.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("agent_batch_http", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load runner: {RUNNER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    runner = load_runner()
    with tempfile.TemporaryDirectory(prefix="agent-batch-runner-") as tmp:
        root = Path(tmp)
        visual_check = root / "archive" / "visual_check"
        visual_check.mkdir(parents=True)
        result_path = visual_check / "visual_check_result.json"
        result_path.write_text(json.dumps({"schema_version": 1, "status": "pending_visual_engine"}), encoding="utf-8")
        layout_path = visual_check / "layout_ocr.md"
        layout_path.write_text("# Visual OCR Pending\n", encoding="utf-8")

        seen_material_args: list[dict[str, Any]] = []

        def fake_call_tool(args: argparse.Namespace, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            if name == "process_material":
                seen_material_args.append(dict(arguments))
                return {
                    "status": "routed",
                    "route": "process_web_archive",
                    "delegated": {
                        "status": "pending_visual_engine",
                        "artifacts": [
                            {"type": "visual_check_json", "path": str(result_path)},
                            {"type": "markdown", "path": str(layout_path)},
                            {"type": "markdown", "path": str(visual_check / "missing.md")},
                        ],
                        "next_actions": [
                            {
                                "tool": "read_artifact",
                                "arguments": {"path": str(result_path), "artifact_type": "visual_check_json"},
                            }
                        ],
                    },
                }
            if name == "read_artifact":
                path = Path(arguments["path"])
                payload = {
                    "path": str(path),
                    "artifact_type": arguments.get("artifact_type"),
                    "text": path.read_text(encoding="utf-8"),
                }
                if arguments.get("artifact_type") == "visual_check_json":
                    payload["json"] = json.loads(path.read_text(encoding="utf-8"))
                return payload
            raise AssertionError(f"Unexpected fake tool call: {name}")

        runner.call_tool = fake_call_tool
        args = argparse.Namespace(artifact_max_chars=4000, artifact_max_lines=120, rerun_mode="as-manifest")
        result = runner.run_manifest_job(
            args,
            {},
            {"id": "archive", "input": str(root / "archive"), "output": str(root / "out")},
            1,
        )
        if result.get("status") != "review":
            raise AssertionError(f"Expected pending visual archive to become review status: {result}")
        artifacts = result.get("artifacts") or []
        if len(artifacts) != 3 or sum(1 for item in artifacts if item.get("status") == "ok") != 2 or sum(1 for item in artifacts if item.get("status") == "failed") != 1:
            raise AssertionError(f"Expected readable synchronous artifacts plus one read failure: {result}")
        summary = runner.summarize([result])
        if summary.get("review") != 1 or summary.get("failed") != 0 or summary.get("hard_failed") != 0 or summary.get("artifact_reads") != 2:
            raise AssertionError(f"Expected review status to be non-failed but artifact-readable: {summary}")
        artifact_summary = runner.summarize_artifacts([result])
        if artifact_summary.get("ok") != 2 or artifact_summary.get("failed") != 1 or artifact_summary.get("type_counts", {}).get("markdown") != 2:
            raise AssertionError(f"Expected top-level artifact read summary: {artifact_summary}")
        report_payload = runner.write_reports(root / "reports", root / "manifest.json", 0.0, [result], partial=False)
        if report_payload.get("artifact_summary", {}).get("failed") != 1:
            raise AssertionError(f"Expected artifact_summary in report payload: {report_payload}")
        report_action_names = {item.get("action") for item in report_payload.get("next_actions") or []}
        if not {"read_run_summary", "inspect_agent_batch_results", "inspect_failed_artifacts", "inspect_review_items"}.issubset(report_action_names):
            raise AssertionError(f"Expected handoff next actions in report payload: {report_payload}")
        if not (root / "reports" / "run_summary.md").exists():
            raise AssertionError(f"Expected run_summary.md to be written: {report_payload}")
        if "Artifact read failures: 1" not in (root / "reports" / "run_summary.md").read_text(encoding="utf-8"):
            raise AssertionError(f"Expected artifact read failures in run_summary.md: {report_payload}")

        previous_payload = {
            "results": [
                {
                    "id": "archive",
                    "status": "review",
                    "job": {
                        "quality_summary": {
                            "review_items": [
                                {
                                    "next_actions": [
                                        {"action": "rerun", "pipeline": "pymupdf4llm"},
                                    ]
                                }
                            ]
                        }
                    },
                },
                {"id": "ok-job", "status": "ok"},
            ]
        }
        selected = runner.select_jobs(
            [{"id": "archive", "input": str(root / "archive"), "output": str(root / "out")}, {"id": "ok-job", "input": "x", "output": "y"}],
            previous_payload,
            "review",
        )
        if [item.get("id") for item in selected] != ["archive"]:
            raise AssertionError(f"Expected only review job to be selected: {selected}")

        selected_ids = runner.selected_job_ids(
            [{"input": str(root / "skip"), "output": str(root / "skip-out")}, {"input": str(root / "anon"), "output": str(root / "anon-out")}],
            {"results": [{"id": "job-2", "status": "review"}]},
            "review",
        )
        if selected_ids != ["job-2"]:
            raise AssertionError(f"Expected original anonymous job id to be preserved: {selected_ids}")

        previous_dir = root / "batch-runs" / "run-001"
        next_dir = root / "batch-runs" / "run-002"
        previous_dir.mkdir(parents=True)
        next_dir.mkdir(parents=True)
        previous_path = previous_dir / "agent-batch-results.json"
        previous_path.write_text(json.dumps(previous_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        discovered = runner.resolve_previous_results_path(None, root / "manifest.json", next_dir, "failed-or-review")
        if discovered != previous_path:
            raise AssertionError(f"Expected previous results auto-discovery: {discovered}")
        discovered_payload = runner.load_previous_results(discovered)
        validation = runner.validate_manifest(
            {
                "jobs": [
                    {"id": "archive", "input": str(root / "archive"), "output": str(root / "out")},
                    {"id": "ok-job", "input": "x", "output": "y"},
                ]
            },
            previous_payload=discovered_payload,
            select="failed-or-review",
            previous_results_path=discovered,
        )
        if validation.get("selected_job_ids") != ["archive"] or validation.get("previous_results") != str(previous_path):
            raise AssertionError(f"Expected auto-discovered previous results to drive selection: {validation}")
        selection = runner.build_selection_summary(
            select="failed-or-review",
            rerun_mode="recommended",
            previous_results_path=previous_path,
            selected_job_ids=validation["selected_job_ids"],
            selected_count=1,
            manifest_job_count=2,
        )
        if selection.get("selection_ratio") != 0.5 or selection.get("previous_results") != str(previous_path):
            raise AssertionError(f"Expected machine-readable selection summary: {selection}")

        args.rerun_mode = "recommended"
        runner.run_manifest_job(
            args,
            {},
            {"id": "archive", "input": str(root / "archive"), "output": str(root / "out")},
            1,
            previous_payload=previous_payload,
        )
        if seen_material_args[-1].get("pdf_pipeline_mode") != "pymupdf4llm":
            raise AssertionError(f"Expected recommended rerun pipeline to be applied: {seen_material_args[-1]}")

        nested_suggestion = {
            "id": "pdf-review",
            "status": "review",
            "job": {
                "quality_summary": {
                    "review_items": [
                        {
                            "suggested_action": "建议用 Umi-OCR 重跑疑难页",
                        }
                    ]
                }
            },
        }
        if runner.extract_recommended_arguments(nested_suggestion) != {"pdf_pipeline_mode": "umi"}:
            raise AssertionError("Expected nested review suggested_action to choose umi pipeline")

        compare_suggestion = {
            "id": "pdf-compare",
            "status": "review",
            "job": {
                "quality_summary": {
                    "review_items": [
                        {
                            "suggested_action": "PDF对比建议重跑 / Compare with MinerU or Umi-OCR",
                        }
                    ]
                }
            },
        }
        if runner.extract_recommended_arguments(compare_suggestion) != {"pdf_pipeline_mode": "auto"}:
            raise AssertionError("Expected compare suggestions to keep pdf pipeline in auto mode")

        plan_payload = runner.write_plan(
            root / "plans",
            root / "manifest.json",
            {
                "jobs": [
                    {"id": "archive", "input": str(root / "archive"), "output": str(root / "out")},
                    {"id": "ok-job", "input": "x", "output": "y"},
                ]
            },
            runner.validate_manifest(
                {
                    "jobs": [
                        {"id": "archive", "input": str(root / "archive"), "output": str(root / "out")},
                        {"id": "ok-job", "input": "x", "output": "y"},
                    ]
                },
                previous_payload=previous_payload,
                select="review",
            ),
        )
        plan_text = (root / "plans" / "agent-batch-plan.md").read_text(encoding="utf-8")
        if plan_payload.get("selection", {}).get("selected_count") != 1 or "Selected jobs: 1/2: archive" not in plan_text:
            raise AssertionError(f"Expected selected job count in plan markdown: {plan_payload}")

        baseline_agent_batch = root / "baseline-agent-batch.json"
        candidate_agent_batch = root / "candidate-agent-batch.json"
        baseline_agent_batch.write_text(
            json.dumps(
                {
                    "schema_version": "agent-batch-v1",
                    "results": [
                        {"id": "ok", "status": "ok", "job": {"quality_summary": {"counts": {"good": 1}, "review_count": 0}}},
                        {"id": "review", "status": "review", "job": {"quality_summary": {"counts": {"review": 1}, "review_count": 1}}},
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        candidate_agent_batch.write_text(
            json.dumps(
                {
                    "schema_version": "agent-batch-v1",
                    "results": [
                        {"id": "ok", "status": "ok", "job": {"quality_summary": {"counts": {"good": 1}, "review_count": 0}}},
                        {"id": "ok2", "status": "ok", "job": {"quality_summary": {"counts": {"good": 1}, "review_count": 0}}},
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        comparison = runner.write_quality_comparison(root / "quality-agent-batch", baseline_agent_batch, candidate_agent_batch)
        if comparison.get("status") != "passed" or not Path(comparison.get("json", "")).exists() or not Path(comparison.get("markdown", "")).exists():
            raise AssertionError(f"Expected passing agent batch quality comparison artifacts: {comparison}")
        comparison_actions = runner.quality_comparison_next_actions(
            comparison,
            manifest=root / "manifest.json",
            current_results=root / "quality-agent-batch" / "agent-batch-results.json",
            suggested_output=root / "quality-agent-batch-rerun",
        )
        comparison_action_names = {item.get("action") for item in comparison_actions}
        if not {"read_quality_comparison", "read_quality_comparison_json"}.issubset(comparison_action_names):
            raise AssertionError(f"Expected readable quality comparison next actions: {comparison_actions}")
        summary_text = runner.render_run_summary(
            {
                "created_at": "now",
                "manifest": "manifest.json",
                "summary": runner.summarize([result]),
                "results": [result],
                "quality_comparison": comparison,
                "next_actions": comparison_actions,
            }
        )
        if "Quality comparison: passed" not in summary_text or "read_quality_comparison" not in summary_text:
            raise AssertionError(f"Expected quality comparison in run summary: {summary_text}")
        selected_summary_text = runner.render_run_summary(
            {
                "created_at": "now",
                "manifest": "manifest.json",
                "selection": selection,
                "summary": runner.summarize([result]),
                "results": [result],
            }
        )
        if "Select: failed-or-review" not in selected_summary_text or "Selected jobs: 1/2" not in selected_summary_text:
            raise AssertionError(f"Expected selection summary in run summary: {selected_summary_text}")
        regressed_agent_batch = root / "regressed-agent-batch.json"
        regressed_agent_batch.write_text(
            json.dumps(
                {
                    "schema_version": "agent-batch-v1",
                    "results": [
                        {"id": "failed", "status": "failed", "job": {"quality_summary": {"counts": {"failed": 1}, "review_count": 0}}},
                        {"id": "review", "status": "review", "job": {"quality_summary": {"counts": {"poor": 1}, "review_count": 1}}},
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        failed_comparison = runner.write_quality_comparison(root / "quality-agent-batch-failed", candidate_agent_batch, regressed_agent_batch)
        failed_actions = runner.quality_comparison_next_actions(
            failed_comparison,
            manifest=root / "manifest.json",
            current_results=root / "quality-agent-batch-failed" / "agent-batch-results.json",
            suggested_output=root / "quality-agent-batch-failed-rerun",
        )
        rerun_action = next((item for item in failed_actions if item.get("action") == "rerun_failed_or_review"), {})
        if failed_comparison.get("status") != "failed" or not rerun_action:
            raise AssertionError(f"Expected failed quality comparison to suggest safe rerun: {failed_comparison}, {failed_actions}")
        if "--select failed-or-review" not in rerun_action.get("powershell_command", "") or not rerun_action.get("command_args", {}).get("previous_results"):
            raise AssertionError(f"Expected failed comparison rerun command and args: {rerun_action}")
        failed_summary_text = runner.render_run_summary(
            {
                "created_at": "now",
                "manifest": "manifest.json",
                "summary": runner.summarize([result]),
                "results": [result],
                "quality_comparison": failed_comparison,
                "next_actions": failed_actions,
            }
        )
        if "## Recommended Rerun" not in failed_summary_text or "--rerun-mode recommended" not in failed_summary_text:
            raise AssertionError(f"Expected recommended rerun command in run summary: {failed_summary_text}")

    print("Agent batch runner smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
