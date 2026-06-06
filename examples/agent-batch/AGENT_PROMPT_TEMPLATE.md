# Agent Batch Prompt Template

Use this project as the only document/image recognition tool. Do not parse PDF, EPUB, screenshots, model caches, or temporary output directly unless the tool reports a failure and asks for log inspection.

## Inputs

- Manifest: `D:\used-by-codex\ebook_markdown_pipeline\examples\agent-batch\batch_manifest.example.json`
- HTTP bridge: read host/port from `D:\used-by-codex\ebook_markdown_pipeline\config\http.env`; Docker agents use `host.docker.internal` with that port.
- Token: provided by the user or `EBOOK_CONVERTER_API_TOKEN`.

## Required Flow

Before running long jobs:

1. Run the batch runner with `--dry-run` or validate the same manifest shape yourself.
2. If `agent-batch-plan.md` reports errors, fix the manifest and stop. Do not start conversion.
3. If it reports warnings, surface them to the user when they affect path visibility, missing inputs, or missing output parents.

For every real manifest job:

1. Call `process_material` with merged defaults and job arguments.
2. If a `job_id` is returned, poll `get_job_status` until `status` is not `running`.
3. If status is `done`, inspect `quality_summary`.
4. Follow `next_actions`; read at least `summary_report`, `review_report`, and one representative Markdown/text artifact when available.
5. If `quality_summary.review_count > 0`, report the review reasons and suggested actions. Do not claim the output is final without mentioning the review queue.
6. If status is `failed`, read `errors`, `events`, and any available report/log artifact. Return a concise failure reason and retry only if the failure is retryable or caused by timeout/fallback settings.
7. If a previous batch result is available, pass it as `--baseline-results`, inspect `benchmark-quality-comparison.md`, and follow top-level `next_actions` in `agent-batch-results.json` before saying the new run improved or remained stable.

## Output To User

Return:

- Batch status: total, ok, review, failed, hard_failed, unsupported, timeout.
- Output directory for each job.
- Review count and top review reasons.
- Artifact paths for summary, review checklist, and main Markdown output.
- Any fallback diagnostics, especially `pymupdf4llm(fallback from ...)`.
- Quality comparison status and report path when `--baseline-results` was used.

## Quality Rule

Prefer stable completion plus explicit review artifacts over silent high-quality assumptions. If the output is `review` or `poor`, preserve the artifact paths and recommend human review or multi-pipeline PDF comparison. Treat `review` as completed-with-review, not as a transport or tool failure.
