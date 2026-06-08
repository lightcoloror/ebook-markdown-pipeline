# Batch Folder

Use this recipe when an agent needs to process a folder without preparing a full `examples/agent-batch/` manifest.

For repeatable production batches, prefer the manifest runner in `examples/agent-batch/`.

## MCP Call

```json
{
  "name": "process_material",
  "arguments": {
    "input": "path/to/material-folder",
    "output": "path/to/output-folder",
    "intent": "auto",
    "recursive": true,
    "include_hidden": false,
    "output_format": "markdown",
    "pdf_pipeline_mode": "auto"
  }
}
```

## Expected Behavior

- Folders containing documents/PDFs route to `start_conversion`.
- Folders containing only images route to `start_image_book_rebuild`.
- Location indexing is not selected unless `intent=locate` or `query` is provided.

## Completion Checklist

- Poll `get_job_status`.
- Confirm `status`.
- Read `quality_summary.counts`.
- Read `summary_report`.
- If `quality_summary.review_count > 0`, read `review_report`.
- If `next_actions` includes `start_conversion` reruns, run them into versioned outputs and compare before replacing anything.

## When To Use The Batch Manifest Instead

- You need `select=failed-or-review`.
- You need baseline comparison.
- You need a durable handoff bundle.
- You need per-job IDs and resumable production runs.
