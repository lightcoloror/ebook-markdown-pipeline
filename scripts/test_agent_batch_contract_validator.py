from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
RUNNER_PATH = PROJECT_DIR / "examples" / "agent-batch" / "agent_batch_http.py"
VALIDATOR_PATH = PROJECT_DIR / "scripts" / "validate_agent_batch_contract.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    runner = load_module("agent_batch_http_validator_test", RUNNER_PATH)
    validator = load_module("validate_agent_batch_contract", VALIDATOR_PATH)

    with tempfile.TemporaryDirectory(prefix="agent-batch-contract-validator-") as tmp:
        root = Path(tmp)
        result = {
            "id": "ok",
            "status": "ok",
            "input": "input.txt",
            "output": "output.md",
            "artifacts": [],
        }
        report = runner.write_reports(root / "reports", root / "manifest.json", 0.0, [result], partial=False)
        if report.get("contract_validation", {}).get("ok") is not True:
            raise AssertionError(f"Expected report to include self-validation: {report}")
        validation = validator.validate_payload(report, root / "reports" / "agent-batch-results.json")
        if not validation.get("ok") or validation.get("payload_kind") != "results":
            raise AssertionError(f"Expected valid agent batch results contract: {validation}")

        plan = runner.write_plan(
            root / "plan",
            root / "manifest.json",
            {"jobs": [{"id": "ok", "input": "input.txt", "output": "out"}]},
            runner.validate_manifest({"jobs": [{"id": "ok", "input": "input.txt", "output": "out"}]}),
        )
        if plan.get("contract_validation", {}).get("ok") is not True:
            raise AssertionError(f"Expected plan to include self-validation: {plan}")
        plan_validation = validator.validate_payload(plan, root / "plan" / "agent-batch-plan.json")
        if not plan_validation.get("ok") or plan_validation.get("payload_kind") != "plan":
            raise AssertionError(f"Expected valid agent batch plan contract: {plan_validation}")

        broken = dict(report)
        broken["contract"] = {"schema_version": "wrong"}
        broken_validation = validator.validate_payload(broken)
        if broken_validation.get("ok") or not broken_validation.get("errors"):
            raise AssertionError(f"Expected broken contract validation to fail: {broken_validation}")

    print("Agent batch contract validator smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
