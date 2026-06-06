# Agent Call Examples

These examples show the same stable flow through three integration styles:

1. Call `process_material`.
2. If a `job_id` is returned, poll `get_job_status` until the job is not running.
3. If no `job_id` is returned but `delegated.artifacts` exists, read those artifacts directly.
4. Read a returned text/JSON artifact with `read_artifact`.

Use HTTP for Docker-hosted agents such as OpenClaw or Hermes when they cannot run Windows stdio MCP directly. Use MCP stdio for MCP-native agents. Use the CLI-style Python example for local automation and debugging.

## HTTP

Start the service:

```powershell
$env:EBOOK_CONVERTER_API_TOKEN = "local-token"
python D:\used-by-codex\ebook_markdown_pipeline\ebook_converter_http.py
```

The default host and port are read from `config/http.env`.

Run:

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\examples\agent-calls\http_process_material.py `
  --token local-token `
  --input D:\books\sample.epub `
  --output D:\books-output
```

## MCP Stdio

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\examples\agent-calls\mcp_stdio_process_material.py `
  --input D:\books\sample.epub `
  --output D:\books-output
```

## CLI-Style Local Call

This imports the same tool layer directly without starting a server:

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\examples\agent-calls\cli_process_material.py `
  --input D:\books\sample.epub `
  --output D:\books-output
```

## Query Mode

If you only need to locate a keyword in PDFs/images:

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\examples\agent-calls\http_process_material.py `
  --input D:\documents `
  --output D:\documents-index `
  --query "合同金额"
```

## Web Archive Mode

For `web-content-fetcher` archive folders, `process_material` may route to the synchronous `process_web_archive` tool. In that case the example scripts read `visual_check_json` or another returned visual artifact directly instead of polling a background job.
