# Service Contract And Readiness

This document is the source of truth for discovering and starting the service-facing entry points of the Graphic-Text Material Converter.

Last reviewed: 2026-07-10 Asia/Shanghai by Codex.

## Status Summary

- Current status for dispatch when HTTP is not listening: `stopped-by-design`.
- HTTP `8765` is not the current contract port.
- The current HTTP port is read from `config/http.env`; at this review it is `9241`.
- The HTTP bridge is not expected to be always-on unless an operator or automation explicitly starts it.
- MCP stdio and CLI remain valid without any listening HTTP port.

## Current Port Contract

The single HTTP port source is:

```text
config/http.env
```

Current values:

```text
EBOOK_CONVERTER_HTTP_SCHEME=http
EBOOK_CONVERTER_HTTP_HOST=127.0.0.1
EBOOK_CONVERTER_HTTP_PORT=9241
EBOOK_CONVERTER_DOCKER_HTTP_HOST=0.0.0.0
```

Do not hard-code `8765`, `9241`, or any other port in dispatch prompts, desktop shortcuts, Docker manifests, or external monitors. Read `config/http.env`, or call HTTP `/health` after the bridge has been started.

## Is HTTP Always Running?

No. The HTTP bridge is an on-demand transport adapter for Docker-hosted or cross-process agents. It is useful when an agent cannot use Windows stdio MCP directly.

If neither `127.0.0.1:9241` nor the configured port is listening, report `stopped-by-design` when HTTP is optional. Report `needs_manual_start` only when the current job explicitly requires HTTP.

## MinerU Backend Service

The optional MinerU backend has a separate fixed localhost service contract in [MINERU_API_SERVICE.md](MINERU_API_SERVICE.md). Its endpoint comes only from `config/mineru-api.env`. The conversion pipeline always passes `--api-url`; a stopped MinerU API triggers the documented local PDF fallback or a real failed report, never MinerU's implicit temporary API.

Use `mineru_api.cmd status|start|health|stop`. This service is also on demand and is not auto-started by discovery, HTTP, MCP, UI, or conversion jobs.

## Entry Point Priority

Use this order for normal operations:

1. `MCP stdio`: preferred for OpenClaw, Hermes, Codex, Claude Code, and any agent that can launch `start_mcp.cmd` and use tool schemas.
2. `HTTP bridge`: preferred for Docker-hosted agents or remote/local processes that cannot use Windows stdio MCP. It must be explicitly started first.
3. `CLI`: stable fallback for local automation, batch processing, debugging, and recovery when HTTP is unavailable.
4. `Desktop UI`: preferred for manual human operation.
5. `Watch-folder`: not a first-class always-on service in this project. Use agent batch manifests, output folders, and handoff artifacts instead of assuming a watcher is running.

## Availability Checks

### Unified Dispatch Status Without Starting Services

```powershell
python scripts\check_dispatch_contract.py
```

This emits `ebook-dispatch-contract-v1` with configured HTTP status, legacy `8765` classification, entrypoint fallbacks, effective module readiness, deterministic material routes, OpenClaw/Telegram/Local Tools guidance, and manual review gates. It never starts HTTP or MinerU, downloads models, or converts a document. See [SERVICE_AND_MODULE_ROUTING_2026-07-16.md](SERVICE_AND_MODULE_ROUTING_2026-07-16.md).

### Read The Config

```powershell
Get-Content .\config\http.env
```

### Check Whether HTTP Is Listening

```powershell
Get-NetTCPConnection -LocalPort <EBOOK_CONVERTER_HTTP_PORT> -ErrorAction SilentlyContinue
```

No result means the HTTP bridge is not running. That is expected and must be reported as `stopped-by-design`; do not auto-start it.

### Check MCP Without Starting HTTP

```powershell
python scripts\test_mcp_stdio.py
```

### Check HTTP Config Without Starting HTTP

```powershell
python scripts\test_http_config.py
```

### Check Core Import Without Heavy Backends

```powershell
python -c "import batch_convert_books; print('ebook_markdown_pipeline import ok')"
```

These checks do not run a real ebook/PDF conversion and do not start heavyweight OCR/VLM backends.

## Safe HTTP Startup

Start locally for host-only access:

```powershell
.\start_http_api.cmd
```

Or:

```powershell
python ebook_converter_http.py
```

Start for Docker agent access only when a local API token is set:

```powershell
$env:EBOOK_CONVERTER_API_TOKEN = "replace-with-a-local-token"
python ebook_converter_http.py --host 0.0.0.0
```

The server reads the default host and port from `config/http.env`. Binding to a non-local host without a token is refused by `ebook_converter_http.py`.

After startup, verify:

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:<EBOOK_CONVERTER_HTTP_PORT>/health
```

The health payload includes `http_config`, `config_sources`, `pipeline_capabilities`, `candidate_backend_registry`, `candidate_artifact_schemas`, `diagnostic_artifact_schemas`, `minimal_ok`, `optional_missing_is_ok`, and route defaults. Agents should inspect those fields, call `list_candidate_backends` through HTTP `/call`, or run `python scripts\list_candidate_backends.py --backend dots_mocr` without starting HTTP before choosing heavy OCR/PDF/VLM routes. Candidate discovery is non-executing and must not start services, install models, or make remote calls.

## Failure And Fallback Semantics

If HTTP is not listening:

- For MCP-capable agents: use `start_mcp.cmd` and call `get_agent_contract` / `process_material`.
- For local automation: call the CLI or Python helper examples directly.
- For Docker agents: report `needs_manual_start` for the HTTP bridge and either ask the operator to start it or switch to a host-side CLI batch/handoff flow.
- Do not mark the whole converter as down if MCP and CLI checks pass.
- Do not auto-start HTTP from discovery, health checks, OpenClaw dispatch, or Telegram automation.

If the configured HTTP port is occupied:

- Do not edit scattered scripts or prompts.
- Change only `config/http.env` after a local port preflight.
- Then re-run `python scripts\test_http_config.py` and update any external port registry through the owning dispatch process.

If `/health` responds but optional backends are missing:

- Treat `minimal_ok=true` as sufficient for EPUB/TXT/text-layer PDF conversion.
- Treat missing MinerU, Marker, Docling, OCR/VLM providers, or GPU as optional degradation unless the specific job requires them.

## OpenClaw And Local-Tools Degradation Policy

OpenClaw or local-tools checks should classify this project as:

- `ready` when MCP or CLI health checks pass and no HTTP bridge is required for the current job.
- `stopped-by-design` when HTTP is not listening but `config/http.env`, MCP, and CLI checks pass; `http.auto_start=false`.
- `needs_manual_start` when Docker/OpenClaw specifically requires HTTP and the bridge is not running.
- `degraded` when minimal checks pass but the requested optional backend is missing or slow/risky.
- `blocked` only when the required entry point for the requested job fails and no fallback is acceptable.

For Docker-based OpenClaw/Hermes jobs, the safe fallback order is:

1. Start HTTP bridge explicitly, then call `http://host.docker.internal:<EBOOK_CONVERTER_HTTP_PORT>`.
2. If HTTP cannot be started, run a host-side CLI or MCP batch and hand off `agent-batch-results.json` / `run_summary.md`.
3. If neither host-side execution nor HTTP is allowed, report `blocked` with the missing entry point and required manual action.

## Port Registry Backfill

This project should not directly modify the global port registry from inside conversion code or documentation checks.

If an external dispatch system tracks ports, it should record:

- service: `ebook_markdown_pipeline`
- mode: `on-demand HTTP bridge` with `stopped-by-design` idle state
- config source: `<project-path>\config\http.env`
- current configured URL: `http://127.0.0.1:9241`
- status when not listening: `stopped-by-design` when optional, or `needs_manual_start` when explicitly required; never `regression`

Any future port change should be made in `config/http.env` first, then verified through `scripts/test_http_config.py` and `/health` after startup.
