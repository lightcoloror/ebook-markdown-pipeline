# Rerun Failed Or Review Outputs

Use this recipe after `get_job_status` reports failed, review, poor, fallback, or weak-structure outputs.

## Preferred Source Of Truth

Use the completed job's top-level `next_actions` first:

```json
{
  "tool": "start_conversion",
  "arguments": {
    "input": "path/to/source.pdf",
    "output": "path/to/output-folder",
    "recursive": false,
    "overwrite": false,
    "resume": false,
    "output_format": "markdown",
    "output_name_suffix": "-agent-rerun-mineru",
    "pdf_pipeline_mode": "mineru"
  }
}
```

If the action is `compare_pdf_pipelines`, run each entry in `arguments_list` as a separate `start_conversion` call.

## Safety Defaults

- Keep `overwrite=false`.
- Keep `resume=false` for targeted reruns.
- Keep `output_name_suffix` so the old output remains available.
- Read the new `summary_report` and `review_report` after rerun.
- Ask the user before replacing or deleting any previous output.

## Fallback Interpretation

- `pymupdf4llm(fallback from mineru)` means the high-quality PDF backend failed or timed out, and a fast text-layer fallback produced output.
- Treat fallback output as useful but not final for structure-heavy documents.
- Read `inspect_fallback_diagnostics` / `read_report` before deciding whether to rerun.

## Minimal Agent Flow

1. Read completed `get_job_status`.
2. Collect `next_actions` where `tool` is `read_report`, `read_artifact`, or `start_conversion`.
3. Read reports first.
4. Run versioned reruns only when the report explains why.
5. Compare title hierarchy, page noise, OCR volume, and `quality_summary` before accepting the candidate output.
