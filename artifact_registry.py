from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path


REGISTRY_SCHEMA_VERSION = "artifact-type-registry-v1"


@dataclass(frozen=True)
class ArtifactTypeProfile:
    key: str
    readable: bool = False
    json_payload: bool = False
    media_type: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


JSON_ARTIFACT_KEYS = (
    "json",
    "agent_batch_results",
    "agent_handoff_bundle_json",
    "agent_smoke_summary_json",
    "conversion_report",
    "summary_json",
    "review_json",
    "review_decisions_json",
    "clusters_json",
    "structure_json",
    "environment_json",
    "environment_lock",
    "environment_lock_compare",
    "environment_lock_compare_json",
    "quality_comparison_json",
    "quality_improvement_queue_json",
    "visual_check_json",
    "visual_blocks_json",
    "table_candidates_json",
    "layout_candidates_json",
    "formula_candidates_json",
    "document_vlm_result_json",
    "external_wrapper_result_json",
    "layout_table_review_bundle_json",
    "optional_backend_scorecard_json",
    "candidate_benchmark_plan_json",
    "image_positions_json",
    "pdf_metadata_json",
    "pdf_outline_json",
    "pdf_layout_evidence_json",
    "ocr_provider_comparison_json",
    "review_lifecycle_json",
    "chunk_map_json",
    "academic_evidence_json",
    "format_baseline_matrix_json",
    "document_intelligence_blocks_json",
)

READABLE_NON_JSON_ARTIFACT_KEYS = (
    "markdown",
    "agent_handoff_bundle_markdown",
    "agent_batch_run_summary",
    "agent_batch_summary",
    "agent_smoke_summary_markdown",
    "html",
    "text",
    "summary_report",
    "review_report",
    "review_decisions",
    "location_index_jsonl",
    "pages_jsonl",
    "order_report",
    "structure_report",
    "environment_report",
    "quality_comparison",
    "requirements_lock",
    "tool_log",
    "ocr_blocks_jsonl",
    "hocr",
    "tsv",
)


def _json_profile(key: str) -> ArtifactTypeProfile:
    return ArtifactTypeProfile(key=key, readable=True, json_payload=True, media_type="application/json")


def _readable_profile(key: str) -> ArtifactTypeProfile:
    media_types = {
        "markdown": "text/markdown",
        "agent_handoff_bundle_markdown": "text/markdown",
        "agent_smoke_summary_markdown": "text/markdown",
        "html": "text/html",
        "hocr": "text/html",
        "tsv": "text/tab-separated-values",
        "location_index_jsonl": "application/x-ndjson",
        "pages_jsonl": "application/x-ndjson",
        "ocr_blocks_jsonl": "application/x-ndjson",
    }
    return ArtifactTypeProfile(key=key, readable=True, media_type=media_types.get(key, "text/plain"))


ARTIFACT_TYPE_PROFILES = tuple(
    [*(_json_profile(key) for key in JSON_ARTIFACT_KEYS), *(_readable_profile(key) for key in READABLE_NON_JSON_ARTIFACT_KEYS)]
)
_PROFILE_BY_KEY = {profile.key: profile for profile in ARTIFACT_TYPE_PROFILES}
JSON_ARTIFACT_TYPES = frozenset(profile.key for profile in ARTIFACT_TYPE_PROFILES if profile.json_payload)
READABLE_ARTIFACT_TYPES = frozenset(profile.key for profile in ARTIFACT_TYPE_PROFILES if profile.readable)


def artifact_profile_for_type(artifact_type: str) -> ArtifactTypeProfile | None:
    return _PROFILE_BY_KEY.get(str(artifact_type or "").strip())


def artifact_registry_payload() -> dict[str, object]:
    return {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "artifact_types": [profile.to_dict() for profile in ARTIFACT_TYPE_PROFILES],
        "json_artifact_types": sorted(JSON_ARTIFACT_TYPES),
        "readable_artifact_types": sorted(READABLE_ARTIFACT_TYPES),
    }


def infer_artifact_type(path: Path) -> str:
    suffix = path.suffix.lower()
    name = path.name.lower()
    if suffix in {".md", ".markdown"}:
        if "agent-handoff-bundle" in name:
            return "agent_handoff_bundle_markdown"
        if "agent-smoke-summary" in name:
            return "agent_smoke_summary_markdown"
        return "markdown"
    if suffix == ".jsonl":
        if "ocr-blocks" in name or "ocr_blocks" in name:
            return "ocr_blocks_jsonl"
        if "location" in name:
            return "location_index_jsonl"
        return "pages_jsonl"
    if suffix == ".json":
        for marker, artifact_type in (
            ("agent-handoff-bundle", "agent_handoff_bundle_json"),
            ("agent-smoke-summary", "agent_smoke_summary_json"),
            ("agent-batch-results", "agent_batch_results"),
            ("layout-table-review-bundle", "layout_table_review_bundle_json"),
            ("backend-scorecard", "optional_backend_scorecard_json"),
            ("candidate-benchmark-plan", "candidate_benchmark_plan_json"),
            ("candidate-plan", "candidate_benchmark_plan_json"),
            ("review-decisions", "review_decisions_json"),
            ("review-checklist", "review_json"),
            ("environment-report", "environment_json"),
            ("environment-lock-compare", "environment_lock_compare_json"),
            ("environment-lock", "environment_lock"),
            ("benchmark-quality-comparison", "quality_comparison_json"),
            ("quality-improvement-queue", "quality_improvement_queue_json"),
            ("visual_check_result", "visual_check_json"),
            ("visual_blocks", "visual_blocks_json"),
            ("ocr-provider-comparison", "ocr_provider_comparison_json"),
            ("ocr_provider_comparison", "ocr_provider_comparison_json"),
            ("external-wrapper-result", "external_wrapper_result_json"),
            ("layout_candidates", "layout_candidates_json"),
            ("layout-candidates", "layout_candidates_json"),
            ("table_candidates", "table_candidates_json"),
            ("table-candidates", "table_candidates_json"),
            ("formula_candidates", "formula_candidates_json"),
            ("formula-candidates", "formula_candidates_json"),
            ("document-vlm-result", "document_vlm_result_json"),
            ("document_vlm_result", "document_vlm_result_json"),
            ("image_positions", "image_positions_json"),
            ("pypdf-metadata", "pdf_metadata_json"),
            ("pdf-metadata", "pdf_metadata_json"),
            ("pypdf-outline", "pdf_outline_json"),
            ("pdf-outline", "pdf_outline_json"),
            ("layout-evidence", "pdf_layout_evidence_json"),
            ("layout_evidence", "pdf_layout_evidence_json"),
            ("pdf-layout-evidence", "pdf_layout_evidence_json"),
            ("summary", "summary_json"),
            ("report", "conversion_report"),
            ("cluster", "clusters_json"),
            ("structure", "structure_json"),
        ):
            if marker in name:
                return artifact_type
        return "json"
    if suffix == ".hocr":
        return "hocr"
    if suffix == ".tsv":
        return "tsv"
    if suffix in {".log", ".txt"}:
        return "text"
    if suffix in {".html", ".htm"}:
        return "html"
    return suffix.lstrip(".") or "artifact"
