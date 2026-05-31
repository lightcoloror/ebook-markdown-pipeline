# Ebook Markdown Pipeline

Use this skill when a user asks to convert EPUB, AZW, MOBI, FB2, TXT, RTF, ODT, or PDF files into Markdown, HTML, or plain text with chapter/title structure, reports, and failure recovery.

## Preferred Path

1. Use the MCP server when available.
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

- `scan_books`: inspect sources and planned pipelines.
- `health_check`: verify Pandoc, Calibre, MinerU, Marker, PyMuPDF4LLM, Umi-OCR, CUDA, and model cache.
- `start_conversion`: launch conversion as a background job.
- `get_job_status`: poll progress and results.
- `read_report`: inspect a generated report JSON.
- `read_pdf_tool_log`: inspect Marker/MinerU logs.

## CLI Fallback

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\batch_convert_books.py INPUT OUTPUT --recursive --resume --output-format markdown
```

## Decision Rules

- Always scan before conversion when the user provides a folder or multiple files.
- Run health check before the first conversion in a new machine/session.
- Use `pdf_pipeline_mode=auto` by default.
- Do not force Marker on long PDFs unless the user explicitly asks.
- For long jobs, start conversion and poll status instead of blocking indefinitely.
- If a PDF conversion fails or looks poor, inspect `.reports/summary.md`, `.reports/review-checklist.md`, per-book report JSON, and `.reports/pdf-tool-logs/*.log`.

## Output Expectations

Report back:

- Output file paths.
- Success/failure count.
- Pipeline used.
- Report path.
- Any quality warnings or fallback events.
