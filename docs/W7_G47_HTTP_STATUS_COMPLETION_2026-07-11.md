# W7-G47 Ebook HTTP Status Completion

Updated: 2026-07-11 19:19:08 +08:00
Acting agent: Codex
Queue: `RFQ-F355DEE60F08`
Status: complete with documented environment constraint

## Result

The project now has an offline `ebook-http-status-contract-v1` that keeps four dimensions independent:

- CLI readiness from `health-check-v2.minimal_ok`.
- Configured HTTP runtime state.
- Optional backend readiness.
- Minimal output and quality-route state.

A stopped listener does not make the CLI unusable. Missing optional backends do not block the core CLI, but they prevent claims of full quality support. Artifact existence and quality acceptance remain separate.

## Port authority

Queue evidence recorded port 8765 as stopped. Current project configuration uses `http://127.0.0.1:9241`. The contract therefore preserves 8765 as non-authoritative legacy evidence and always discovers the current URL through `config/http.env`.

Neither port was started. Final connection probes returned 10035 for both ports.

## Fixture evidence

Five synthetic cases cover:

- Legacy 8765 stopped while configured HTTP is stopped.
- Healthy listener mock without a real socket.
- Stale PID.
- CLI ready while HTTP is stopped.
- Missing optional backends with degraded output.

Four non-healthy HTTP cases still discover a callable CLI. Two cases explicitly show an existing artifact whose quality did not pass. No fixture makes 8765 current authority.

## Files

- Status composer: `http_status_contract.py`
- Read-only CLI: `scripts/check_http_status_contract.py`
- Fixture: `benchmarks/fixtures/ebook-http-status-contract.json`
- Evidence runner: `scripts/run_http_status_evidence.py`
- Contract: `docs/HTTP_STATUS_CONTRACT.md`
- Proposal-only discovery metadata: `docs/HTTP_STATUS_DISCOVERY_PROPOSAL.json`
- Evidence: `benchmarks/runs/w7-g47-http-status/cp3-cp5-20260711/http-status-evidence.json`
- Audit: `benchmarks/runs/w7-g47-http-status/completion-audit-20260711.json`

## Verification

- Readiness: 42/42 passed.
- Service readiness test: passed.
- HTTP status contract test: passed.
- HTTP status evidence test: passed.
- Unittest compatibility: 1/1 passed.
- Targeted pytest: 2/2 passed; 83 unrelated legacy cases deselected.
- Deterministic double run: SHA-256 `e9b55baee5dff2754129bf62ac2c151b919cd0e73598b182804f3ceeb0779f4d`.
- Sensitive scan: clean.
- Residual W7 processes: 0.
- Core HTTP/config and shared registry hashes: unchanged.

The current quality-gate attempt was not reported as passed: all seven unchanged conversion samples hit their 90-second timeout under machine-wide resource contention. W6's frozen evidence remains 7/7 quality-gate and 83/83 pytest, and converter hashes are unchanged. One confirmed W7 health-check process that had exceeded its normal window was terminated; no unrelated process was touched.

## Boundaries

No HTTP service, external API, download, dependency installation, private document, Docker, proxy/MCP, account, publication, shared registry write, or knowledge-base write occurred. Existing uncommitted work was preserved. No commit or push was performed.
