# Third-Party Notices

This project is a local orchestration layer for ebook and PDF conversion tools. It does not vendor the third-party tools listed below. Users install and use those tools separately under their own licenses.

## License Choice

This project is released under the GNU Affero General Public License v3.0 (AGPL-3.0).

The reason is conservative compatibility for public sharing: several referenced or integrated PDF tools are strong-copyleft licensed, especially PyMuPDF / PyMuPDF4LLM under AGPL-3.0 or commercial licensing. MinerU public licensing information has also included AGPL-3.0 / strong-copyleft constraints, while Marker is commonly distributed under GPL-3.0-level terms. AGPL-3.0 is therefore the strictest practical open-source license among the referenced tools.

This is an engineering compliance note, not legal advice.

## Referenced Tools

| Tool | Used For | License Notes |
| --- | --- | --- |
| Pandoc | EPUB/FB2/ODT/TXT and Markdown/HTML/text conversion | GPL-family project; installed separately |
| Calibre / ebook-convert | AZW/AZW3/MOBI/RTF intermediate conversion | GPL-family project; installed separately |
| PyMuPDF | PDF preflight, splitting, rendering support | AGPL-3.0 or commercial license |
| PyMuPDF4LLM | PDF-to-Markdown fallback | AGPL-3.0 via PyMuPDF ecosystem |
| MinerU | Structured PDF parsing | Public information indicates AGPL-3.0 / strong-copyleft constraints; installed separately |
| Marker | PDF parsing option | GPL-3.0-level project; installed separately |
| Umi-OCR / PaddleOCR-json | OCR fallback workflow | Installed separately; check upstream licenses and bundled OCR model licenses |
| tkinterdnd2 | Optional drag-and-drop UI support | Python package dependency; installed separately |

## Distribution Boundary

This repository contains only the orchestration scripts, UI, logging, retry, report, and workflow code. It does not redistribute third-party binaries, model weights, or book content.

If you redistribute a packaged build that bundles any third-party binaries or models, review and include the corresponding upstream license texts and notices.
