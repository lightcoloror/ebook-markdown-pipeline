# Structure Enhancement

Use this recipe when a conversion succeeded but the Markdown hierarchy is weak, for example when `quality_summary.review_items[].quality_reasons` includes `没有 Markdown 标题` or `章节层级`.

This is a second-pass review workflow. It does not replace the original output, and it does not call online providers by default.

## When To Use

- The job finished with `status=done`.
- The output Markdown exists and is readable.
- `quality_summary.review_count > 0`.
- A review item recommends `enhance_markdown_structure`, or the quality reasons mention weak headings.

Do not use this as a blind replacement for rerunning PDFs through MinerU/Docling. For complex PDFs, compare parser outputs first when the report recommends `compare_pdf_pipelines`.

## MCP Flow

1. Read the completed job:

```json
{
  "name": "get_job_status",
  "arguments": {
    "job_id": "job-..."
  }
}
```

2. Find a review item whose `next_actions` contains:

```json
{
  "tool": "enhance_markdown_structure",
  "arguments": {
    "input": "path/to/generated.md",
    "output": "path/to/.structure-enhanced",
    "source_kind": "markdown",
    "model_mode": "local",
    "provider_mode": "fake",
    "overwrite": false
  }
}
```

3. Call the action exactly as returned:

```json
{
  "name": "enhance_markdown_structure",
  "arguments": {
    "input": "path/to/generated.md",
    "output": "path/to/.structure-enhanced",
    "source_kind": "markdown",
    "model_mode": "local",
    "provider_mode": "fake",
    "overwrite": false
  }
}
```

4. Read the returned artifacts:

```json
{
  "name": "read_artifact",
  "arguments": {
    "path": "path/to/.structure-enhanced/book.structure-enhanced.md",
    "artifact_type": "markdown"
  }
}
```

Also read the `structure_report` artifact before recommending replacement.

## Optional Provider Enhancement

Only after an explicit user or caller decision, rerun `enhance_markdown_structure` with non-local `model_mode`.

```json
{
  "name": "enhance_markdown_structure",
  "arguments": {
    "input": "path/to/generated.md",
    "output": "path/to/.structure-enhanced",
    "source_kind": "markdown",
    "model_mode": "hybrid",
    "provider_mode": "openai_compatible",
    "allow_remote": true,
    "overwrite": false
  }
}
```

This uses the same provider safety contract as `run_online_enhancement`: no remote call happens with `model_mode=local`, and OpenAI-compatible calls require `allow_remote=true`.

## Acceptance Checklist

- The original Markdown still exists unchanged.
- The enhanced Markdown is in `.structure-enhanced` or another review folder.
- The report contains `local_structure_repair.decisions`.
- The report records whether `online_enhancement` was skipped, fake, or remote.
- The user or reviewer compares both files before replacing anything.
