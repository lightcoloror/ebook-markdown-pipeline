from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_DIR / "scripts" / "build_candidate_benchmark_manifest.py"


def main() -> int:
    module = load_module()
    samples = [
        {"id": "scan", "path": "D:/missing/scanned.pdf", "category": "scanned_pdf"},
        {"id": "table", "path": "D:/missing/table.pdf", "category": "pdf_table"},
        {"id": "wide", "path": "D:/missing/info.png", "category": "infographic_image"},
        {"id": "policy", "path": "D:/missing/policy.pdf", "category": "insurance_policy"},
    ]
    payload = module.build_candidate_benchmark_plan(samples, manifest=Path("samples.local.json"))
    if payload.get("schema_version") != module.SCHEMA_VERSION:
        raise AssertionError(f"Unexpected candidate benchmark schema: {payload}")
    by_id = {item["id"]: item for item in payload["samples"]}
    if "MonkeyOCR" not in by_id["scan"].get("candidate_backends", []):
        raise AssertionError(f"Expected scanned PDF document-VLM candidates: {by_id['scan']}")
    scan_previews = {item.get("backend"): item for item in by_id["scan"].get("candidate_backend_previews") or []}
    if (scan_previews.get("MonkeyOCR", {}).get("run_preview") or {}).get("schema_version") != "candidate-run-preview-v1":
        raise AssertionError(f"Expected scanned PDF run preview: {by_id['scan']}")
    if (scan_previews.get("MonkeyOCR", {}).get("run_preview") or {}).get("model_install_enabled"):
        raise AssertionError(f"Benchmark preview must remain non-executing: {by_id['scan']}")
    if "pdf_table" not in by_id["table"].get("candidate_backends", []):
        raise AssertionError(f"Expected pdf_table candidate: {by_id['table']}")
    if "dots.mocr" not in by_id["wide"].get("candidate_backends", []):
        raise AssertionError(f"Expected infographic VLM candidates: {by_id['wide']}")
    if by_id["policy"].get("candidate_class") != "chinese_hierarchy_document" or "structure_repair" not in by_id["policy"].get("candidate_backends", []):
        raise AssertionError(f"Expected Chinese hierarchy policy sample routing: {by_id['policy']}")
    if "structure_report" not in by_id["policy"].get("expected_artifacts", []):
        raise AssertionError(f"Expected Chinese hierarchy structure artifacts: {by_id['policy']}")
    if not payload.get("promotion_gate", {}).get("required_evidence"):
        raise AssertionError(f"Expected promotion gate evidence: {payload}")
    classes = {item.get("class"): item for item in payload.get("sample_classes") or []}
    policy_class = classes.get("chinese_hierarchy_document") or {}
    if not any("Chinese numbered clauses" in question for question in policy_class.get("review_questions") or []):
        raise AssertionError(f"Expected Chinese hierarchy review questions: {policy_class}")
    table_previews = {item.get("backend"): item for item in classes["pdf_table"].get("candidate_backend_previews") or []}
    if "pdf_table" not in table_previews or (table_previews["pdf_table"].get("run_preview") or {}).get("default_mode") != "plan":
        raise AssertionError(f"Expected pdf_table run preview on sample class: {classes['pdf_table']}")

    with tempfile.TemporaryDirectory(prefix="candidate-benchmark-manifest-") as tmp:
        root = Path(tmp)
        manifest = root / "samples.json"
        manifest.write_text(json.dumps({"schema_version": "benchmark-samples-v1", "samples": samples}, ensure_ascii=False), encoding="utf-8")
        output = root / "candidate-plan.json"
        completed = subprocess.run([sys.executable, str(SCRIPT), "--manifest", str(manifest), "--output", str(output)], cwd=PROJECT_DIR, text=True, capture_output=True, check=False)
        if completed.returncode != 0:
            raise AssertionError(f"CLI failed:\nSTDOUT={completed.stdout}\nSTDERR={completed.stderr}")
        persisted = json.loads(output.read_text(encoding="utf-8"))
        if len(persisted.get("samples") or []) != 4:
            raise AssertionError(f"Expected persisted samples: {persisted}")
        persisted_scan = next(item for item in persisted.get("samples") or [] if item.get("id") == "scan")
        if not persisted_scan.get("candidate_backend_previews"):
            raise AssertionError(f"Expected persisted run previews: {persisted_scan}")
    print("Candidate benchmark manifest test passed.")
    return 0


def load_module():
    spec = importlib.util.spec_from_file_location("build_candidate_benchmark_manifest", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    raise SystemExit(main())
