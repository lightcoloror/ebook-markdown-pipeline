# Offline Stage Quality Contract

Status: implemented locally
Schema: `offline-stage-quality-v1`
Updated: 2026-07-11
Acting agent: Codex

## Purpose

Evaluate existing local reports without changing conversion backends. Artifact existence and quality acceptance are independent.

## Vocabulary

| Stage | Question |
| --- | --- |
| `parse` | Does a non-empty parsed artifact exist? |
| `layout` | Is reading order and heading structure evidenced? |
| `image` | Is semantic image content recovered when required? |
| `table` | Is row and column retention evidenced? |
| `ocr` | Is OCR present and sufficiently confident? |
| `asset` | Are referenced local assets complete? |
| `markdown` | Does Markdown meet deterministic minimum quality? |

Stage statuses: `passed`, `degraded`, `blocked`, `not_applicable`, `not_evaluated`.

Route statuses:

- `minimal-deliverable`: all required deterministic stages passed.
- `degraded`: an artifact exists, but required stages need review.
- `blocked`: a required stage failed and no proven local fallback exists.
- `fallback-proposed`: a required stage failed and an available local fallback may be tried explicitly.

## Invariants

- `artifact.exists=true` never implies `quality.passed=true`.
- Evaluation deep-copies input and is read-only.
- Fallback proposals are never automatic and never change the default backend.
- OCR, layout, table, and asset gaps expose evidence and `manual_review_required`.
- Missing optional backends cannot be represented as full support.
- No API, model download, private document, registry write, or persistent service is required.

## Interfaces

```python
from ebook_markdown_pipeline.offline_quality_router import evaluate_offline_quality
```

```powershell
python scripts\offline_quality_route.py report.json --source-kind text_pdf
```

The CLI writes only when `--output` is explicitly supplied.
