# Incremental Backend Scaffolding

This implementation adds local-only evidence contracts without installing models, starting services, or changing routing.

- Docling writes `*.docling-document.json` only after a successful Docling conversion. A sidecar write failure is diagnostic-only and never changes Markdown fallback behavior.
- `gmft_table` and `opendataloader_pdf_fast` are candidate-only workers. Their `execute` mode returns `skipped`; neither imports/downloads a model, starts a service, or processes a real parser result.
- `evaluate_document_quality.py` reads existing review-bundle JSON plus optional reference thresholds. It reports `text`, `table`, `formula`, `layout`, and `reading_order` individually. Missing reference data is `not_evaluated`; it never emits an overall score.
- Quality evaluation JSON can be attached to a review bundle and loaded by `generate_backend_scorecard.py --quality-evaluation <path>`. Environment and promotion gates remain authoritative.

The fixture manifest at `benchmarks/fixtures/incremental-candidate-fixtures.json` is design-only: its paths are intentionally empty and it does not download or generate PDFs.