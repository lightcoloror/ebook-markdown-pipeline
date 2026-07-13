from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))
from ebook_markdown_pipeline.http_status_contract import build_http_status_contract, explain_http_status

DEFAULT_FIXTURE = PROJECT_DIR / "benchmarks" / "fixtures" / "ebook-http-status-contract.json"
DEFAULT_OUTPUT = PROJECT_DIR / "benchmarks" / "runs" / "w7-g47-http-status" / "latest"
QUEUE_ID = "RFQ-F355DEE60F08"

def main() -> int:
    parser = argparse.ArgumentParser(description="Build deterministic ebook HTTP status evidence.")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = build_evidence(args.fixture.resolve())
    write_evidence(payload, args.output.resolve())
    print(json.dumps({"status": "passed", "cases": len(payload["cases"]), "output": str(args.output.resolve())}, ensure_ascii=False))
    return 0

def build_evidence(fixture_path: Path) -> dict[str, Any]:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    cases = []
    for item in fixture["cases"]:
        result = build_http_status_contract(item["observation"])
        cases.append({
            "id": item["id"],
            "status": result["status"],
            "cli_status": result["cli"]["status"],
            "cli_callable": result["cli"]["callable"],
            "http_status": result["http_runtime"]["status"],
            "optional_status": result["optional_backends"]["status"],
            "minimal_output_status": result["minimal_output"]["status"],
            "artifact_exists": result["minimal_output"]["artifact_exists"],
            "quality_passed": result["minimal_output"]["quality_passed"],
            "preferred_entrypoint": result["discovery"]["preferred_entrypoint"],
            "legacy_8765_authoritative": result["legacy_8765"]["authoritative_for_current_runtime"],
            "explanation": explain_http_status(result),
            "contract": result,
        })
    by_id = {item["id"]: item for item in cases}
    stopped = by_id["cli-ready-http-stopped"]
    missing = by_id["backend-missing-degraded-output"]
    if stopped["http_status"] != "stopped-by-design" or not stopped["cli_callable"] or stopped["preferred_entrypoint"] != "cli":
        raise RuntimeError(f"Stopped HTTP must preserve CLI discovery: {stopped}")
    if missing["optional_status"] != "degraded" or missing["quality_passed"] or not missing["cli_callable"]:
        raise RuntimeError(f"Optional missing must remain callable but not full quality: {missing}")
    if any(item["legacy_8765_authoritative"] for item in cases):
        raise RuntimeError("Legacy port 8765 must not become current authority while config uses 9241")
    return {
        "schema_version": "ebook-http-status-evidence-v1",
        "queue_id": QUEUE_ID,
        "fixture": {"path": str(fixture_path), "sha256": sha256_file(fixture_path)},
        "queue_evidence_refs": [
            "D:/used-by-codex/docs/codex-session-index/local-tools-health-snapshot.json",
            "D:/used-by-codex/docs/codex-session-index/infra-health-baseline-run2-2026-07-11.json",
        ],
        "policy": {
            "local_only": True,
            "proposal_only": True,
            "service_start_allowed": False,
            "registry_write_allowed": False,
        },
        "cases": cases,
        "summary": {
            "case_count": len(cases),
            "http_states": {state: sum(1 for item in cases if item["http_status"] == state) for state in sorted({item["http_status"] for item in cases})},
            "cli_callable_while_http_not_healthy": sum(1 for item in cases if item["cli_callable"] and item["http_status"] != "healthy"),
            "artifact_exists_quality_failed": sum(1 for item in cases if item["artifact_exists"] and not item["quality_passed"]),
            "legacy_8765_current_authority_count": sum(1 for item in cases if item["legacy_8765_authoritative"]),
            "service_starts": 0,
            "registry_writes": 0,
        },
    }

def write_evidence(payload: dict[str, Any], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "http-status-evidence.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    lines = [
        "# W7-G47 HTTP Status Evidence", "",
        f"- Queue: `{payload['queue_id']}`",
        "- Service starts: 0",
        "- Registry writes: 0", "",
        "| Case | CLI | HTTP | Optional | Output | Artifact | Quality | Discovery |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in payload["cases"]:
        lines.append(f"| {item['id']} | {item['cli_status']} | {item['http_status']} | {item['optional_status']} | {item['minimal_output_status']} | {item['artifact_exists']} | {item['quality_passed']} | {item['preferred_entrypoint']} |")
    lines.extend(["", "Port 8765 is preserved as legacy stopped evidence, not current runtime authority.", ""])
    (output / "http-status-evidence.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")

def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

if __name__ == "__main__":
    raise SystemExit(main())
