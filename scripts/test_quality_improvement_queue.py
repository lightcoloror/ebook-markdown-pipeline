from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

from build_quality_improvement_queue import build_quality_improvement_queue  # noqa: E402


def main() -> int:
    payload = {
        "schema_version": "benchmark-run-v1",
        "created_at": "2026-06-22 10:00:00",
        "manifest": r"D:\private\samples.local.json",
        "output": r"D:\private\benchmarks\runs\full-real-current",
        "results": [
            {
                "id": "weak-pdf",
                "source": r"D:\private\weak.pdf",
                "category": "scanned_pdf",
                "status": "ok",
                "metrics": {
                    "level": "poor",
                    "score": 41,
                    "headings": 0,
                    "reasons": ["没有 Markdown 标题，章节层级可能缺失", "存在 HTML 标签残留"],
                },
                "conversion_results": [{"output": r"D:\private\weak.md", "report": r"D:\private\weak.report.json"}],
            },
            {
                "id": "good-ebook",
                "source": r"D:\private\good.epub",
                "category": "ebook",
                "metrics": {"level": "good", "score": 95, "headings": 12, "reasons": []},
            },
            {
                "id": "ocr-review",
                "source": r"D:\private\ocr.pdf",
                "category": "pdf",
                "status": "ok",
                "metrics": {
                    "level": "review",
                    "score": 72,
                    "headings": 2,
                    "short_line_ratio": 0.5,
                    "reasons": ["疑似 OCR 短行噪声"],
                },
            },
        ],
    }
    queue = build_quality_improvement_queue(payload)
    if queue["summary"]["count"] != 2:
        raise AssertionError(f"Expected two review/poor queue items: {queue}")
    categories = queue["summary"]["issue_categories"]
    if categories.get("weak_heading_structure") != 1 or categories.get("ocr_noise_or_linebreaks") != 1:
        raise AssertionError(f"Expected classified issue categories: {queue}")
    if "source" in queue["items"][0] or "D:\\private" in json.dumps(queue, ensure_ascii=False):
        raise AssertionError(f"Default queue output should redact private paths: {queue}")

    with tempfile.TemporaryDirectory(prefix="quality-queue-") as tmp:
        root = Path(tmp)
        input_path = root / "benchmark-results.json"
        output_dir = root / "queue"
        input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, "-B", "scripts/build_quality_improvement_queue.py", "--benchmark-results", str(input_path), "--output", str(output_dir)],
            cwd=PROJECT_DIR,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=True,
        )
        result = json.loads(completed.stdout)
        if result.get("count") != 2:
            raise AssertionError(f"Unexpected CLI queue result: {result}")
        if not (output_dir / "quality-improvement-queue.md").exists():
            raise AssertionError("Expected Markdown quality queue artifact.")

    print("Quality improvement queue test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

