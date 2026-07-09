from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


REGISTRY_SCHEMA_VERSION = "candidate-backend-registry-v1"
RUN_PREVIEW_SCHEMA_VERSION = "candidate-run-preview-v1"
READINESS_CONTRACT_SCHEMA_VERSION = "candidate-readiness-contract-v1"


@dataclass(frozen=True)
class CandidateBackendProfile:
    key: str
    display_name: str
    module: str
    health_names: tuple[str, ...]
    capability_names: tuple[str, ...]
    role: str
    best_for: str
    install_cost: str
    gpu_or_model: str
    license_note: str
    default_policy: str
    command_hint: str
    artifact_contract: tuple[str, ...]
    risk: str
    sample_classes: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["schema_version"] = REGISTRY_SCHEMA_VERSION
        payload["readiness_contract"] = self.readiness_contract()
        payload["run_preview"] = self.run_preview()
        return payload

    def run_preview(self, *, capability: str = "", trigger: str = "") -> dict[str, Any]:
        return candidate_run_preview(self, capability=capability, trigger=trigger)

    def readiness_contract(self) -> dict[str, Any]:
        return candidate_readiness_contract(self)

def candidate_run_preview(profile: CandidateBackendProfile, *, capability: str = "", trigger: str = "") -> dict[str, Any]:
    return {
        "schema_version": RUN_PREVIEW_SCHEMA_VERSION,
        "backend": profile.display_name,
        "registry_key": profile.key,
        "capability": capability,
        "trigger": trigger,
        "execution_policy": "plan_or_fake_first_no_model_install_no_service_start",
        "default_mode": "plan",
        "safe_modes": ["plan", "fake"],
        "execute_requires_explicit_approval": True,
        "model_install_enabled": False,
        "service_start_enabled": False,
        "remote_call_enabled": False,
        "command_hint": profile.command_hint,
        "expected_artifacts": list(profile.artifact_contract),
        "readiness_checks": list(profile.health_names),
        "capability_checks": list(profile.capability_names),
        "readiness_contract": profile.readiness_contract(),
        "missing_state_policy": "report_needs_manual_start_or_model_config; do_not_start_or_install",
        "promotion_gate_required": True,
        "will_not": [
            "install models",
            "start services",
            "make remote calls",
            "process private documents without explicit user input",
            "promote default routing",
        ],
        "next_actions": [
            {
                "action": "run_plan_or_fake_first",
                "tool": "external_wrapper_plan",
                "safe_default": True,
                "destructive": False,
                "why": "inspect command/artifact plan before any real backend execution",
            },
            {
                "action": "read_wrapper_result",
                "tool": "read_artifact",
                "artifact_type": "external_wrapper_result_json",
                "safe_default": True,
                "destructive": False,
                "why": "review normalized wrapper result before comparing quality",
            },
            {
                "action": "update_scorecard",
                "tool": "generate_backend_scorecard",
                "safe_default": True,
                "destructive": False,
                "why": "fold wrapper/candidate artifacts into promotion gates",
            },
            {
                "action": "build_review_bundle",
                "tool": "build_layout_table_review_bundle",
                "safe_default": True,
                "destructive": False,
                "why": "compare layout/table/formula evidence before route changes",
            },
        ],
    }

def candidate_readiness_contract(profile: CandidateBackendProfile) -> dict[str, Any]:
    key = normalize_backend_name(profile.key)
    external_repo_keys = {"monkeyocr", "dots_mocr", "doclayout_yolo", "pdf_table", "table_to_xlsx"}
    service_keys = {"dots_mocr"}
    model_cache_keys = {"tesseract", "doctr", "monkeyocr", "dots_mocr", "doclayout_yolo", "pdf_table", "table_to_xlsx"}
    gpu_or_heavy_keys = {"doctr", "monkeyocr", "dots_mocr", "doclayout_yolo", "pdf_table", "table_to_xlsx"}
    model_cache_hints = {
        "tesseract": ["TESSDATA_PREFIX", "external Tesseract language data directory"],
        "doctr": ["docTR model cache outside this repository"],
        "monkeyocr": ["MONKEYOCR_ROOT", "model_configs.yaml", "model weight paths referenced by MonkeyOCR config"],
        "dots_mocr": ["DOTS_MOCR_ROOT", "DOTS_MOCR_BASE_URL", "weights/DotsOCR or manually managed vLLM model cache"],
        "doclayout_yolo": ["DOCLAYOUT_YOLO_MODEL", "external YOLO/DocLayout model cache"],
        "pdf_table": ["PDF_TABLE_MODEL_DIR", "external pdf_table/Paddle table model cache"],
        "table_to_xlsx": ["PADDLEOCR_MODEL_DIR", "IMG2TABLE_HOME", "RAPIDTABLE_MODEL_DIR", "external table-recognition model cache"],
    }
    missing_states = ["planned_only"]
    if key in external_repo_keys:
        missing_states.append("needs_env")
    if key in model_cache_keys:
        missing_states.append("needs_model")
    if key in service_keys:
        missing_states.append("needs_server")
    return {
        "schema_version": READINESS_CONTRACT_SCHEMA_VERSION,
        "backend": profile.display_name,
        "registry_key": profile.key,
        "install_cost": profile.install_cost,
        "runtime_requirement": profile.gpu_or_model,
        "requires_external_repo": key in external_repo_keys,
        "requires_model_cache": key in model_cache_keys,
        "requires_service": key in service_keys,
        "requires_gpu_or_heavy_runtime": key in gpu_or_heavy_keys,
        "manual_start_required": key in service_keys,
        "manual_start_hint": manual_start_hint_for_key(key),
        "model_cache_hints": model_cache_hints.get(key, []),
        "health_names": list(profile.health_names),
        "capability_names": list(profile.capability_names),
        "plan_command_hint": profile.command_hint,
        "supported_artifacts": list(profile.artifact_contract),
        "missing_states": missing_states,
        "ready_state": "ready only after env, model/cache, and manually managed service checks pass",
        "model_install_enabled": False,
        "service_start_enabled": False,
        "remote_call_enabled": False,
    }


def manual_start_hint_for_key(key: str) -> str:
    if key == "dots_mocr":
        return "Start and verify the dots.mocr/vLLM/OpenAI-compatible service outside this project; the registry reports needs_server and will not launch it."
    return "No service is started by this project; use plan/fake mode until a human prepares the external runtime."

def normalize_backend_name(value: str) -> str:
    return value.lower().replace("-", "_").replace(".", "_").replace(" ", "_").strip()


CANDIDATE_BACKENDS: tuple[CandidateBackendProfile, ...] = (
    CandidateBackendProfile(
        key="pypdf",
        display_name="pypdf",
        module="scripts/pypdf_diagnostics_worker.py",
        health_names=("pypdf diagnostics worker",),
        capability_names=("pdf_lightweight_fallbacks",),
        role="lightweight PDF metadata/outline diagnostics worker",
        best_for="PDF metadata, outline, page-count, split/merge utility evidence when PyMuPDF output needs a lightweight second opinion",
        install_cost="low",
        gpu_or_model="pure Python package; no GPU or model weights",
        license_note="personal-use candidate; keep dependency external",
        default_policy="candidate-only diagnostics; not default Markdown conversion",
        command_hint="python scripts/pypdf_diagnostics_worker.py --input <pdf> --output <run-dir> --mode plan",
        artifact_contract=("pdf_metadata_json", "pdf_outline_json", "markdown", "external_wrapper_result_json"),
        risk="metadata/outline utility only; never final Markdown route",
        sample_classes=("pdf_text_layer", "academic_pdf"),
    ),
    CandidateBackendProfile(
        key="pdfminer_six",
        display_name="pdfminer.six",
        module="scripts/pdfminer_text_worker.py",
        health_names=("pdfminer.six text worker",),
        capability_names=("pdf_lightweight_fallbacks",),
        role="pure-Python PDF text-layer diagnostics worker",
        best_for="text-layer debugging and comparison when PyMuPDF/PyMuPDF4LLM output looks suspicious",
        install_cost="low",
        gpu_or_model="pure Python package; no GPU or model weights",
        license_note="personal-use candidate; keep dependency external",
        default_policy="candidate-only diagnostics; not default Markdown conversion",
        command_hint="python scripts/pdfminer_text_worker.py --input <pdf> --output <run-dir> --mode plan",
        artifact_contract=("text", "pages_jsonl", "markdown", "external_wrapper_result_json"),
        risk="text sample/debug only; output is not book-quality Markdown",
        sample_classes=("pdf_text_layer", "academic_pdf"),
    ),
    CandidateBackendProfile(
        key="tesseract",
        display_name="Tesseract OCR",
        module="scripts/tesseract_ocr_worker.py",
        health_names=("Tesseract OCR worker",),
        capability_names=("ocr_candidate_workers",),
        role="classic OCR/hOCR/TSV baseline worker plan",
        best_for="direct OCR standards baseline after OCRmyPDF/Umi/RapidOCR comparison needs page-level evidence",
        install_cost="medium",
        gpu_or_model="external tesseract command and language data; no GPU",
        license_note="personal-use candidate; language data terms tracked separately",
        default_policy="candidate-only direct OCR baseline; not default scanned-PDF route",
        command_hint="python scripts/tesseract_ocr_worker.py --input <image> --output <run-dir> --mode plan",
        artifact_contract=("text", "ocr_blocks_jsonl", "hocr", "tsv", "external_wrapper_result_json"),
        risk="direct OCR only; OCRmyPDF remains the searchable-PDF workflow",
        sample_classes=("scanned_pdf", "infographic_image", "image_set"),
    ),
    CandidateBackendProfile(
        key="doctr",
        display_name="docTR",
        module="scripts/doctr_ocr_worker.py",
        health_names=("docTR OCR worker",),
        capability_names=("ocr_candidate_workers",),
        role="Python OCR detection/recognition worker plan",
        best_for="detection+recognition API comparison on clean images or rendered PDF pages",
        install_cost="medium/heavy",
        gpu_or_model="Python package plus OCR models; GPU optional but model setup required",
        license_note="personal-use candidate; model cache and runtime stay external",
        default_policy="candidate-only OCR benchmark; never default routing",
        command_hint="python scripts/doctr_ocr_worker.py --input <image> --output <run-dir> --mode plan",
        artifact_contract=("ocr_blocks_jsonl", "markdown", "external_wrapper_result_json"),
        risk="adapter is fake/plan first until ocr-blocks-v1 normalization is implemented",
        sample_classes=("infographic_image", "image_set", "scanned_pdf"),
    ),
    CandidateBackendProfile(
        key="monkeyocr",
        display_name="MonkeyOCR",
        module="scripts/monkeyocr_worker.py",
        health_names=("MonkeyOCR worker",),
        capability_names=("external_document_vlm_wrappers",),
        role="external document VLM worker plan",
        best_for="complex scanned/layout-heavy PDFs or image folders when a full Markdown + layout artifact bundle is worth testing",
        install_cost="heavy",
        gpu_or_model="external repo, isolated Python, model weights, and usually CUDA/remote inference",
        license_note="personal-use candidate; keep upstream code and weights outside this repository",
        default_policy="candidate-only; explicit plan/fake/execute worker, never default routing",
        command_hint="python scripts/monkeyocr_worker.py --input <input> --output <run-dir> --mode plan",
        artifact_contract=("markdown", "middle_json", "content_list_json", "layout_review_pdf", "span_review_pdf", "model_debug_pdf", "image_assets_dir"),
        risk="heavy model/runtime; explicit only; never whole-book default route",
        sample_classes=("scanned_pdf", "pdf_two_column", "ppt_export_pdf", "infographic_image", "image_set"),
    ),
    CandidateBackendProfile(
        key="dots_mocr",
        display_name="dots.mocr",
        module="scripts/dots_mocr_worker.py",
        health_names=("dots.mocr provider",),
        capability_names=("external_document_vlm_wrappers",),
        role="external HTTP/GPU document VLM provider plan",
        best_for="multilingual document layout parsing through a vLLM/OpenAI-compatible service",
        install_cost="heavy",
        gpu_or_model="external parser repo or HTTP service, model weights, and GPU/remote inference",
        license_note="personal-use candidate; model/server terms tracked separately",
        default_policy="candidate-only; provider/worker must be manually selected, never default routing",
        command_hint="python scripts/dots_mocr_worker.py --input <input> --output <run-dir> --mode plan",
        artifact_contract=("layout_blocks_json", "markdown", "markdown_no_header_footer", "layout_overlay_image", "page_index_jsonl"),
        risk="requires manually managed vLLM/OpenAI-compatible service or local HF weights; no automatic remote call",
        sample_classes=("scanned_pdf", "pdf_two_column", "ppt_export_pdf", "infographic_image", "web_archive"),
    ),
    CandidateBackendProfile(
        key="doclayout_yolo",
        display_name="DocLayout-YOLO",
        module="scripts/doclayout_yolo_worker.py",
        health_names=("DocLayout-YOLO baseline",),
        capability_names=("layout_detector_baseline",),
        role="layout detector baseline plan",
        best_for="selected-page bbox/overlay evidence for inspect_document and layout-heavy PDF triage",
        install_cost="medium/heavy",
        gpu_or_model="external model weights; GPU helpful but selected-page CPU experiments may be possible",
        license_note="personal-use candidate; keep model cache outside this repository",
        default_policy="candidate-only; layout evidence, not default Markdown conversion",
        command_hint="python scripts/doclayout_yolo_worker.py --input <input> --output <run-dir> --pages 1-3 --mode plan",
        artifact_contract=("layout_candidates_json", "layout_overlay_image", "layout_summary"),
        risk="layout evidence only; never final Markdown",
        sample_classes=("pdf_two_column", "ppt_export_pdf", "web_archive"),
    ),
    CandidateBackendProfile(
        key="pdf_table",
        display_name="pdf_table",
        module="scripts/pdf_table_worker.py",
        health_names=("pdf_table worker",),
        capability_names=("external_table_worker",),
        role="external table-page worker plan",
        best_for="table-heavy PDF/image pages that need comparison against Camelot/Tabula/pdfplumber",
        install_cost="heavy",
        gpu_or_model="external pdftable command plus table/OCR/layout models",
        license_note="personal-use candidate; model cache and upstream project stay external",
        default_policy="candidate-only; table pages only, never whole-book default routing",
        command_hint="python scripts/pdf_table_worker.py --input <input> --output <run-dir> --pages <table-pages> --mode plan",
        artifact_contract=("table_markdown", "table_html", "table_cells_json", "table_overlay_image", "table_comparison_summary"),
        risk="table pages only; compare against Camelot/Tabula/pdfplumber before recommendation",
        sample_classes=("pdf_table",),
    ),
    CandidateBackendProfile(
        key="table_to_xlsx",
        display_name="table_to_xlsx",
        module="scripts/table_to_xlsx_worker.py",
        health_names=("table_to_xlsx worker",),
        capability_names=("table_to_xlsx_export",),
        role="candidate photo/scanned table to XLSX worker plan",
        best_for="photo or scanned paper Excel-like tables that need editable XLSX draft output",
        install_cost="medium/heavy",
        gpu_or_model="PaddleOCR TableRecognitionPipelineV2 or img2table/RapidTable plus OCR/table models",
        license_note="personal-use candidate; upstream runtime/model terms tracked separately",
        default_policy="candidate-only; XLSX draft export only, never default whole-document routing",
        command_hint="python scripts/table_to_xlsx_worker.py --input <image-or-pdf-page> --output <run-dir> --mode plan",
        artifact_contract=("table_xlsx", "table_candidates_json", "table_to_xlsx_summary"),
        risk="Excel output is an editable draft; formulas, formatting, filters, colors, and exact column widths are not reliably recovered",
        sample_classes=("pdf_table", "infographic_image", "image_set"),
    ),
)


_BY_KEY = {normalize_backend_name(profile.key): profile for profile in CANDIDATE_BACKENDS}
_BY_DISPLAY = {normalize_backend_name(profile.display_name): profile for profile in CANDIDATE_BACKENDS}
for profile in CANDIDATE_BACKENDS:
    for health_name in profile.health_names:
        _BY_DISPLAY[normalize_backend_name(health_name)] = profile


def candidate_backend_for_key(key: str) -> CandidateBackendProfile | None:
    return _BY_KEY.get(normalize_backend_name(key))


def candidate_backend_for_display(name: str) -> CandidateBackendProfile | None:
    return _BY_DISPLAY.get(normalize_backend_name(name))


def candidate_backends_for_sample_class(sample_class: str) -> list[CandidateBackendProfile]:
    sample_class = normalize_backend_name(sample_class)
    return [profile for profile in CANDIDATE_BACKENDS if sample_class in profile.sample_classes]


def candidate_backend_registry_payload() -> dict[str, Any]:
    return {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "execution_policy": "candidate_only_plan_or_fake_first",
        "remote_call_enabled": False,
        "model_install_enabled": False,
        "run_preview_schema_version": RUN_PREVIEW_SCHEMA_VERSION,
        "readiness_contract_schema_version": READINESS_CONTRACT_SCHEMA_VERSION,
        "backends": [profile.to_dict() for profile in CANDIDATE_BACKENDS],
    }
