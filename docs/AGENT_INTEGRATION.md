# Agent Integration

This project is designed for stable AI-agent invocation through a layered interface:

1. Core Python conversion functions.
2. CLI for humans and automation scripts.
3. MCP stdio server for agents.
4. Skills or plugins as thin wrappers around MCP/CLI.

Do not duplicate conversion logic in agent-specific plugins. Keep conversion behavior in `batch_convert_books.py` and expose it through stable wrappers.

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

## MCP Tools

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
- `mineru_segment_min_pages`
- `mineru_segment_pages`

### `get_job_status`

Polls job progress, recent events, and final results.

### `read_report`

Reads a generated `.reports/*.report.json` file.

### `read_pdf_tool_log`

Reads the tail of a persisted Marker/MinerU log file from `.reports/pdf-tool-logs/*.log`.

## Agent Usage Policy

- Prefer `scan_books` before `start_conversion`.
- Run `health_check` before the first conversion in a new environment.
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
