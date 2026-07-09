# Decision: Photo or Scanned Table to XLSX

Date: 2026-07-09
Status: accepted for local personal pipeline planning
Project: `D:\used-by-codex\ebook_markdown_pipeline`

## Decision

For the workflow:

```text
photo / scanned paper Excel-like table
-> recognize table structure and cell text
-> output editable .xlsx
```

the project should not treat the existing Markdown/PDF conversion pipeline as sufficient. It should add a dedicated table-to-xlsx lane.

Chosen backend order:

1. PaddleOCR `TableRecognitionPipelineV2` / PP-TableMagic as the preferred heavy backend.
2. `img2table` as the low-friction baseline for bordered/light-background tables.
3. `RapidTable` as a structure-recognition fallback that can emit HTML/logic structure and be converted to `.xlsx`.
4. Existing `pdf_table`, PaddleOCR-VL, Surya, Camelot, Tabula, and pdfplumber remain comparison or evidence backends, not the primary `.xlsx` route.

## Why

The existing project can already produce table evidence such as Markdown, HTML, CSV, JSON, overlays, and `table-candidates.json`, but the main output formats are still Markdown, HTML, and text. It does not currently provide a direct editable `.xlsx` output contract for scanned or photographed tables.

PaddleOCR TableRecognitionPipelineV2 is the best primary fit because official documentation describes a table recognition pipeline for documents/images with table classification, table structure recognition, cell detection, OCR, orientation correction, and unwarping modules. Its result object supports `save_to_xlsx()`, `save_to_html()`, `save_to_json()`, and visual output. Source: <https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/table_recognition_v2.html>

`img2table` is the best lightweight baseline because it directly targets PDF and image table extraction, supports OCR backends, returns structured table objects, and can export extracted tables to `.xlsx`. Source: <https://github.com/xavctn/img2table>

`RapidTable` is useful as a fallback/structure engine because it integrates PP-Structure and ModelScope-style table recognition algorithms and returns HTML-like table structure. It is less direct than PaddleOCR/img2table for Excel output but useful for comparison. Source: <https://github.com/RapidAI/RapidTable>

## Boundary

Do not promise perfect recovery of an original Excel file. The realistic output is an editable `.xlsx` draft.

Expected recoverable information:

- cell text
- row/column grid
- some merged-cell structure
- one worksheet per detected table or per page/table
- review metadata and confidence signals

Not reliably recoverable:

- formulas
- original formatting
- conditional formatting
- data validation
- filters
- exact column widths
- colors and fonts
- hidden rows/columns

## Integration Shape

Add a candidate-only worker first:

```text
scripts/table_to_xlsx_worker.py
```

Initial contract:

- `mode=plan`: report chosen backend and required environment without downloading models.
- `mode=fake`: write a small valid `.xlsx` plus normalized sidecar artifacts for tests.
- `mode=execute`: initially consume already-structured table evidence such as CSV or `table-candidates.json` and export `.xlsx`; heavy image recognition remains explicit and environment-gated.

Future recognition backends:

- `--backend paddle_table_v2`
- `--backend img2table`
- `--backend rapidtable`

Shared normalized artifacts:

- `table-candidates.json`
- `table-to-xlsx-result.json`
- `table.xlsx`
- optional overlay images
- optional backend raw JSON/HTML

Promotion rule:

No backend becomes default from README claims or one private sample. Promotion requires a small benchmark set containing:

- clean printed grid table
- photographed skewed table
- scanned bordered table
- borderless table
- merged-cell table
- Chinese/English mixed table
- numeric-heavy table

Each run should compare:

- table count
- cell count
- non-empty cell count
- merged-cell support
- OCR error sample
- manual review flags
- `.xlsx` openability

## Existing Project Mapping

Keep:

- `pdf_table_worker.py`: table-page candidate evidence, not final Excel route.
- PaddleOCR-VL wrapper: layout-heavy document evidence, not first-choice table-to-xlsx backend.
- Camelot/Tabula/pdfplumber: text-layer PDF table extractors, useful only when the PDF has extractable text.
- DocLayout-YOLO: table/region detection evidence only.

Add:

- `table_to_xlsx_worker.py`: dedicated Excel export lane.
- Candidate backend registry entry: `table_to_xlsx`.
- Optional artifact type: `table_xlsx`.
- Tests that validate `.xlsx` artifact generation without installing models.

## Next Step

Create a first patch that adds the candidate-only worker and tests without installing PaddleOCR, img2table, RapidTable, or any model weights.

## Implementation Update

2026-07-09 continued execution:

- Added `scripts/table_to_xlsx_worker.py` in `D:\used-by-codex\ebook_markdown_pipeline`.
- Added `scripts/test_table_to_xlsx_worker.py`.
- Registered `table_to_xlsx` in `candidate_backend_registry.py`.
- Added `table_to_xlsx` to `docs/BACKENDS.md`.
- Added `table_xlsx` expectation to the `pdf_table` benchmark class in `scripts/build_candidate_benchmark_manifest.py`.
- Kept the worker candidate-only and explicit. It does not install dependencies, download models, or process private documents by default.

Implemented modes:

- `mode=plan`: reports backend readiness and optional dependency status.
- `mode=fake`: creates a minimal valid `.xlsx` for contract tests.
- `mode=execute` with existing CSV/Markdown evidence: exports an editable `.xlsx` draft.
- `mode=execute --backend img2table`: calls `img2table` only when already installed; otherwise returns a structured failure.
- `mode=execute --backend paddle_table_v2`: stays gated unless `paddleocr` is installed and the caller explicitly passes `--allow-model-download` or `--paddlex-config`.

Verification completed:

- `python -B scripts\test_table_to_xlsx_worker.py`
- `python -B scripts\test_candidate_backend_registry.py`
- `python -B scripts\test_candidate_benchmark_manifest.py`
- `git diff --check`
- `python -B scripts\check_project_readiness.py` -> `42/42 passed`

Current boundary:

- Real image/table recognition has an adapter path but was not executed.
- `img2table`, PaddleOCR, RapidTable, and model weights were not installed.
- Next real experiment should use non-private fixture images and compare `img2table` vs PaddleOCR TableRecognitionPipelineV2 output quality before promotion.
