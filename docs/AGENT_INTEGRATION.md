# Agent Integration

This project is designed for stable AI-agent invocation through a layered interface:

1. Core Python conversion functions.
2. CLI for humans and automation scripts.
3. MCP stdio server for agents.
4. Skills or plugins as thin wrappers around MCP/CLI.

Do not duplicate conversion logic in agent-specific plugins. Keep conversion behavior in `batch_convert_books.py` and expose it through stable wrappers.

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

## Batch Templates

Repeatable agent batch templates live in `examples/agent-batch/`:

- `batch_manifest.example.json`: a stable manifest shape for conversion, location indexing, and screenshot rebuild jobs.
- `agent_batch_http.py`: deterministic HTTP runner that calls `process_material`, polls `get_job_status`, reads `next_actions` artifacts, and writes `agent-batch-results.json` plus `agent-batch-summary.md`.
- `AGENT_PROMPT_TEMPLATE.md`: prompt block for OpenClaw, Hermes, Codex, or another LLM agent.

Use these templates for ordinary multi-file production batches. Use `scripts/stress_agent_http.py` only for concurrency and failure-recovery testing.

## Docker Agent Integration

For Docker-hosted agents, use the HTTP bridge unless the project directory and all converter dependencies are mounted inside the container.

Docker packaging and volume conventions are documented in [DOCKER_USAGE.md](DOCKER_USAGE.md).

Host-side startup:

```powershell
$env:EBOOK_CONVERTER_API_TOKEN = "replace-with-a-local-token"
python D:\used-by-codex\ebook_markdown_pipeline\ebook_converter_http.py --host 0.0.0.0 --port 8765
```

Container-side health check:

```bash
curl -H "Authorization: Bearer replace-with-a-local-token" http://host.docker.internal:8765/health
```

The health response includes `schema_version`, `tool_count`, `tools`, `supports_async_jobs`, and `supports_artifacts`. Agents should use it for capability discovery before making tool calls.

Container-side tool call:

```bash
curl -H "Authorization: Bearer replace-with-a-local-token" \
  -H "Content-Type: application/json" \
  -d '{"name":"scan_books","arguments":{"input":"D:\\books","output":"D:\\books-md","recursive":true}}' \
  http://host.docker.internal:8765/call
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

### `get_job_status`

Polls job progress, recent events, and final results.

For conversion jobs, the final response also includes `quality_summary`.
Agents should read it before presenting the generated Markdown as final:

- `quality_summary.counts` shows how many outputs are `good`, `review`, or `poor`.
- `quality_summary.review_items` includes source/output/report paths, quality score, reasons, and a machine-readable `suggested_action`.
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
