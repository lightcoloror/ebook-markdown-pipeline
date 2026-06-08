from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="enhance-markdown-structure-cli-") as tmp:
        root = Path(tmp)
        source = root / "weak.md"
        output = root / "out"
        source.write_text(
            "第一章 总则\n\n"
            "第五条 保险责任\n\n"
            "（一）旅游意外身故\n\n"
            "被保险人自遭受该意外之日起一百八十日内以该意外为直接、完全原因而身故。\n",
            encoding="utf-8",
            newline="\n",
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                str(PROJECT_DIR / "scripts" / "enhance_markdown_structure.py"),
                str(source),
                str(output),
            ],
            cwd=str(PROJECT_DIR),
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(f"CLI failed:\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}")
        payload = json.loads(completed.stdout)
        markdown = Path(payload.get("output") or "")
        report = Path(payload.get("report") or "")
        review_report = Path(payload.get("review_report") or "")
        if not markdown.exists() or not report.exists() or not review_report.exists():
            raise AssertionError(f"Expected CLI artifacts to exist: {payload}")
        text = markdown.read_text(encoding="utf-8")
        if "### 第五条" not in text or "#### （一）旅游意外身故" not in text:
            raise AssertionError(f"Expected repaired Markdown hierarchy:\n{text}")
        report_payload = json.loads(report.read_text(encoding="utf-8"))
        if report_payload.get("schema_version") != "markdown-structure-enhancement-v1":
            raise AssertionError(f"Expected report schema: {report_payload}")
        if not (report_payload.get("local_structure_repair") or {}).get("decisions"):
            raise AssertionError(f"Expected local structure decisions: {report_payload}")
        if markdown == source:
            raise AssertionError(f"CLI must not overwrite source: {payload}")
    print("Enhance Markdown structure CLI smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
