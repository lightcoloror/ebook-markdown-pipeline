from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
RUNNER_PATH = PROJECT_DIR / "examples" / "agent-batch" / "agent_batch_http.py"
BUNDLE_PATH = PROJECT_DIR / "scripts" / "build_agent_handoff_bundle.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    runner = load_module("agent_batch_http_bundle_test", RUNNER_PATH)
    bundle_mod = load_module("build_agent_handoff_bundle", BUNDLE_PATH)
    with tempfile.TemporaryDirectory(prefix="agent-handoff-bundle-") as tmp:
        root = Path(tmp)
        result = {
            "id": "review",
            "status": "review",
            "input": "input.pdf",
            "output": "output.md",
            "artifacts": [],
            "job": {"quality_summary": {"review_count": 1, "review_items": [{"quality_level": "poor", "suggested_action": "compare pipelines"}]}},
        }
        report = runner.write_reports(root / "run-001", root / "manifest.json", 0.0, [result], partial=False)
        results_path = root / "run-001" / "agent-batch-results.json"
        bundle = bundle_mod.build_bundle(results_path)
        if bundle.get("schema_version") != "agent-handoff-bundle-v1" or bundle.get("handoff_ready") is not False:
            raise AssertionError(f"Expected review bundle to need attention: {bundle}")
        if bundle.get("contract_validation", {}).get("ok") is not True:
            raise AssertionError(f"Expected valid contract in handoff bundle: {bundle}")
        if not bundle.get("next_actions") or not bundle.get("review_items"):
            raise AssertionError(f"Expected next actions and review items in handoff bundle: {bundle}")
        out = root / "bundle"
        out.mkdir()
        (out / "agent-handoff-bundle.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        markdown = bundle_mod.render_bundle_markdown(bundle)
        if "Agent Handoff Bundle" not in markdown or "Contract validation: ok" not in markdown or "Needs attention: True" not in markdown:
            raise AssertionError(f"Expected readable handoff bundle markdown: {markdown}")
        newest = bundle_mod.newest_batch_results(root)
        if newest is None or newest.resolve() != results_path.resolve():
            raise AssertionError(f"Expected newest batch discovery: {newest}, report={report}")
    print("Agent handoff bundle smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
