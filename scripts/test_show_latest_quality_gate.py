from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]


def load_module():
    spec = importlib.util.spec_from_file_location("show_latest_quality_gate", PROJECT_DIR / "scripts" / "show_latest_quality_gate.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load show_latest_quality_gate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    module = load_module()
    with tempfile.TemporaryDirectory(prefix="latest-quality-gate-") as tmp:
        root = Path(tmp)
        module.LATEST_DIR = root / "latest"
        module.QUALITY_GATE_DIR = root / "quality-gate"
        missing = module.load_latest_release()
        if missing.get("found"):
            raise AssertionError(f"Expected missing latest quality gate: {missing}")

        module.LATEST_DIR.mkdir(parents=True)
        run_dir = root / "run"
        run_dir.mkdir()
        report = run_dir / "minimal.md"
        report.write_text("# Minimal\n", encoding="utf-8")
        payload = {
            "schema_version": "quality-gate-release-v1",
            "output": str(run_dir),
            "regression_tags": ["duration_regression"],
            "summary": {"status": "passed", "failed_steps": []},
            "steps": [{"name": "minimal", "status": "passed", "exit_code": 0, "report": str(report)}],
        }
        (module.LATEST_DIR / "release-index.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        latest = module.load_latest_release()
        if not latest.get("found") or latest.get("payload", {}).get("summary", {}).get("status") != "passed":
            raise AssertionError(f"Expected latest release payload: {latest}")
        if latest.get("artifact_status") != "ok" or latest.get("missing_artifacts"):
            raise AssertionError(f"Expected valid latest artifacts: {latest}")
        markdown = module.render_markdown(latest)
        if "Latest Quality Gate" not in markdown or "minimal" not in markdown or "duration_regression" not in markdown or "Artifact status: ok" not in markdown:
            raise AssertionError(f"Expected readable latest quality gate markdown: {markdown}")

        stale_payload = dict(payload)
        stale_payload["output"] = str(root / "missing-run")
        stale_payload["steps"] = [{"name": "minimal", "status": "passed", "exit_code": 0, "report": str(root / "missing-run" / "minimal.md")}]
        (module.LATEST_DIR / "release-index.json").write_text(json.dumps(stale_payload, ensure_ascii=False), encoding="utf-8")
        stale = module.load_latest_release()
        if stale.get("artifact_status") != "stale" or len(stale.get("missing_artifacts") or []) != 2:
            raise AssertionError(f"Expected stale artifact detection: {stale}")
        stale_markdown = module.render_markdown(stale)
        if "Artifact status: stale" not in stale_markdown or "Missing Artifacts" not in stale_markdown:
            raise AssertionError(f"Expected stale Markdown warning: {stale_markdown}")
    print("Latest quality gate viewer smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
