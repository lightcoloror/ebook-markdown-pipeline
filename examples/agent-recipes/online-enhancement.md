# Online Enhancement

Use this recipe when a caller explicitly asks for optional model-backed enhancement after local conversion, OCR, or review has already identified a weak area.

Default behavior is safe and offline: `provider_mode=fake`, `model_mode=local`, and no remote call is made.

## Supported Tasks

- `text_structure`: repair Markdown heading hierarchy.
- `vlm_layout`: describe image or infographic layout.
- `ocr_layout`: OCR an image with layout blocks.
- `table_repair`: repair true table candidates only.
- `embedding`: create optional vectors for semantic search experiments.

## CLI Flow

Fake text-structure dry run:

```powershell
python scripts\run_online_enhancement.py text_structure `
  --input-text "Title`n`nBody" `
  --output .\online-review
```

Fake embedding dry run:

```powershell
python scripts\run_online_enhancement.py embedding `
  --input-texts "chapter title" "important paragraph"
```

Explicit OpenAI-compatible image/VLM call:

```powershell
python scripts\run_online_enhancement.py vlm_layout `
  --input-path path\to\infographic.png `
  --output .\online-review `
  --provider-mode openai_compatible `
  --model-mode hybrid `
  --allow-remote
```

The command prints JSON. When `--output` is provided, it also writes `online-enhancement-<task>.json/md` artifacts.

## MCP Flow

```json
{
  "name": "run_online_enhancement",
  "arguments": {
    "task": "text_structure",
    "provider_mode": "fake",
    "input_text": "Title\n\nBody",
    "output": "out/online-review"
  }
}
```

For real OpenAI-compatible calls, all three switches are required:

```json
{
  "provider_mode": "openai_compatible",
  "model_mode": "hybrid",
  "allow_remote": true
}
```

## Safety Checklist

- Do not call vendor APIs directly; always use `run_online_enhancement`.
- Do not set `allow_remote=true` unless the user or caller explicitly accepted cost/privacy risk.
- Do not send whole documents by default; send the smallest reviewable page, image, table, or Markdown segment.
- Read generated `online-enhancement-<task>.md` before using it to replace or merge content.
