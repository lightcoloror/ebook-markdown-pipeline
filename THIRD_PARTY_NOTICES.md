# Third-Party Notices

This project is a local orchestration layer for ebook, PDF, Office, image, and web-archive conversion tools. It does not vendor the third-party tools listed below. Users install and use those tools separately under their own licenses.

For a clearer engineering view of what is directly invoked, what is only an architectural reference, and what this repository owns, see [docs/REFERENCES_AND_REUSE.md](docs/REFERENCES_AND_REUSE.md). For a broader research inventory of related open-source projects and U-drive distribution risk tiers, see [docs/OPEN_SOURCE_PROJECT_INVENTORY.md](docs/OPEN_SOURCE_PROJECT_INVENTORY.md).

## License Choice

This project is released under the GNU Affero General Public License v3.0 (AGPL-3.0).

The reason is conservative compatibility for public sharing: several referenced or integrated PDF tools are strong-copyleft licensed, especially PyMuPDF / PyMuPDF4LLM under AGPL-3.0 or commercial licensing. Marker is distributed under GPL-3.0-or-later, and Calibre/Pandoc are GPL-family projects. MinerU's audited current source uses a custom Apache-2.0-based open-source license with additional commercial and attribution terms, while its model terms remain separate. AGPL-3.0 is therefore still the strictest practical open-source license among the referenced tools.

This is an engineering compliance note, not legal advice.

## Referenced Tools

| Tool | Used For | License Notes |
| --- | --- | --- |
| Pandoc | EPUB/FB2/ODT/TXT and Markdown/HTML/text conversion | GPL-family project; installed separately |
| Calibre / ebook-convert | AZW/AZW3/MOBI/RTF intermediate conversion | GPL-family project; installed separately |
| PyMuPDF | PDF preflight, splitting, rendering support | AGPL-3.0 or commercial license |
| PyMuPDF4LLM | PDF-to-Markdown fallback | AGPL-3.0 via PyMuPDF ecosystem |
| MinerU | Structured PDF parsing | Audited source uses `LicenseRef-MinerU-Open-Source-License`; installed separately; model terms checked separately |
| Marker | PDF parsing option | GPL-3.0-or-later project; installed separately; model terms checked separately |
| Docling | Optional Office/document/PDF structure backend | MIT-licensed codebase; installed separately; check model dependencies |
| Microsoft MarkItDown | Optional fast multi-format Markdown baseline | MIT-licensed upstream project; installed separately |
| Apache Tika | Optional MIME/metadata/text-sample inspection | Apache-2.0 upstream project; used through separately configured Tika Server or command wrapper |
| GROBID | Optional academic PDF/TEI inspection | Apache-2.0 upstream project; used through separately configured GROBID Server |
| OCRmyPDF | Optional scanned PDF preprocessing to searchable PDF | MPL-2.0 upstream project; installed separately with Tesseract |
| pdf-craft | Optional scanned-book PDF-to-Markdown reconstruction | MIT-licensed upstream project; installed separately; Poppler, DeepSeek OCR model/runtime, and transitive licenses checked separately |
| pdfplumber | Optional PDF layout, coordinate, and table diagnostics | MIT-licensed upstream project; installed separately |
| Camelot | Optional text-based PDF table extraction candidate | MIT-licensed upstream project; installed separately |
| Tabula / tabula-py | Optional text-based PDF table extraction fallback | MIT-licensed upstream projects; installed separately; requires Java |
| Umi-OCR / PaddleOCR-json | OCR fallback workflow | Umi-OCR audited as MIT; PaddleOCR-json audited as Apache-2.0; bundled OCR model licenses checked separately |
| Pix2Text | Optional Chinese screenshot/formula/image-page Markdown enhancement | MIT-licensed upstream project; installed separately; model dependencies checked separately |
| Surya | Optional OCR/layout/reading-order/table enhancement | Apache-2.0 upstream project; installed separately; code and model weights are licensed separately; review model/commercial-use terms before redistribution |
| CnOCR | Optional Chinese/English OCR comparison provider | Apache-2.0 upstream project; installed separately; model/runtime dependencies checked separately |
| olmOCR | Optional VLM OCR PDF/image-to-Markdown benchmark backend | Apache-2.0 upstream project; installed separately; model/runtime/API provider terms checked separately |
| GOT-OCR 2.0 | Optional CUDA image OCR experiment wrapper | Upstream demo code/model/runtime terms checked separately; installed and configured outside this repository |
| DeepSeek-OCR | Optional CUDA/Transformers VLM OCR experiment wrapper | Upstream code/model/runtime terms checked separately; installed and configured outside this repository |
| PaddleOCR-VL | Optional infographic/layout-heavy image enhancement | PaddleOCR source audited as Apache-2.0; model/license terms checked separately |
| Qwen-VL | Optional heavier VLM image enhancement | Qwen-VL code audited as Apache-2.0; model and runtime terms checked separately |
| tkinterdnd2 | Optional drag-and-drop UI support | MIT-licensed Python package dependency; installed separately |

## Distribution Boundary

This repository contains only the orchestration scripts, UI, logging, retry, report, and workflow code. It does not redistribute third-party binaries, model weights, or book content.

Some docs and code comments reference upstream design patterns, such as pluggable LLM services, local/remote VLM backends, MCP-style tool contracts, and document-object artifact boundaries. These references are implementation guidance for this orchestration layer, not copied upstream source code.

If you redistribute a packaged build that bundles any third-party binaries or models, review and include the corresponding upstream license texts and notices.
