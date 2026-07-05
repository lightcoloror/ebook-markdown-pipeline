from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.chunk_map import build_chunk_map  # noqa: E402
from ebook_markdown_pipeline.ebook_converter_mcp import call_tool  # noqa: E402


def main() -> int:
    markdown = """# 第一章 总则

<!-- page: 1 -->

这是第一段正文，用于形成 narrative text。

## 第一节 范围

- 条目一
- 条目二

| A | B |
| --- | --- |
| 1 | 2 |
"""
    structure_report = {
        "schema_version": "markdown-structure-enhancement-v1",
        "local_structure_repair": {
            "schema_version": "structure-repair-v1",
            "decision_count": 2,
            "cleanup_decision_count": 1,
            "action_counts": {"promoted_to_heading": 2},
        },
    }
    with tempfile.TemporaryDirectory(prefix="chunk-map-") as tmp:
        root = Path(tmp)
        markdown_path = root / "sample.md"
        structure_path = root / "sample.structure.json"
        markdown_path.write_text(markdown, encoding="utf-8")
        structure_path.write_text(json.dumps(structure_report, ensure_ascii=False), encoding="utf-8")
        payload = build_chunk_map(markdown_path, structure_json=structure_path, max_chunk_chars=80)
        if payload["schema_version"] != "chunk-map-v1" or payload["summary"]["chunk_count"] < 2:
            raise AssertionError(f"Expected chunk map chunks: {payload}")
        if payload["summary"]["element_types"].get("table") != 1 or payload["summary"]["page_break_count"] != 1:
            raise AssertionError(f"Expected table and page-break elements: {payload}")
        if payload["policy"]["mode"] != "metadata_only_no_platform_import":
            raise AssertionError(f"Expected metadata-only policy: {payload}")

        output = root / "chunks"
        completed = subprocess.run(
            [sys.executable, "-B", "scripts/build_chunk_map.py", "--markdown", str(markdown_path), "--structure-json", str(structure_path), "--output", str(output), "--max-chunk-chars", "80"],
            cwd=PROJECT_DIR,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=True,
        )
        cli_result = json.loads(completed.stdout)
        if cli_result.get("chunks", 0) < 2 or not (output / "chunk-map.md").exists():
            raise AssertionError(f"Unexpected CLI chunk-map result: {cli_result}")

        agent_output = root / "agent-chunks"
        agent_result = call_tool(
            "build_chunk_map",
            {"markdown": str(markdown_path), "structure_json": str(structure_path), "output": str(agent_output), "max_chunk_chars": 80},
        )
        if agent_result.get("status") != "ok" or (agent_result.get("summary") or {}).get("chunk_count", 0) < 2:
            raise AssertionError(f"Unexpected agent chunk-map result: {agent_result}")
        read_result = call_tool("read_artifact", {"path": str(agent_output / "chunk-map.json"), "artifact_type": "chunk_map_json"})
        if (read_result.get("summary") or {}).get("kind") != "chunk_map":
            raise AssertionError(f"Expected read_artifact chunk-map summary: {read_result}")

    print("Chunk map artifact test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
