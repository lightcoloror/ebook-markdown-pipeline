# 图文材料转换器 Agent Tool Contract

This document defines the stable calling contract for AI agents using 图文材料转换器 as a general document/image material recognition tool.

The stable machine-readable server id remains `ebook-markdown-pipeline` for compatibility. User-facing surfaces should display `图文材料转换器` / `Graphic-Text Material Converter`.

## Stable Entry Points

MCP-native agents can call `get_agent_contract` to retrieve the same stable calling contract in machine-readable form. The response uses `schema_version=ebook-agent-contract-v1` and includes `display_name=图文材料转换器`, preferred entrypoints, specialist tools, full tool schemas, artifact/error contract versions, and docs pointers.

Preferred order:

1. `process_material`
2. `get_job_status`
3. `read_artifact`
4. Specialist tools only when needed

Agents should not directly parse PDFs, images, temporary directories, SQLite files, or model outputs when a tool exists for that purpose.

Agents should also not call online model providers directly for document recognition. Online API support must remain behind this project's provider abstraction so that privacy, cost, retry, fallback, artifact schema, and report logging stay consistent.

`get_agent_contract` and `health_check` expose `online_provider_health` when `config/online_models.example.json` or `EBOOK_CONVERTER_ONLINE_MODELS_CONFIG` is readable. This is configuration health only: it reports provider names, types, models, configured base URLs, key environment variable names, and missing-key status without making remote API calls.

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
- `image_book_threshold`: retained for compatibility; auto routing now recognizes image folders by default.
- `ocr`: `auto`, `always`, or `never`.
- `model_mode`: `local`, `online`, `hybrid`, or `auto`. Current implementation uses this for recommendation/risk reporting only; default conversion remains local-first.

Online-model option:

- `inspect_document` returns `online_enhancement` with `recommended`, `enabled_by_model_mode`, `remote_call_enabled`, `recommended_routes`, `estimated_pages`, `estimated_items`, `estimated_cost_risk`, `privacy_risk`, `reason`, and `next_step`.
- `remote_call_enabled` is currently always `false` in inspection. The field exists so future provider-backed pipelines can become explicit and auditable.
- Agents should not call vendor APIs directly even when `online_enhancement.recommended=true`; use `run_online_enhancement` only after the user or caller explicitly chooses online/hybrid enhancement.

Routing rules:

- Documents and ebooks route to `start_conversion`.
- PDFs route to `start_conversion` with a PDF pipeline selected from preflight signals.
- Single images and image folders route to `start_image_book_rebuild` by default so the output is recognized Markdown plus review artifacts.
- `web-content-fetcher` archive folders with `rebuild_input/manifest.json` route to `process_web_archive`.
- Any input with `intent=locate` or `query` routes to `start_location_index`, then returns a `next_actions` entry for `query_location_index` when a query is present.
- Unsupported or missing inputs return `status=unsupported` and do not start a job.

Return shape:

```json
{
  "status": "routed",
  "route": "start_image_book_rebuild",
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
          "tool": "read_report",
          "arguments": {
            "path": "output/.reports/book.report.json"
          },
          "why": "inspect converter diagnostics and quality reasons"
        },
        {
          "action": "compare_pdf_pipelines",
          "tool": "start_conversion",
          "arguments_list": [
            {
              "input": "input/book.pdf",
              "output": "output",
              "recursive": false,
              "overwrite": false,
              "resume": false,
              "output_format": "markdown",
              "output_name_suffix": "-agent-rerun-mineru",
              "pdf_pipeline_mode": "mineru"
            },
            {
              "input": "input/book.pdf",
              "output": "output",
              "recursive": false,
              "overwrite": false,
              "resume": false,
              "output_format": "markdown",
              "output_name_suffix": "-agent-rerun-docling",
              "pdf_pipeline_mode": "docling"
            }
          ],
          "why": "compare structure recovery rather than trusting one parser"
        }
      ]
    }
  ]
}
```

Agents should treat `quality_summary.review_count > 0` as a prompt to read the `summary_report` or `review_report` before presenting the output as final.

Review checklist JSON entries and completed conversion jobs also include machine-readable `next_actions`. Prefer actions with `tool` and `arguments` / `arguments_list` instead of inferring commands from prose. Rerun actions default to `overwrite=false`, `resume=false`, and an `output_name_suffix` such as `-agent-rerun-mineru`, so agents can compare outputs without replacing the original. These actions are advisory, not automatic permission to overwrite files; ask the user before destructive replacement.

## Structure Repair Report

Per-book conversion reports may include `structure_repair` when Markdown headings were promoted, normalized, or backed by external evidence. Agents should read this block before assuming a weak heading hierarchy is final.

Important fields:

- `action_counts`: counts of `promoted_to_heading`, `normalized_heading`, and `kept_with_evidence`.
- `decisions[].line_number`: original line number in the Markdown before repair.
- `decisions[].original` and `decisions[].repaired`: the exact line before and after repair.
- `decisions[].action`: whether the line was promoted, normalized, or kept with evidence.
- `decisions[].confidence`: conservative 0-1 score for the repair decision.
- `decisions[].reason`: human-readable explanation.
- `decisions[].signals`: machine-readable evidence such as `domain_grammar:*`, `candidate_source:pdf_outline`, `candidate_source:pymupdf_font_jump`, `candidate_source:mineru_paragraph_title`, `candidate_source:docling_heading`, and `nearest_parent:*`.
- `inferred_outline`: repaired heading hierarchy with `level`, `title`, `parent`, and `path`.

Low-confidence or surprising repairs should be treated as review cues, not as silent final truth.

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

Both files include a `contract` block with `schema_version=agent-batch-contract-v1`, `payload_schema_version`, `runner`, `capabilities`, and `required_fields`. Use `contract.capabilities` to detect handoff support such as `selection_summary`, `artifact_summary`, `handoff_next_actions`, `attention_summary`, and `legacy_action_synthesis`.

Use `scripts/validate_agent_batch_contract.py <path> --json` to validate `agent-batch-plan.json` or `agent-batch-results.json` before relying on a handoff artifact from another run or older session.

Freshly generated plan/results payloads include `contract_validation` with `ok`, `payload_kind`, and validation errors. Treat `contract_validation.ok=false` as a handoff contract failure even if conversion outputs exist.

The Markdown summaries mirror this as `Contract validation: ok` or `failed`, so agents can check the human-readable handoff before opening the JSON.

When `contract_validation.ok=false`, batch results and `inspect_agent_batch_results` expose `inspect_contract_validation` in `next_actions`; agents should inspect those errors before trusting other handoff fields.

Use the MCP/HTTP tool `build_agent_handoff_bundle` or the CLI wrapper `scripts/build_agent_handoff_bundle.py --batch-results <agent-batch-results.json> --output <dir>` to produce `agent-handoff-bundle.json/md`, a compact handoff index containing contract validation, attention, selection, artifact summary, next actions, artifacts, and review items. The tool returns `agent_handoff_bundle_json` and `agent_handoff_bundle_markdown` artifacts that agents can read through `read_artifact`.

The handoff bundle includes `handoff_ready`, `handoff_status`, and `recommended_next_action`. Agents should use these fields instead of deriving readiness from raw counts. Current statuses are `ready`, `contract_failed`, `needs_recovery`, `needs_artifact_review`, `needs_quality_compare`, `needs_review`, and `needs_attention`. When possible, `recommended_next_action` is copied from the existing top-level `next_actions`, preserving executable `tool` / `arguments`, `command_args`, or `powershell_command` fields.

`agent-batch-results.json` includes `artifact_summary` with total/ok/failed artifact read counts, `type_counts`, and `failed_artifacts`. Agents should inspect this before assuming all referenced artifacts were readable.

Real and partial batch results include top-level `next_actions` for handoff. Baseline comparisons may append quality-comparison actions, but agents should first follow `read_run_summary`, `inspect_agent_batch_results`, and `build_agent_handoff_bundle`, then handle conditional `inspect_failed_artifacts` and `inspect_review_items`.

Agents taking over an existing batch should call `inspect_agent_batch_results` on `agent-batch-results.json` before inventing paths or parsing the whole file themselves. If the exact results path is unknown, call `list_agent_batch_results` on the output root first and inspect the newest or most relevant item. These tools return summary counts, quality comparison status, top-level `next_actions`, `recommended_rerun`, extracted review items, and artifact paths for `run_summary.md` / quality comparison reports.

The inspect/list tools include an `attention` triage block with `needs_attention`, reason codes, hard-failed count, review count, artifact failure count, quality comparison status, and partial-run status. Use it to decide whether to inspect details before accepting a batch.

`inspect_agent_batch_results` is backward-compatible with older `agent-batch-results.json` files. If top-level handoff actions are missing, it synthesizes `read_run_summary`, `inspect_failed_artifacts`, `inspect_review_items`, and quality-comparison read actions from `summary`, `artifact_summary`, and `quality_comparison`.

For this comparison, agent-batch `review` means completed-with-review rather than transport failure. It contributes to completion success but increases the review/poor quality rate, so agents should report it as usable output that still needs inspection.

## Environment Capabilities

HTTP `/contract` returns the stable transport contract for HTTP-native agents:

```json
{
  "schema_version": "ebook-http-contract-v1",
  "transport": "http",
  "artifact_schema_version": "artifact-schema-v1",
  "entrypoints": ["process_material", "get_job_status", "read_artifact"],
  "supports_async_jobs": true,
  "supports_artifacts": true,
  "tools": [],
  "docs": {}
}
```

Agents should read `/contract` before `/tools` when they need the preferred entrypoints, docs pointers, artifact schema version, and error contract in one response.

HTTP `/health` returns the transport contract plus lightweight operating status:

```json
{
  "ok": true,
  "transport": "http",
  "http_config": {
    "config_path": "C:\\path\\to\\ebook-markdown-pipeline\\config\\http.env",
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
  "risk_status": "missing_dependencies",
  "config_sources": {
    "http": "C:\\path\\to\\ebook-markdown-pipeline\\config\\http.env",
    "example_env": "C:\\path\\to\\ebook-markdown-pipeline\\config.example.env"
  },
  "route_defaults": {
    "process_material": "recognize_or_convert",
    "images": "start_image_book_rebuild",
    "location_index": "requires intent=locate or query"
  },
  "long_task_guidance": {
    "prefer_async_tools": true,
    "poll_tool": "get_job_status"
  }
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

`get_agent_contract` and HTTP `/contract` also expose the same operating context fields: `pipeline_capabilities`, `risk_status`, `config_sources`, `route_defaults`, and `long_task_guidance`. Agents should use these fields instead of guessing ports, assuming every optional backend is installed, or launching heavy whole-document OCR/VLM jobs synchronously.

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
  "online_enhancement": {
    "model_mode": "hybrid",
    "recommended": true,
    "enabled_by_model_mode": true,
    "remote_call_enabled": false,
    "recommended_routes": ["vlm_layout", "table_repair", "text_structure_llm"],
    "estimated_pages": 32,
    "estimated_cost_risk": "medium",
    "privacy_risk": "high",
    "reason": "complex layout/tables/multicolumn signals may need layout-aware enhancement"
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

## Online Enhancement

`run_online_enhancement` is the explicit provider-backed entry point for optional online/fake enhancement. It does not run during default conversion.

Supported tasks:

- `text_structure`: repair low-confidence Markdown heading hierarchy.
- `vlm_layout`: extract image/infographic visual layout into Markdown and blocks.
- `table_repair`: repair true table candidates without forcing card layouts into tables.

Safety rules:

- `provider_mode=fake` is the default and is used for dry-run contracts and tests.
- `provider_mode=openai_compatible` requires `model_mode=hybrid|online|auto`.
- Remote calls also require `allow_remote=true`.
- API keys are read only from environment variables named in `config/online_models.example.json`.

Example fake call:

```json
{
  "name": "run_online_enhancement",
  "arguments": {
    "task": "text_structure",
    "provider_mode": "fake",
    "input_text": "Title\n\nBody"
  }
}
```

Example remote-gated call:

```json
{
  "name": "run_online_enhancement",
  "arguments": {
    "task": "vlm_layout",
    "provider_mode": "openai_compatible",
    "model_mode": "hybrid",
    "allow_remote": true,
    "input_path": "path/to/infographic.png",
    "mime_type": "image/png"
  }
}
```

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
