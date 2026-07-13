from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))
from ebook_markdown_pipeline.scripts.run_offline_quality_evidence import DEFAULT_BASELINE, build_evidence, write_evidence

def main() -> int:
    first = build_evidence(DEFAULT_BASELINE)
    second = build_evidence(DEFAULT_BASELINE)
    if first != second:
        raise AssertionError("Offline quality evidence must be deterministic")
    statuses = {item["route_status"] for item in first["cases"]}
    if statuses != {"minimal-deliverable", "degraded", "blocked", "fallback-proposed"}:
        raise AssertionError(statuses)
    separated = [item for item in first["cases"] if item["artifact_exists"] and not item["quality_passed"]]
    if not separated:
        raise AssertionError("Artifact existence must be independent from quality acceptance")
    scan = next(item for item in first["cases"] if item["id"] == "scanned-pdf")
    if scan["fallback_proposal"]["backend"] != "rapidocr" or scan["fallback_proposal"]["automatic"]:
        raise AssertionError(scan)
    blocked = next(item for item in first["cases"] if item["id"] == "scanned-pdf-no-local-ocr")
    if blocked["route_status"] != "blocked" or blocked["fallback_proposal"]["available"]:
        raise AssertionError(blocked)
    with tempfile.TemporaryDirectory(prefix="offline-quality-evidence-") as tmp:
        output = Path(tmp)
        write_evidence(first, output)
        stored = json.loads((output / "offline-quality-evidence.json").read_text(encoding="utf-8"))
        if stored != first or not (output / "offline-quality-evidence.md").is_file():
            raise AssertionError("Evidence round-trip failed")
    print("Offline quality evidence contract test passed.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
