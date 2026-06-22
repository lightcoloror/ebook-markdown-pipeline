# Changelog

All notable public-facing changes should be recorded here. This project keeps optional heavy backends separate from the minimal local workflow, so release notes should distinguish core behavior from optional enhancements.

## Unreleased

### Added

- Release checklist for public tags and GitHub releases.
- Optional backend scorecard for MarkItDown, OCRmyPDF, pdf-craft, Tabula, CnOCR, Pix2Text, Surya, GOT-OCR, DeepSeek-OCR, olmOCR, Apache Tika, and GROBID.
- Structure repair cleanup audit fields for repeated headers/footers, standalone page numbers, consecutive duplicate lines, and early table-of-contents remnants.
- `enhance_job_artifact` agent tool for safe second-pass Markdown structure enhancement from a completed job id without guessing output paths.
- Soft environment capability checks for FFmpeg/avconv (`media_helper`) and requests/urllib3/chardet compatibility (`python_dependency_consistency`).
- Public-safe GitHub release notes generator that combines `CHANGELOG.md` with release quality-gate evidence and omits local artifact paths by default.
- Quality improvement queue generator for classifying review/poor benchmark outputs into structure, OCR cleanup, Markdown cleanup, and table/layout follow-up work.
- `build_quality_improvement_queue` MCP/HTTP tool and desktop UI advanced action for opening quality queues as review workbenches.

### Changed

- Release quality gate now includes the optional backend scorecard.
- Dragging image-only batches into the UI defaults to image-book recognition instead of location indexing.
- `process_material` now exposes top-level `online_enhancement` guidance and can return a versioned/non-overwriting `enhance_job_artifact` next action when `model_mode=hybrid|online|auto` recommends text-structure repair.
- Output filenames now strip common source-site domain tags before writing Markdown/report artifacts.
- HTTP health/contract responses now expose on-demand service readiness and configured HTTP fallback guidance.
- Quality queue follow-up actions are safe/non-destructive by default; concrete local paths are only included when explicitly requested for private triage.

### Safety

- Online model providers remain explicit enhancement paths only.
- Missing optional heavy backends remain non-fatal for minimal installs.
- Remote provider calls still require explicit `allow_remote=true`; job-artifact enhancement remains local/fake unless the caller opts into an OpenAI-compatible provider.
