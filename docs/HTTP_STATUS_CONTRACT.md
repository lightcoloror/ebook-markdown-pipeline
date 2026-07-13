# Ebook HTTP Status Contract

Status: local offline contract
Schema: `ebook-http-status-contract-v1`
Updated: 2026-07-11
Acting agent: Codex

## State dimensions

The following dimensions are independent:

- `cli`: `ready`, `degraded`, or `blocked`, based on `health-check-v2.minimal_ok`.
- `http_runtime`: `healthy`, `stopped-by-design`, `stale-pid`, or `unknown`.
- `optional_backends`: `ready`, `degraded`, or `unknown`.
- `minimal_output`: `minimal-deliverable`, `degraded`, `blocked`, or `fallback-proposed`.

A stopped HTTP listener does not make the CLI unusable. Missing optional backends do not block minimal CLI conversion, but they prevent claims of full quality support. Artifact existence and quality acceptance remain separate.

## Port authority

The queue evidence records port 8765 as stopped. Current project discovery reads `config/http.env`, whose configured URL is `http://127.0.0.1:9241`. Therefore 8765 is retained as legacy evidence only and is not used as current runtime authority.

The contract never starts either port. A healthy listener is covered only by a synthetic mock observation.

## PID handling

A PID file is stale when its process is absent or its command does not match the ebook bridge. The offline contract reports `stale-pid`; it never terminates the referenced process.

## Discovery

When HTTP is healthy, discovery may prefer HTTP. When HTTP is stopped or stale and CLI minimal health is ready, discovery prefers:

```powershell
python batch_convert_books.py --health-check
```

HTTP URL discovery must read `config/http.env`. Registry changes remain proposal-only in this goal.
