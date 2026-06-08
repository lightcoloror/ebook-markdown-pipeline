from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ebook-quality-gate-") as tmp:
        root = Path(tmp)
        fixtures = root / "fixtures"
        output = root / "quality-run"
        run("generate_quality_fixtures.py", "--output", str(fixtures))
        minimal = json.loads((fixtures / "quality-minimal.json").read_text(encoding="utf-8"))
        full = json.loads((fixtures / "quality-full.json").read_text(encoding="utf-8"))
        if len(minimal.get("samples") or []) < 5:
            raise AssertionError(f"Expected minimal fixture samples: {minimal}")
        if len(full.get("samples") or []) <= len(minimal.get("samples") or []):
            raise AssertionError(f"Expected full profile to include extra OCR/image samples: {full}")
        paths = [str(item.get("path") or "") for item in full.get("samples") or []]
        if fixtures.resolve().is_relative_to(PROJECT_DIR) and any(Path(path).is_absolute() for path in paths):
            raise AssertionError(f"Repository fixture manifests must use repository-relative paths: {paths}")

        run(
            "run_quality_gate.py",
            "--profile",
            "minimal",
            "--fixtures-dir",
            str(fixtures),
            "--output",
            str(output),
            "--reuse-fixtures",
            "--sample-timeout",
            "60",
        )
        payload = json.loads((output / "benchmark-results.json").read_text(encoding="utf-8"))
        gates = ((payload.get("summary") or {}).get("quality_gates") or {})
        if gates.get("status") != "passed":
            raise AssertionError(f"Expected passing quality gate: {gates}")
        if not (output / "quality-regression-summary.md").exists():
            raise AssertionError("Expected quality-regression-summary.md")
    print("Quality gate smoke test passed.")
    return 0


def run(script: str, *args: str) -> None:
    subprocess.run([sys.executable, str(PROJECT_DIR / "scripts" / script), *args], cwd=PROJECT_DIR, check=True)


if __name__ == "__main__":
    raise SystemExit(main())
