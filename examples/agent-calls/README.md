# Agent Call Examples

These examples show the same stable flow through three integration styles:

1. Call `process_material`.
2. Poll `get_job_status` until the job is not running.
3. Read a returned text artifact with `read_artifact`.

Use HTTP for Docker-hosted agents such as OpenClaw or Hermes when they cannot run Windows stdio MCP directly. Use MCP stdio for MCP-native agents. Use the CLI-style Python example for local automation and debugging.

## HTTP

Start the service:

```powershell
$env:EBOOK_CONVERTER_API_TOKEN = "local-token"
python D:\used-by-codex\ebook_markdown_pipeline\ebook_converter_http.py --host 127.0.0.1 --port 8765
```

Run:

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\examples\agent-calls\http_process_material.py `
  --url http://127.0.0.1:8765 `
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
  --url http://127.0.0.1:8765 `
  --input D:\documents `
  --output D:\documents-index `
  --query "合同金额"
```
