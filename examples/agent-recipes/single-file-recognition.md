# Single File Recognition

Use this recipe for one ebook, PDF, Office document, image, or screenshot when the goal is conversion/recognition, not keyword location indexing.

## MCP Call

```json
{
  "name": "process_material",
  "arguments": {
    "input": "path/to/source-file-or-image.png",
    "output": "path/to/output-folder",
    "intent": "auto",
    "recursive": false,
    "output_format": "markdown",
    "pdf_pipeline_mode": "auto"
  }
}
```

## HTTP Call

```bash
curl -H "Authorization: Bearer ${EBOOK_CONVERTER_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"name":"process_material","arguments":{"input":"path/to/source-file-or-image.png","output":"path/to/output-folder","intent":"auto","recursive":false,"output_format":"markdown","pdf_pipeline_mode":"auto"}}' \
  "http://host.docker.internal:${EBOOK_CONVERTER_HTTP_PORT}/call"
```

## Follow-Up

1. If the response has `job_id`, call `get_job_status` until `status` is `done`, `failed`, or `skipped`.
2. Read `quality_summary.review_count`.
3. If review count is zero, follow the first readable `next_actions` entry, usually `read_artifact`.
4. If review count is non-zero, read `review_report` and follow executable `next_actions`.
5. If a rerun is suggested, keep `overwrite=false` and use the suggested `output_name_suffix`.

## Notes

- Do not set `query` unless the user asked where something appears.
- Do not set `intent=locate` for ordinary OCR/conversion.
- For images and image folders, `intent=auto` uses recognition/image-book rebuilding by default.
