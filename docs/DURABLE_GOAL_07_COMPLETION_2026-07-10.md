# Durable Goal 07 Completion Report

Date: 2026-07-10
Project: `D:\used-by-codex\ebook_markdown_pipeline`
Goal status: complete

## Scope and boundaries

The pipeline now exposes a positional-input-free structured health check, separates minimal readiness from optional backend availability, and proves five synthetic local material classes through Markdown, manifest, quality, fallback, resume, job/artifact, and handoff contracts.

No dependency or model was installed or upgraded. No external OCR/VLM API was called. No private material was read or uploaded. No persistent HTTP/UI service was started, and port 8765 was not changed. Planned-only providers remain planned-only.

## Checkpoint evidence

| Checkpoint | Result | Evidence |
| --- | --- | --- |
| CP1 health CLI | Passed | `docs/DURABLE_GOAL_07_CP1_EVIDENCE_2026-07-10.md`; `python batch_convert_books.py --health-check` returned `health-check-v2`, `minimal_ok=true`, `status=degraded_optional`, exit 0. |
| CP2 five fixtures | Passed 5/5 | `benchmarks/runs/durable-goal-07-fixtures/cp2-20260710/baseline-summary.json` |
| CP3 fallback/resume | Passed | `scripts/test_batch_control_flow.py`; `scripts/test_delimited_text_fallback.py`; PDF fixture reports preserve `pymupdf-text(fallback from pymupdf4llm)` diagnostics. |
| CP4 deterministic quality risks | Passed | `scripts/test_deterministic_quality_risks.py`; `benchmarks/runs/durable-goal-07-fixtures/cp4-20260710/baseline-summary.json` |
| CP5 agent contracts | Passed | `benchmarks/runs/durable-goal-07-fixtures/cp5-20260710/baseline-summary.json`; `handoff-bundle.json`; `scripts/test_job_artifact_schema.py`; service/HTTP/MCP/handoff tests. |
| CP6 docs and registry | Passed | `docs/AGENT_INTEGRATION.md`; `docs/SERVICE_CONTRACT.md`; `docs/RELEASE_CHECKLIST.md`; `D:\used-by-codex\tool-registry.json`. |

## Five-class baseline

The CP5 baseline is synthetic and local-only. All cases produced Markdown, manifest, and quality reports:

| Fixture | Backend evidence | Result |
| --- | --- | --- |
| EPUB | Pandoc | Passed |
| Text PDF | `pymupdf-text(fallback from pymupdf4llm)` | Passed |
| Complex PDF | `pymupdf-text(fallback from pymupdf4llm)` | Passed |
| Office DOCX | MarkItDown | Passed |
| Image set | `image_book_rebuilder_no_ocr` | Passed |

The handoff bundle uses `material-consumer-handoff-v1`, supports `bookwiki` and `video_knowledge_pipeline`, uses local artifact refs only, and sets `network_transfer_allowed=false`.

## Unified contracts

- Job schema: `ebook-job-v1`
- Artifact schema: `artifact-schema-v1`
- Consumer handoff schema: `material-consumer-handoff-v1`
- Optional idle HTTP state: `stopped-by-design`
- HTTP auto-start: `false`
- Registry health command: `python batch_convert_books.py --health-check`

## Validation record

- `python batch_convert_books.py --health-check`: passed; minimal core ready, optional gaps degraded/missing without exit 1.
- `python scripts\run_quality_gate.py`: passed 7/7; evidence at `benchmarks/runs/quality-gate/20260710-202233`.
- `python -m unittest discover -s tests -v`: passed, 1 compatibility discovery test.
- `python -B scripts\check_project_readiness.py`: passed 42/42.
- `python -B scripts\test_docs_contract.py`: passed.
- `python -m py_compile ...`: passed.
- `git diff --check`: passed.
- Full pytest compatibility run: 80 passed and one stale Docling assertion failed; the assertion was corrected to test auto fallback and forced Docling separately, then its direct and pytest-targeted tests passed.
- Post-fix full pytest run: 80 passed; `test_agent_contract.py` was terminated by Windows with return code `0xFFFFFFFF` and no assertion output while another unrelated process was under high memory load. The same agent contract was immediately rerun alone and passed, including automatic shutdown of its short-lived local HTTP server. Final coverage evidence is therefore 80 suite tests plus the isolated agent contract pass; there is no single-run 81/81 result.

JUnit evidence is stored under `C:\Users\lightcolor\Documents\Codex\2026-07-04\ebook-markdown-pipeline-continuation\outputs`.

## Optional backend state

Available core and local paths include Pandoc, Calibre, PyMuPDF/PyMuPDF4LLM fallback, MinerU cache, Marker, MarkItDown, RapidOCR, Tesseract, and CUDA. Optional missing or degraded paths include Docling, OCRmyPDF, Camelot/Tabula, CnOCR, GOT-OCR, DeepSeek-OCR, Tika, GROBID, pdf-craft, olmOCR, image-layout VLM wrappers, MonkeyOCR, dots.mocr, DocLayout-YOLO, and pdf_table. These remain scenario-driven installation suggestions only.

## Repository state

Changes are left uncommitted and unpushed for user review. Generated private material, model downloads, external uploads, and persistent services are absent from this goal run.