from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.document_intelligence_blocks import build_document_intelligence_blocks  # noqa: E402
from ebook_markdown_pipeline.ebook_converter_mcp import call_tool  # noqa: E402


def main() -> int:
    table = {
        "schema_version": "table-candidates-v1",
        "pages": [{"page": 1, "tables": [{"bbox": [0, 0, 10, 10], "confidence": 0.9, "cells": [{"text": "A", "bbox": [0, 0, 5, 5]}]}]}],
    }
    formula = {
        "schema_version": "formula-candidates-v1",
        "pages": [{"page": 1, "formulas": [{"latex": "x^2", "bbox": [1, 2, 3, 4], "confidence": 0.8, "source": "p1.png"}]}],
    }
    with tempfile.TemporaryDirectory(prefix="document-intelligence-blocks-") as tmp:
        root = Path(tmp)
        table_path = root / "table-candidates.json"
        formula_path = root / "formula-candidates.json"
        table_path.write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
        formula_path.write_text(json.dumps(formula, ensure_ascii=False), encoding="utf-8")
        payload = build_document_intelligence_blocks([table_path, formula_path])
        summary = payload["summary"]
        if summary.get("block_count") != 3 or summary.get("relationship_count") != 1:
            raise AssertionError(f"Expected normalized table/cell/formula blocks: {payload}")
        if payload["policy"]["cloud_calls"] != "not_performed_by_this_builder":
            raise AssertionError(f"Expected no cloud-call policy: {payload}")

        output = root / "blocks"
        completed = subprocess.run(
            [sys.executable, "-B", "scripts/build_document_intelligence_blocks.py", "--source", str(table_path), "--source", str(formula_path), "--output", str(output)],
            cwd=PROJECT_DIR,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=True,
        )
        cli_result = json.loads(completed.stdout)
        if cli_result.get("summary", {}).get("relationship_count") != 1 or not (output / "document-intelligence-blocks.md").exists():
            raise AssertionError(f"Unexpected CLI result: {cli_result}")

        agent_output = root / "agent-blocks"
        agent_result = call_tool("build_document_intelligence_blocks", {"sources": [str(table_path), str(formula_path)], "output": str(agent_output)})
        if agent_result.get("status") != "ok" or (agent_result.get("summary") or {}).get("block_count") != 3:
            raise AssertionError(f"Unexpected agent result: {agent_result}")
        read_result = call_tool("read_artifact", {"path": str(agent_output / "document-intelligence-blocks.json"), "artifact_type": "document_intelligence_blocks_json"})
        if (read_result.get("summary") or {}).get("kind") != "document_intelligence_blocks":
            raise AssertionError(f"Expected read_artifact summary: {read_result}")
    print("Document intelligence blocks artifact test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
