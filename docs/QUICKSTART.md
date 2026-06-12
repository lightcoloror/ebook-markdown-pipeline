# Quickstart

This page is the smallest useful path for new users. It intentionally avoids heavy PDF/OCR/VLM backends.

## 1. Install

```powershell
git clone https://github.com/lightcoloror/ebook-markdown-pipeline.git
cd ebook-markdown-pipeline
python -m pip install -r requirements.txt
```

Install these command-line tools when available:

- `pandoc` for EPUB, FB2, TXT, ODT, Markdown, and HTML conversions.
- `ebook-convert` from Calibre for AZW, AZW3, MOBI, and RTF.

## 2. Start The UI

```powershell
python book_converter_ui.py
```

On Windows, you can also double-click `start_ui.cmd`.

Use the normal workflow:

1. Drag files or folders into the window.
2. Click `扫描 / Scan`.
3. Click `开始 / Start` or `按推荐执行 / Run Recommended`.
4. Open the generated Markdown or report from the result row.

## 3. Batch Convert From CLI

```powershell
python batch_convert_books.py .\samples .\out --recursive --output-format markdown
```

Outputs go to the selected output folder. Reports, logs, quality summaries, and review checklists are written under `.reports/`.

## 4. Check The Install

```powershell
python scripts\test_minimal_entrypoints.py
python scripts\run_quality_gate.py --profile minimal
```

The quality gate reuses the committed public fixtures by default and only generates them when missing; use `--regenerate-fixtures` when you intentionally want to refresh those sample files. If those checks pass, the minimal local workflow is ready. Install heavier backends only when a report recommends them.
