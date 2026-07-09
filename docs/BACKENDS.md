# Backend Guide

The converter is local-first and tool-first. Backends are optional specialist tools behind the same routing, reporting, and quality layer.

| Backend | Role | Default? | Install Cost | Notes |
| --- | --- | --- | --- | --- |
| Pandoc | EPUB, FB2, TXT, ODT, Markdown, HTML conversion | Recommended minimal | Low | Best first install for common ebooks and text documents. |
| Calibre / `ebook-convert` | AZW, AZW3, MOBI, RTF conversion | Recommended for ebook collections | Medium | Used before Markdown cleanup for Kindle formats. |
| Built-in CSV/TSV fallback | Delimited text to Markdown table | Yes for CSV/TSV | None | Does not require Docling; decodes common encodings, sniffs delimiters, and escapes Markdown table cells. |
| PyMuPDF / PyMuPDF4LLM | PDF preflight, outlines, text-layer fast path | Yes for light PDF fallback | Low | Good for text-layer PDFs and diagnostics. |
| Docling | Structured Office/document/PDF parsing | Optional | Medium | Useful for DOCX, PPTX, XLSX, HTML, and structure comparisons. CSV/TSV use the built-in delimited-text fallback by default. |
| Apache Tika | Broad MIME/metadata/text-sample inspection | Optional explicit inspect | Medium | Use through Tika Server or a command template for unusual formats; not a main conversion route. |
| GROBID | Academic PDF/TEI inspection | Optional explicit inspect | Heavy | Use through a configured GROBID Server for papers, DOI, authors, abstract, references, and TEI evidence; not a main conversion route. |
| MinerU | Structured PDF parsing | Optional | Heavy | Use for complex/scanned PDFs when quality reports recommend it. |
| Marker | Layout-aware PDF parsing | Optional | Heavy | Use as a high-quality PDF comparison backend. |
| MarkItDown | Fast multi-format Markdown baseline | Optional, explicit only | Low/Medium | Use for baseline comparison, not as the default router. |
| OCRmyPDF | Scanned PDF to searchable PDF preprocessing | Optional, explicit/recommended rerun | Medium | Writes a searchable PDF artifact, then runs fast PDF conversion. Original PDF is not overwritten. |
| pdf-craft | Scanned-book PDF-to-Markdown reconstruction with TOC assumptions | Optional, explicit only | Heavy | Use as an experiment backend for scanned books; requires Poppler plus DeepSeek OCR model/GPU setup. |
| pdfplumber | PDF layout, coordinates, table candidates | Optional diagnostics | Low/Medium | Writes explanatory diagnostics, not main Markdown conversion. |
| Camelot | Text-based PDF table extraction | Optional diagnostics | Medium | Runs only for suspected table pages when installed. |
| Tabula / tabula-py | Text-based PDF table extraction fallback | Optional diagnostics | Medium | Runs only for suspected table pages when installed; requires Java. |
| Umi-OCR / PaddleOCR-json | Local OCR for scanned pages and images | Optional | Medium | Strong practical OCR backend for local Windows workflows. |
| RapidOCR | Python-native OCR fallback, embedded Office-image OCR, and benchmark provider | Optional | Low/Medium | Easier for scripts/agents; outputs the same OCR block schema and can insert OCR text under DOCX/PPTX/XLSX image references. GPU is used only when ONNX Runtime CUDA dependencies are compatible; otherwise CPU fallback is reported cleanly. |
| CnOCR | Chinese/English OCR benchmark and fallback experiment | Optional | Low/Medium | Use for Chinese OCR provider comparison before promoting it to a default route. |
| Pix2Text | Chinese screenshots, formulas, and image-page Markdown enhancement | Optional | Medium/Heavy | First optional layout-heavy enhancement attempt when installed; not required for minimal conversion. |
| Surya | OCR, layout, reading-order, and table enhancement | Optional | Heavy | Explicit image/layout experiment backend; may start a VLM inference server. Code and model weights are licensed separately; review model/commercial-use terms before redistribution. |
| GOT-OCR 2.0 | CUDA image OCR experiment wrapper | Optional explicit only | Heavy | Demo-script wrapper for single image/crop/multi-page experiments; not part of auto routing. |
| DeepSeek-OCR | CUDA/Transformers VLM OCR experiment wrapper | Optional explicit only | Heavy | Wrapper for explicit image-to-Markdown OCR experiments; not part of auto routing. |
| olmOCR | VLM PDF/image OCR to Markdown benchmark | Optional explicit only | Heavy | Use as a GPU/remote-inference comparison backend for complex scanned PDFs; not part of auto routing. |
| PaddleOCR-VL / Qwen-VL / MinerU VLM | Layout-heavy image/infographic enhancement fallback | Optional heavy | Heavy | Explicit enhancement only; not required for minimal conversion. |
| MonkeyOCR | External document VLM worker plan for complex PDFs/images | Candidate only | Heavy | Plan/fake/execute wrapper only. Do not install models or route by default; use scorecards before promotion. |
| dots.mocr | External HTTP/GPU document VLM provider plan | Candidate only | Heavy | Prefer remote/vLLM/OpenAI-compatible provider shape. Service/model startup is manual and never automatic. |
| DocLayout-YOLO | Layout detector baseline for bbox/overlay evidence | Candidate only | Medium/Heavy | Layout evidence only, not Markdown conversion. Use for selected pages in inspect/benchmark flows. |
| pdf_table | External table-page worker plan | Candidate only | Heavy | Table pages only. Compare with Camelot/Tabula/pdfplumber before using as a recommendation. |
| table_to_xlsx | Photo/scanned table to editable XLSX worker plan | Candidate only | Medium/Heavy | Uses PaddleOCR TableRecognitionPipelineV2, img2table, or RapidTable as explicit future backends. Current safe path exports existing table evidence to an `.xlsx` draft without installing models. |
| Unlimited-OCR | Long-horizon VLM OCR candidate for multi-page images/PDF pages | Not integrated; candidate only | Heavy | Do not install or route by default. Consider only if fixture/real-sample scorecards prove a clear quality gain and it can replace an existing heavy VLM/OCR module rather than add another large model. |

## Routing Defaults

- Minimal ebook/text work should stay on Pandoc, Calibre, and fast PDF paths.
- Tika is an explicit inspection enhancement; it helps identify/preview unusual files but does not replace format-specific converters.
- GROBID is an explicit academic-PDF enhancement; it helps inspect papers and references but does not replace the general PDF Markdown route.
- Heavy PDF/OCR/VLM backends should be selected by recommendation, review action, or explicit user/agent request.
- Online model APIs must go through the provider abstraction and are never required for the default local workflow.
- Unlimited-OCR is documented as a possible future heavy enhancement backend, but it is intentionally not integrated for now because local model/runtime storage cost is high. Promotion requires evidence that it materially improves layout-heavy/image-book quality and can simplify or replace an existing heavy route such as PaddleOCR-VL, Qwen-VL, MinerU VLM, GOT-OCR, DeepSeek-OCR, or olmOCR.
- `media_helper` and `python_dependency_consistency` are environment soft-risk capabilities, not conversion backends. If they are degraded, normal EPUB/TXT/text-layer-PDF conversion can still proceed; fix them when optional media/provider/model-download workflows need them.

## Diagnostics And Artifacts

- PDF layout diagnostics write `table-diagnostics.json` and table candidates under `.reports/tables/`; Camelot and Tabula artifacts are fallback evidence, not main conversion output.
- OCR provider comparison writes `ocr-provider-comparison.json/md` and `ocr-blocks.jsonl`.
- Optional backend scorecard writes `backend-scorecard.json/md` and summarizes availability, install cost, GPU/model needs, license notes, and whether a backend should stay explicit-only or appear as a recommended follow-up.
- Quality gates write `benchmark-summary.md` and `quality-regression-summary.md/json`.

Run the scorecard directly when deciding whether to promote a newly installed optional backend:

```powershell
python scripts\generate_backend_scorecard.py --output .\benchmarks\runs\backend-scorecard
```
