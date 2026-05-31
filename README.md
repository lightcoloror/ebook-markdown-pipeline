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
- 批量结束后会生成 `.reports/summary.md` 和 `.reports/summary.json`，汇总失败项、质量复查队列、管道分布和 PDF 风险
- 批量结束后也会生成 `.reports/review-checklist.md/json`，列出需要人工复查的文件、report 路径和建议动作
- EPUB / Calibre 中转 EPUB 会读取 `toc.ncx` / `nav.xhtml`，尽量把原书目录标题提升为 Markdown 层级标题
- UI 会在用户目录保存上次路径、PDF 模式、工具路径和开关设置，下次启动自动恢复
- PDF 自动模式会先快速预检文本层、图片占比、目录页/表格页迹象和扫描版风险，再选择 Marker 或 MinerU
- Marker/MinerU 长任务会流式读取外部工具输出；能解析页码时显示当前页，页处理完成后会切换为“正在收尾/写文件”，并提示长时间无输出的疑似卡住状态
- 每次 Marker/MinerU 调用会写入 `.reports/pdf-tool-logs/*.log`，report 中也会记录 `pdf_tool_diagnostics`，用于排查卡在页级解析、收尾写文件、无输出等待、启动失败或非零退出码
- PDF 工具有自动防卡死保护：无输出超过 `--pdf-tool-idle-timeout` 或页处理完成后收尾超过 `--pdf-tool-finalize-timeout` 会终止进程树、保留临时目录并自动回退到 PyMuPDF4LLM
- 200 页以上 PDF 默认按 50 页分段跑 MinerU，降低长文档整本卡死的风险；可用 `--mineru-segment-min-pages` 和 `--mineru-segment-pages` 调整
- UI 提供复查入口：打开复查清单、选中输出、选中报告和最近 PDF 工具日志

## 用法

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\batch_convert_books.py `
  D:\books `
  D:\books-md `
  --recursive `
  --output-format markdown `
  --manifest D:\books-md\manifest.json
```

## Agent 调用

推荐调用层级：

- `MCP`：给 OpenClaw、Hermes Agent、Codex 等 agent 稳定调用，支持扫描、环境检查、后台转换、轮询进度、读取 report 和 PDF 工具日志。
- `CLI`：自动化脚本和人工排错的稳定兜底入口。
- `Skill`：给支持 skill 的 agent 提供调用规范，避免 agent 自己重写转换逻辑。

MCP 配置示例：

```json
{
  "mcpServers": {
    "ebook-markdown-pipeline": {
      "command": "C:\\path\\to\\ebook_markdown_pipeline\\start_mcp.cmd",
      "args": []
    }
  }
}
```

把 `C:\path\to\ebook_markdown_pipeline` 改成实际项目路径即可。本机当前路径是 `D:\used-by-codex\ebook_markdown_pipeline`。

MCP 工具包括：

- `scan_books`：扫描输入并返回每本书的转换计划。
- `health_check`：检查 Pandoc、Calibre、MinerU、Marker、Umi-OCR、PyMuPDF4LLM、CUDA 和模型缓存。
- `start_conversion`：启动后台转换任务。
- `get_job_status`：轮询任务状态、阶段事件和结果。
- `read_report`：读取转换 report。
- `read_pdf_tool_log`：读取 Marker/MinerU 日志尾部。

详细说明见 [docs/AGENT_INTEGRATION.md](docs/AGENT_INTEGRATION.md)。支持 skill 的 agent 可参考 [skills/ebook-markdown-pipeline/SKILL.md](skills/ebook-markdown-pipeline/SKILL.md)。

接入前可先跑 MCP smoke test：

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\scripts\test_mcp_stdio.py
```

需要测试一次真实转换时：

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\scripts\test_mcp_stdio.py --convert
```

Docker 里的 OpenClaw / Hermes Agent 这类容器无法直接执行 Windows 路径的 stdio MCP 时，可以启动 HTTP bridge：

```powershell
$env:EBOOK_CONVERTER_API_TOKEN = "replace-with-a-local-token"
python D:\used-by-codex\ebook_markdown_pipeline\ebook_converter_http.py --host 0.0.0.0 --port 8765
```

容器内通过 `http://host.docker.internal:8765` 调用，接口复用同一套 MCP tool 名称和 JSON 参数。详见 [docs/AGENT_INTEGRATION.md](docs/AGENT_INTEGRATION.md)。

本机 Docker 集成烟测：

```powershell
powershell -ExecutionPolicy Bypass -File D:\used-by-codex\ebook_markdown_pipeline\scripts\run_docker_agent_smoke.ps1
```

## 轻量定位索引

如果只需要知道关键词出现在“哪份 PDF 的哪一页”或“哪张图片”，不需要精确坐标，可以使用页级/图片级定位索引：

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\document_locator.py index `
  D:\documents `
  D:\documents-index `
  --recursive `
  --ocr auto
```

查询：

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\document_locator.py query `
  D:\documents-index\document_locations.sqlite `
  "合同金额" `
  --format markdown
```

输出会包含源文件、PDF 页码或图片文件、匹配片段。查询会先走 SQLite FTS，必要时回退到普通子串匹配；英文下划线、OCR 漏字等场景会做轻量 token 回退，所以适合“先定位到哪页/哪张图，再人工复核”的用法。`--ocr never` 只用 PDF 文本层，速度最快；`--ocr auto` 会对无文本层 PDF 页和图片调用 Umi-OCR。批量建索引时，单个坏文件会记录为 `failed`，不会中断整批任务。

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
- Python packages in [requirements.txt](requirements.txt), including `PyMuPDF` and `PyMuPDF4LLM`

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
- `.reports/summary.md` 是批量复查入口；优先看 `Failed` 和 `Review Queue` 两个部分。
- `.reports/review-checklist.md` 是人工复查清单，适合转换完后逐项检查和决定是否换管道重跑。
- `--resume` 会读取已有 manifest，跳过已经成功或已经跳过且输出文件仍存在的条目。
- PDF 自动模式会在长文档上避免默认跑很慢的 `Marker`，并改用 `MinerU` 保留更好的结构；需要快速低结构 OCR 时可手动选 `Umi-OCR`。
- 如果 PDF 长任务疑似卡住，优先查看对应 `.reports/*.report.json` 里的 `pdf_tool_diagnostics.log`，再打开 `.reports/pdf-tool-logs/*.log` 看最后的 `stdout`、`heartbeat`、`finalizing` 或 `exit` 记录。
- 自动回退可用 `--no-pdf-auto-fallback` 关闭；超时阈值传 `0` 表示禁用对应超时。
- `html` 和 `text` 输出会尽量复用 `pandoc` 做后续格式转换。
- `AZW/MOBI` 默认要求是无 DRM 文件。
- `--dry-run` 可以先看会执行哪些命令。

## 许可证

本项目以 [GNU Affero General Public License v3.0](LICENSE) 发布。

选择 AGPL-3.0 的原因是：本项目直接或间接集成/调用的 PDF 处理工具中，`PyMuPDF` / `PyMuPDF4LLM` 使用 AGPL-3.0 或商业双许可，`MinerU` 公开信息也包含 AGPL-3.0/强 copyleft 约束，`Marker` 属于 GPL-3.0 级别。为了公开分享时采用“参考过的开源工具里最严格”的口径，本项目选择 AGPL-3.0。

第三方工具和模型不包含在本仓库中，用户需要按各自项目许可证和模型许可证自行安装与使用。详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
