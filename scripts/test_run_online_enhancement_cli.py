from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="run-online-enhancement-cli-") as tmp:
        root = Path(tmp)
        output = root / "out"
        structure = run_cli(
            "text_structure",
            "--input-text",
            "Title\n\nBody",
            "--output",
            str(output),
        )
        if structure.get("status") != "ok" or not (structure.get("result") or {}).get("markdown", "").startswith("# Title"):
            raise AssertionError(f"Expected fake structure enhancement: {structure}")
        artifact_paths = [Path(item.get("path") or "") for item in structure.get("artifacts") or []]
        if not artifact_paths or not all(path.exists() for path in artifact_paths):
            raise AssertionError(f"Expected persisted CLI artifacts: {structure}")

        embedding = run_cli("embedding", "--input-texts", "alpha", "beta")
        vectors = (embedding.get("result") or {}).get("vectors") or []
        if embedding.get("status") != "ok" or len(vectors) != 2:
            raise AssertionError(f"Expected fake embedding vectors: {embedding}")

        blocked = run_cli(
            "text_structure",
            "--input-text",
            "Title",
            "--provider-mode",
            "openai_compatible",
            expect_code=1,
        )
        if blocked.get("error") is not True or "model_mode=local" not in blocked.get("message", ""):
            raise AssertionError(f"Expected local mode to block remote provider: {blocked}")
    print("Run online enhancement CLI smoke test passed.")
    return 0


def run_cli(*args: str, expect_code: int = 0) -> dict:
    completed = subprocess.run(
        [sys.executable, "-B", str(PROJECT_DIR / "scripts" / "run_online_enhancement.py"), *args],
        cwd=str(PROJECT_DIR),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if completed.returncode != expect_code:
        raise AssertionError(
            f"Unexpected return code {completed.returncode}, expected {expect_code}.\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return json.loads(completed.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
