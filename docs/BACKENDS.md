# Backend Guide

The converter is local-first and tool-first. Backends are optional specialist tools behind the same routing, reporting, and quality layer.

| Backend | Role | Default? | Install Cost | Notes |
| --- | --- | --- | --- | --- |
| Pandoc | EPUB, FB2, TXT, ODT, Markdown, HTML conversion | Recommended minimal | Low | Best first install for common ebooks and text documents. |
| Calibre / `ebook-convert` | AZW, AZW3, MOBI, RTF conversion | Recommended for ebook collections | Medium | Used before Markdown cleanup for Kindle formats. |
| PyMuPDF / PyMuPDF4LLM | PDF preflight, outlines, text-layer fast path | Yes for light PDF fallback | Low | Good for text-layer PDFs and diagnostics. |
| Docling | Structured Office/document/PDF parsing | Optional | Medium | Useful for DOCX, PPTX, XLSX, HTML, CSV, and structure comparisons. |
| MinerU | Structured PDF parsing | Optional | Heavy | Use for complex/scanned PDFs when quality reports recommend it. |
| Marker | Layout-aware PDF parsing | Optional | Heavy | Use as a high-quality PDF comparison backend. |
| MarkItDown | Fast multi-format Markdown baseline | Optional, explicit only | Low/Medium | Use for baseline comparison, not as the default router. |
| OCRmyPDF | Scanned PDF to searchable PDF preprocessing | Optional, explicit/recommended rerun | Medium | Writes a searchable PDF artifact, then runs fast PDF conversion. Original PDF is not overwritten. |
| pdfplumber | PDF layout, coordinates, table candidates | Optional diagnostics | Low/Medium | Writes explanatory diagnostics, not main Markdown conversion. |
| Camelot | Text-based PDF table extraction | Optional diagnostics | Medium | Runs only for suspected table pages when installed. |
| Umi-OCR / PaddleOCR-json | Local OCR for scanned pages and images | Optional | Medium | Strong practical OCR backend for local Windows workflows. |
| RapidOCR | Python-native OCR fallback and benchmark provider | Optional | Low/Medium | Easier for scripts/agents; outputs the same OCR block schema. |
| PaddleOCR-VL / Qwen-VL / MinerU VLM | Layout-heavy image/infographic enhancement | Optional heavy | Heavy | Explicit enhancement only; not required for minimal conversion. |

## Routing Defaults

- Minimal ebook/text work should stay on Pandoc, Calibre, and fast PDF paths.
- Heavy PDF/OCR/VLM backends should be selected by recommendation, review action, or explicit user/agent request.
- Online model APIs must go through the provider abstraction and are never required for the default local workflow.

## Diagnostics And Artifacts

- PDF layout diagnostics write `table-diagnostics.json` and table candidates under `.reports/tables/`.
- OCR provider comparison writes `ocr-provider-comparison.json/md` and `ocr-blocks.jsonl`.
- Quality gates write `benchmark-summary.md` and `quality-regression-summary.md/json`.
