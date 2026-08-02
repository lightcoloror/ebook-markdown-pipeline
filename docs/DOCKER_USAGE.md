# Docker / HTTP Service Usage

<!-- Documentation update: 2026-08-02 09:37:26 | Codex (GPT-5) | Added non-root image and fail-closed random-token guidance. -->

The Docker image exposes the HTTP bridge for agents that cannot use stdio MCP directly.

## Build

```bash
docker build -t ebook-material-tools:local .
```

## Run

```bash
set -a && . ./config/http.env && set +a
export EBOOK_CONVERTER_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
docker run --rm -p "${EBOOK_CONVERTER_HTTP_PORT}:${EBOOK_CONVERTER_HTTP_PORT}" \
  -e EBOOK_CONVERTER_API_TOKEN \
  --env-file ./config/http.env \
  -v "$PWD/data/input:/data/input" \
  -v "$PWD/data/output:/data/output" \
  ebook-material-tools:local
```

## Compose

```bash
export EBOOK_CONVERTER_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
docker compose --env-file config/http.env -f docker-compose.example.yml up --build
```

## Health

```bash
curl -H "Authorization: Bearer ${EBOOK_CONVERTER_API_TOKEN}" \
  "http://127.0.0.1:${EBOOK_CONVERTER_HTTP_PORT}/health"
```

The health response includes tool names, `schema_version`, async job support, and artifact support.

## Agent Call

```bash
curl -H "Authorization: Bearer ${EBOOK_CONVERTER_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"name":"process_material","arguments":{"input":"/data/input","output":"/data/output","recursive":true}}' \
  "http://127.0.0.1:${EBOOK_CONVERTER_HTTP_PORT}/call"
```

If a `job_id` is returned, poll:

```bash
curl -H "Authorization: Bearer ${EBOOK_CONVERTER_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"name":"get_job_status","arguments":{"job_id":"job-..."}}' \
  "http://127.0.0.1:${EBOOK_CONVERTER_HTTP_PORT}/call"
```

## Volumes

Suggested mounts:

- `/data/input`: source documents/images.
- `/data/output`: generated Markdown, reports, indexes, and review artifacts.
- `/data/cache`: optional model/cache location for future heavier backends.

## Notes

- The image runs as the unprivileged appuser; .dockerignore excludes local environment files, caches, and benchmark artifacts.
- Non-local HTTP binds reject missing, short, and known placeholder tokens.
- The example image installs Python dependencies and Pandoc only.
- Calibre, MinerU, Marker, GPU runtimes, and OCR model assets are not bundled in this minimal image.
- For heavy PDF or OCR workloads, prefer a host install or a custom image with the required model caches mounted.
