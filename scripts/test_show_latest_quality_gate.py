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
        payload = {
            "schema_version": "quality-gate-release-v1",
            "output": str(root / "run"),
            "regression_tags": ["duration_regression"],
            "summary": {"status": "passed", "failed_steps": []},
            "steps": [{"name": "minimal", "status": "passed", "exit_code": 0, "report": str(root / "run" / "minimal.md")}],
        }
        (module.LATEST_DIR / "release-index.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        latest = module.load_latest_release()
        if not latest.get("found") or latest.get("payload", {}).get("summary", {}).get("status") != "passed":
            raise AssertionError(f"Expected latest release payload: {latest}")
        markdown = module.render_markdown(latest)
        if "Latest Quality Gate" not in markdown or "minimal" not in markdown or "duration_regression" not in markdown:
            raise AssertionError(f"Expected readable latest quality gate markdown: {markdown}")
    print("Latest quality gate viewer smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
