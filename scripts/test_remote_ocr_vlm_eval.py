from __future__ import annotations

import json
import subprocess
import sys
import shutil
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]


def main() -> int:
    root = PROJECT_DIR / ".tmp-tests" / "remote-ocr-vlm-eval-test"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    try:
        output = root / "dry"
        dry = run_cli("--output", str(output))
        if dry.get("status") != "planned" or dry.get("result_count") != 1:
            raise AssertionError(f"Expected dry-run planned result: {dry}")
        dry_payload = json.loads((output / "remote-ocr-vlm-eval.json").read_text(encoding="utf-8"))
        if dry_payload.get("remote_call_enabled") is not False:
            raise AssertionError(f"Dry run must not enable remote calls: {dry_payload}")

        fake_output = root / "fake"
        fake = run_cli("--execute", "--fake", "--output", str(fake_output))
        if fake.get("status") != "ok":
            raise AssertionError(f"Expected fake execution ok: {fake}")
        fake_payload = json.loads((fake_output / "remote-ocr-vlm-eval.json").read_text(encoding="utf-8"))
        result = (fake_payload.get("results") or [])[0]
        if result.get("status") != "ok" or (result.get("quality_hints") or {}).get("markdown_chars", 0) <= 0:
            raise AssertionError(f"Expected fake markdown quality hints: {fake_payload}")

        blocked_output = root / "blocked"
        blocked = run_cli("--execute", "--output", str(blocked_output), expect_code=1)
        if blocked.get("status") != "failed":
            raise AssertionError(f"Expected remote execution without allow flag to fail safely: {blocked}")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("Remote OCR/VLM eval contract test passed.")
    return 0


def run_cli(*args: str, expect_code: int = 0) -> dict:
    completed = subprocess.run(
        [sys.executable, "-B", str(PROJECT_DIR / "scripts" / "run_remote_ocr_vlm_eval.py"), *args],
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
