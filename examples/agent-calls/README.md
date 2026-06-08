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
python ebook_converter_http.py
```

The default host and port are read from `config/http.env`.

Run:

```powershell
python examples\agent-calls\http_process_material.py `
  --token local-token `
  --input C:\books\sample.epub `
  --output C:\books-output
```

## MCP Stdio

```powershell
python examples\agent-calls\mcp_stdio_process_material.py `
  --input C:\books\sample.epub `
  --output C:\books-output
```

## CLI-Style Local Call

This imports the same tool layer directly without starting a server:

```powershell
python examples\agent-calls\cli_process_material.py `
  --input C:\books\sample.epub `
  --output C:\books-output
```

## Agent Batch Handoff

When taking over an existing batch without starting MCP or HTTP, use the local CLI-style helper to list recent batch results under an output root:

```powershell
python examples\agent-calls\cli_agent_batch_handoff.py list `
  C:\agent-batch-output `
  --max-depth 3
```

Inspect a known `agent-batch-results.json`:

```powershell
python examples\agent-calls\cli_agent_batch_handoff.py inspect `
  C:\agent-batch-output\run-002\agent-batch-results.json
```

Build a compact handoff bundle through the same local helper:

```powershell
python examples\agent-calls\cli_agent_batch_handoff.py bundle `
  --batch-results C:\agent-batch-output\run-002\agent-batch-results.json `
  --output C:\agent-batch-output\run-002\handoff
```

Docker-hosted agents can use the same handoff tools through the HTTP bridge:

```powershell
python examples\agent-calls\http_agent_batch_handoff.py `
  --url http://host.docker.internal:9241 `
  list C:\agent-batch-output
```

When another agent needs a compact handoff package instead of the full batch JSON, call the MCP/HTTP tool `build_agent_handoff_bundle` or the local wrapper:

```powershell
python examples\agent-calls\http_agent_batch_handoff.py `
  --url http://host.docker.internal:9241 `
  bundle `
  --batch-results C:\agent-batch-output\run-002\agent-batch-results.json `
  --output C:\agent-batch-output\run-002\handoff
```

## Query Mode

If you only need to locate a keyword in PDFs/images:

```powershell
python examples\agent-calls\http_process_material.py `
  --input C:\documents `
  --output C:\documents-index `
  --query "合同金额"
```

## Web Archive Mode

For `web-content-fetcher` archive folders, `process_material` may route to the synchronous `process_web_archive` tool. In that case the example scripts read `visual_check_json` or another returned visual artifact directly instead of polling a background job.
