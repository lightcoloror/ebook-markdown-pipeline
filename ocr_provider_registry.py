from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


OCR_PROVIDER_REGISTRY_SCHEMA_VERSION = "ocr-provider-registry-v1"


@dataclass(frozen=True)
class OcrProviderProfile:
    key: str
    display_name: str
    kind: str
    executable: bool
    health_name: str
    install_cost: str
    default_status: str
    default_policy: str
    command_hint: str
    artifact_contract: tuple[str, ...]
    best_for: str
    risk: str
    tasks: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["schema_version"] = OCR_PROVIDER_REGISTRY_SCHEMA_VERSION
        return payload


def normalize_ocr_provider_name(value: str) -> str:
    return value.lower().replace("-", "_").replace(".", "_").replace(" ", "_").strip()


OCR_PROVIDERS: tuple[OcrProviderProfile, ...] = (
    OcrProviderProfile(
        key="rapidocr",
        display_name="RapidOCR",
        kind="python_native_ocr",
        executable=True,
        health_name="RapidOCR",
        install_cost="low/medium",
        default_status="available_when_installed",
        default_policy="optional comparison/fallback; not default unless explicitly selected or Umi fails",
        command_hint="python scripts/compare_ocr_providers.py <images> --providers rapidocr",
        artifact_contract=("ocr-provider-comparison.json", "ocr-provider-comparison.md", "ocr-blocks.jsonl"),
        best_for="CPU-friendly OCR comparison and scriptable fallback for screenshots/images",
        risk="runtime backend selection must avoid noisy CUDA fallback when dependencies are mismatched",
        tasks=("text_ocr", "ocr_blocks"),
    ),
    OcrProviderProfile(
        key="cnocr",
        display_name="CnOCR",
        kind="python_native_chinese_ocr",
        executable=True,
        health_name="CnOCR",
        install_cost="low/medium",
        default_status="available_when_installed",
        default_policy="comparison-only Chinese/English OCR provider; not default routing",
        command_hint="python scripts/compare_ocr_providers.py <images> --providers cnocr",
        artifact_contract=("ocr-provider-comparison.json", "ocr-provider-comparison.md", "ocr-blocks.jsonl"),
        best_for="Chinese/English OCR comparison before changing local OCR defaults",
        risk="model/runtime cost and language-specific quality must be benchmarked first",
        tasks=("text_ocr", "chinese_ocr", "ocr_blocks"),
    ),
    OcrProviderProfile(
        key="umi",
        display_name="Umi-OCR / PaddleOCR-json",
        kind="external_process_ocr",
        executable=True,
        health_name="Umi-OCR/PaddleOCR-json",
        install_cost="medium",
        default_status="available_when_configured",
        default_policy="preferred practical Windows local OCR path when configured; default only through image OCR auto policy",
        command_hint="python scripts/compare_ocr_providers.py <images> --providers umi --umi-paddle-exe <exe> --umi-paddle-module <py>",
        artifact_contract=("ocr-provider-comparison.json", "ocr-provider-comparison.md", "ocr-blocks.jsonl"),
        best_for="existing Umi-OCR desktop/PaddleOCR-json setups with stable block output",
        risk="external process path can be missing or permission-limited; keep graceful fallback",
        tasks=("text_ocr", "ocr_blocks"),
    ),
    OcrProviderProfile(
        key="doctr",
        display_name="docTR",
        kind="candidate_python_ocr",
        executable=False,
        health_name="docTR",
        install_cost="medium/heavy",
        default_status="planned_only",
        default_policy="candidate-only OCR detection+recognition benchmark; never default routing",
        command_hint="python scripts/doctr_ocr_worker.py --input <image> --output <run-dir> --mode plan",
        artifact_contract=("ocr-provider-comparison.json", "ocr-provider-comparison.md", "ocr-blocks.jsonl"),
        best_for="Python-native detection+recognition API comparison on clean image/PDF page samples",
        risk="model/runtime setup not installed by this project; compare only after fake/fixture contract exists",
        tasks=("text_ocr", "detection", "recognition", "ocr_blocks"),
    ),
    OcrProviderProfile(
        key="tesseract",
        display_name="Tesseract",
        kind="candidate_classic_ocr",
        executable=False,
        health_name="Tesseract",
        install_cost="medium",
        default_status="planned_only",
        default_policy="candidate-only direct OCR/hOCR/TSV baseline; not default direct OCR route; OCRmyPDF remains the scanned-PDF path",
        command_hint="python scripts/tesseract_ocr_worker.py --input <image> --output <run-dir> --mode plan",
        artifact_contract=("ocr-provider-comparison.json", "ocr-provider-comparison.md", "ocr-blocks.jsonl", "hocr", "tsv"),
        best_for="classic OCR baseline and standards-compatible hOCR/TSV block evidence",
        risk="language data and command availability vary; do not bypass OCRmyPDF for scanned PDFs by default",
        tasks=("text_ocr", "hocr", "tsv", "ocr_blocks"),
    ),
    OcrProviderProfile(
        key="surya_ocr",
        display_name="Surya OCR",
        kind="candidate_layout_ocr_wrapper",
        executable=False,
        health_name="Surya wrapper",
        install_cost="heavy",
        default_status="planned_only",
        default_policy="candidate-only OCR/layout/reading-order comparison; never default routing",
        command_hint="python scripts/surya_image_to_md.py --input <image> --output <run-dir> --mode ocr --dry-run",
        artifact_contract=("markdown", "ocr-provider-comparison.json", "ocr-blocks.jsonl", "layout_candidates_json"),
        best_for="layout-heavy screenshots where OCR, reading order, and table evidence should be compared together",
        risk="model/runtime may be heavy or server-backed; explicit only",
        tasks=("text_ocr", "layout", "reading_order", "table", "ocr_blocks"),
    ),
    OcrProviderProfile(
        key="pix2text_text",
        display_name="Pix2Text text-only",
        kind="candidate_formula_text_wrapper",
        executable=False,
        health_name="Pix2Text wrapper",
        install_cost="medium/heavy",
        default_status="planned_only",
        default_policy="candidate-only Chinese text/formula/image-page comparison; not default OCR route",
        command_hint="python scripts/pix2text_image_to_md.py --input <image> --output <run-dir> --dry-run",
        artifact_contract=("markdown", "formula_candidates_json", "ocr-provider-comparison.json", "ocr-blocks.jsonl"),
        best_for="Chinese screenshots and formula-heavy images where text and formula preservation matter",
        risk="may load multiple OCR/formula models; compare on targeted samples before promotion",
        tasks=("text_ocr", "formula", "image_markdown", "ocr_blocks"),
    ),
)


_BY_KEY = {normalize_ocr_provider_name(profile.key): profile for profile in OCR_PROVIDERS}
_BY_DISPLAY = {normalize_ocr_provider_name(profile.display_name): profile for profile in OCR_PROVIDERS}
for profile in OCR_PROVIDERS:
    _BY_DISPLAY[normalize_ocr_provider_name(profile.health_name)] = profile


def ocr_provider_for_key(key: str) -> OcrProviderProfile | None:
    return _BY_KEY.get(normalize_ocr_provider_name(key))


def ocr_provider_for_display(name: str) -> OcrProviderProfile | None:
    return _BY_DISPLAY.get(normalize_ocr_provider_name(name))


def executable_ocr_provider_keys() -> tuple[str, ...]:
    return tuple(profile.key for profile in OCR_PROVIDERS if profile.executable)


def ocr_provider_registry_payload() -> dict[str, Any]:
    return {
        "schema_version": OCR_PROVIDER_REGISTRY_SCHEMA_VERSION,
        "execution_policy": "compare_only_no_model_install",
        "remote_call_enabled": False,
        "model_install_enabled": False,
        "providers": [profile.to_dict() for profile in OCR_PROVIDERS],
    }

