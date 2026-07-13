# W6-G41 Offline Quality Routing Completion

Updated: 2026-07-11 17:07:29 +08:00
Acting agent: Codex
Status: complete

## Result

The project now has a deterministic, read-only offline stage-quality evaluator for parse, layout, image, table, OCR, asset, and Markdown stages. It does not change default conversion backend selection.

Artifact existence and quality acceptance are separate fields. An existing artifact may be degraded and require review without being represented as quality-passed.

## Route evidence

Eight synthetic local cases cover text PDF, scanned PDF, EPUB, Office, mixed-image material, complex PDF, and a table-gap probe:

| Route | Count |
| --- | ---: |
| `minimal-deliverable` | 1 |
| `degraded` | 5 |
| `fallback-proposed` | 1 |
| `blocked` | 1 |

Five cases explicitly have `artifact_exists=true` and `quality_passed=false`. Seven cases expose `manual_review_required` and exact review stages. No human action was required during this goal.

The scanned PDF case proposes RapidOCR only when the frozen local capability is `ok`; the same fixture is `blocked` when local OCR is marked missing. The table probe remains degraded because dedicated table extraction is missing. Proposals are non-automatic and version-neutral.

## Files

- Evaluator: `offline_quality_router.py`
- Read-only CLI: `scripts/offline_quality_route.py`
- Evidence runner: `scripts/run_offline_quality_evidence.py`
- Contract: `docs/OFFLINE_STAGE_QUALITY_CONTRACT.md`
- CP1 baseline: `benchmarks/runs/w6-g41-offline-quality/cp1-baseline-20260711.json`
- CP3-CP5 evidence: `benchmarks/runs/w6-g41-offline-quality/cp3-cp5-20260711/offline-quality-evidence.json`
- Completion audit: `benchmarks/runs/w6-g41-offline-quality/completion-audit-20260711.json`

## Verification

- Health: `health-check-v2`, `minimal_ok=true`, optional state `degraded_optional`.
- Readiness: 42/42 passed.
- Quality gate: 7/7 passed.
- Unittest compatibility: 1/1 passed.
- Targeted pytest: 2/2 passed.
- Full pytest: 83/83 passed in 437.29 seconds.
- Deterministic evidence: two runs produced SHA-256 `9092eaf77c752ee7895d658a374105a54d7ef749879bb359497b28c06d85189e`.
- JUnit SHA-256: `ecb0486139ea29dc7b5d070e0a716af3e6adaac562c4665a514bdd0d29b20008`.
- Sensitive scan: clean.
- Port 8765 listeners before/after: 0/0.
- Residual W6 test processes: 0.
- Core converter, artifact schema, MCP, and readiness hashes remained unchanged from CP1.

## Boundaries

No network call, model download, dependency install, private document processing, persistent service, shared registry write, knowledge-base write, commit, or push was performed. Existing uncommitted work was preserved.
