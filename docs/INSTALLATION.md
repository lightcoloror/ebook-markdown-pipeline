# Installation

This project is local-first and modular. You do not need to install every backend before using it. Start with the smallest useful setup, then add heavier PDF/OCR/VLM/Agent pieces only when your materials need them.

## 1. Minimal Setup

Good for:

- EPUB, FB2, TXT, ODT to Markdown.
- Text-layer PDFs through PyMuPDF4LLM/PyMuPDF.
- Desktop UI, basic CLI, and lightweight reports.

Install:

```powershell
git clone https://github.com/lightcoloror/ebook-markdown-pipeline.git
cd ebook-markdown-pipeline
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Recommended external tool:

- Pandoc for EPUB/FB2/TXT/ODT and Markdown/HTML/text conversion.

Start the UI:

```powershell
python book_converter_ui.py
```

Run a CLI conversion:

```powershell
python batch_convert_books.py `
  .\samples `
  .\out `
  --recursive `
  --output-format markdown `
  --manifest .\out\manifest.json
```

If you mainly use Kindle-style formats, also install Calibre so `ebook-convert` is available for AZW/AZW3/MOBI/RTF normalization.

## 2. PDF Enhanced Setup

Good for:

- Long PDFs.
- Scanned PDFs.
- Layout-heavy PDFs.
- PDF pipeline comparison and review reports.

Optional backends:

| Backend | Best For | Notes |
| --- | --- | --- |
| PyMuPDF4LLM | Fast text-layer PDF baseline | Installed by `requirements.txt`. |
| MinerU | Complex PDF structure recovery | Heavy; may need model downloads and enough RAM/GPU/CPU time. |
| Marker | Short layout-heavy PDF parsing | Heavy; model/network setup can be slow. |
| Umi-OCR / PaddleOCR-json | Scanned PDF/image OCR fallback | Configure paths through environment variables. |
| Docling | Office/document formats and optional PDF comparison | Install only when needed. |

Install optional Docling support:

```powershell
python -m pip install -r requirements-docling.txt
```

Configure Umi-OCR if you use it:

```powershell
Copy-Item config.example.env .env
notepad .env
```

Set one or more of:

```powershell
EBOOK_CONVERTER_UMI_DIR=C:\path\to\Umi-OCR
EBOOK_CONVERTER_UMI_PLUGIN_DIR=C:\path\to\Umi-OCR\UmiOCR-data\plugins\win7_x64_PaddleOCR-json
EBOOK_CONVERTER_UMI_PADDLE_EXE=C:\path\to\PaddleOCR-json.exe
EBOOK_CONVERTER_UMI_PADDLE_MODULE=C:\path\to\PPOCR_api.py
```

Check the environment:

```powershell
python batch_convert_books.py .\samples .\out --health-check
```

Compare PDF pipelines for a representative file:

```powershell
python scripts\compare_pipelines.py `
  --input C:\books\sample.pdf `
  --output benchmarks\compare-runs\sample `
  --pipelines pymupdf4llm mineru umi docling `
  --pipeline-timeout 600
```

For long books, compare selected pages first:

```powershell
python scripts\compare_pipelines.py `
  --input C:\books\huge.pdf `
  --output benchmarks\compare-runs\huge-pages `
  --pipelines pymupdf4llm mineru umi docling `
  --page-ranges 1-3,100-102,600-602 `
  --pipeline-timeout 120
```

## 3. Local VLM / Image Layout Setup

Good for:

- Infographics.
- Dense screenshots.
- Image books.
- Complex image layouts where plain OCR loses structure.

The default image workflow remains local-first and conservative:

1. Umi-OCR/PaddleOCR-json extracts text and coordinates.
2. The project marks suspicious pages as `layout-heavy`.
3. Optional VLM backends can generate enhanced Markdown artifacts.

Optional environment variables:

```powershell
EBOOK_CONVERTER_TOOL_CACHE=C:\path\to\ebook-converter-tools
EBOOK_CONVERTER_VLM_PYTHON=C:\path\to\python.exe
EBOOK_CONVERTER_PADDLEOCR_COMMAND=paddleocr
PADDLEOCR_VL_COMMAND="python scripts\paddleocr_vl_image_to_md.py --input {input} --output {output}"
QWEN_VL_MODEL=Qwen/Qwen2.5-VL-3B-Instruct
```

Run an image-book rebuild:

```powershell
python image_book_rebuilder.py build `
  C:\screenshots `
  C:\screenshots-out\book.md `
  --recursive
```

Run the PaddleOCR-VL wrapper dry-run:

```powershell
python scripts\paddleocr_vl_image_to_md.py `
  --input C:\images\sample.png `
  --output C:\images-out\sample.md `
  --dry-run
```

Heavy local VLM backends may download large models on first use. Keep them optional unless you actually need infographic or complex-layout enhancement.

## 4. Agent / API Setup

Good for:

- OpenClaw, Hermes Agent, Codex, Claude Code, or other automation agents.
- Docker-hosted agents that need a Windows host conversion service.
- Repeatable batch processing and handoff artifacts.

MCP stdio:

```powershell
.\start_mcp.cmd
python scripts\test_mcp_stdio.py
```

HTTP bridge:

```powershell
$env:EBOOK_CONVERTER_API_TOKEN = "replace-with-a-local-token"
python ebook_converter_http.py --host 0.0.0.0
```

The default HTTP host/port is read from `config/http.env`. Do not duplicate host/port values in desktop shortcuts, Docker manifests, or agent prompts; read the config file or `/health` response instead.

HTTP health check:

```powershell
curl -H "Authorization: Bearer replace-with-a-local-token" `
  "http://127.0.0.1:9241/health"
```

Agent smoke suite:

```powershell
python scripts\test_agent_smoke_suite.py --fail-fast
```

Batch template:

```powershell
python examples\agent-batch\agent_batch_http.py `
  --manifest examples\agent-batch\batch_manifest.example.json `
  --output C:\agent-batch-output\run-001 `
  --dry-run
```

For Docker usage, see [DOCKER_USAGE.md](DOCKER_USAGE.md). For the stable tool contract, see [TOOL_CONTRACT.md](TOOL_CONTRACT.md). For the architecture overview, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Configuration Files

| File | Purpose | Commit? |
| --- | --- | --- |
| `config/http.env` | Shared default HTTP host/port source | Yes |
| `config.example.env` | Safe example for optional local paths and provider variables | Yes |
| `.env` | Your local private overrides | No |
| `benchmarks/*.local.json` | Private real-sample benchmark manifests | No |

## Troubleshooting

- If a command is missing, run `python batch_convert_books.py .\samples .\out --health-check`.
- If PDF conversion hangs or falls back, inspect `.reports/summary.md`, `.reports/review-checklist.md`, and `.reports/pdf-tool-logs/`.
- If an Agent call returns `review` or `poor`, read the returned `next_actions` and artifact paths before rerunning.
- If optional model backends are slow, first compare selected pages instead of the whole PDF.
