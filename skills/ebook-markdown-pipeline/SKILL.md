# Ebook Markdown Pipeline

Use this skill when a user asks to convert EPUB, AZW, MOBI, FB2, TXT, RTF, ODT, or PDF files into Markdown, HTML, or plain text with chapter/title structure, reports, and failure recovery. Also use it when the user wants page/image-level location search or screenshot-to-Markdown reconstruction.

## Preferred Path

1. Use `process_material` through the MCP server when available.
2. Use the CLI when MCP is unavailable.
3. Do not reimplement ebook or PDF parsing in the agent.

## MCP Server

Start command:

```powershell
D:\used-by-codex\ebook_markdown_pipeline\start_mcp.cmd
```

Smoke test:

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\scripts\test_mcp_stdio.py
```

Use these tools:

- `process_material`: default high-level entry point; inspect input and route to conversion, location indexing, or image-book rebuilding.
- `scan_books`: inspect sources and planned pipelines.
- `health_check`: verify Pandoc, Calibre, MinerU, Marker, PyMuPDF4LLM, Umi-OCR, CUDA, and model cache.
- `export_environment_report`: write Markdown/JSON environment diagnostics artifacts for handoff or debugging.
- `inspect_document`: lightweight preflight for unknown inputs.
- `start_conversion`: launch conversion as a background job.
- `get_job_status`: poll progress and results.
- `read_artifact`: read Markdown, JSON, reports, and logs exposed by returned artifacts.
- `read_report`: inspect a generated report JSON.
- `read_pdf_tool_log`: inspect Marker/MinerU logs.
- `build_location_index`: build a lightweight PDF-page/image search index when exact layout is not required.
- `query_location_index`: search the lightweight location index and return source plus page/image.
- `start_location_index`: launch location indexing as a background job.
- `start_image_book_rebuild`: reconstruct Markdown from unordered or duplicate screenshots as a background job.
- `process-web-archive.cmd`: prepare `visual_check/` outputs for a `web-content-fetcher` archive; it first tries screenshot OCR through `image_book_rebuilder` and falls back to a pending visual contract if OCR is unavailable.

## CLI Fallback

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\batch_convert_books.py INPUT OUTPUT --recursive --resume --output-format markdown
```

## Decision Rules

- Prefer `process_material` first unless the user already specified a specialist action.
- Always inspect or scan before conversion when the user provides a folder or multiple files.
- Run health check before the first conversion in a new machine/session.
- Use `pdf_pipeline_mode=auto` by default.
- If the user only needs to know which PDF page or image contains information, use the location index tools instead of full Markdown conversion.
- If the input is a large folder of screenshots, use image-book reconstruction rather than plain OCR.
- If the input is a `web-content-fetcher` archive folder, first run `wcf archive rebuild <archive> --with-visual-check`, then run `D:\used-by-codex\ebook_markdown_pipeline\process-web-archive.cmd <archive>`, then rerun `wcf archive rebuild` so final human/agent files absorb OCR text, visual blocks, and review warnings.
- Do not force Marker on long PDFs unless the user explicitly asks.
- For long jobs, start conversion and poll status instead of blocking indefinitely.
- Prefer returned `artifacts` and `next_actions` over guessing output paths.
- If a PDF conversion fails or looks poor, inspect `.reports/summary.md`, `.reports/review-checklist.md`, per-book report JSON, and `.reports/pdf-tool-logs/*.log`.

## Output Expectations

Report back:

- Output file paths.
- Success/failure count.
- Pipeline used.
- Report path.
- Any quality warnings or fallback events.
