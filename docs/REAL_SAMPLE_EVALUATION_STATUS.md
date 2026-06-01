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
- Image-book rebuilding now treats per-image Umi-OCR failures as review items instead of failing the whole screenshot set; it restarts the OCR engine once and records `ocr_status` / `ocr_message` in `pages.jsonl`.
- Screenshot page-number parsing now handles OCR-noisy page markers such as `01108`, `03108`, and `041 08` as `01/08`, `03/08`, and `04/08` when filename ordering supports that interpretation.

## Latest Image Set Verification

Run directory: `benchmarks/runs/image-set-order-smoke`

The previously failing image set `2026年3月21日Claude制作的图文笔记堪称范本` now completes successfully:

| Metric | Result |
| --- | --- |
| Benchmark status | ok |
| Images | 8 |
| Parsed page numbers | 1, 2, 3, 4, 5, 6, 7, 8 |
| Low-confidence order items | 0 |
| OCR failed items | 0 |

This verifies both the Umi-OCR per-image failure isolation path and the noisy page-number ordering improvement on a real screenshot set.

## Current Blockers For Final Decision

- Docling is not installed in the active Python environment.
- MinerU is available through a separate local venv path but not importable in the active Python environment; timeboxed PDF runs show MinerU-like paths can still leave heavy subprocesses if the parent process is externally aborted.
- Umi-OCR can still return invalid JSON for some image batches, but image-book rebuilding now isolates failures per image and records them in the review report instead of failing the whole set.
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
