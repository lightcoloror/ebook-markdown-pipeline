# Benchmarks

This folder defines repeatable real-sample evaluation for the converter.

## Public Quality Gate

The repository includes generated public fixtures for lightweight regression checks. They contain only synthetic text, EPUB, PDF, and image materials; no copyrighted books are required.

Generate fixtures only:

```powershell
python scripts\generate_quality_fixtures.py
```

Run the default lightweight gate:

```powershell
python scripts\run_quality_gate.py
```

The default `minimal` profile covers `TXT`, `EPUB`, an `AZW3 substitute` sample, text-layer PDF, two-column PDF, and PPT-exported slide-like PDF. It is intended for ordinary development before/after checks.

Use the full profile when you intentionally want OCR/image-heavy coverage:

```powershell
python scripts\run_quality_gate.py --profile full
```

The `full` profile additionally includes a scanned image-only PDF, an infographic PNG, and an unordered/duplicate screenshot folder. It may require local OCR/VLM dependencies depending on the pipeline choices.

## Private Real-Sample Manifests

Local files are not committed. Use:

```powershell
python scripts\discover_benchmark_samples.py `
  C:\books `
  C:\more-books `
  --output benchmarks\samples.local.json `
  --limit 50
```

For a fixed quality regression set, copy `benchmarks/sample-set-manifest.example.json` to a local manifest such as `benchmarks/samples.local.json`, replace paths with local files, and keep that local manifest uncommitted.

Run a benchmark:

```powershell
python scripts\run_benchmarks.py `
  --manifest benchmarks\samples.local.json `
  --output benchmarks\runs\latest `
  --sample-timeout 600 `
  --pdf-mode-for-benchmark fast
```

Each run writes:

- `benchmark-results.json`: complete machine-readable records for agents and later aggregation.
- `benchmark-results.partial.json`: incrementally updated after each sample, so interrupted long runs still preserve completed evidence.
- `benchmark-summary.md`: human review table with status, quality, runtime, sample category, and failure reason.
- `benchmark-summary.partial.md`: readable partial summary for interrupted runs.
- `quality-regression-summary.json/md`: aggregated metrics for success, headings, page-heading ratio, text volume, repeated noise, fallback count, and review/poor count.
- `docling-decision.md`: evidence-based recommendation for whether Docling should become default for document-like formats. Missing dependencies or weak real-sample success keep Docling optional.

Use `--sample-timeout` to mark one stuck sample as `timeout` and continue the rest of the run. On Windows, the runner terminates the timed-out process tree so MinerU/Marker children do not linger as orphan processes.

Use `--pdf-mode-for-benchmark fast` to route PDFs through `PyMuPDF4LLM` during broad sample-set runs. This gives a stable baseline for 20-50 samples; use `compare_pipelines.py` for slower high-quality PDF pipeline comparisons.

Compare PDF pipelines:

```powershell
python scripts\compare_pipelines.py `
  --input C:\books\sample.pdf `
  --output benchmarks\compare-runs\sample `
  --pipelines pymupdf4llm mineru umi docling `
  --pipeline-timeout 600
```

The comparison report writes `pipeline-comparison.md` with runtime, heading count, text length, table hints, page-number noise hints, and manual scoring slots. `--pipeline-timeout` marks one slow pipeline as `timeout` and continues; partial JSON/Markdown reports are written after every pipeline. The desktop UI exposes the same workflow through `PDF对比 / Compare`; `推荐重跑 / Rerun Rec` reprocesses the selected item with its recommended pipeline.

For very long PDFs, compare selected pages instead of the whole book:

```powershell
python scripts\compare_pipelines.py `
  --input C:\books\huge.pdf `
  --output benchmarks\compare-runs\huge-pages `
  --pipelines pymupdf4llm mineru umi docling `
  --pipeline-timeout 120 `
  --page-ranges 1-3,100-102,600-602
```

`--page-ranges` uses 1-based page numbers, extracts a small comparison PDF, and records both the original PDF and extracted page range in the report.

Summarize multiple PDF comparisons:

```powershell
python scripts\summarize_pdf_comparisons.py `
  benchmarks\compare-runs\sample-a `
  benchmarks\compare-runs\sample-b `
  --output benchmarks\compare-runs\summary.md
```

The summary report lists the requested pipeline, actual pipeline, status, score, headings, text length, runtime, and links back to each detailed comparison. Actual pipeline matters when a requested backend succeeds through fallback, such as `docling` producing `pymupdf4llm(fallback from docling)`.

Stress HTTP agent calls:

```powershell
python scripts\stress_agent_http.py `
  --manifest benchmarks\samples.local.json `
  --iterations 20 `
  --concurrency 4 `
  --retries 2
```

The stress summary records success rate, artifact read rate, average duration, and max duration. Transient network errors, 5xx responses, and `/call` envelopes with `retryable=true` are retried according to `--retries`.

Use `--run-timeout` to put a wall-clock limit on the whole stress run. Completed iterations are written incrementally to `agent-stress-results.partial.json` and `agent-stress-summary.partial.md`, so interrupted or timeboxed runs still preserve evidence. Use `--http-timeout` to keep individual `/call` requests from hanging too long while polling jobs or reading artifacts.

For agent-facing PDF stability checks, combine `--pdf-pipeline-mode`, `--pdf-tool-idle-timeout`, `--pdf-tool-finalize-timeout`, and `--docling-timeout`. Conversion reports include `pdf_fallback_diagnostics` when a slow or failed PDF backend falls back to PyMuPDF4LLM, and `docling_diagnostics` when Docling itself is timeboxed.

Docker container smoke:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_docker_agent_smoke.ps1 `
  -Port 8770 `
  -ReportDir benchmarks\runs\docker-agent-smoke-current `
  -ContainerIterations 2
```

This starts the converter HTTP bridge, creates tiny fixtures for common formats, runs one local conversion job, then calls `/health`, `/call scan_books`, repeated `/call start_conversion`, `/call get_job_status`, and `/call read_artifact` from the `openclaw-openclaw-gateway-1` and `hermes-agent` Docker containers through `host.docker.internal`. The report is written as `docker-agent-smoke.json` and `docker-agent-smoke.md`.
