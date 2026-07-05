from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.ebook_converter_mcp import call_tool  # noqa: E402
from ebook_markdown_pipeline.format_baseline_matrix import build_format_baseline_matrix  # noqa: E402


def main() -> int:
    markitdown = report("sample.docx", "sample.md", "markitdown", "ok", "good", 90, 4, 1200)
    docling = report("sample.docx", "sample.md", "docling", "ok", "review", 70, 1, 1000)
    tika = {
        "tool": "tika",
        "status": "ok",
        "source": "sample.docx",
        "tika": {"status": "ok", "detected_mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "text_chars": 1100},
    }
    with tempfile.TemporaryDirectory(prefix="format-baseline-matrix-") as tmp:
        root = Path(tmp)
        paths = []
        for name, payload in [("markitdown.report.json", markitdown), ("docling.report.json", docling), ("tika.inspect.json", tika)]:
            path = root / name
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            paths.append(path)
        payload = build_format_baseline_matrix(paths)
        summary = payload["summary"]
        if summary.get("row_count") != 3 or summary.get("baseline_counts", {}).get("tika") != 1:
            raise AssertionError(f"Expected format baseline rows: {payload}")
        if (summary.get("best_available_baseline") or {}).get("baseline") != "markitdown":
            raise AssertionError(f"Expected MarkItDown as best baseline from quality score: {payload}")
        if "inspect_only_not_markdown_route" not in payload["rows"][-1].get("risks", []):
            raise AssertionError(f"Expected Tika inspect-only risk: {payload}")

        output = root / "matrix"
        completed = subprocess.run(
            [sys.executable, "-B", "scripts/build_format_baseline_matrix.py", "--source", str(paths[0]), "--source", str(paths[1]), "--source", str(paths[2]), "--output", str(output)],
            cwd=PROJECT_DIR,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=True,
        )
        cli_result = json.loads(completed.stdout)
        if cli_result.get("summary", {}).get("row_count") != 3 or not (output / "format-baseline-matrix.md").exists():
            raise AssertionError(f"Unexpected CLI matrix result: {cli_result}")

        agent_output = root / "agent-matrix"
        agent_result = call_tool("build_format_baseline_matrix", {"sources": [str(path) for path in paths], "output": str(agent_output)})
        if agent_result.get("status") != "ok" or (agent_result.get("summary") or {}).get("row_count") != 3:
            raise AssertionError(f"Unexpected agent matrix result: {agent_result}")
        read_result = call_tool("read_artifact", {"path": str(agent_output / "format-baseline-matrix.json"), "artifact_type": "format_baseline_matrix_json"})
        if (read_result.get("summary") or {}).get("kind") != "format_baseline_matrix":
            raise AssertionError(f"Expected read_artifact summary: {read_result}")
    print("Format baseline matrix artifact test passed.")
    return 0


def report(source: str, output: str, pipeline: str, status: str, level: str, score: int, headings: int, chars: int) -> dict:
    return {
        "source": source,
        "output": output,
        "status": status,
        "pipeline": pipeline,
        "detected_format": "DOCX",
        "output_exists": True,
        "output_size_bytes": chars,
        "duration_seconds": 1.0,
        "quality": {
            "level": level,
            "score": score,
            "headings": headings,
            "characters": chars,
            "short_line_ratio": 0.1,
            "page_number_lines": 0,
            "table_like_lines": 0,
            "reasons": [],
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
