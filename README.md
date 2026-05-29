# Ebook Markdown Pipeline

最稳的本地批量方案：

- `EPUB / FB2 / ODT / TXT` 直接用 `pandoc`
- `AZW / AZW3 / MOBI / RTF` 用 `calibre -> EPUB -> pandoc`
- `PDF` 自动模式下短文档用 `Marker`，长文档自动使用 `MinerU pipeline` 做结构化解析；`Umi-OCR` 仅作为手动兜底模式

脚本文件：

- [batch_convert_books.py](D:\used-by-codex\ebook_markdown_pipeline\batch_convert_books.py)
- [book_converter_ui.py](D:\used-by-codex\ebook_markdown_pipeline\book_converter_ui.py)

## UI 界面

启动桌面界面：

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\book_converter_ui.py
```

也可以直接双击：

- [start_ui.cmd](D:\used-by-codex\ebook_markdown_pipeline\start_ui.cmd)

界面能力：

- 自动识别输入文件格式
- 支持把文件或文件夹直接拖放到窗口中
- 自动探测常见的 `pandoc`、`ebook-convert`、`marker_single` 安装路径
- 扫描文件夹并预览每个文件会走哪条转换流水线
- 选择输出格式：`markdown`、`html`、`text`
- 自定义 `pandoc`、`ebook-convert`、`marker_single` 路径
- 一键检查当前选择需要的转换环境，包括 Pandoc、Calibre、MinerU、MinerU 模型缓存、PyMuPDF4LLM、Umi-OCR 和 CUDA
- 批量转换并显示日志
- 默认写入 `manifest.json` 和 `.reports/*.report.json`，方便失败后继续跑和排查每本书的耗时/管道/输出位置
- report 会包含轻量 Markdown 质量评分，用来提示无标题、页码噪声、脚注密度、乱码、HTML 残留等风险
- PDF 自动模式会先快速预检文本层、图片占比、目录页/表格页迹象和扫描版风险，再选择 Marker 或 MinerU
- Marker/MinerU 长任务会流式读取外部工具输出；能解析页码时显示当前页，解析不到时也会持续显示运行中、已用时和预计剩余

## 用法

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\batch_convert_books.py `
  D:\books `
  D:\books-md `
  --recursive `
  --output-format markdown `
  --manifest D:\books-md\manifest.json
```

失败后只重跑未完成项：

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\batch_convert_books.py `
  D:\books `
  D:\books-md `
  --recursive `
  --manifest D:\books-md\manifest.json `
  --resume
```

只检查当前选择需要的依赖和环境：

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\batch_convert_books.py `
  D:\books `
  D:\books-md `
  --recursive `
  --health-check
```

单文件：

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\batch_convert_books.py `
  D:\books\sample.azw3 `
  D:\books-md `
  --overwrite
```

## 依赖

- `pandoc`
- `ebook-convert` from calibre
- `mineru`
- `marker_single`

如果命令不在 `PATH`，可以显式传：

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\batch_convert_books.py `
  D:\books `
  D:\books-md `
  --recursive `
  --pandoc-command D:\ProgramData\anaconda3\Scripts\pandoc.exe `
  --calibre-command "C:\Program Files\Calibre2\ebook-convert.exe" `
  --marker-command marker_single
```

## 说明

- 默认不会覆盖已存在的 `.md`，加 `--overwrite` 才会覆盖。
- 默认会为每本书写入 `.reports/<书名>.report.json`；不需要报告时加 `--no-reports`。
- report 中的 `quality.level` 分为 `good / review / poor`，用于快速筛出需要人工复查的输出。
- PDF report 中的 `pdf_preflight` 会记录页数、采样页数、文本层比例、平均文字数、图片面积比例、目录/表格迹象、是否疑似扫描版和自动选择原因。
- `--resume` 会读取已有 manifest，跳过已经成功或已经跳过且输出文件仍存在的条目。
- PDF 自动模式会在长文档上避免默认跑很慢的 `Marker`，并改用 `MinerU` 保留更好的结构；需要快速低结构 OCR 时可手动选 `Umi-OCR`。
- `html` 和 `text` 输出会尽量复用 `pandoc` 做后续格式转换。
- `AZW/MOBI` 默认要求是无 DRM 文件。
- `--dry-run` 可以先看会执行哪些命令。
