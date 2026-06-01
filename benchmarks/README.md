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
  --output D:\used-by-codex\ebook_markdown_pipeline\benchmarks\runs\latest
```

Compare PDF pipelines:

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\scripts\compare_pipelines.py `
  --input D:\books\sample.pdf `
  --output D:\used-by-codex\ebook_markdown_pipeline\benchmarks\compare-runs\sample `
  --pipelines pymupdf4llm mineru umi docling
```

Stress HTTP agent calls:

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\scripts\stress_agent_http.py `
  --url http://127.0.0.1:8765 `
  --manifest D:\used-by-codex\ebook_markdown_pipeline\benchmarks\samples.local.json `
  --iterations 20 `
  --concurrency 4
```
