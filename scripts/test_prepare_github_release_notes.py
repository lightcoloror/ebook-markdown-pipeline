from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]


def load_module():
    path = PROJECT_DIR / "scripts" / "prepare_github_release_notes.py"
    spec = importlib.util.spec_from_file_location("prepare_github_release_notes", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load prepare_github_release_notes.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    module = load_module()
    changelog = module.extract_unreleased_changelog(PROJECT_DIR / "CHANGELOG.md")
    if "Added" not in changelog or not any("enhance_job_artifact" in item for item in changelog["Added"]):
        raise AssertionError(f"Expected changelog extraction to include enhance_job_artifact: {changelog}")

    with tempfile.TemporaryDirectory(prefix="release-notes-") as tmp:
        root = Path(tmp)
        report = root / "minimal.md"
        report.write_text("# Minimal\n", encoding="utf-8")
        release_dir = root / "release"
        release_dir.mkdir()
        slash = chr(92)
        private_output = f"D:{slash}private{slash}quality-gate{slash}run"
        payload = {
            "schema_version": "quality-gate-release-v1",
            "profile": "release",
            "output": private_output,
            "regression_tags": ["duration_regression"],
            "summary": {"status": "passed", "failed_steps": []},
            "steps": [{"name": "minimal", "status": "passed", "exit_code": 0, "report": str(report)}],
        }
        summary_path = release_dir / "release-summary.json"
        summary_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        quality = module.load_quality_gate(summary_path)
        notes = module.render_release_notes(
            version="v0.2.0-rc1",
            title="v0.2.0-rc1 - test",
            changelog=changelog,
            quality_gate=quality,
            include_local_paths=False,
        )
        if "v0.2.0-rc1 - test" not in notes or "duration_regression" not in notes or "enhance_job_artifact" not in notes:
            raise AssertionError(f"Expected generated release notes content: {notes}")
        if private_output in notes or str(summary_path) in notes:
            raise AssertionError(f"Public release notes should redact local paths: {notes}")
        redacted = module.redact_local_paths(f"artifact {private_output}")
        if private_output in redacted or "<local path>" not in redacted:
            raise AssertionError(f"Expected explicit redaction helper to hide local paths: {redacted}")

        local_notes = module.render_release_notes(
            version="v0.2.0-rc1",
            title="v0.2.0-rc1 - test",
            changelog=changelog,
            quality_gate=quality,
            include_local_paths=True,
        )
        if private_output not in local_notes or str(summary_path) not in local_notes:
            raise AssertionError(f"Local release notes should include paths when requested: {local_notes}")

    print("GitHub release notes generator smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
