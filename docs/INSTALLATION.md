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
| Built-in CSV/TSV fallback | Delimited text files | No extra install; converts CSV/TSV to Markdown tables. |
| MinerU | Complex PDF structure recovery | Heavy; may need model downloads and enough RAM/GPU/CPU time. |
| Marker | Short layout-heavy PDF parsing | Heavy; model/network setup can be slow. |
| OCRmyPDF | Scanned PDF preprocessing into searchable PDF | Install with Tesseract; use explicitly or through recommended reruns. |
| pdf-craft | Scanned-book PDF-to-Markdown reconstruction | Heavy; requires Poppler plus local DeepSeek OCR model/GPU setup for real conversion. |
| pdfplumber | PDF layout/table/coordinate diagnostics | Optional; writes diagnostic evidence, not a main Markdown conversion path. |
| Camelot | Text-based PDF table extraction | Optional future/advanced backend; use only for table-heavy text PDFs. |
| Tabula / tabula-py | Text-based PDF table extraction fallback | Optional; requires Java and writes table artifacts only. |
| Umi-OCR / PaddleOCR-json | Scanned PDF/image OCR fallback | Configure paths through environment variables. |
| Docling | Office/document formats and optional PDF comparison; CSV/TSV do not require Docling | Install only when needed. |
| MarkItDown | Fast multi-format Markdown baseline | Install only when you need comparison evidence. |
| Apache Tika | Broad MIME/metadata/text-sample inspection | Optional explicit inspect; use a Tika Server URL or command wrapper. |
| GROBID | Academic PDF/TEI inspection | Optional explicit inspect; use a configured GROBID Server URL. |

Install optional Docling support:

```powershell
python -m pip install -r requirements-docling.txt
```

Install optional MarkItDown baseline support:

```powershell
python -m pip install -r requirements-markitdown.txt
```

Use MarkItDown explicitly when you want a quick comparison backend:

```powershell
python batch_convert_books.py .\samples .\out --document-pipeline-mode markitdown
python batch_convert_books.py .\samples .\out --pdf-pipeline-mode markitdown
```

Apache Tika is optional and explicit-only. It is useful for unusual extensions, MIME detection, metadata, and a short text sample before deciding whether a dedicated converter is worth adding. It is not a main Markdown conversion path.

Use a local Tika Server:

```powershell
$env:EBOOK_CONVERTER_TIKA_SERVER_URL="http://127.0.0.1:9998"
python document_inspector.py .\unknown-file.bin --use-tika
```

Or use a command wrapper that prints JSON with optional `detected_mime`, `metadata`, and `text` fields:

```powershell
$env:EBOOK_CONVERTER_TIKA_COMMAND="python path\to\tika_wrapper.py {input}"
python document_inspector.py .\unknown-file.bin --use-tika
```

GROBID is optional and explicit-only. It is useful for academic PDFs when you need title/authors/abstract/DOI/reference-count/TEI evidence. It is not a general PDF-to-Markdown route.

```powershell
$env:EBOOK_CONVERTER_GROBID_SERVER_URL="http://127.0.0.1:8070"
python document_inspector.py .\paper.pdf --use-grobid
```

Configure Umi-OCR if you use it:

OCRmyPDF is optional. When selected with `--pdf-pipeline-mode ocrmypdf`, the project writes a searchable PDF under `.reports/ocrmypdf/` and then runs the fast PDF conversion path. The original PDF is not overwritten.

pdf-craft is optional and explicit-only. Use it when you want a scanned-book reconstruction experiment with TOC assumptions, not as a default PDF route:

```powershell
python -m pip install -r requirements-pdfcraft.txt
python batch_convert_books.py .\scanned-books .\out --pdf-pipeline-mode pdfcraft
```

Real pdf-craft runs may need Poppler, local DeepSeek OCR models, and GPU/CUDA setup. By default the wrapper runs in local-only model mode to avoid surprise downloads; pass `--pdfcraft-allow-download` only when you intentionally want pdf-craft to download models.

pdfplumber diagnostics run automatically when installed and reports are enabled. Camelot and Tabula are table-only extractors for text-layer PDFs; they do not replace the main Markdown conversion route.

```powershell
python -m pip install pdfplumber camelot-py
python -m pip install -r requirements-tabula.txt
```

Tabula requires a working Java runtime. If Java or tabula-py is missing, the report records `tabula_status=missing_dependency` and the normal conversion continues.

```powershell
Copy-Item config.example.env .env
notepad .env
```

The UI, CLI, HTTP, and MCP entrypoints automatically load `.env` from the project root. Existing shell, CI, Docker, or agent-provided environment variables take priority and are not overwritten.

Set one or more of:

```powershell
EBOOK_CONVERTER_UMI_DIR=C:\path\to\Umi-OCR
EBOOK_CONVERTER_UMI_PLUGIN_DIR=C:\path\to\Umi-OCR\UmiOCR-data\plugins\win7_x64_PaddleOCR-json
EBOOK_CONVERTER_UMI_PADDLE_EXE=C:\path\to\PaddleOCR-json.exe
EBOOK_CONVERTER_UMI_PADDLE_MODULE=C:\path\to\PPOCR_api.py
```

RapidOCR is an optional Python-native OCR fallback for image and screenshot workflows. It is easier for scripts and agents to call than a desktop Umi-OCR bundle, but it is not the default replacement:

```powershell
python -m pip install -r requirements-rapidocr.txt
python image_book_rebuilder.py build .\screenshots .\screenshots-out --ocr-provider rapidocr
```

Use RapidOCR for lightweight fallback or benchmark runs; keep Umi-OCR as the preferred local OCR path when it is already configured and producing better results.

RapidOCR GPU note: `EBOOK_CONVERTER_RAPIDOCR_DEVICE=auto` uses CUDA only when ONNX Runtime reports a compatible CUDA provider and the matching CUDA/cuDNN runtime files are available. If `onnxruntime-gpu` lists CUDA but its DLL dependencies are missing, the converter selects CPU and records the reason in `--health-check` instead of letting repeated provider fallback logs pollute upstream batch runs. To repair GPU mode, keep only one ONNX Runtime package in the environment and install a CUDA/cuDNN stack that matches the ONNX Runtime GPU build, or downgrade `onnxruntime-gpu` to the CUDA major version already present on the machine. Use `EBOOK_CONVERTER_RAPIDOCR_ALLOW_UNSTABLE_CUDA=1` only for manual experiments.

For the safest GPU setup, create an isolated RapidOCR venv and point the project at it instead of changing the main project Python:

```powershell
$env:EBOOK_CONVERTER_RAPIDOCR_PYTHON = "C:\path\to\rapidocr-gpu-venv\Scripts\python.exe"
$env:EBOOK_CONVERTER_RAPIDOCR_DEVICE = "cuda"
python image_book_rebuilder.py build .\screenshots .\screenshots-out --ocr-provider rapidocr
```

The external worker preloads NVIDIA DLL directories from that venv and communicates with the main pipeline over UTF-8 JSON lines, so CLI/UI/MCP callers can keep using the normal RapidOCR provider.

CnOCR is an optional Chinese/English OCR comparison provider. Install it only when you want to benchmark Chinese image OCR against Umi-OCR/RapidOCR before changing defaults:

```powershell
python -m pip install -r requirements-cnocr.txt
```

Optional CnOCR constructor tuning can be passed through environment variables:

```powershell
$env:EBOOK_CONVERTER_CNOCR_REC_MODEL_NAME = "ch_PP-OCRv5"
$env:EBOOK_CONVERTER_CNOCR_DET_MODEL_NAME = "ch_PP-OCRv5_det"
$env:EBOOK_CONVERTER_CNOCR_CONTEXT = "cpu"
```

Compare RapidOCR, CnOCR, and Umi-OCR on small public or local image samples:

```powershell
python scripts\compare_ocr_providers.py `
  .\benchmarks\fixtures\generated\images `
  --recursive `
  --providers rapidocr cnocr umi `
  --output .\benchmarks\runs\ocr-provider-compare
```

Check the environment:

```powershell
python batch_convert_books.py .\samples .\out --health-check
```

The health report separates minimal readiness from optional/heavy backends. `media_helper=degraded` means FFmpeg/avconv is missing for optional media-adjacent helpers; `python_dependency_consistency=degraded` means the requests/urllib3/chardet stack may be inconsistent for optional HTTP/provider/model-download workflows. Neither warning blocks the minimal local conversion path.

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
3. Optional image-layout backends can generate enhanced Markdown artifacts. Pix2Text and Surya are tried before heavier VLM backends when installed.

Optional environment variables:

```powershell
EBOOK_CONVERTER_TOOL_CACHE=C:\path\to\ebook-converter-tools
EBOOK_CONVERTER_VLM_PYTHON=C:\path\to\python.exe
PIX2TEXT_COMMAND="python scripts\pix2text_image_to_md.py --input {input} --output {output}"
PIX2TEXT_LANGUAGES=en,ch_sim
PIX2TEXT_DEVICE=cpu
SURYA_COMMAND="python scripts\surya_image_to_md.py --input {input} --output {output}"
SURYA_OCR_COMMAND=surya_ocr
SURYA_LAYOUT_COMMAND=surya_layout
SURYA_TABLE_COMMAND=surya_table
GOT_OCR_SCRIPT=C:\path\to\GOT\demo\run_ocr_2.0.py
GOT_OCR_CROP_SCRIPT=C:\path\to\GOT\demo\run_ocr_2.0_crop.py
GOT_OCR_MODEL=C:\path\to\GOT_weights
GOT_OCR_PYTHON=C:\path\to\got-env\python.exe
EBOOK_CONVERTER_PADDLEOCR_COMMAND=paddleocr
PADDLEOCR_VL_COMMAND="python scripts\paddleocr_vl_image_to_md.py --input {input} --output {output}"
QWEN_VL_MODEL=Qwen/Qwen2.5-VL-3B-Instruct
EBOOK_CONVERTER_OLMOCR_COMMAND=olmocr
EBOOK_CONVERTER_OLMOCR_SERVER=http://remote-server:8000/v1
EBOOK_CONVERTER_OLMOCR_MODEL=allenai/olmOCR-2-7B-1025-FP8
EBOOK_CONVERTER_OLMOCR_API_KEY_ENV=OLMOCR_API_KEY
```

Install Pix2Text only if you need Chinese screenshots, formulas, or image-page Markdown enhancement:

```powershell
python -m pip install -r requirements-pix2text.txt
```

Install Surya only if you need OCR, layout, reading-order, or table recognition experiments. Treat Surya as an optional enhancement, not a default runtime dependency. Its code and model weights are licensed separately, so review upstream model/commercial-use terms before redistribution or commercial packaging:

```powershell
python -m pip install -r requirements-surya.txt
```

GOT-OCR is an explicit CUDA/demo-script experiment path, not a normal install. Follow upstream setup in a separate environment, then point this project at the demo script and model:

```powershell
# requirements-got-ocr.txt is documentation-only; it does not install CUDA/flash-attn.
python scripts\got_ocr_image_to_md.py `
  --input C:\images\sample.png `
  --output C:\images-out\sample.got.md `
  --script C:\path\to\GOT\demo\run_ocr_2.0.py `
  --model C:\path\to\GOT_weights `
  --type format `
  --dry-run
```

DeepSeek-OCR is also explicit-only. It is useful for VLM OCR experiments on difficult images or page crops, but it needs a separate CUDA/torch/transformers environment:

```powershell
# requirements-deepseek-ocr.txt is documentation-only; keep the heavy runtime separate.
$env:DEEPSEEK_OCR_PYTHON = "C:\path\to\deepseek-ocr-env\python.exe"
$env:DEEPSEEK_OCR_MODEL = "deepseek-ai/DeepSeek-OCR"
python scripts\deepseek_ocr_image_to_md.py `
  --input C:\images\sample.png `
  --output C:\images-out\sample.deepseek.md `
  --prompt-mode markdown `
  --dry-run
```

Install olmOCR only if you need an explicit VLM OCR benchmark for complex scanned PDFs or image-based documents. Upstream recommends a clean Python environment; local GPU inference needs substantial VRAM/disk, while remote inference can use the lightweight package:

```powershell
python -m pip install -r requirements-olmocr.txt
python batch_convert_books.py .\samples\scan.pdf .\out --pdf-pipeline-mode olmocr
```

The API key value is read from the named environment variable and is not written to reports. It may still be passed to the upstream CLI process when remote inference requires `--api_key`, so prefer a local/self-hosted server without a key when possible.

Run an image-book rebuild:

```powershell
python image_book_rebuilder.py build `
  C:\screenshots `
  C:\screenshots-out\book.md `
  --recursive
```

Run the Pix2Text wrapper dry-run:

```powershell
python scripts\pix2text_image_to_md.py `
  --input C:\images\sample.png `
  --output C:\images-out\sample.md `
  --dry-run
```

Run the Surya wrapper dry-run:

```powershell
python scripts\surya_image_to_md.py `
  --input C:\images\sample.png `
  --output C:\images-out\sample.md `
  --dry-run
```

Run the PaddleOCR-VL wrapper dry-run:

```powershell
python scripts\paddleocr_vl_image_to_md.py `
  --input C:\images\sample.png `
  --output C:\images-out\sample.md `
  --dry-run
```

Heavy local VLM backends may download large models on first use. Keep them optional unless you actually need infographic or complex-layout enhancement.

If you plan to test future online-model integration, start from the template:

```powershell
copy config\online_providers.example.json config\online_providers.local.json
$env:EBOOK_CONVERTER_ONLINE_PROVIDERS_CONFIG = "config\online_providers.local.json"
```

`config\online_models.example.json` is kept as a legacy-compatible alias for older local setups. New setups should prefer `config\online_providers.example.json` and `EBOOK_CONVERTER_ONLINE_PROVIDERS_CONFIG`.

The current default conversion flow does not call remote APIs. `online_providers.py` provides provider health checks, fake-provider tests, and an optional OpenAI-compatible adapter for future text structure, OCR layout, VLM layout, table repair, and embedding work. Keep API keys in environment variables such as `VLM_API_KEY`, `OCR_LAYOUT_API_KEY`, `TEXT_LLM_API_KEY`, `TABLE_LLM_API_KEY`, and `EMBEDDING_API_KEY`; do not write real keys into the JSON file.

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
