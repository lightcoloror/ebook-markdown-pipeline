# Agent Integration

This project is designed for stable AI-agent invocation through a layered interface:

1. Core Python conversion functions.
2. CLI for humans and automation scripts.
3. MCP stdio server for agents.
4. Skills or plugins as thin wrappers around MCP/CLI.

Do not duplicate conversion logic in agent-specific plugins. Keep conversion behavior in `batch_convert_books.py` and expose it through stable wrappers.

Tool-first integration lessons are documented in [TOOL_FIRST_LESSONS.md](TOOL_FIRST_LESSONS.md). Future agents should prefer existing tools and project core functions, then add only orchestration, glue, logging, fallback, quality review, and UI/API wrappers.

The long-term technical direction is documented in [TECHNICAL_DIRECTION.md](TECHNICAL_DIRECTION.md): this project should evolve into a general image/document material recognition tool for AI agents, with Docling as the future default document-understanding backend, MinerU as the complex-document backend, and Umi-OCR/PaddleOCR as local OCR fallback.

The stable agent calling contract is documented in [TOOL_CONTRACT.md](TOOL_CONTRACT.md). Agents should prefer `process_material`, poll long jobs with `get_job_status`, and read outputs through `read_artifact`.

## Recommended Integration

Use MCP for OpenClaw, Hermes Agent, Codex, Claude Code, or other agents that support tool schemas.

```powershell
D:\used-by-codex\ebook_markdown_pipeline\start_mcp.cmd
```

Example MCP server config:

```json
{
  "mcpServers": {
    "ebook-markdown-pipeline": {
      "command": "C:\\path\\to\\ebook_markdown_pipeline\\start_mcp.cmd",
      "args": []
    }
  }
}
```

The same config is available at `examples/mcp_config.json`.
Replace `C:\path\to\ebook_markdown_pipeline` with the real project path.

Before connecting an agent, run the stdio smoke test:

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\scripts\test_mcp_stdio.py
```

Use `--convert` if you also want to test a tiny real TXT conversion.

For routine agent-facing changes, run the fast smoke suite. It covers MCP/HTTP, local CLI, batch handoff, smoke summary fields, and docs contract checks:

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\scripts\test_agent_smoke_suite.py
```

Pass `--output <dir>` to persist `agent-smoke-summary.json/md` as handoff evidence for another session or agent. The JSON report includes `artifacts` and `next_actions`; failed runs include failed test names and per-test rerun commands.

Use `--fail-fast` for local debugging when the first failure is enough; omit it when you want a complete handoff report.

Use `--full` before releases or broad contract changes to include the slower full agent contract test.

## Batch Templates

Repeatable agent batch templates live in `examples/agent-batch/`:

- `batch_manifest.example.json`: a stable manifest shape for conversion, location indexing, and screenshot rebuild jobs.
- `agent_batch_http.py`: deterministic HTTP runner that validates manifests with `--dry-run`, calls `process_material`, polls `get_job_status`, reads `next_actions` artifacts, and writes `agent-batch-results.json`, `agent-batch-summary.md`, and `run_summary.md`.
- `AGENT_PROMPT_TEMPLATE.md`: prompt block for OpenClaw, Hermes, Codex, or another LLM agent.

Use these templates for ordinary multi-file production batches. Use `scripts/stress_agent_http.py` only for concurrency and failure-recovery testing.

When rerunning or optimizing a batch, pass the prior `agent-batch-results.json` as `--baseline-results`. The runner writes `benchmark-quality-comparison.json/md`, links the comparison status from `run_summary.md`, and exposes top-level `next_actions` in `agent-batch-results.json`. If comparison fails, `run_summary.md` includes a copyable recommended rerun command for `--select failed-or-review --rerun-mode recommended`. Use `--fail-on-regression` for unattended agent runs where a lower success rate, lower good rate, higher review/poor rate, higher timeout rate, or higher failed rate should fail the run.

Every dry-run plan and real batch result includes a `selection` block with `select`, `rerun_mode`, `previous_results`, `selected_job_ids`, `selected_count`, and `manifest_job_count`. Use it before claiming a run covered the whole manifest or only a targeted failed/review rerun.

Every dry-run plan and real batch result also includes `contract`, with `schema_version=agent-batch-contract-v1`, `payload_schema_version`, `capabilities`, and `required_fields`. Agents should read `contract.capabilities` before assuming support for newer handoff fields.

Use `scripts/validate_agent_batch_contract.py <agent-batch-results.json|agent-batch-plan.json> --json` when another session or agent needs a quick machine-readable contract check before trusting a handoff artifact.

Freshly generated agent batch plans/results also include `contract_validation`; check that `contract_validation.ok` is true before trusting the handoff fields.

`agent-batch-summary.md`, `run_summary.md`, and `agent-batch-plan.md` also show `Contract validation: ok` or `failed` near the top for quick human/agent review.

If contract validation fails, generated or inspected batch results expose `inspect_contract_validation` in `next_actions` with the validation errors.

Use the MCP/HTTP tool `build_agent_handoff_bundle` or the CLI wrapper `scripts/build_agent_handoff_bundle.py --batch-results <agent-batch-results.json> --output <dir>` to create a lightweight `agent-handoff-bundle.json/md` index for another session. The bundle includes contract validation, attention, selection, artifact summary, next actions, and review items without copying large outputs.

Real batch results also include `artifact_summary` with total/ok/failed read counts, artifact type counts, and failed artifact read records. Check it before drilling into each job's `artifacts`.

Top-level `next_actions` are always present in real or partial batch results. They include `read_run_summary`, `inspect_agent_batch_results`, `build_agent_handoff_bundle`, and conditional `inspect_failed_artifacts` / `inspect_review_items` actions before any quality-comparison actions.

When taking over a previous batch, call `inspect_agent_batch_results` with the prior `agent-batch-results.json`. If the path is unknown, call `list_agent_batch_results` on the likely output root first. These tools return the summary, quality comparison status, `recommended_rerun`, review items, and artifact paths without requiring the agent to parse the whole JSON by hand.

`inspect_agent_batch_results` and `list_agent_batch_results` also return `attention`, a first-pass triage block with `needs_attention` and reasons such as `hard_failed_jobs`, `review_jobs`, `artifact_read_failures`, and `quality_regression`.

For legacy batch results that predate top-level handoff actions, `inspect_agent_batch_results` synthesizes missing `read_run_summary`, `inspect_failed_artifacts`, `inspect_review_items`, and quality-comparison read actions from the current summary fields.

For broad real-sample benchmarks outside agent batches, use `scripts/run_benchmarks.py` with quality gates and `scripts/compare_benchmark_quality.py` to compare a baseline `benchmark-results.json` or `quality-regression-summary.json` against a candidate run. This is the preferred evidence path before changing defaults such as PDF pipeline selection, Docling enablement, or OCR cleanup rules.

## Docker Agent Integration

For Docker-hosted agents, use the HTTP bridge unless the project directory and all converter dependencies are mounted inside the container.

Docker packaging and volume conventions are documented in [DOCKER_USAGE.md](DOCKER_USAGE.md).

Host-side startup:

```powershell
$env:EBOOK_CONVERTER_API_TOKEN = "replace-with-a-local-token"
python D:\used-by-codex\ebook_markdown_pipeline\ebook_converter_http.py --host 0.0.0.0
```

The HTTP port is read from `config/http.env` unless explicitly overridden.

Container-side health check:

```bash
curl -H "Authorization: Bearer replace-with-a-local-token" "http://host.docker.internal:${EBOOK_CONVERTER_HTTP_PORT}/health"
```

The health response includes `schema_version`, `tool_count`, `tools`, `supports_async_jobs`, `supports_artifacts`, `http_config`, `pipeline_capabilities`, and `risk_status`. Agents should use it for capability discovery before making tool calls and should read `http_config.config_path` instead of guessing ports.

Container-side tool call:

```bash
curl -H "Authorization: Bearer replace-with-a-local-token" \
  -H "Content-Type: application/json" \
  -d '{"name":"scan_books","arguments":{"input":"D:\\books","output":"D:\\books-md","recursive":true}}' \
  "http://host.docker.internal:${EBOOK_CONVERTER_HTTP_PORT}/call"
```

The HTTP bridge intentionally reuses the MCP tool names and payloads. Treat it as a Docker transport adapter, not as a separate conversion implementation.

Local Docker smoke test:

```powershell
powershell -ExecutionPolicy Bypass -File D:\used-by-codex\ebook_markdown_pipeline\scripts\run_docker_agent_smoke.ps1
```

The smoke test generates tiny `TXT / FB2 / RTF / EPUB / ODT / AZW3 / MOBI / AZW / PDF` fixtures, starts the HTTP bridge temporarily, converts them through the API, and verifies that the OpenClaw and Hermes containers can call the bridge through `host.docker.internal`.

## MCP Tools

### `process_material`

High-level router for unknown inputs. It calls lightweight inspection, chooses the next tool, starts a background job when needed, and returns `job_id`, `route`, `inspection`, `warnings`, `errors`, and `next_actions`.

Use this as the default entry point for agents.

For `web-content-fetcher` archive folders, `process_material` routes to `process_web_archive` and returns `visual_check/` artifacts directly. It does not start a background job in that route.

### `process_web_archive`

Prepares visual-check artifacts for a `web-content-fetcher` archive folder:

- `visual_check/layout_ocr.md`
- `visual_check/visual_blocks.json`
- `visual_check/table_candidates.json`
- `visual_check/image_positions.json`
- `visual_check/visual_check_result.json`

Use it after `web-content-fetcher archive rebuild --with-visual-check` has generated `rebuild_input/manifest.json`. After this tool writes `visual_check/`, rerun `web-content-fetcher archive rebuild` so the final archive outputs can absorb OCR text, layout warnings, table candidates, and image-position evidence.

### `scan_books`

Scans input files or folders and returns planned conversion pipelines.

Required:

- `input`
- `output`

Useful optional parameters:

- `recursive`
- `include_hidden`
- `output_format`
- `pdf_pipeline_mode`

### `health_check`

Checks required external commands, Python dependencies, CUDA status, and model cache.

Agents can also call `export_environment_report` through MCP/HTTP when they need persistent diagnostics. It returns `markdown_report`, `json_report`, and readable artifacts:

```json
{
  "name": "export_environment_report",
  "arguments": {
    "input": "D:\\materials",
    "output": "D:\\materials\\.reports\\environment",
    "recursive": true
  }
}
```

For persistent environment handoff, run:

```powershell
python scripts\export_environment_report.py --input D:\materials --output D:\materials\.reports\environment
```

This writes `environment-report.md/json` with runtime metadata, raw checks, and the same capability matrix returned by `health_check`.

To compare a future run against a saved environment lock, call `compare_environment_lock`:

```json
{
  "name": "compare_environment_lock",
  "arguments": {
    "lock": "D:\\materials\\.reports\\environment\\environment-lock.json",
    "output": "D:\\materials\\.reports\\environment-compare"
  }
}
```

### `inspect_document`

Lightweight preflight inspection for a file or folder. It does not run heavy document models.

Use it to decide the next tool:

- PDF: returns page count, text-layer ratio, image/layout/table/two-column signals, scanned likelihood, and recommended PDF route.
- Image: returns dimensions, hash, OCR risk warnings, and whether to use location indexing or image-book rebuilding.
- Folder: returns supported document/image counts and sample inspection results.

### `start_conversion`

Starts a background conversion job and returns `job_id`.

Use this for long jobs. Do not block an agent call waiting for Marker or MinerU to finish.

Important options:

- `resume`: default true
- `overwrite`: default false
- `manifest`
- `report_dir`
- `pdf_tool_idle_timeout`
- `pdf_tool_finalize_timeout`
- `docling_timeout`
- `docling_fallback_to_pandoc`
- `mineru_segment_min_pages`
- `mineru_segment_pages`

Reports may include `pdf_fallback_diagnostics` and `docling_diagnostics`. Agents should surface these fields when a job succeeds through fallback, because a successful artifact can still mean a lower-structure fallback pipeline was used.

PDF conversion reports may also include `pdf_outline`, a preview of built-in PDF bookmarks with `level`, `title`, and `page`. When review `next_actions` includes `inspect_pdf_outline`, compare these bookmarks against generated Markdown headings before accepting or replacing the output.

### `get_job_status`

Polls job progress, recent events, and final results.

For conversion jobs, the final response also includes `quality_summary`.
Agents should read it before presenting the generated Markdown as final:

- `quality_summary.counts` shows how many outputs are `good`, `review`, or `poor`.
- `quality_summary.review_items` includes source/output/report paths, quality score, reasons, `suggested_action`, and machine-readable per-item `next_actions`.
- If `review_count` is greater than zero, follow `next_actions` to read `summary_report` and `review_report`, then either show the user the review reason or rerun with a better recommended PDF pipeline.

### `read_report`

Reads a generated `.reports/*.report.json` file.

### `read_pdf_tool_log`

Reads the tail of a persisted Marker/MinerU log file from `.reports/pdf-tool-logs/*.log`.

### `read_artifact`

Reads text-like artifacts returned by other tools, with `max_chars` and `max_lines` limits.

Use this for:

- Markdown outputs.
- JSON reports.
- JSONL previews.
- Review checklists.
- Order reports.
- Tool logs.

Do not use it to read SQLite artifacts directly. For `location_index_sqlite`, call `query_location_index`.

### `build_location_index`

Builds a lightweight page/image-level search index for PDF and image files.

Use this when the user only needs fuzzy location:

- PDF file plus page number.
- Image filename.
- Text snippet around the match.

Important options:

- `ocr=never`: only use existing PDF text layers.
- `ocr=auto`: use PDF text layers first, OCR empty PDF pages and images with Umi-OCR.
- `ocr=always`: OCR every PDF page and image.

Outputs:

- `document_locations.jsonl`
- `document_locations.sqlite`

If one source file fails, the indexer records a `failed` item and continues with the rest of the batch.

### `start_location_index`

Starts `build_location_index` as a background job and returns `job_id`.

Use this instead of `build_location_index` for large folders, image-heavy inputs, or OCR-enabled runs. Poll with `get_job_status`; final job results include `artifacts`.

### `query_location_index`

Searches `document_locations.sqlite` and returns `source`, `source_name`, `kind`, `page`, `location`, `engine`, `snippet`, `match_quality`, and `token_hits`.

The response also includes `search_mode` and `used_query`. The normal path is SQLite FTS; when FTS cannot match, the tool falls back to exact LIKE and then all-token LIKE matching. This is intended for coarse page/image location, not exact bounding-box extraction.

### `rebuild_image_book`

OCRs a folder of screenshots/images, detects duplicate or near-duplicate screenshots, uses page numbers / filename numbers / timestamps / text overlap to infer order, and writes a Markdown draft.

Outputs:

- `book.md`: reconstructed Markdown draft.
- `order.md`: inferred order with confidence and overlap evidence.
- `structure.md/json`: inferred heading/title outline with source image, page number, and order confidence.
- `review.md`: duplicate groups, low-confidence order items, and empty OCR items.
- `pages.jsonl`: per-image OCR and metadata.
- `clusters.json`: duplicate/near-duplicate groups.

### `start_image_book_rebuild`

Starts `rebuild_image_book` as a background job and returns `job_id`.

Use this for large screenshot folders or OCR-enabled image-book rebuilding. Poll with `get_job_status`; progress events include OCR page progress, dedupe, ordering, and write stages.

## Agent Usage Policy

- Prefer `scan_books` before `start_conversion`.
- Run `health_check` before the first conversion in a new environment.
- Use `build_location_index` instead of full conversion when the user only needs to find which page/image contains a keyword.
- Use `start_location_index` instead of `build_location_index` for long or OCR-heavy indexing.
- Use `rebuild_image_book` when the user has unordered screenshots and wants a single Markdown draft with review artifacts.
- Use `start_image_book_rebuild` instead of `rebuild_image_book` for long screenshot folders.
- For PDFs, keep `pdf_pipeline_mode=auto` unless the user explicitly chooses another mode.
- For long-running conversions, call `start_conversion`, then poll `get_job_status`.
- If output quality is questionable, inspect `summary.md`, `review-checklist.md`, per-book report JSON, and PDF tool logs.
- Do not ask an agent to parse ebook/PDF internals directly unless this tool failed and the report/log shows why.

## CLI Fallback

If MCP is unavailable, use the CLI directly:

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\batch_convert_books.py `
  D:\books `
  D:\books-md `
  --recursive `
  --resume `
  --output-format markdown
```

## Stability Contract

The MCP tool names and top-level JSON keys should be treated as stable:

- `job_id`
- `status`
- `events`
- `results`
- `report`
- `log`
- `plans`
- `checks`

Future changes should add fields rather than rename or remove these keys.

Tools that write files should return `schema_version` and `artifacts` when possible. Artifact objects follow `artifact-schema-v1`:

- `type`: stable artifact type, such as `markdown`, `location_index_sqlite`, `pages_jsonl`, `order_report`, or `review_report`.
- `path`: local filesystem path.
- `label`: human-readable label.
- `media_type`: MIME-style content type when known.
- `description`: optional extra detail.
