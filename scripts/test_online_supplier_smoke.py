from __future__ import annotations

import shutil
import sys
from pathlib import Path
from uuid import uuid4


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

from run_online_supplier_smoke import run_supplier_smoke  # noqa: E402


def main() -> int:
    output = PROJECT_DIR / f".tmp-online-supplier-smoke-test-{uuid4().hex[:8]}"
    try:
        planned = run_supplier_smoke(output / "plan", provider_mode="fake", execute=False)
        if planned.get("status") != "planned" or planned.get("pipeline", {}).get("status") != "planned":
            raise AssertionError(f"Supplier smoke plan made an unexpected transition: {planned}")
        if planned.get("stage_assertions"):
            raise AssertionError("Planning must not claim stage execution evidence.")

        executed = run_supplier_smoke(
            output / "fake-execute",
            provider_mode="fake",
            execute=True,
            max_estimated_cost_usd=0.01,
        )
        if executed.get("status") != "passed":
            raise AssertionError(f"Fake supplier smoke did not pass all stages: {executed}")
        if not all(item.get("passed") for item in executed.get("stage_assertions") or []):
            raise AssertionError(f"Fake supplier smoke stage evidence is incomplete: {executed}")
        remote_evidence = [
            (item.get("evidence") or {}).get("remote_requests_made")
            for item in executed.get("stage_assertions") or []
        ]
        if any(
            any(bool(value) for value in evidence) if isinstance(evidence, list) else bool(evidence)
            for evidence in remote_evidence
        ):
            raise AssertionError("Fake supplier smoke must not report a remote request.")

        guarded = run_supplier_smoke(
            output / "guard",
            provider_mode="vkp_shared",
            execute=True,
            confirm_data_export=False,
            max_estimated_cost_usd=0.01,
        )
        if guarded.get("status") != "failed":
            raise AssertionError(f"Unconfirmed shared supplier smoke did not fail closed: {guarded}")
        pipeline = guarded.get("pipeline") or {}
        if pipeline.get("code") != "data_export_confirmation_required" or pipeline.get("remote_requests_made") is not False:
            raise AssertionError(f"Supplier smoke guard drifted: {pipeline}")

        for payload in (planned, executed, guarded):
            run_dir = Path(payload["run_root"])
            if not (run_dir / "online-supplier-smoke.json").is_file():
                raise AssertionError(f"Missing supplier smoke JSON artifact: {run_dir}")
            if not (run_dir / "online-supplier-smoke.md").is_file():
                raise AssertionError(f"Missing supplier smoke Markdown artifact: {run_dir}")
        print("Online supplier smoke contract test passed.")
        return 0
    finally:
        shutil.rmtree(output, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
