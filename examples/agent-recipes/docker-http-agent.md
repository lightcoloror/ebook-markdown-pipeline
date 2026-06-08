# Docker HTTP Agent

Use this recipe for OpenClaw, Hermes Agent, or another Docker-hosted agent that needs to call the converter running on the Windows host.

## Host Side

Start the HTTP bridge on the host:

```powershell
$env:EBOOK_CONVERTER_API_TOKEN = "replace-with-a-local-token"
python ebook_converter_http.py --host 0.0.0.0
```

The port is read from `config/http.env` unless explicitly overridden.

## Container Side

Discover the service:

```bash
curl -H "Authorization: Bearer ${EBOOK_CONVERTER_API_TOKEN}" \
  "http://host.docker.internal:${EBOOK_CONVERTER_HTTP_PORT}/contract"
```

Call `process_material`:

```bash
curl -H "Authorization: Bearer ${EBOOK_CONVERTER_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"name":"process_material","arguments":{"input":"path/to/input","output":"path/to/output","intent":"auto","recursive":true,"output_format":"markdown","pdf_pipeline_mode":"auto"}}' \
  "http://host.docker.internal:${EBOOK_CONVERTER_HTTP_PORT}/call"
```

Poll `get_job_status`:

```bash
curl -H "Authorization: Bearer ${EBOOK_CONVERTER_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"name":"get_job_status","arguments":{"job_id":"job-id-from-process-material"}}' \
  "http://host.docker.internal:${EBOOK_CONVERTER_HTTP_PORT}/call"
```

## Agent Rules

- Use `/health` for runtime capability and risk status.
- Use `/contract` for stable tool schema.
- Reuse MCP tool names and JSON arguments through HTTP `/call`.
- Do not parse logs for success if `get_job_status` already has `status`, `quality_summary`, and `next_actions`.
- Do not call online model APIs directly; wait for this project to expose provider-backed tools.
