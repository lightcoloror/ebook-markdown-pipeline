# Changelog

All notable public-facing changes should be recorded here. This project keeps optional heavy backends separate from the minimal local workflow, so release notes should distinguish core behavior from optional enhancements.

## Unreleased

### Added

- Release checklist for public tags and GitHub releases.
- Optional backend scorecard for MarkItDown, OCRmyPDF, pdf-craft, Tabula, CnOCR, Pix2Text, Surya, GOT-OCR, DeepSeek-OCR, olmOCR, Apache Tika, and GROBID.
- Structure repair cleanup audit fields for repeated headers/footers, standalone page numbers, consecutive duplicate lines, and early table-of-contents remnants.
- `enhance_job_artifact` agent tool for safe second-pass Markdown structure enhancement from a completed job id without guessing output paths.
- Soft environment capability checks for FFmpeg/avconv (`media_helper`) and requests/urllib3/chardet compatibility (`python_dependency_consistency`).

### Changed

- Release quality gate now includes the optional backend scorecard.
- Dragging image-only batches into the UI defaults to image-book recognition instead of location indexing.
- `process_material` now exposes top-level `online_enhancement` guidance and can return a versioned/non-overwriting `enhance_job_artifact` next action when `model_mode=hybrid|online|auto` recommends text-structure repair.

### Safety

- Online model providers remain explicit enhancement paths only.
- Missing optional heavy backends remain non-fatal for minimal installs.
- Remote provider calls still require explicit `allow_remote=true`; job-artifact enhancement remains local/fake unless the caller opts into an OpenAI-compatible provider.
