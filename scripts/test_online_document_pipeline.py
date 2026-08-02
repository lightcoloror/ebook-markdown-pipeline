from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from uuid import uuid4

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR.parent))

from ebook_markdown_pipeline.online_document_pipeline import (  # noqa: E402
    OnlinePipelineOptions,
    enhance_embedded_images_online,
    fuse_ocr_vlm_pages,
    normalize_remote_markdown_response,
    run_online_document_pipeline,
    run_structure_stage,
    run_vlm_stage,
    select_vlm_candidates,
)


def main() -> int:
    output = PROJECT_DIR / f".tmp-online-pipeline-test-{uuid4().hex[:8]}"
    try:
        assert_remote_guard(output)
        assert_fake_image(output)
        assert_vlm_selection_and_fusion()
        assert_outer_markdown_fence_normalization()
        assert_structure_stage_normalizes_outer_fence(output)
        assert_vlm_exception_audit(output)
        assert_fake_embedded_image(output)
        assert_fake_text(output)
        assert_fake_epub(output)
        assert_fake_csv(output)
        assert_same_stem_outputs_are_disambiguated(output)
        print("Online document pipeline test passed.")
        return 0
    finally:
        shutil.rmtree(output, ignore_errors=True)


def assert_remote_guard(output: Path) -> None:
    source = PROJECT_DIR / "benchmarks" / "fixtures" / "generated" / "pdf" / "text-layer.pdf"
    result = run_online_document_pipeline(
        source,
        output / "guard",
        options=OnlinePipelineOptions(provider_mode="vkp_shared", execute=True),
    )
    if result.get("code") != "data_export_confirmation_required" or result.get("remote_requests_made") is not False:
        raise AssertionError(f"Remote execution must fail closed before any request: {result}")


def assert_fake_image(output: Path) -> None:
    source = PROJECT_DIR / "benchmarks" / "fixtures" / "generated" / "images" / "ocr" / "english.png"
    result = run_online_document_pipeline(
        source,
        output / "image",
        options=OnlinePipelineOptions(provider_mode="fake", execute=True, max_estimated_cost_usd=0.01),
    )
    if result.get("status") != "ok" or result.get("provider_mode") != "fake":
        raise AssertionError(f"Fake image conversion failed: {result}")
    converted = Path(result["results"][0]["output"])
    text = converted.read_text(encoding="utf-8")
    if "source-image: 1" not in text or not converted.name.endswith(".md") or ".online-" not in converted.name:
        raise AssertionError(f"Image output lost provenance/versioning: {converted}\n{text}")
    stages = result["results"][0].get("stages") or []
    vlm = next((item for item in stages if item.get("stage") == "vlm_layout"), {})
    if vlm.get("status") != "ok" or vlm.get("selected_count") != 1:
        raise AssertionError(f"Standalone image did not execute the online VLM stage: {vlm}")
    serialized = json.dumps(result, ensure_ascii=False)
    if '"api_key"' in serialized or '"authorization"' in serialized.lower():
        raise AssertionError("Online artifacts must not contain credential fields.")


def assert_vlm_selection_and_fusion() -> None:
    image = PROJECT_DIR / "benchmarks" / "fixtures" / "generated" / "images" / "ocr" / "english.png"
    ocr_pages = [{"page_number": 1, "index": 0, "markdown": "A sufficiently long OCR paragraph with ordinary reading order and no fragmented layout."}]
    selected = select_vlm_candidates(
        [image],
        ocr_pages,
        source=image,
        mode="auto",
        max_pages=12,
        min_ocr_chars=80,
    )
    if len(selected) != 1 or "standalone_image" not in selected[0]["selection_reasons"]:
        raise AssertionError(f"Standalone image VLM selection failed: {selected}")
    never = select_vlm_candidates(
        [image],
        ocr_pages,
        source=image,
        mode="never",
        max_pages=12,
        min_ocr_chars=80,
    )
    if never:
        raise AssertionError(f"vlm_mode=never selected pages: {never}")
    ordinary_pdf = select_vlm_candidates(
        [image],
        ocr_pages,
        source=Path("ordinary.pdf"),
        mode="auto",
        max_pages=12,
        min_ocr_chars=20,
    )
    if ordinary_pdf:
        raise AssertionError(f"Ordinary PDF page should not consume a VLM call: {ordinary_pdf}")
    forced = select_vlm_candidates(
        [image],
        ocr_pages,
        source=Path("ordinary.pdf"),
        mode="always",
        max_pages=1,
        min_ocr_chars=20,
    )
    if len(forced) != 1 or forced[0]["selection_reasons"] != ["vlm_mode_always"]:
        raise AssertionError(f"vlm_mode=always failed: {forced}")
    fused = fuse_ocr_vlm_pages(
        [{"page_number": 1, "index": 0, "markdown": "Original OCR evidence that must remain intact."}],
        [{"page_number": 1, "index": 0, "status": "ok", "markdown": "Visual diagram relation", "selection_reasons": ["fragmented_short_blocks"]}],
    )
    if "Original OCR evidence" not in fused[0]["markdown"] or "Visual diagram relation" not in fused[0]["markdown"]:
        raise AssertionError(f"Low-overlap VLM fusion lost evidence: {fused}")


def assert_outer_markdown_fence_normalization() -> None:
    fenced = "```markdown\n# Heading\n\n```python\nprint('kept')\n```\n```"
    normalized = normalize_remote_markdown_response(fenced)
    if normalized != "# Heading\n\n```python\nprint('kept')\n```":
        raise AssertionError(f"Outer Markdown fence was not normalized safely: {normalized}")
    python_fence = "```python\nprint('standalone code')\n```"
    if normalize_remote_markdown_response(python_fence) != python_fence:
        raise AssertionError("A real language code block must not be unwrapped.")


def assert_structure_stage_normalizes_outer_fence(output: Path) -> None:
    class FencedGateway:
        def execute(self, *_args, **_kwargs):
            return {
                "markdown": "```markdown\n# Repaired heading\n\nBody.\n```",
                "execution": {"ok": True},
                "remote_requests_made": True,
            }

    repaired, reports, warnings = run_structure_stage(
        "Original body.",
        source=Path("synthetic.txt"),
        stage_dir=output / "structure-fence",
        options=OnlinePipelineOptions(
            provider_mode="vkp_shared",
            execute=True,
            confirm_data_export=True,
            max_estimated_cost_usd=0.01,
        ),
        budget=0.01,
        shared_gateway=FencedGateway(),
    )
    if repaired != "# Repaired heading\n\nBody." or warnings:
        raise AssertionError(f"Structure-stage response normalization failed: {repaired}; {warnings}")
    if reports[0].get("response_normalization") != ["outer_markdown_fence_removed"]:
        raise AssertionError(f"Structure-stage normalization was not reported: {reports}")

    class EmptyGateway:
        def execute(self, *_args, **_kwargs):
            return {"markdown": "", "execution": {"ok": False}, "remote_requests_made": False}

    fallback, fallback_reports, fallback_warnings = run_structure_stage(
        "Original body.",
        source=Path("synthetic.txt"),
        stage_dir=output / "structure-fallback",
        options=OnlinePipelineOptions(
            provider_mode="vkp_shared",
            execute=True,
            confirm_data_export=True,
            max_estimated_cost_usd=0.01,
        ),
        budget=0.01,
        shared_gateway=EmptyGateway(),
    )
    if fallback != "Original body." or not fallback_warnings:
        raise AssertionError(f"Structure fallback no longer preserves the source: {fallback}")
    if fallback_reports[0].get("response_normalization"):
        raise AssertionError(f"Fallback must not be mislabeled as fence normalization: {fallback_reports}")


def assert_vlm_exception_audit(output: Path) -> None:
    class FailingGateway:
        def execute(self, *_args, **_kwargs):
            raise RuntimeError("simulated failure after execution start")

    image = PROJECT_DIR / "benchmarks" / "fixtures" / "generated" / "images" / "ocr" / "english.png"
    result = run_vlm_stage(
        [{"page_number": 1, "image": str(image), "ocr_markdown": "OCR evidence"}],
        source=image,
        stage_dir=output / "vlm-exception",
        options=OnlinePipelineOptions(
            provider_mode="vkp_shared",
            execute=True,
            confirm_data_export=True,
            max_estimated_cost_usd=0.01,
        ),
        budget=0.01,
        shared_gateway=FailingGateway(),
    )
    page = result["pages"][0]
    if page.get("remote_requests_made") is not True:
        raise AssertionError(f"VLM exception must conservatively report possible remote export: {page}")
    if page.get("remote_request_evidence") != "conservative_after_execution_exception":
        raise AssertionError(f"VLM exception audit evidence is missing: {page}")

def assert_fake_embedded_image(output: Path) -> None:
    root = output / "embedded"
    root.mkdir(parents=True, exist_ok=True)
    image = root / "diagram.png"
    shutil.copy2(
        PROJECT_DIR / "benchmarks" / "fixtures" / "generated" / "images" / "ocr" / "english.png",
        image,
    )
    baseline = root / "document.md"
    markdown = "# Document\n\n![Diagram](diagram.png)\n"
    baseline.write_text(markdown, encoding="utf-8")
    enhanced, report = enhance_embedded_images_online(
        markdown,
        baseline,
        source=root / "document.docx",
        stage_dir=root / "analysis",
        options=OnlinePipelineOptions(provider_mode="fake", execute=True, vlm_mode="auto"),
        budget=0.01,
        shared_gateway=None,
    )
    if not report or report.get("vlm_status") != "ok" or report.get("vlm_selected_count") != 1:
        raise AssertionError(f"Embedded image did not execute the VLM stage: {report}")
    if report.get("stage") != "embedded_image_ocr" or report.get("analysis_mode") != "online_ocr_plus_optional_vlm":
        raise AssertionError(f"Embedded image report broke its backward-compatible stage contract: {report}")
    if "Fake OCR block" not in enhanced or "Fake Layout" not in enhanced:
        raise AssertionError(f"Embedded OCR/VLM fusion was not inserted into Markdown: {enhanced}")

def assert_fake_epub(output: Path) -> None:
    source = PROJECT_DIR / "benchmarks" / "fixtures" / "generated" / "ebooks" / "sample.epub"
    result = run_online_document_pipeline(
        source,
        output / "epub",
        options=OnlinePipelineOptions(provider_mode="fake", execute=True, max_estimated_cost_usd=0.01),
    )
    if result.get("status") != "ok":
        raise AssertionError(f"Fake EPUB conversion failed: {result}")
    converted = Path(result["results"][0]["output"])
    if not converted.is_file() or ".online-" not in converted.name:
        raise AssertionError(f"EPUB output is not versioned: {converted}")


def assert_fake_csv(output: Path) -> None:
    source = output / "inputs" / "sample.csv"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("name,value\nalpha,1\nbeta,2\n", encoding="utf-8")
    result = run_online_document_pipeline(
        source,
        output / "csv",
        options=OnlinePipelineOptions(provider_mode="fake", execute=True, max_estimated_cost_usd=0.01),
    )
    if result.get("status") != "ok":
        raise AssertionError(f"Fake CSV conversion failed: {result}")
    converted = Path(result["results"][0]["output"])
    if "alpha" not in converted.read_text(encoding="utf-8"):
        raise AssertionError(f"CSV deterministic baseline lost table content: {converted}")


def assert_fake_text(output: Path) -> None:
    source = PROJECT_DIR / "benchmarks" / "fixtures" / "generated" / "text" / "sample.txt"
    result = run_online_document_pipeline(
        source,
        output / "text",
        options=OnlinePipelineOptions(provider_mode="fake", execute=True, max_estimated_cost_usd=0.01),
    )
    if result.get("status") != "ok":
        raise AssertionError(f"Fake text conversion failed: {result}")
    stages = result["results"][0].get("stages") or []
    baseline = next((item for item in stages if item.get("stage") == "deterministic_baseline"), {})
    if baseline.get("local_model_inference") is not False or "docling" in str(baseline.get("pipeline") or "").lower():
        raise AssertionError(f"online_only baseline must remain deterministic: {baseline}")


def assert_same_stem_outputs_are_disambiguated(output: Path) -> None:
    source_root = output / "same-stem-inputs"
    source_root.mkdir(parents=True, exist_ok=True)
    (source_root / "shared-name.txt").write_text("# TXT source\n\nText variant.\n", encoding="utf-8")
    (source_root / "shared-name.md").write_text("# Markdown source\n\nMarkdown variant.\n", encoding="utf-8")
    result = run_online_document_pipeline(
        source_root,
        output / "same-stem-output",
        options=OnlinePipelineOptions(provider_mode="fake", execute=True, max_estimated_cost_usd=0.01),
    )
    outputs = [Path(item["output"]) for item in result.get("results") or [] if item.get("status") == "ok"]
    if len(outputs) != 2 or len(set(outputs)) != 2 or not all(path.is_file() for path in outputs):
        raise AssertionError(f"Same-stem sources collided: {result}")
    names = {path.name for path in outputs}
    if not any("shared-name.txt.online-" in name for name in names):
        raise AssertionError(f"TXT output was not format-disambiguated: {names}")
    if not any("shared-name.md.online-" in name for name in names):
        raise AssertionError(f"Markdown output was not format-disambiguated: {names}")
    plans = result.get("sources") or []
    if {item.get("output_disambiguator") for item in plans} != {"txt", "md"}:
        raise AssertionError(f"Manifest did not record output disambiguators: {plans}")


if __name__ == "__main__":
    raise SystemExit(main())
