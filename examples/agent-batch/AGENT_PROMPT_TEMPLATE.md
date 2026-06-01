# Agent Batch Prompt Template

Use this project as the only document/image recognition tool. Do not parse PDF, EPUB, screenshots, model caches, or temporary output directly unless the tool reports a failure and asks for log inspection.

## Inputs

- Manifest: `D:\used-by-codex\ebook_markdown_pipeline\examples\agent-batch\batch_manifest.example.json`
- HTTP bridge: `http://host.docker.internal:8765` for Docker agents, or `http://127.0.0.1:8765` on the host.
- Token: provided by the user or `EBOOK_CONVERTER_API_TOKEN`.

## Required Flow

For every manifest job:

1. Call `process_material` with merged defaults and job arguments.
2. If a `job_id` is returned, poll `get_job_status` until `status` is not `running`.
3. If status is `done`, inspect `quality_summary`.
4. Follow `next_actions`; read at least `summary_report`, `review_report`, and one representative Markdown/text artifact when available.
5. If `quality_summary.review_count > 0`, report the review reasons and suggested actions. Do not claim the output is final without mentioning the review queue.
6. If status is `failed`, read `errors`, `events`, and any available report/log artifact. Return a concise failure reason and retry only if the failure is retryable or caused by timeout/fallback settings.

## Output To User

Return:

- Batch status: total, ok, failed, unsupported, timeout.
- Output directory for each job.
- Review count and top review reasons.
- Artifact paths for summary, review checklist, and main Markdown output.
- Any fallback diagnostics, especially `pymupdf4llm(fallback from ...)`.

## Quality Rule

Prefer stable completion plus explicit review artifacts over silent high-quality assumptions. If the output is `review` or `poor`, preserve the artifact paths and recommend human review or multi-pipeline PDF comparison.
