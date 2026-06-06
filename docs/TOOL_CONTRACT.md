# Agent Tool Contract

This document defines the stable calling contract for AI agents using this project as a general document/image material recognition tool.

## Stable Entry Points

Preferred order:

1. `process_material`
2. `get_job_status`
3. `read_artifact`
4. Specialist tools only when needed

Agents should not directly parse PDFs, images, temporary directories, SQLite files, or model outputs when a tool exists for that purpose.

## Main Router: `process_material`

Use `process_material` as the default entry point for unknown input.

Required:

- `input`: file or folder path.
- `output`: output folder path.

Optional:

- `intent`: `auto`, `convert`, `locate`, or `rebuild`.
- `query`: keyword or phrase to locate.
- `recursive`: default `true`.
- `include_hidden`: default `false`.
- `output_format`: `markdown`, `html`, or `text`.
- `image_book_threshold`: default `8`.
- `ocr`: `auto`, `always`, or `never`.

Routing rules:

- Documents and ebooks route to `start_conversion`.
- PDFs route to `start_conversion` with a PDF pipeline selected from preflight signals.
- Image folders below `image_book_threshold` route to `start_location_index`.
- Image folders at or above `image_book_threshold` route to `start_image_book_rebuild`.
- `web-content-fetcher` archive folders with `rebuild_input/manifest.json` route to `process_web_archive`.
- Any input with `query` routes to `start_location_index`, then returns a `next_actions` entry for `query_location_index`.
- Unsupported or missing inputs return `status=unsupported` and do not start a job.

Return shape:

```json
{
  "status": "routed",
  "route": "start_location_index",
  "inspection": {},
  "delegated": {},
  "job_id": "job-...",
  "warnings": [],
  "errors": [],
  "next_actions": []
}
```

## Long Jobs

The following tools are long-running by design:

- `start_conversion`
- `start_location_index`
- `start_image_book_rebuild`
- `process_material` when it starts any of the above

`process_web_archive` is synchronous in the current implementation. It may run screenshot OCR when a screenshot is available, but it returns direct artifacts instead of a `job_id`.

Agents must poll:

```json
{
  "name": "get_job_status",
  "arguments": {
    "job_id": "job-..."
  }
}
```

Stop polling when `status` is not `running`.

Stable job fields:

- `job_id`
- `kind`
- `status`
- `started_at`
- `finished_at`
- `input`
- `output`
- `total`
- `completed`
- `events`
- `results`
- `artifacts`
- `quality_summary`
- `warnings`
- `errors`
- `next_actions`
- `error`

For conversion jobs, `quality_summary` is available after completion:

```json
{
  "counts": {
    "good": 3,
    "review": 1
  },
  "review_count": 1,
  "review_items": [
    {
      "source": "D:\\input\\book.pdf",
      "output": "D:\\output\\book.md",
      "report": "D:\\output\\.reports\\book.report.json",
      "quality_level": "review",
      "quality_score": 74,
      "quality_reasons": ["没有 Markdown 标题，章节层级可能缺失"],
      "suggested_action": "run_compare_pipelines_or_rerun_recommended_pdf_backend",
      "next_actions": [
        {
          "action": "read_report",
          "path": "D:\\output\\.reports\\book.report.json",
          "why": "inspect converter diagnostics and quality reasons"
        },
        {
          "action": "compare_pdf_pipelines",
          "pipelines": "mineru,docling,pymupdf4llm",
          "why": "compare structure recovery rather than trusting one parser"
        }
      ]
    }
  ]
}
```

Agents should treat `quality_summary.review_count > 0` as a prompt to read the `summary_report` or `review_report` before presenting the output as final.

Review checklist JSON entries also include machine-readable `next_actions`. These actions are advisory, not automatic permission to overwrite files. Prefer versioned reruns and ask the user before destructive replacement.

## Batch Quality Baselines

Agent batch runs should preserve `agent-batch-results.json` as the machine-readable handoff artifact. When a previous run exists, invoke `examples/agent-batch/agent_batch_http.py` with:

- `--baseline-results <prior agent-batch-results.json>`
- `--fail-on-regression` for unattended runs that must fail on quality regression

The runner writes:

- `benchmark-quality-comparison.json`
- `benchmark-quality-comparison.md`

`run_summary.md` includes the quality comparison status and Markdown report path. A comparison status of `failed` means one or more configured regression checks failed. The default checks guard against lower success rate, lower good rate, higher review/poor rate, higher timeout rate, and higher failed rate.

When baseline comparison is enabled, `agent-batch-results.json` also includes top-level `next_actions`. Agents should first read `read_quality_comparison` / `read_quality_comparison_json`; if `rerun_failed_or_review` is present, use its `command_args` or `powershell_command` to rerun with `--select failed-or-review --rerun-mode recommended` and keep the prior results as the baseline. `run_summary.md` mirrors this as a copyable recommended rerun command.

`agent-batch-plan.json` and `agent-batch-results.json` include a `selection` block: `select`, `rerun_mode`, `previous_results`, `selected_job_ids`, `selected_count`, `manifest_job_count`, and `selection_ratio`. Agents should use this block to distinguish full runs from targeted reruns.

`agent-batch-results.json` includes `artifact_summary` with total/ok/failed artifact read counts, `type_counts`, and `failed_artifacts`. Agents should inspect this before assuming all referenced artifacts were readable.

Real and partial batch results include top-level `next_actions` for handoff. Baseline comparisons may append quality-comparison actions, but agents should first follow `read_run_summary` and `inspect_agent_batch_results`, then handle conditional `inspect_failed_artifacts` and `inspect_review_items`.

Agents taking over an existing batch should call `inspect_agent_batch_results` on `agent-batch-results.json` before inventing paths or parsing the whole file themselves. If the exact results path is unknown, call `list_agent_batch_results` on the output root first and inspect the newest or most relevant item. These tools return summary counts, quality comparison status, top-level `next_actions`, `recommended_rerun`, extracted review items, and artifact paths for `run_summary.md` / quality comparison reports.

The inspect/list tools include an `attention` triage block with `needs_attention`, reason codes, hard-failed count, review count, artifact failure count, quality comparison status, and partial-run status. Use it to decide whether to inspect details before accepting a batch.

`inspect_agent_batch_results` is backward-compatible with older `agent-batch-results.json` files. If top-level handoff actions are missing, it synthesizes `read_run_summary`, `inspect_failed_artifacts`, `inspect_review_items`, and quality-comparison read actions from `summary`, `artifact_summary`, and `quality_comparison`.

For this comparison, agent-batch `review` means completed-with-review rather than transport failure. It contributes to completion success but increases the review/poor quality rate, so agents should report it as usable output that still needs inspection.

## Environment Capabilities

HTTP `/health` returns the transport contract plus lightweight operating status:

```json
{
  "ok": true,
  "transport": "http",
  "http_config": {
    "config_path": "D:\\used-by-codex\\ebook_markdown_pipeline\\config\\http.env",
    "local_url": "http://127.0.0.1:9241",
    "docker_url": "http://host.docker.internal:9241",
    "bind_host": "127.0.0.1",
    "bind_port": 9241
  },
  "pipeline_capabilities": {
    "ready": ["structured_ebooks", "pdf_fast_text"],
    "degraded": [],
    "missing": ["docling_documents"]
  },
  "risk_status": "missing_dependencies"
}
```

Use `risk_status` as a quick preflight:

- `ok`: core dependencies are available.
- `degraded`: usable, but some capability is slower or limited.
- `missing_dependencies`: at least one optional or required capability is missing; inspect `pipeline_capabilities` before choosing a route.

`health_check` returns both raw dependency `checks` and a capability matrix:

```json
{
  "checks": [],
  "capabilities": [
    {
      "name": "pdf_structure_recovery",
      "status": "ok",
      "detail": "MinerU available with model cache.",
      "action": "Use MinerU for complex PDFs."
    }
  ],
  "ready_capabilities": ["structured_ebooks", "pdf_fast_text"],
  "degraded_capabilities": ["gpu_acceleration"],
  "missing_capabilities": ["docling_documents"]
}
```

Agents should use `capabilities` before choosing heavy PDF/OCR routes. For example, if `pdf_structure_recovery` is missing, prefer `pdf_fast_text`, `local_ocr`, or a user-visible health fix instead of blindly launching MinerU.

For persistent handoff, use `export_environment_report`. It writes `environment-report.md`, `environment-report.json`, `environment-lock.json`, and `requirements.lock.txt`, returns their paths, and exposes them as readable artifacts. Use this before large unattended batches or when another agent needs to understand or compare the machine state without shell access.

Use `compare_environment_lock` with a prior `environment-lock.json` to detect drift in Python package versions/importability, external command paths/versions, Torch/CUDA, and capability status. When `output` is provided it writes `environment-lock-compare.md/json` artifacts.

## Structure Strategy

`inspect_document` returns a lightweight `structure_strategy` and `next_actions` for documents, PDFs, images, and folders:

```json
{
  "kind": "pdf",
  "recommendation": "mineru",
  "structure_strategy": {
    "mode": "layout_aware_structure_recovery",
    "confidence": "medium",
    "preferred_tools": ["mineru", "docling", "marker"]
  },
  "next_actions": [
    {
      "tool": "start_conversion",
      "pdf_pipeline_mode": "mineru",
      "why": "recover headings, tables, and layout blocks"
    }
  ]
}
```

Use this when deciding whether to convert, build a location index, rebuild an image book, export a review pack, or compare PDF pipelines.

For `web-content-fetcher` archives, `inspect_document` returns:

```json
{
  "kind": "web_archive",
  "recommendation": "process_web_archive_visual_check",
  "structure_strategy": {
    "mode": "web_archive_visual_check",
    "confidence": "medium"
  },
  "next_actions": [
    {
      "tool": "process_web_archive",
      "why": "prepare visual_check artifacts for archive rebuild"
    }
  ]
}
```

## Web Archive Visual Check

Use `process_web_archive` for a `web-content-fetcher` archive folder after `archive rebuild --with-visual-check` has prepared `rebuild_input/manifest.json`.

Required:

- `input`: archive folder path.

Optional:

- `output`: custom visual-check output folder. Omit this for the standard `archive/visual_check/` layout.

The tool writes visual evidence files only. It does not replace the source Markdown, HTML, screenshot, or final `web-content-fetcher` outputs.

Returned artifacts:

- `visual_check_json`: `visual_check_result.json`, including status, warnings, counts, and next step.
- `markdown`: `layout_ocr.md`, screenshot OCR Markdown or a pending placeholder.
- `visual_blocks_json`: OCR/layout block candidates.
- `table_candidates_json`: Markdown/OCR table candidates.
- `image_positions_json`: DOM image positions and screenshot visual-region candidates.

When no screenshot or OCR engine is available, `status` is usually `pending_visual_engine`; agents should read `warnings` and avoid treating `layout_ocr.md` as recognized evidence.

## Artifacts

Tools that write files should return `schema_version=artifact-schema-v1` and an `artifacts` array.

Artifact object:

```json
{
  "type": "markdown",
  "path": "D:\\output\\book.md",
  "label": "Rebuilt Markdown",
  "media_type": "text/markdown",
  "description": "optional"
}
```

Common artifact types:

- `markdown`
- `html`
- `text`
- `conversion_report`
- `summary_report`
- `summary_json`
- `review_report`
- `review_json`
- `matches_json`
- `location_index_sqlite`
- `location_index_jsonl`
- `pages_jsonl`
- `clusters_json`
- `order_report`
- `structure_report`
- `structure_json`
- `environment_report`
- `environment_json`
- `environment_lock`
- `environment_lock_compare`
- `environment_lock_compare_json`
- `visual_check_json`
- `visual_blocks_json`
- `table_candidates_json`
- `image_positions_json`
- `requirements_lock`
- `tool_log`

## Reading Artifacts

Use `read_artifact` for text-like artifacts.

Use it for:

- Markdown.
- JSON.
- JSONL previews.
- Review reports.
- Order reports.
- Logs.

Do not use it for SQLite. For location indexes, use `query_location_index`.

## Specialist Tools

Use specialist tools when the desired action is already known:

- `inspect_document`: lightweight preflight without heavy models.
- `scan_books`: conversion planning only.
- `health_check`: environment and dependency check.
- `export_environment_report`: write Markdown/JSON environment diagnostics artifacts for handoff and debugging.
- `compare_environment_lock`: compare current environment against an exported `environment-lock.json`.
- `build_location_index`: synchronous short location indexing.
- `start_location_index`: async location indexing.
- `query_location_index`: query a generated SQLite location index.
- `export_location_review_pack`: export matched PDF pages or images for human review.
- `rebuild_image_book`: synchronous short screenshot rebuild.
- `start_image_book_rebuild`: async screenshot rebuild.
- `rebuild_image_book_from_order`: rebuild Markdown from `pages.jsonl` plus a manually edited `order.md` without rerunning OCR.
- `read_report`: JSON conversion report reader.
- `read_pdf_tool_log`: PDF tool log tail reader.

## Failure Handling

If a tool returns `error=true`, agents should:

1. Read `message`.
2. Inspect `warnings`, `errors`, `events`, and `artifacts` if present.
3. For failed jobs, call `get_job_status` once more before giving up, because logs/events may be appended near shutdown.
4. For conversion quality issues, read `review_report`, `summary_report`, or per-file `conversion_report`.
5. For SQLite artifacts, do not call `read_artifact`; call a query tool.

HTTP `/call` errors use a stable envelope:

```json
{
  "request_id": "req-...",
  "ok": false,
  "error": true,
  "code": "invalid_request",
  "message": "Unknown tool: missing_tool",
  "retryable": false,
  "transport": "http",
  "schema_version": "artifact-schema-v1"
}
```

Current error codes:

- `unauthorized`: authentication failed; do not retry without changing credentials.
- `not_found`: endpoint path is wrong; do not retry unchanged.
- `invalid_json`: request body is not valid JSON; do not retry unchanged.
- `invalid_request`: tool name or arguments are invalid; do not retry unchanged.
- `tool_error`: unexpected tool/runtime failure; retry may be useful after checking logs or changing inputs.

HTTP `/call` success responses include both an envelope and the raw tool fields for backward compatibility:

```json
{
  "request_id": "req-...",
  "ok": true,
  "result": {
    "status": "routed"
  },
  "status": "routed"
}
```

## Sync vs Async Rules

Safe synchronous tools:

- `inspect_document`
- `scan_books`
- `health_check`
- `query_location_index`
- `read_artifact`
- `read_report`
- `read_pdf_tool_log`

Potentially slow synchronous tools:

- `build_location_index`
- `rebuild_image_book`

Preferred async tools:

- `start_conversion`
- `start_location_index`
- `start_image_book_rebuild`
- `process_material`

## Stability Rules

- Tool names are stable.
- Top-level JSON keys are additive; existing keys should not be renamed or removed.
- Agents should ignore unknown fields.
- Agents should prefer `artifacts` over guessing output paths.
- Agents should prefer `next_actions` over inventing follow-up calls.
- After conversion jobs finish, agents should inspect `quality_summary` first, then follow `next_actions` to read `summary_report`, `review_report`, and a representative Markdown artifact.
- CLI, MCP, HTTP, and UI should reuse the same Python core functions.

## Examples

Minimal HTTP, MCP stdio, and CLI-style examples are in `examples/agent-calls/`.
