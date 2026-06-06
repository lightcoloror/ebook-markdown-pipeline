# Agent Batch Templates

This directory contains copyable templates for OpenClaw, Hermes Agent, Codex, or any agent that can call the HTTP bridge.

## Files

- `batch_manifest.example.json`: machine-readable batch plan.
- `agent_batch_http.py`: deterministic HTTP runner for the stable `/call` workflow.
- `AGENT_PROMPT_TEMPLATE.md`: prompt/instruction block for LLM agents.

## Start HTTP Bridge

Host process:

```powershell
$env:EBOOK_CONVERTER_API_TOKEN = "local-token"
python D:\used-by-codex\ebook_markdown_pipeline\ebook_converter_http.py --host 0.0.0.0 --token local-token
```

The default HTTP port is read from `config/http.env`. Docker agents should call `http://host.docker.internal:<EBOOK_CONVERTER_HTTP_PORT>`. Host-local scripts default to `config/http.env`.

## Run Batch

Validate the manifest before long-running work:

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\examples\agent-batch\agent_batch_http.py `
  --manifest D:\used-by-codex\ebook_markdown_pipeline\examples\agent-batch\batch_manifest.example.json `
  --output D:\agent-batch-output\run-001 `
  --dry-run
```

This writes:

- `agent-batch-plan.json`
- `agent-batch-plan.md`

Run the real batch after the plan is valid:

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\examples\agent-batch\agent_batch_http.py `
  --token local-token `
  --manifest D:\used-by-codex\ebook_markdown_pipeline\examples\agent-batch\batch_manifest.example.json `
  --output D:\agent-batch-output\run-001 `
  --timeout 900
```

Outputs:

- `agent-batch-results.json`
- `agent-batch-summary.md`
- partial versions after each completed manifest job

## Web Archive Jobs

`web-content-fetcher` archive folders can be included in the same manifest. Use the archive folder as `input` and keep `intent=auto`:

```json
{
  "id": "web-archive-visual-check",
  "input": "D:\\web-archives\\example-archive",
  "output": "D:\\agent-batch-output\\web-archives",
  "intent": "auto"
}
```

The router detects `rebuild_input/manifest.json`, calls `process_web_archive`, and reads `visual_check/` artifacts directly. This route is synchronous and may return `status=review` when the archive has no screenshot or OCR output yet. Treat `review` as “artifact generated but needs human/agent inspection,” not as a transport failure.

The batch runner exits successfully when jobs are only `ok` or `review`. Use `summary.hard_failed` for real failures such as `failed`, `timeout`, `unsupported`, or `no_job`.

## Agent Rules

- Prefer this batch runner when the agent needs repeatable multi-file processing.
- Run `--dry-run` first when the manifest was generated or edited by an agent.
- Use `stress_agent_http.py` for concurrency/stability testing, not ordinary user batches.
- Keep `pdf_pipeline_mode=auto` unless the user explicitly requests a backend.
- Always inspect `quality_summary.review_count` before claiming the batch is complete.
- Preserve `summary_report`, `review_report`, and Markdown artifact paths in the final response.
