from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_DIR / "scripts" / "table_to_xlsx_worker.py"


def run_worker(output: Path, extra_args: list[str]) -> dict:
    input_file = output / "input.png"
    input_file.parent.mkdir(parents=True, exist_ok=True)
    input_file.write_bytes(b"fake image")
    command = [
        sys.executable,
        str(SCRIPT),
        "--input",
        str(input_file),
        "--output",
        str(output / "run"),
        *extra_args,
    ]
    completed = subprocess.run(command, cwd=PROJECT_DIR, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"worker did not emit JSON:\nSTDOUT={completed.stdout}\nSTDERR={completed.stderr}") from exc
    if completed.returncode != 0 and payload.get("status") != "failed":
        raise AssertionError(f"worker failed unexpectedly:\nSTDOUT={completed.stdout}\nSTDERR={completed.stderr}")
    return payload


def assert_xlsx(path: Path, expected_text: str) -> None:
    if not path.exists():
        raise AssertionError(f"Expected XLSX artifact: {path}")
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        if "xl/worksheets/sheet1.xml" not in names or "xl/workbook.xml" not in names:
            raise AssertionError(f"Expected workbook parts in XLSX: {names}")
        sheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
        if expected_text not in sheet:
            raise AssertionError(f"Expected {expected_text!r} in worksheet: {sheet}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="table-to-xlsx-worker-") as tmp:
        root = Path(tmp)

        plan = run_worker(root / "plan", ["--mode", "plan"])
        if plan.get("status") != "planned" or plan.get("backend") != "table_to_xlsx":
            raise AssertionError(f"Unexpected plan payload: {plan}")

        fake = run_worker(root / "fake", ["--mode", "fake"])
        if fake.get("status") != "ok":
            raise AssertionError(f"Unexpected fake payload: {fake}")
        xlsx_artifact = next((item for item in fake.get("artifacts") or [] if item.get("type") == "table_xlsx"), None)
        if not xlsx_artifact:
            raise AssertionError(f"Expected table_xlsx artifact: {fake}")
        assert_xlsx(Path(xlsx_artifact["path"]), "fake")

        csv_path = root / "table.csv"
        csv_path.write_text("Name,Value\nA,42\n", encoding="utf-8")
        exported = run_worker(root / "csv", ["--mode", "execute", "--csv", str(csv_path)])
        if exported.get("status") != "ok" or (exported.get("metrics") or {}).get("row_count") != 2:
            raise AssertionError(f"Unexpected CSV export payload: {exported}")
        exported_xlsx = next((item for item in exported.get("artifacts") or [] if item.get("type") == "table_xlsx"), None)
        if not exported_xlsx:
            raise AssertionError(f"Expected exported XLSX artifact: {exported}")
        assert_xlsx(Path(exported_xlsx["path"]), "42")

        missing_img2table = run_worker(root / "missing-img2table", ["--mode", "execute", "--backend", "img2table"])
        if missing_img2table.get("status") != "failed" or not missing_img2table.get("warnings"):
            raise AssertionError(f"Expected missing img2table to fail cleanly: {missing_img2table}")

        gated_paddle = run_worker(root / "gated-paddle", ["--mode", "execute", "--backend", "paddle_table_v2"])
        if gated_paddle.get("status") != "failed" or not gated_paddle.get("warnings"):
            raise AssertionError(f"Expected PaddleOCR execute mode to be environment-gated: {gated_paddle}")

    print("table_to_xlsx worker test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
