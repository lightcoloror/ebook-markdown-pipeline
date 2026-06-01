# Real Sample Evaluation Status

Last updated: 2026-06-01 16:20

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
- The desktop UI exposes review-flow buttons for opening outputs/reports/artifacts, opening the review checklist, retrying failures, rerunning with the recommended pipeline, copying failure reasons, and exporting PDF comparison reports with per-pipeline timeouts.

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

## Latest Fast PDF Benchmark Verification

Run directory: `benchmarks/runs/fast-real-20-docling`

Command:

```powershell
python scripts\run_benchmarks.py `
  --manifest benchmarks\samples.local.json `
  --output benchmarks\runs\fast-real-20-docling `
  --limit 20 `
  --overwrite `
  --sample-timeout 90 `
  --pdf-mode-for-benchmark fast
```

Result:

| Metric | Result |
| --- | --- |
| Samples | 20 |
| Status | 18 ok, 2 timeout |
| Quality | 12 good, 5 review |
| PDF mode | fast -> `pymupdf4llm` |
| PDF runtime | Most sampled PDFs completed in about 5-15 seconds; one scanned PDF took about 30 seconds; one complex layered PDF timed out at 90 seconds. |
| Docling docs | 7 ok, 1 timeout |
| Docling version | 2.96.1 |
| Docling decision | enable_docling_for_docling_formats |

This separates broad sample-set stability benchmarking from slow high-quality PDF pipeline comparison. Use `--pdf-mode-for-benchmark fast` for 20-50 sample runs, then use `compare_pipelines.py` for selected representative PDFs.

## Latest Four-Pipeline PDF Comparison

Run directory: `benchmarks/compare-runs/real-four-pipelines-01`

Command:

```powershell
python scripts\compare_pipelines.py `
  --input "D:\downloads\03定位认知：如何找到适合自己的内容方向？.pdf" `
  --output benchmarks\compare-runs\real-four-pipelines-01 `
  --pipelines pymupdf4llm mineru umi docling `
  --overwrite `
  --pipeline-timeout 60
```

Result:

| Pipeline | Status | Seconds | Score | Notes |
| --- | --- | ---: | ---: | --- |
| pymupdf4llm | ok | 6.411 | 74 | Fast baseline, longer OCR text, no headings. |
| mineru | timeout | 70.056 |  | Timed out under the 60 second per-pipeline limit. |
| umi | ok | 4.099 | 90 | Best score on this one-page scanned sample; shorter text and two headings. |
| docling | failed | 7.189 |  | PDF/OCR path failed with a local permission/model-cache issue. |

This confirms that document-format Docling success should not be generalized to PDF defaults. PDF defaults should remain preflight/pipeline specific, and representative PDFs should be compared with per-pipeline timeouts.

## Current Blockers For Final Decision

- Docling 2.96.1 is installed and passed the current document-format threshold. Keep it as the default backend for DOCX/PPTX/XLSX/HTML/Markdown/CSV when the optional dependency is installed.
- MinerU is available through a separate local venv path but not importable in the active Python environment; timeboxed PDF runs show MinerU-like paths can still leave heavy subprocesses if the parent process is externally aborted.
- Umi-OCR can still return invalid JSON for some image batches, but image-book rebuilding now isolates failures per image and records them in the review report instead of failing the whole set.
- Docling's PDF/OCR path may need a writable model/cache directory; the latest PDF comparison failed on a permission issue inside the global Python/site-packages path.
- Installing Docling into the global Python 3.13 environment introduced or exposed dependency conflicts reported by `pip check` for CrewAI, AutoGen, LiteLLM, and related packages. For long-term stability, prefer a project-specific virtual environment for this converter.
- GitHub push is currently blocked by an invalid `gh` token, but local commits are clean.

## Next Required Runs

After confirming MinerU command paths, run:

```powershell
python scripts\run_benchmarks.py `
  --manifest benchmarks\samples.local.json `
  --output benchmarks\runs\full-real-01 `
  --overwrite `
  --sample-timeout 600 `
  --pdf-mode-for-benchmark fast
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

The current local evidence meets the threshold for document-like formats:

- at least 8 document-like samples are attempted with Docling installed,
- success rate is at least 80%,
- good-quality rate is at least 60%,
- failures are actionable or isolated to unsupported file types.

Decision: enable Docling by default for DOCX/PPTX/XLSX/HTML/CSV/Markdown when the optional dependency is installed.

PDF should still be decided by the PDF comparison reports, not by Docling document-format performance.
