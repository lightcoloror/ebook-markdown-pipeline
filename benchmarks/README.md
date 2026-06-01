# Benchmarks

This folder defines repeatable real-sample evaluation for the converter.

Local files are not committed. Use:

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\scripts\discover_benchmark_samples.py `
  D:\downloads `
  D:\BaiduSyncdisk\电子书 `
  --output D:\used-by-codex\ebook_markdown_pipeline\benchmarks\samples.local.json `
  --limit 50
```

Run a benchmark:

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\scripts\run_benchmarks.py `
  --manifest D:\used-by-codex\ebook_markdown_pipeline\benchmarks\samples.local.json `
  --output D:\used-by-codex\ebook_markdown_pipeline\benchmarks\runs\latest `
  --sample-timeout 600 `
  --pdf-mode-for-benchmark fast
```

Each run writes:

- `benchmark-results.json`: complete machine-readable records for agents and later aggregation.
- `benchmark-results.partial.json`: incrementally updated after each sample, so interrupted long runs still preserve completed evidence.
- `benchmark-summary.md`: human review table with status, quality, runtime, sample category, and failure reason.
- `benchmark-summary.partial.md`: readable partial summary for interrupted runs.
- `docling-decision.md`: evidence-based recommendation for whether Docling should become default for document-like formats. Missing dependencies or weak real-sample success keep Docling optional.

Use `--sample-timeout` to mark one stuck sample as `timeout` and continue the rest of the run. On Windows, the runner terminates the timed-out process tree so MinerU/Marker children do not linger as orphan processes.

Use `--pdf-mode-for-benchmark fast` to route PDFs through `PyMuPDF4LLM` during broad sample-set runs. This gives a stable baseline for 20-50 samples; use `compare_pipelines.py` for slower high-quality PDF pipeline comparisons.

Compare PDF pipelines:

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\scripts\compare_pipelines.py `
  --input D:\books\sample.pdf `
  --output D:\used-by-codex\ebook_markdown_pipeline\benchmarks\compare-runs\sample `
  --pipelines pymupdf4llm mineru umi docling `
  --pipeline-timeout 600
```

The comparison report writes `pipeline-comparison.md` with runtime, heading count, text length, table hints, page-number noise hints, and manual scoring slots. `--pipeline-timeout` marks one slow pipeline as `timeout` and continues; partial JSON/Markdown reports are written after every pipeline. The desktop UI exposes the same workflow through `PDF对比 / Compare`; `推荐重跑 / Rerun Rec` reprocesses the selected item with its recommended pipeline.

Stress HTTP agent calls:

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\scripts\stress_agent_http.py `
  --url http://127.0.0.1:8765 `
  --manifest D:\used-by-codex\ebook_markdown_pipeline\benchmarks\samples.local.json `
  --iterations 20 `
  --concurrency 4 `
  --retries 2
```

The stress summary records success rate, artifact read rate, average duration, and max duration. Transient network errors, 5xx responses, and `/call` envelopes with `retryable=true` are retried according to `--retries`.

Use `--run-timeout` to put a wall-clock limit on the whole stress run. Completed iterations are written incrementally to `agent-stress-results.partial.json` and `agent-stress-summary.partial.md`, so interrupted or timeboxed runs still preserve evidence. Use `--http-timeout` to keep individual `/call` requests from hanging too long while polling jobs or reading artifacts.
