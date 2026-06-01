# Real Sample Evaluation Status

Last updated: 2026-06-01 18:02

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

## Latest Full Real Benchmark Verification

Run directory: `benchmarks/runs/full-real-current`

Command:

```powershell
python scripts\run_benchmarks.py `
  --manifest benchmarks\samples.local.json `
  --output benchmarks\runs\full-real-current `
  --overwrite `
  --sample-timeout 120 `
  --pdf-mode-for-benchmark fast
```

Result:

| Metric | Result |
| --- | --- |
| Samples | 50 |
| Status | 50 ok |
| Quality | 35 good, 8 review, 4 poor, 3 unscored image sets |
| Categories | 10 scanned_pdf, 10 complex_pdf, 10 pdf, 10 docling_doc, 7 ebook, 3 image_set |
| PDF mode | fast -> `pymupdf4llm` |
| Slowest sample | 93.905 seconds, complex layered PDF, quality poor |
| Docling docs | 10 ok, 8 good, 2 review |
| Docling decision | enable_docling_for_docling_formats |

This is the strongest stability evidence so far: the full 50-sample manifest completed without failures under the current timeout/fallback protections. Remaining work is quality-focused rather than crash/stuck-focused: the 4 poor and 8 review outputs mostly lack Markdown headings, contain HTML residue, or show OCR line-break noise. These are candidates for targeted PDF pipeline comparison and structure-enhancement passes rather than broad stability fixes.

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

## Latest Targeted Poor/Review PDF Comparisons

Summary report: `benchmarks/compare-runs/review-quality-summary-current.md`

Compared representative poor/review PDFs from `benchmarks/runs/full-real-current` with `pymupdf4llm`, `mineru`, `umi`, and `docling`, using a 75 second per-pipeline timeout:

| Sample | Result |
| --- | --- |
| `03定位认知：如何找到适合自己的内容方向？.pdf` | `umi-ocr` was best: score 90, 2 headings, 5.358 seconds. `pymupdf4llm` scored 74 with no headings; MinerU timed out; Docling fell back to PyMuPDF4LLM. |
| `Daily-Emotions-Charts-for-Adults.pdf` | `umi-ocr` was best: score 90, 3 headings, 3.642 seconds. `pymupdf4llm` scored 60 with no headings; MinerU timed out; Docling fell back to PyMuPDF4LLM. |
| `[OCR]_名老中医之路（周凤梧）_20250818_1257.layered.pdf` | All four whole-document pipelines timed out at 75 seconds. The PDF has 1238 pages and 113 bookmarks, so it should be compared by segment or sampled pages rather than whole-book four-pipeline runs. |
| `[OCR]_名老中医之路（周凤梧）_20250818_1257.layered.pdf`, pages `1-3,100-102,600-602` | Page-range comparison completed. `umi-ocr` produced the most usable text volume and 10 headings in 7.974 seconds, but scored 65 because of OCR short-line noise. `pymupdf4llm` was fast but extracted only 72 characters. MinerU still timed out at 90 seconds; Docling fell back to PyMuPDF4LLM. |

`compare_pipelines.py` now records both requested and actual pipeline. This matters because Docling PDF attempts can succeed through `pymupdf4llm(fallback from docling)`, and the comparison report should not mislabel fallback output as native Docling quality.

Interpretation: for short scanned or visual PDFs where the user mainly wants usable text and rough headings, Umi-OCR is currently the strongest fallback. For long layered books, the next quality task is page-range/segment comparison, not increasing whole-document timeouts blindly.

`compare_pipelines.py --page-ranges` now supports 1-based selected-page comparison for very long PDFs. This makes long-book quality review practical without committing every pipeline to the entire document.

Umi-OCR Markdown post-processing now keeps page boundaries as HTML comments instead of `## Page N` headings, and conservatively promotes likely OCR page titles such as `出版者的话` / `澹前颜后话医德`. On the same layered-PDF page-range sample, Umi-OCR improved from score 65 / review / 10 mostly page headings to score 90 / good / 3 content headings, while preserving page markers as comments. A short scanned PDF smoke check remained score 90.

The desktop UI now exposes page-range PDF comparison through the `对比页码 / Pages` field next to the compare timeout. When populated with values such as `1-3,100,600-602`, `PDF对比 / Compare` passes `--page-ranges` to `compare_pipelines.py`; the value is saved in the UI config and restored on restart.

## Latest Agent HTTP Stress Verification

Fast run directory: `benchmarks/runs/agent-http-fast`

Command shape:

```powershell
python scripts\stress_agent_http.py `
  --url http://127.0.0.1:8770 `
  --manifest benchmarks\agent-stress-fast.local.json `
  --output benchmarks\runs\agent-http-fast\stress `
  --iterations 4 `
  --concurrency 2 `
  --timeout 60 `
  --run-timeout 160 `
  --http-timeout 15 `
  --retries 1 `
  --pdf-pipeline-mode pymupdf4llm
```

Result:

| Metric | Result |
| --- | --- |
| Iterations | 4 |
| Concurrency | 2 |
| Status | 4 ok |
| Artifact reads | 4 / 4 |
| Success rate | 1.0 |
| Average duration | 3.919 seconds |
| Max duration | 6.695 seconds |

Mixed run directory: `benchmarks/runs/agent-http-mixed-timeboxed`

The mixed run used the broader local agent manifest with 6 iterations, concurrency 2, 70 second job polling timeout, and 180 second wall-clock run timeout.

| Metric | Result |
| --- | --- |
| Iterations | 6 |
| Concurrency | 2 |
| Status | 5 ok, 1 failed |
| Artifact reads | 5 / 6 |
| Success rate | 0.833 |
| Artifact read rate | 0.833 |
| Average duration | 14.866 seconds |
| Max duration | 76.918 seconds |
| Failure | One DOCX sample remained `running` past the 70 second polling timeout. |

Agent stress tooling now writes `agent-stress-results.partial.json` and `agent-stress-summary.partial.md` after each completed iteration. This means a host-level interruption or a long-running conversion no longer loses all evidence.

Docling fallback verification directories:

- `benchmarks/runs/docling-timeout-fallback`
- `benchmarks/runs/agent-http-slow-docx-fallback`
- `benchmarks/runs/agent-http-mixed-docling-fallback`

Additional result after adding Docling task isolation:

| Run | Result |
| --- | --- |
| Slow DOCX CLI with `--docling-timeout 1` | Conversion succeeded as `docling(fallback)`; report records Docling timeout and Pandoc fallback success. |
| Slow DOCX over HTTP `/call` with `--docling-timeout 20` | 1 / 1 ok, artifact read 1 / 1, duration 38.064 seconds; report records Docling timeout and Pandoc fallback success. |
| Mixed HTTP `/call` with `--docling-timeout 20` | 6 / 6 ok, artifact reads 6 / 6, average duration 13.013 seconds, max duration 17.922 seconds. |

Docling document conversion now runs in an isolated subprocess when `docling_timeout > 0`. The default timeout is 45 seconds, and DOCX/HTML/Markdown/CSV can fall back to a lightweight Pandoc/text path unless `--no-docling-fallback` is set.

PDF fallback verification directories:

- `benchmarks/runs/pdf-docling-fallback`
- `benchmarks/runs/agent-http-pdf-docling-fallback`

Additional PDF fallback result:

| Run | Result |
| --- | --- |
| PDF CLI with `--pdf-pipeline-mode docling --docling-timeout 8` | Conversion succeeded as `pymupdf4llm(fallback from docling)`; report records Docling timeout and `pdf_fallback_diagnostics.status=ok`. |
| PDF over HTTP `/call` with `pdf_pipeline_mode=docling`, `docling_timeout=8`, and PDF tool timeouts | 1 / 1 ok, artifact read 1 / 1, duration 20.371 seconds; report records Docling timeout and PyMuPDF4LLM fallback success. |

`process_material` and `start_conversion` now expose `pdf_tool_idle_timeout`, `pdf_tool_finalize_timeout`, `docling_timeout`, and fallback controls so agents can timebox heavy PDF/document backends without losing artifact access.

Docker agent smoke directory: `benchmarks/runs/docker-agent-smoke-current`

Command shape:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_docker_agent_smoke.ps1 `
  -Port 8770 `
  -ReportDir benchmarks\runs\docker-agent-smoke-current `
  -ContainerIterations 2
```

Result:

| Metric | Result |
| --- | --- |
| Generated formats | txt, fb2, rtf, epub, odt, azw3, mobi, azw, pdf |
| Local HTTP conversion | 10 / 10 ok |
| OpenClaw container `/health` | exit 0 |
| OpenClaw container `/call scan_books` | exit 0, 10 plans |
| OpenClaw container repeated conversion jobs | 2 / 2 done |
| OpenClaw container artifact reads | 2 / 2 ok |
| Hermes container `/health` | exit 0 |
| Hermes container `/call scan_books` | exit 0, 10 plans |
| Hermes container repeated conversion jobs | 2 / 2 done |
| Hermes container artifact reads | 2 / 2 ok |

This verifies that the Dockerized OpenClaw gateway container and Hermes agent container can reach the converter through `host.docker.internal`, repeatedly start async conversion jobs, poll job status, and read Markdown artifacts through the stable HTTP surface. It is intentionally a deterministic gateway/tool smoke rather than an LLM-planner evaluation: it proves the callable integration path that those agents should use, while avoiding model/auth flakiness from each agent's own LLM provider.

## Current Blockers For Final Decision

- Docling 2.96.1 is installed and passed the current document-format threshold. Keep it as the default backend for DOCX/PPTX/XLSX/HTML/Markdown/CSV when the optional dependency is installed.
- MinerU is available through a separate local venv path but not importable in the active Python environment; timeboxed PDF runs show MinerU-like paths can still leave heavy subprocesses if the parent process is externally aborted.
- Umi-OCR can still return invalid JSON for some image batches, but image-book rebuilding now isolates failures per image and records them in the review report instead of failing the whole set.
- Docling's PDF/OCR path may need a writable model/cache directory; the latest PDF comparison failed on a permission issue inside the global Python/site-packages path.
- Installing Docling into the global Python 3.13 environment introduced or exposed dependency conflicts reported by `pip check` for CrewAI, AutoGen, LiteLLM, and related packages. For long-term stability, prefer a project-specific virtual environment for this converter.
- GitHub push is currently blocked by an invalid `gh` token, but local commits are clean.
- Agent HTTP calls are now stable for fast real samples, mixed samples, and direct Docker container access from OpenClaw/Hermes. Slow Docling document jobs now have subprocess isolation, timeout diagnostics, and fallback for DOCX/HTML/Markdown/CSV. PDF fallback diagnostics now record failed/slow Docling/Marker/MinerU attempts and PyMuPDF4LLM fallback status. The remaining agent-facing risk is mostly long-running high-quality PDF backends such as MinerU/Marker on large books, where more representative long-PDF samples should still be benchmarked.

## Next Required Runs

The 50-sample fast benchmark, targeted poor/review PDF comparisons, selected-page comparison, Umi-OCR heading cleanup, and UI page-range compare flow have completed. Next, consider more OCR cleanup for repeated page headers/footers:

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
