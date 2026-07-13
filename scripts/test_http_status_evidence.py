from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))
from ebook_markdown_pipeline.scripts.run_http_status_evidence import DEFAULT_FIXTURE, build_evidence, write_evidence

def main() -> int:
    first = build_evidence(DEFAULT_FIXTURE)
    second = build_evidence(DEFAULT_FIXTURE)
    if first != second:
        raise AssertionError("HTTP status evidence is not deterministic")
    if first["summary"]["cli_callable_while_http_not_healthy"] < 1:
        raise AssertionError(first)
    if first["summary"]["artifact_exists_quality_failed"] < 1:
        raise AssertionError(first)
    if first["summary"]["legacy_8765_current_authority_count"] != 0:
        raise AssertionError(first)
    with tempfile.TemporaryDirectory(prefix="http-status-evidence-") as tmp:
        output = Path(tmp)
        write_evidence(first, output)
        stored = json.loads((output / "http-status-evidence.json").read_text(encoding="utf-8"))
        if stored != first or not (output / "http-status-evidence.md").is_file():
            raise AssertionError("HTTP status evidence round-trip failed")
    print("HTTP status evidence test passed.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
