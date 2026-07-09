# img2table Baseline: Photo/Scanned Table to XLSX

Date: 2026-07-09
Project: `D:\used-by-codex\ebook_markdown_pipeline`
Worker: `scripts\table_to_xlsx_worker.py`
Scope: local baseline only; no private documents and no model installation.

## Summary

`img2table` is usable as a lightweight structure baseline, but not yet a complete photo-to-Excel route on this machine.

Observed result:

- With the default Python environment, `img2table` is installed but OpenCV loads a user-site `cv2` without `ximgproc`, so image table detection is not ready.
- With `PYTHONNOUSERSITE=1`, Python loads the OpenCV contrib build and `cv2.ximgproc` is available.
- With `--ocr none`, `img2table` can export a valid `.xlsx` grid from the synthetic bordered sample.
- The resulting workbook recovered structure only: `A1:C4`, 4 rows, 12 cell slots, blank cell text.
- Tesseract is available through `tesseract.cmd`, but local languages are only `chi_sim` and `tessdata\chi_sim`; default `eng` is not available.

## Commands Verified

Default health:

```powershell
python -B scripts\table_to_xlsx_worker.py --input <synthetic-table.png> --output <health-default> --mode plan --backend img2table --ocr tesseract
```

Key health result:

```json
{
  "img2table": true,
  "cv2_ximgproc": false,
  "tesseract_languages": ["chi_sim", "tessdata\\chi_sim"],
  "selected_language_available": false
}
```

Contrib-enabled health:

```powershell
$env:PYTHONNOUSERSITE='1'
python -B scripts\table_to_xlsx_worker.py --input <synthetic-table.png> --output <health-contrib> --mode plan --backend img2table --ocr tesseract
```

Key health result:

```json
{
  "img2table": true,
  "cv2_ximgproc": true,
  "tesseract_languages": ["chi_sim", "tessdata\\chi_sim"],
  "selected_language_available": false
}
```

Successful structure-only export:

```powershell
$env:PYTHONNOUSERSITE='1'
python -B scripts\table_to_xlsx_worker.py --input <synthetic-table.png> --output <run-img2table-no-ocr-health-fixed> --mode execute --backend img2table --ocr none --detect-rotation --implicit-rows --implicit-columns --borderless-tables
```

Output status: `ok`

Artifacts:

- `table.xlsx`
- `table-to-xlsx-result.json`

## Implementation Follow-Up

The worker now reports:

- `cv2_ximgproc` availability.
- Tesseract language list, including Windows `.cmd` wrappers.
- Clean failure when `img2table` is installed but the loaded `cv2` lacks `ximgproc`.
- Correct `ok` preservation when a backend-specific exporter succeeds.

## Decision Update

Keep the backend ranking from `docs\plans\2026-07-09-table-to-xlsx-decision.md`:

1. PaddleOCR `TableRecognitionPipelineV2` remains the preferred full recognition backend.
2. `img2table` remains the baseline for bordered/light-background tables.
3. `RapidTable` remains a fallback/structure comparison candidate.

Practical next step before real documents:

- Run `img2table` with `PYTHONNOUSERSITE=1` and `--ocr tesseract --ocr-lang chi_sim` on a non-private Chinese sample.
- Add an English Tesseract language pack only if English screenshots or mixed-language samples are required.
- Keep PaddleOCR model installation gated behind explicit approval.
