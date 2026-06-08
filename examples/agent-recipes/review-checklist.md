# Review Checklist

Use this recipe when conversion succeeds but the quality report says `review` or `poor`.

## Artifacts To Read

Read these artifacts through `read_artifact` or `read_report`, not by guessing local paths:

- `summary_report`
- `summary_json`
- `review_report`
- `review_json`
- per-file `conversion_report`
- Markdown output

## What To Inspect

- `quality_summary.review_count`
- `quality_summary.review_items[].quality_reasons`
- `quality_summary.review_items[].pdf_outline_alignment`
- `quality_summary.review_items[].next_actions`
- `structure_repair.decisions[]` in per-file reports
- `pdf_fallback_diagnostics` in per-file reports

## Structure Repair Evidence

When a report includes `structure_repair`, inspect:

- `action`: what changed, such as `promoted_to_heading` or `normalized_heading`.
- `confidence`: whether the repair was strong enough to trust.
- `reason`: human-readable explanation.
- `signals`: machine-readable evidence such as numbering pattern, font hint, TOC match, or parent context.
- `inferred_outline`: the resulting heading tree.

## Output Acceptance

Accept output only after:

- The output artifact is readable.
- The title hierarchy looks plausible for the source type.
- Page-number or footer noise is not dominating headings.
- Any fallback diagnostics are understood.
- Suggested reruns, if used, were written as versioned outputs.
