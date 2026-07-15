from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
import types
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.artifact_registry import infer_artifact_type
from ebook_markdown_pipeline.batch_convert_books import record_docling_sidecar
from ebook_markdown_pipeline.candidate_backend_registry import candidate_backend_for_key
from ebook_markdown_pipeline.docling_backend import convert_with_docling
from ebook_markdown_pipeline.ebook_converter_mcp import read_artifact
from ebook_markdown_pipeline.scripts.evaluate_document_quality import build_quality_evaluation, write_quality_evaluation


def load_script(name: str):
    path = PROJECT_DIR / "scripts" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def fake_docling_result(source: Path) -> dict:
    original = {name: sys.modules.get(name) for name in ("docling", "docling.document_converter")}
    package = types.ModuleType("docling")
    converter_module = types.ModuleType("docling.document_converter")

    class FakeDocument:
        def export_to_markdown(self):
            return "# Fake\n"

        def model_dump(self):
            return {"texts": [{"label": "section_header", "text": "Fake", "prov": [{"page_no": 1, "bbox": {"l": 1, "t": 2, "r": 3, "b": 4}}]}], "pages": [{"page_no": 1}]}

    class FakeConverter:
        def convert(self, _source):
            return types.SimpleNamespace(document=FakeDocument(), status="success", errors=[], timings={})

    converter_module.DocumentConverter = FakeConverter
    sys.modules["docling"] = package
    sys.modules["docling.document_converter"] = converter_module
    try:
        return convert_with_docling(source)
    finally:
        for name, value in original.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


def run_worker(name: str, root: Path) -> dict:
    source = root / "sample.pdf"
    source.write_bytes(b"%PDF-1.4\n% fixture\n%%EOF\n")
    output = root / name
    completed = subprocess.run([sys.executable, str(PROJECT_DIR / "scripts" / name), "--input", str(source), "--output", str(output), "--mode", "fake"], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if completed.returncode != 0:
        raise AssertionError(f"{name}: {completed.stdout}\n{completed.stderr}")
    return json.loads(completed.stdout)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="incremental-scaffolding-") as tmp:
        root = Path(tmp)
        source = root / "sample.docx"
        source.write_bytes(b"fake")
        docling = fake_docling_result(source)
        if docling["provenance"] != {"text_item_count": 1, "page_count": 1, "bbox_count": 1}:
            raise AssertionError(docling)
        output = root / "sample.md"
        args = argparse.Namespace(_docling_diagnostics=[])
        record_docling_sidecar(args, source, output, docling)
        sidecar = Path(args._docling_sidecars[str(output)]["path"])
        from ebook_markdown_pipeline import batch_convert_books as converter
        converted = root / "converted.md"
        pipeline_args = argparse.Namespace(output_format="markdown", dry_run=False, _docling_diagnostics=[])
        original_backend, original_postprocess, original_emit = converter.run_docling_backend, converter.postprocess_text_output, converter.emit_stage
        try:
            converter.run_docling_backend = lambda *_args: docling
            converter.postprocess_text_output = lambda *_args, **_kwargs: None
            converter.emit_stage = lambda *_args, **_kwargs: None
            converter.run_docling_convert(source, converted, pipeline_args)
        finally:
            converter.run_docling_backend, converter.postprocess_text_output, converter.emit_stage = original_backend, original_postprocess, original_emit
        if not converted.is_file() or not Path(pipeline_args._docling_sidecars[str(converted)]["path"]).is_file():
            raise AssertionError("Docling conversion path did not expose its sidecar")
        if infer_artifact_type(sidecar) != "docling_document_json":
            raise AssertionError(sidecar)
        if read_artifact({"path": str(sidecar)})["summary"]["bbox_count"] != 1:
            raise AssertionError("Docling sidecar summary missing")

        for key in ("gmft_table", "opendataloader_pdf_fast"):
            profile = candidate_backend_for_key(key)
            if profile is None or profile.run_preview()["model_install_enabled"] or profile.run_preview()["service_start_enabled"]:
                raise AssertionError(profile)
        gmft = run_worker("gmft_table_worker.py", root)
        odl = run_worker("opendataloader_pdf_worker.py", root)
        if gmft["status"] != "ok" or odl["status"] != "ok" or any(item["metrics"].get("model_downloads") for item in (gmft, odl)):
            raise AssertionError({"gmft": gmft, "odl": odl})

        bundle = {"artifact_summaries": [{"backend": "gmft_table", "summary": {"markdown_char_count": 20, "block_count": 2, "reading_order_count": 1}}], "table_review_matrix": [{"rows": [{"backend": "gmft_table", "table_count": 1}]}], "formula_review_matrix": [{"rows": [{"backend": "gmft_table", "formula_count": 1}]}]}
        reference = {"schema_version": "document-quality-reference-v1", "dimensions": {name: {"minimum": 1} for name in ("text", "table", "formula", "layout", "reading_order")}}
        evaluation = build_quality_evaluation(bundle, reference)
        if evaluation.get("overall_score") is not None or evaluation["summary"]["evaluated_dimension_count"] != 5:
            raise AssertionError(evaluation)
        evaluation_dir = root / "evaluation"
        write_quality_evaluation(evaluation_dir, evaluation)
        quality_path = evaluation_dir / "document-quality-evaluation.json"
        if infer_artifact_type(quality_path) != "document_quality_evaluation_json":
            raise AssertionError(quality_path)
        bundle_module = load_script("build_layout_table_review_bundle.py")
        if not bundle_module.collect_quality_evaluations([quality_path]):
            raise AssertionError("Review bundle did not accept quality evidence")
        scorecard_module = load_script("generate_backend_scorecard.py")
        evidence = scorecard_module.collect_document_quality_evaluations([quality_path], [])
        if len(evidence) != 1 or evidence[0]["quality_signals"].get("quality_dimension_evaluated_count") != 5:
            raise AssertionError(evidence)
    print("Incremental backend scaffolding test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())