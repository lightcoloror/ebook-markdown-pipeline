# References And Reuse

This project follows a tool-first integration model: use mature local tools where they already exist, and keep this repository focused on orchestration, routing, quality review, UI, logging, recovery, and agent-facing contracts. For a broader candidate inventory and U-drive distribution risk tiers, see [OPEN_SOURCE_PROJECT_INVENTORY.md](OPEN_SOURCE_PROJECT_INVENTORY.md).

It does not vendor third-party parser engines, OCR binaries, model weights, or ebook/PDF content. Install optional backends separately and follow each upstream project's license terms.

## Direct Tool Integration

These tools are invoked as local commands, Python packages, or wrappers when available:

| Project / Tool | Role In This Project | Integration Boundary |
| --- | --- | --- |
| Pandoc | EPUB, FB2, TXT, ODT, Markdown, HTML, and text conversion | Called as an external converter. |
| Calibre / `ebook-convert` | AZW, AZW3, MOBI, and RTF intermediate conversion | Called as an external converter before Markdown normalization. |
| PyMuPDF | PDF inspection, text layer checks, page rendering, and outline/bookmark extraction | Used through its Python API. |
| PyMuPDF4LLM | Fast PDF-to-Markdown fallback for text-layer PDFs | Used as a lightweight PDF backend. |
| MinerU | Structured PDF parsing for complex or scanned PDFs | Called as an optional heavyweight backend. |
| Marker | Layout-aware PDF parsing option | Called as an optional PDF backend. |
| Docling | Optional Office/document/PDF structure backend | Called as an optional backend when installed. |
| Microsoft MarkItDown | Optional fast multi-format Markdown baseline for EPUB/DOCX/PPTX/XLSX/HTML/PDF comparison | Called through its Python API when explicitly selected. |
| OCRmyPDF | Optional scanned PDF preprocessing into searchable PDFs | Called as an external command when explicitly selected or recommended for rerun. |
| Umi-OCR / PaddleOCR-json | Local OCR fallback for images and scanned pages | Called through local executable/module paths configured by the user. |
| PaddleOCR-VL wrapper | Optional infographic/layout-heavy image enhancement | Called through project wrapper scripts when configured. |
| Qwen-VL wrapper | Optional heavier VLM enhancement for difficult images | Called through project wrapper scripts when configured. |

## Architecture Patterns Referenced

The codebase also references several design patterns from adjacent open-source tools and agent integrations:

| Reference Pattern | How It Is Used Here |
| --- | --- |
| Marker-style pluggable LLM service | Future online model support should sit behind provider abstractions rather than being hardcoded into each pipeline. |
| MinerU-style local/remote VLM backend split | Heavy document vision can run locally, on a remote GPU, or through an online-compatible backend without changing the agent contract. |
| PaddleOCR MCP-style stable tool contract | Agent-facing calls should keep stable schemas while the underlying backend can be local, official API, cloud, or self-hosted. |
| Docling-style document object/artifact boundary | Convert messy source files into structured artifacts first; do not ask agents to parse raw PDFs/images directly. |

These are architectural references, not vendored code copies.

## What This Repository Owns

- Input inspection and routing across ebook, PDF, Office, image, and web-archive materials.
- Safe fallback chains and timeout handling for heavyweight PDF/OCR tools.
- Markdown cleanup, TOC alignment, structure repair, and quality scoring.
- Persistent reports, review checklists, tool logs, environment reports, and batch manifests.
- Desktop UI, CLI, HTTP API, MCP server, and agent handoff artifacts.
- Versioned rerun behavior so comparisons do not overwrite earlier output by default.

## What This Repository Does Not Own

- Ebook rendering engines.
- PDF layout/OCR model weights.
- Upstream OCR engines or cloud model APIs.
- Legal compliance for redistributed third-party binaries or model packages.
- Copyright clearance for user-provided books, PDFs, screenshots, or datasets.

## Online API Direction

Future online model support should remain behind provider interfaces such as `OcrLayoutProvider`, `VlmLayoutProvider`, `TextStructureProvider`, and `EmbeddingProvider`. See [ONLINE_MODEL_API_INTEGRATION.md](ONLINE_MODEL_API_INTEGRATION.md) for the planned abstraction and safety rules.
