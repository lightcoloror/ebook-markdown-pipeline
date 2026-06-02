# Tool-First Integration Lessons

This project should prefer existing converters, OCR engines, document parsers, APIs, and local tools. New code should mainly provide orchestration, glue, routing, logging, recovery, quality review, UI, and agent-facing contracts.

## Core Principle

Do not ask the project to reinvent ebook conversion, OCR, PDF parsing, or model inference.

Let specialist tools do specialist work:

- Pandoc: structured ebook/document conversion to Markdown, HTML, or text.
- Calibre: Kindle and ebook format normalization, especially AZW/AZW3/MOBI/RTF to EPUB.
- MinerU, Marker, Docling: heavier PDF/document structure extraction.
- Umi-OCR/PaddleOCR: local OCR fallback and image/PDF text extraction.
- PyMuPDF/PyMuPDF4LLM: fast PDF text-layer fallback and lightweight inspection.

Let this project do the integration work:

- Detect input format and route to the right backend.
- Normalize command paths and environment variables.
- Apply timeouts and kill stuck subprocesses.
- Fall back when a tool fails or produces weak output.
- Preserve logs, temporary artifacts, summaries, reports, and manual review records.
- Score output quality and generate review checklists.
- Provide stable CLI, UI, HTTP, and MCP surfaces for humans and agents.

## What Worked

- Keep conversion behavior in the Python core and expose it through thin CLI, UI, HTTP, MCP, and agent-batch wrappers.
- Treat every external tool as unreliable at runtime, even when it is installed. Tools can hang, need model downloads, fail through proxy errors, or become incompatible with another dependency.
- Record every meaningful fallback in report JSON. A successful output may still be a low-structure fallback such as `pymupdf-text(fallback from pymupdf4llm)`.
- Prefer recoverable batch execution over perfect one-shot conversion. `manifest.json`, `.reports/summary.json`, `review-checklist.json`, logs, and history loading are as important as the Markdown file.
- Keep user-facing actions concrete. Buttons like `PDF对比 / Compare`, `只载问题 / Problems`, and `发现历史 / Discover` matter because users need to continue from imperfect output.
- Make risky operations non-destructive by default. Recommended reruns should write to versioned rerun directories before replacing the main output.

## Pitfalls

- `status=ok` does not prove the output is good. A PDF can convert successfully while preserving only page-level headings and noisy footers.
- A dependency being importable does not prove compatibility. `pymupdf4llm` can import but fail against a newer or different PyMuPDF API.
- A new history feature is incomplete if it only records future runs. Existing `.reports/summary.json` files must be discoverable and importable.
- UI functionality is incomplete if users cannot see or reach the button. Long toolbars, long paths, and long table cells need wrapping, short labels, detail rows, or horizontal scrolling.
- Deep integration is expensive. Avoid copying internals from large upstream projects unless a small wrapper cannot solve the problem.

## Decision Rules

1. First look for a local tool, CLI, API, open-source package, or existing project function.
2. If a suitable tool exists, call it directly through a stable boundary.
3. If light integration is enough, write wrappers, routing, configuration, logging, fallback, and review logic.
4. If the tool output is weak, compare another tool or preserve a review artifact instead of silently accepting it.
5. If a task requires from-scratch parsing, OCR, model inference, or major refactoring, pause and check whether the value justifies the maintenance burden.
6. If the project is being prepared for public sharing, review licenses and keep the repository license compatible with the strictest referenced dependency.

## Pattern To Reuse

Use this architecture for similar projects:

```text
input files
-> lightweight inspection
-> route to specialist backend
-> capture logs and diagnostics
-> fallback when needed
-> quality scoring
-> review checklist
-> versioned reruns and manual review
-> stable CLI/UI/API/MCP surfaces
```

## One-Sentence Summary

The model should own orchestration, judgment, recovery, and user workflow; specialist tools should own conversion, OCR, parsing, and model inference.
