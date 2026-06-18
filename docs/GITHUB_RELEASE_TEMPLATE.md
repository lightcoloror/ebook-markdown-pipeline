# Release Title

`vX.Y.Z - short summary`

## Highlights

- Local-first graphic/text material conversion to Markdown.
- Minimal path remains lightweight; heavy OCR/VLM backends are optional.
- Agent interfaces remain available through CLI, HTTP, and MCP.

## Quick Start

```powershell
git clone https://github.com/lightcoloror/ebook-markdown-pipeline.git
cd ebook-markdown-pipeline
python -m pip install -r requirements.txt
python book_converter_ui.py
```

## Quality Gate

Generate the first draft from the current changelog and quality-gate evidence:

```powershell
python scripts\prepare_github_release_notes.py --version vX.Y.Z --output .\release-notes.md
```

Then verify or paste the latest local result from:

```powershell
python scripts\run_quality_gate.py --profile release
python scripts\show_latest_quality_gate.py
```

- Status:
- Regression tags:
- Release summary:
- Optional backend scorecard:

## Compatibility Notes

- Minimal install supports common ebook/text workflows and text-layer PDF fallback.
- MinerU, Marker, Docling, Umi-OCR, OCRmyPDF, Pix2Text, Surya, GOT-OCR, DeepSeek-OCR, olmOCR, Tika, GROBID, and table extractors are optional.
- `media_helper` or `python_dependency_consistency` health warnings are soft risks for optional media/provider/model-download workflows unless this release explicitly requires those workflows.
- Online model APIs require explicit provider configuration and `allow_remote=true`.

## Third-Party Notices

This repository is an orchestration layer. It does not vendor parser/OCR/model code, model weights, private samples, or API keys. Users must follow each optional backend's license and model terms.
