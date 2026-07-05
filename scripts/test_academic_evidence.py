from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.academic_evidence import build_academic_evidence  # noqa: E402
from ebook_markdown_pipeline.ebook_converter_mcp import call_tool  # noqa: E402


def main() -> int:
    grobid = {
        "status": "ok",
        "tool": "grobid",
        "title": "Academic Parsing Test",
        "authors": ["Ada Lovelace"],
        "author_count": 1,
        "doi": "10.1234/example",
        "year": "2026",
        "abstract_sample": "This paper validates academic evidence.",
        "reference_count": 2,
        "section_headings": ["Introduction", "Method"],
        "tei_chars": 2048,
    }
    formulas = {
        "schema_version": "formula-candidates-v1",
        "backend": "pix2text",
        "status": "review",
        "pages": [{"page": 1, "formulas": [{"latex": "x^2", "bbox": [1, 2, 3, 4], "confidence": 0.9, "source": "page-1.png"}]}],
    }
    with tempfile.TemporaryDirectory(prefix="academic-evidence-") as tmp:
        root = Path(tmp)
        grobid_path = root / "grobid.json"
        formula_path = root / "formula-candidates.json"
        grobid_path.write_text(json.dumps(grobid, ensure_ascii=False), encoding="utf-8")
        formula_path.write_text(json.dumps(formulas, ensure_ascii=False), encoding="utf-8")
        payload = build_academic_evidence([grobid_path, formula_path])
        summary = payload["summary"]
        if summary.get("reference_count") != 2 or summary.get("formula_count") != 1:
            raise AssertionError(f"Expected academic/formula summary: {payload}")
        if payload["policy"]["remote_calls"] != "not_performed_by_this_artifact_builder":
            raise AssertionError(f"Expected no remote-call policy: {payload}")

        output = root / "academic"
        completed = subprocess.run(
            [sys.executable, "-B", "scripts/build_academic_evidence.py", "--source", str(grobid_path), "--source", str(formula_path), "--output", str(output)],
            cwd=PROJECT_DIR,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=True,
        )
        cli_result = json.loads(completed.stdout)
        if cli_result.get("summary", {}).get("doi_count") != 1 or not (output / "academic-evidence.md").exists():
            raise AssertionError(f"Unexpected academic evidence CLI result: {cli_result}")

        agent_output = root / "agent-academic"
        agent_result = call_tool("build_academic_evidence", {"sources": [str(grobid_path), str(formula_path)], "output": str(agent_output)})
        if agent_result.get("status") != "ok" or (agent_result.get("summary") or {}).get("formula_count") != 1:
            raise AssertionError(f"Unexpected academic evidence tool result: {agent_result}")
        read_result = call_tool("read_artifact", {"path": str(agent_output / "academic-evidence.json"), "artifact_type": "academic_evidence_json"})
        if (read_result.get("summary") or {}).get("kind") != "academic_evidence":
            raise AssertionError(f"Expected academic evidence summary: {read_result}")

    print("Academic evidence artifact test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
