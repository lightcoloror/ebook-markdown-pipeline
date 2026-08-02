# Changelog

<!-- Documentation update: 2026-08-01 23:35:28 | Codex (GPT-5) | Added and synchronized the explicit online-only/shared-VKP mode. -->
<!-- Documentation update: 2026-08-02 00:01:43 | Codex (GPT-5) | Recorded fast shared-gateway health discovery and Agent/HTTP/MCP regression evidence. -->
<!-- Documentation update: 2026-08-02 00:09:00 | Codex (GPT-5) | Classified required versus optional online-only routes and removed blocking UI runtime probes. -->
<!-- Documentation update: 2026-08-02 00:28:09 | Codex (GPT-5) | Recorded real VKP loopback integration and consent/runtime boundary fixes. -->
<!-- Documentation update: 2026-08-02 00:34:42 | Codex (GPT-5) | Added isolated real-LiteLLM loopback coverage without supplier network calls. -->
<!-- Documentation update: 2026-08-02 00:57:12 | Codex (GPT-5) | Added automatic shared-VKP VLM execution and normalized nested remote-request evidence. -->
<!-- Documentation update: 2026-08-02 01:44:25 | Codex (GPT-5) | Added collision-safe online outputs and a public 24-format online-only matrix. -->
<!-- Documentation update: 2026-08-02 01:58:12 | Codex (GPT-5) | Added a fail-closed synthetic real-supplier smoke contract and structure-stage network evidence. -->
<!-- Documentation update: 2026-08-02 02:02:36 | Codex (GPT-5) | Fixed successful no-op structure responses being mislabeled as fallback. -->
<!-- Documentation update: 2026-08-02 02:08:04 | Codex (GPT-5) | Completed fast selected-provider discovery and removed historical private-path release blockers. -->
<!-- Documentation update: 2026-08-02 02:34:59 | Codex (GPT-5) | Added a no-network goal-level completion audit for the online-only/shared-VKP mode. -->
<!-- Documentation update: 2026-08-02 08:28:42 | Codex (GPT-5) | Recorded the authorized synthetic real-supplier smoke and bounded shared-gateway startup readiness fix. -->
<!-- Documentation update: 2026-08-02 08:40:28 | Codex (GPT-5) | Normalized provider-added outer Markdown fences found by the real supplier smoke. -->

All notable public-facing changes should be recorded here. This project keeps optional heavy backends separate from the minimal local workflow, so release notes should distinguish core behavior from optional enhancements.

## Unreleased

### Added

- Full `online_only` document pipeline for PDFs, images, ebooks, and Office/text formats, with remote OCR/structure inference, versioned Markdown, stage manifests, and resume support.
- Shared VKP gateway adapter that reuses VKP provider routes, LiteLLM gateway, consent/cost policy, and Windows DPAPI credential references without copying API keys.
- Secretless loopback integration test that exercises real VKP route resolution, LiteLLM config rendering, DPAPI gateway authorization, consent, trusted connector, runtime client, and online document conversion without contacting a supplier.
- Isolated LiteLLM process integration test that verifies real gateway master-key authentication and local OCR/chat forwarding while removing supplier API keys from the subprocess environment.
- Automatic online-only VLM stage for standalone images and deterministic layout-heavy PDF candidates, with `auto|always|never` controls, page caps, OCR-preserving fusion, and shared VKP semantic-frame routing.
- Public no-network online-only regression matrix covering all 17 supported document/ebook extensions and 7 image extensions.
- Versioned synthetic supplier smoke tool that defaults to planning and strictly verifies remote OCR, VLM layout, and text-structure evidence when explicitly executed.
- Goal-level online mode completion audit that verifies shared routes, one VKP credential source, compatible provider discovery, public interfaces, pinned source commits, and five-field decision records without reading keys or calling suppliers.
- Authorized synthetic real-supplier smoke evidence covering remote OCR, VLM layout, and text-structure stages under a USD 0.10 execution cap.
- `start_online_conversion` MCP/HTTP/Agent tool, `process_material(model_mode=online_only)` routing, CLI entrypoint, and a desktop UI mode with explicit data-export/cost confirmation.
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
- HTTP/MCP capability discovery now uses a no-secret fast VKP route/listener probe and reuses one dependency scan, preventing online-only discovery from exceeding Agent health timeouts.
- Online-only readiness now treats remote OCR and text structure as required while VLM layout remains optional; UI preflight no longer blocks or freezes when only the optional VLM route is absent.
- Shared VKP consent now clamps retries to the route-locked ceiling and authorizes total attempts including retries without increasing the user cost cap.
- Shared VKP runtime access now grants only the exact artifact paths for each call, restores the prior environment afterward, and serializes the temporary authorization window across concurrent jobs.
- Shared VKP result normalization now detects remote execution evidence across generic task wrappers and nested runtime/network-accounting fields instead of under-reporting successful VLM/text exports.
- Online-only batches now add source-format disambiguators only when same-directory cleaned stems collide, preventing EPUB/AZW3/MOBI-style outputs from overwriting one another while preserving normal single-file names.
- Online text-structure stage summaries now expose redacted route, consent, provider mode, and remote-request evidence for top-level audits and strict supplier smoke validation.
- Successful non-empty remote structure responses are now `ok` even when unchanged; `content_changed` reports no-op versus rewrite without conflating it with fallback.
- Fast shared-VKP health now maps task-route profile bindings to the currently selected OCR/VLM/text providers without importing secrets or the full runtime.
- Shared VKP on-demand startup now uses bounded readiness polling, avoiding false failures while LiteLLM/Uvicorn is still binding its loopback port.
- Online text-structure responses now remove only provider-added outer Markdown fences while preserving genuine nested code blocks and recording the normalization in artifacts.
- Historical public docs and offline status evidence now use portable repository/workspace references; the full public release check passes.
- Quality queue follow-up actions are safe/non-destructive by default; concrete local paths are only included when explicitly requested for private triage.

### Safety

- Local-first remains the default; full online conversion is explicit and requires data-export confirmation plus a positive cost ceiling.
- Local supplier-smoke, consent, quality, and test artifacts under `.local/` are ignored and never part of the public source tree.
- Online-only output is versioned and non-overwriting by default, with consent/execution artifacts and no serialized API key values.
- Online model providers remain explicit enhancement paths only.
- Missing optional heavy backends remain non-fatal for minimal installs.
- Remote provider calls still require explicit `allow_remote=true`; job-artifact enhancement remains local/fake unless the caller opts into an OpenAI-compatible provider.
