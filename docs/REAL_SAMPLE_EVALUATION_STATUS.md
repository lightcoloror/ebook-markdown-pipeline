# Real Sample Evaluation Status

Last updated: 2026-06-01 15:50

This document tracks the evidence needed before changing default pipelines, especially the optional Docling backend.

## Current Sample Set

Local manifest: `benchmarks/samples.local.json`

The manifest is intentionally not committed because it contains local file paths, but it currently contains 50 real samples:

| Category | Count |
| --- | ---: |
| scanned_pdf | 10 |
| complex_pdf | 10 |
| pdf | 10 |
| docling_doc | 10 |
| ebook | 7 |
| image_set | 3 |

This satisfies the target shape for real-sample coverage: ebooks, scanned PDFs, complex PDFs, screenshot/image sets, and DOCX/PPTX-like document formats.

## Latest Timeboxed Evidence

Run directory: `benchmarks/runs/real-25-timeboxed`

Command:

```powershell
python scripts\run_benchmarks.py `
  --manifest benchmarks\samples.local.json `
  --output benchmarks\runs\real-25-timeboxed `
  --limit 25 `
  --overwrite `
  --sample-timeout 90
```

The run was interrupted at the host/tool layer, but `benchmark-results.partial.json` preserved 9 completed records:

| Status | Count | Evidence |
| --- | ---: | --- |
| timeout | 6 | PDF/MinerU samples exceeded 90 seconds. |
| failed | 2 | Docling documents failed because the optional `docling` package is not installed. |
| failed | 1 | Image set failed because Umi-OCR returned invalid JSON for one batch. |

Partial Docling policy: `keep_optional`

This is not enough to make Docling default because the dependency is missing; it only proves that the current environment should keep Docling optional.

## Stability Fixes Added From This Evidence

- `run_benchmarks.py --sample-timeout` marks a stuck sample as `timeout` and continues the batch.
- `benchmark-results.partial.json` is written after every sample.
- `benchmark-summary.partial.md` and `docling-decision.partial.md` are also written for interrupted runs.
- On Windows, timed-out samples terminate the child process tree with `taskkill /T /F` so MinerU/Marker subprocesses do not remain as long-lived orphans.

## Current Blockers For Final Decision

- Docling is not installed in the active Python environment.
- MinerU is available through a separate local venv path but not importable in the active Python environment; timeboxed PDF runs show MinerU-like paths can still leave heavy subprocesses if the parent process is externally aborted.
- Umi-OCR can return invalid JSON for some image batches; this needs either input isolation, per-image retry, or better stderr/stdout capture in the image rebuild pipeline.
- GitHub push is currently blocked by an invalid `gh` token, but local commits are clean.

## Next Required Runs

After installing Docling and confirming MinerU command paths, run:

```powershell
python scripts\run_benchmarks.py `
  --manifest benchmarks\samples.local.json `
  --output benchmarks\runs\full-real-01 `
  --overwrite `
  --sample-timeout 600
```

Then choose 3-5 representative PDFs and run:

```powershell
python scripts\compare_pipelines.py `
  --input D:\path\to\sample.pdf `
  --output benchmarks\compare-runs\sample `
  --pipelines pymupdf4llm mineru umi docling `
  --overwrite
```

## Decision Rule For Docling

Keep Docling optional until real local runs show:

- at least 8 document-like samples are attempted with Docling installed,
- success rate is at least 80%,
- good-quality rate is at least 60%,
- failures are actionable or isolated to unsupported file types.

Only then consider making Docling the default for DOCX/PPTX/XLSX/HTML/CSV. PDF should still be decided by the PDF comparison reports, not by Docling document-format performance.
