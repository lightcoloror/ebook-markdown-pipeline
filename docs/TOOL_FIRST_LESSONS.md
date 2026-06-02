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

## External Best Practices That Match This Project

- Unix-style composition: keep tools modular, clear, and reusable; compose them instead of building one large all-purpose parser.
- Adapter/facade boundaries: call Pandoc, Calibre, MinerU, Marker, Docling, Umi-OCR, and PyMuPDF through stable wrappers rather than spreading command details across UI, CLI, and agent code.
- Workflow orchestration: retries, timeouts, failure handling, and state should live in the orchestrator layer, not inside every worker path.
- Idempotency: batch jobs need manifests, stable output paths, skip/resume behavior, and safe rerun directories so repeated execution does not corrupt results.
- Agent manager pattern: one orchestrator should choose and call specialized tools; do not let a free-form agent parse files directly when a tool contract exists.
- Human-in-the-loop gates: uncertain or destructive steps need explicit review artifacts or versioned output before replacement.
- Observability: tool logs, fallback diagnostics, actual pipeline names, and report paths are part of the product, not debug leftovers.

## Project-Specific Lessons

- Calibre is valuable as an ebook normalizer, not as the whole Markdown solution. Use it for `AZW/AZW3/MOBI/RTF -> EPUB`, and as a fallback for weak `EPUB/FB2/ODT` output, but keep Pandoc and TOC alignment in the Markdown path.
- MinerU can finish page processing but still hang during finalization or managed-process shutdown. Progress must distinguish page progress from finalization progress, and finalization timeout must preserve logs and artifacts.
- `pymupdf4llm` can fail at runtime even when importable. The project needs a `pymupdf-text(fallback from pymupdf4llm)` path so fast PDF fallback does not block batches.
- A PDF result can be technically successful but semantically poor when headings are page numbers. Quality review must detect page-heading dominance, page-number noise, repeated footer/header lines, and short-line noise.
- Existing history matters. UI history must discover old `.reports/summary.json` and `review-checklist.json` files, not only runs created after the feature was added.
- UI visibility is reliability. If users cannot see `PDF对比 / Compare`, `发现历史 / Discover`, or `只载问题 / Problems`, the workflow is broken even if the function exists.
- Recommended reruns must be non-destructive. Write to `.reports/reruns/<timestamp>-<pipeline>-<book>/` first, then let the user compare before replacing main output.
- Agent batch runners should validate manifests before starting long jobs. `--dry-run` and plan artifacts reduce accidental expensive conversions.

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

## Operational Checklist

Use this checklist before adding or changing a feature:

1. Is there already a local tool, CLI, API, package, or project function that can do the core work?
2. Is the new code only routing, wrapping, logging, recovery, UI, or quality review?
3. Does the tool call have timeout, log capture, error classification, and diagnostic reporting?
4. Does the job remain recoverable through manifest, summary, report, or history state?
5. Is the operation idempotent or explicitly versioned?
6. Does the UI expose the next action as a reachable button?
7. Does `status=ok` still pass through quality scoring and review artifacts?
8. Does agent-facing output include artifact paths instead of requiring path guessing?
9. Are risky reruns non-destructive by default?
10. Is the fallback path named honestly in reports and summaries?

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

## Useful References

- Unix philosophy: modular tools and composition.
- OpenAI Agents manager/orchestration pattern: a central orchestrator calls bounded specialist tools.
- Azure AI agent design patterns: use sequential, parallel, and hierarchical orchestration deliberately; add scoring and human gates for nondeterministic outputs.
- AWS agentic workflow orchestration: central orchestration is useful when work requires specialized tools or models.
- Orkes/Conductor idempotency guidance: workflow-level and task-level idempotency both matter for retries.
- Recent LLM tool-use research: the hard problem is no longer a single tool call, but long-running multi-tool orchestration with state, feedback, safety, cost, and verifiability.

## One-Sentence Summary

The model should own orchestration, judgment, recovery, and user workflow; specialist tools should own conversion, OCR, parsing, and model inference.
