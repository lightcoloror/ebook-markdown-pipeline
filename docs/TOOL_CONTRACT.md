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

## Environment Capabilities

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
