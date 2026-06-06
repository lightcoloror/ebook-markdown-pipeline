# Ebook Markdown Pipeline

最稳的本地批量方案：

- `EPUB / FB2 / ODT / TXT` 直接用 `pandoc`
- `AZW / AZW3 / MOBI / RTF` 用 `calibre -> EPUB -> pandoc`
- `DOCX / PPTX / XLSX / HTML / Markdown / CSV` 默认用已验证的 `Docling` 后端；未安装时会在环境检查和报告里明确提示
- Docling 文档转换默认在独立子进程中运行，超过 45 秒会中止；DOCX/HTML/Markdown/CSV 会自动降级到 Pandoc 或轻量文本输出，并在 report 中记录 `docling(fallback)`
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
- UI 主界面只保留常用流程按钮；复查、PDF 对比、环境导出、Agent 调用、定位索引等低频操作集中在 `高级 / Advanced` 窗口
- 自动探测常见的 `pandoc`、`ebook-convert`、`marker_single` 安装路径
- 电子书优先用 Pandoc；当 EPUB/FB2/ODT 的 Pandoc 输出质量较弱或失败时，会尝试 Calibre 预处理为 EPUB 后再转 Markdown，并在 report 中记录是否采用 fallback
- 扫描文件夹并预览每个文件会走哪条转换流水线
- 选择输出格式：`markdown`、`html`、`text`
- 自定义 `pandoc`、`ebook-convert`、`marker_single` 路径
- 一键检查当前选择需要的转换环境，包括 Pandoc、Calibre、MinerU、MinerU 模型缓存、PyMuPDF4LLM、Umi-OCR 和 CUDA
- UI 启动后会自动做轻量自检，检查页面文件/提交内存、GPU 显存、torch/CUDA、MinerU 残留进程和关键依赖风险，并写入日志区
- UI 提供 `清理残留 / Cleanup`，可在确认没有任务运行时终止 MinerU 相关残留进程
- 批量转换并显示日志
- 默认写入 `manifest.json` 和 `.reports/*.report.json`，方便失败后继续跑和排查每本书的耗时/管道/输出位置
- report 会包含轻量 Markdown 质量评分，用来提示无标题、页码噪声、脚注密度、乱码、HTML 残留等风险
- 批量结束后会生成 `.reports/summary.md` 和 `.reports/summary.json`，汇总失败项、质量复查队列、管道分布和 PDF 风险
- 批量结束后也会生成 `.reports/review-checklist.md/json` 和 `.reports/review-decisions.md/json`，列出需要人工复查的文件、report 路径、建议动作和 accept/retry/manual-review 决策
- EPUB / Calibre 中转 EPUB 会读取 `toc.ncx` / `nav.xhtml`，尽量把原书目录标题提升为 Markdown 层级标题
- UI 会在用户目录保存上次路径、PDF 模式、工具路径和开关设置，下次启动自动恢复
- PDF 自动模式会先快速预检文本层、图片占比、目录页/表格页迹象和扫描版风险，再选择 Marker 或 MinerU
- Marker/MinerU 长任务会流式读取外部工具输出；能解析页码时显示当前页，页处理完成后会切换为“正在收尾/写文件”，并提示长时间无输出的疑似卡住状态
- 每次 Marker/MinerU 调用会写入 `.reports/pdf-tool-logs/*.log`，report 中也会记录 `pdf_tool_diagnostics`，用于排查卡在页级解析、收尾写文件、无输出等待、启动失败或非零退出码
- PDF 工具有自动防卡死保护：无输出超过 `--pdf-tool-idle-timeout` 或页处理完成后收尾超过 `--pdf-tool-finalize-timeout` 会终止进程树、保留临时目录并自动回退到 PyMuPDF4LLM
- MinerU/Marker 日志中出现明确失败信号时会提前中止并降级，例如 `ArrayMemoryError`、`WinError 1455`、CUDA DLL 加载失败或 `Local mineru-api exited before becoming healthy`
- 200 页以上 PDF 默认按 50 页分段跑 MinerU，降低长文档整本卡死的风险；可用 `--mineru-segment-min-pages` 和 `--mineru-segment-pages` 调整
- UI 提供复查入口：打开复查清单、选中输出、选中报告和最近 PDF 工具日志
- UI 的 `PDF对比 / Compare` 支持 `对比页码 / Pages`，可填 `1-3,100,600-602` 对超长 PDF 只抽页比较四管道质量

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

Agent 默认优先调用 `process_material`。它会先做轻量预检，再按输入和意图自动分流到转换、定位索引或截图成书重建；只有需要强制管道、排错或复查时，才直接调用更底层的工具。

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

- `process_material`：高层路由入口，自动识别输入并启动合适的异步任务。
- `scan_books`：扫描输入并返回每本书的转换计划。
- `health_check`：检查 Pandoc、Calibre、MinerU、Marker、Umi-OCR、PyMuPDF4LLM、CUDA 和模型缓存。
- `inspect_document`：预检文件/目录类型、PDF 风险和推荐管道。
- `start_conversion`：启动后台转换任务。
- `start_location_index`：后台建立 PDF/图片页级或图级定位索引。
- `query_location_index`：查询关键词出现在哪份 PDF 的哪一页或哪张图片。
- `export_location_review_pack`：把定位命中的 PDF 页或图片导出成复查包。
- `start_image_book_rebuild`：后台从乱序、重复、部分重叠截图重建 Markdown 草稿。
- `rebuild_image_book_from_order`：按人工改过的 `order.md` 重新生成截图书 Markdown。
- `get_job_status`：轮询任务状态、阶段事件和结果。
- `read_artifact`：按 artifact 类型安全读取 Markdown、JSON、日志、报告等输出。
- `read_report`：读取转换 report。
- `read_pdf_tool_log`：读取 Marker/MinerU 日志尾部。

稳定调用契约见 [docs/TOOL_CONTRACT.md](docs/TOOL_CONTRACT.md)，详细接入说明见 [docs/AGENT_INTEGRATION.md](docs/AGENT_INTEGRATION.md)。支持 skill 的 agent 可参考 [skills/ebook-markdown-pipeline/SKILL.md](skills/ebook-markdown-pipeline/SKILL.md)。
HTTP、MCP stdio 和 CLI-style 的最小调用示例见 [examples/agent-calls](examples/agent-calls)。

如果要把当前机器环境封装成可复查材料，可导出环境快照：

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\scripts\export_environment_report.py `
  --input D:\downloads `
  --output D:\downloads\.reports\environment
```

输出 `environment-report.md/json`，包含 Python/系统信息、依赖检查和能力矩阵，适合发给其他 agent 或用于环境故障复盘。

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
python D:\used-by-codex\ebook_markdown_pipeline\ebook_converter_http.py --host 0.0.0.0
```

HTTP host/port 默认读取 `config/http.env`。容器内通过 `http://host.docker.internal:<EBOOK_CONVERTER_HTTP_PORT>` 调用，接口复用同一套 MCP tool 名称和 JSON 参数。详见 [docs/AGENT_INTEGRATION.md](docs/AGENT_INTEGRATION.md)。

也可以使用仓库内的 `Dockerfile` 和 [docker-compose.example.yml](docker-compose.example.yml) 部署本地 HTTP 服务；容器路径和健康检查见 [docs/DOCKER_USAGE.md](docs/DOCKER_USAGE.md)。

本机 Docker 集成烟测：

```powershell
powershell -ExecutionPolicy Bypass -File D:\used-by-codex\ebook_markdown_pipeline\scripts\run_docker_agent_smoke.ps1
```

## 轻量定位索引

如果只需要知道关键词出现在“哪份 PDF 的哪一页”或“哪张图片”，不需要精确坐标，可以使用页级/图片级定位索引：

桌面 UI 也支持这个流程：批量选择或拖入 PDF/图片后，点击 `定位索引 / Location Index`，会在输出文件夹生成 `document_locations.sqlite` 和 `document_locations.jsonl`。

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

输出会包含源文件、PDF 页码或图片文件、匹配片段、匹配质量和 token 命中数。查询会先走 SQLite FTS，必要时回退到完整子串匹配和 all-token 子串匹配；英文下划线、中文分词不稳定、OCR 漏字等场景会做轻量 token 回退，所以适合“先定位到哪页/哪张图，再人工复核”的用法。`--ocr never` 只用 PDF 文本层，速度最快；`--ocr auto` 会对无文本层 PDF 页和图片调用 Umi-OCR。批量建索引时，单个坏文件会记录为 `failed`，不会中断整批任务。

导出命中页/图片复查包：

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\document_locator.py export-review `
  D:\documents-index\document_locations.sqlite `
  "合同金额" `
  D:\documents-index\review-pack
```

复查包会生成 `review.md`、`matches.json` 和 `pages/`，PDF 命中会尽量渲染对应页，图片命中会复制原图，方便人工检查。

## 真实样本评测 / Benchmarks

当前真实样本评测状态和 Docling 默认策略证据见 [docs/REAL_SAMPLE_EVALUATION_STATUS.md](docs/REAL_SAMPLE_EVALUATION_STATUS.md)。

先从本机目录发现 20-50 个真实样本，生成本地清单：

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\scripts\discover_benchmark_samples.py `
  D:\downloads `
  D:\BaiduSyncdisk\电子书 `
  --output D:\used-by-codex\ebook_markdown_pipeline\benchmarks\samples.local.json `
  --limit 50
```

运行批量评测，记录推荐管道、耗时、质量评分和失败原因：

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\scripts\run_benchmarks.py `
  --manifest D:\used-by-codex\ebook_markdown_pipeline\benchmarks\samples.local.json `
  --output D:\used-by-codex\ebook_markdown_pipeline\benchmarks\runs\latest `
  --sample-timeout 600 `
  --pdf-mode-for-benchmark fast `
  --min-success-rate 0.95 `
  --max-timeout-rate 0.05 `
  --max-failed-rate 0 `
  --fail-on-quality-gate
```

输出目录会包含：

- `benchmark-results.json`：机器可读的完整结果，适合后续汇总或 agent 读取。
- `benchmark-results.partial.json`：每个样本结束后增量写入；即使某次长评测被中断，也能保留已完成证据。
- `benchmark-summary.md`：人工快速浏览的样本状态、质量和失败原因。
- `benchmark-summary.partial.md`：中断前可读的阶段性摘要。
- `docling-decision.md`：根据真实样本自动给出 Docling 是否默认启用的建议；在样本不足、依赖缺失或成功率偏低时会保持 Docling 为可选后端。
- `quality-regression-summary.md/json`：汇总成功率、标题数量、页码标题比例、噪声行、fallback 次数和可选质量 gate。传入 `--fail-on-quality-gate` 后，任何配置的 gate 失败都会让命令以非 0 退出，适合 agent 批处理或 CI。

`--sample-timeout` 可以避免单个坏文件、慢 OCR 或模型收尾卡住拖死整批评测；超时样本会记录为 `timeout` 并继续处理后续样本。Windows 下会用进程树终止，避免 MinerU/Marker 等子进程留下孤儿进程。

`--pdf-mode-for-benchmark fast` 会把 PDF 批量评测切到 `PyMuPDF4LLM`，适合先跑完整 20-50 个样本拿到速度、基础结构和失败证据；不要用它替代最终质量判断。需要比较 MinerU / Docling / PyMuPDF4LLM / Umi-OCR 的实际效果时，仍然使用下面的 `compare_pipelines.py` 对代表性 PDF 单独跑多管道。

对同一个 PDF 比较多条管道：

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\scripts\compare_pipelines.py `
  --input D:\books\sample.pdf `
  --output D:\used-by-codex\ebook_markdown_pipeline\benchmarks\compare-runs\sample `
  --pipelines pymupdf4llm mineru umi docling `
  --pipeline-timeout 600
```

输出的 `pipeline-comparison.md` 会对比各管道的耗时、标题数量、正文长度、表格迹象、页码噪声和人工评分入口。`--pipeline-timeout` 会限制单条管道耗时，并在每条管道结束后写出 `pipeline-comparison.partial.json/md`，避免 MinerU、Marker、Docling PDF OCR 等慢管道拖死整次对比。桌面 UI 里选中 PDF 后也可以点 `PDF对比 / Compare` 生成同类报告；如果填写 `对比页码 / Pages`，UI 会传入 `--page-ranges` 只比较指定页；选中失败或待复查条目后，`推荐重跑 / Rerun Rec` 会按报告里的推荐管道重新执行该文件。

Agent/批量场景下可用 `--docling-timeout <秒>` 控制 Docling 文档后端的最长运行时间；`--no-docling-fallback` 可关闭 DOCX/HTML/Markdown/CSV 的自动轻量兜底。HTTP `/call` 的 `start_conversion` / `process_material` 也支持 `docling_timeout` 和 `docling_fallback_to_pandoc` 参数。

PDF 后端降级会写入 `pdf_fallback_diagnostics`：包括原管道、降级管道、失败/超时原因、耗时和 fallback 状态。Agent 或 UI 看到 `pymupdf4llm(fallback from ...)` 时，应提示用户这是稳定性兜底结果，结构质量可能低于 MinerU/Docling/Marker 的高质量输出。如果本机 `pymupdf4llm` 与 PyMuPDF 版本不兼容，快速 PDF 管道会继续降级为 `pymupdf-text(fallback from pymupdf4llm)`，只抽取 PDF 文本层，适合不中断批处理和定位，但章节结构质量通常较弱。

Umi-OCR 输出会保留页边界，但页边界使用 `<!-- Page N -->` 注释而不是 Markdown 标题，避免把每一页误当成章节；同时会保守提升部分 OCR 识别出的页内标题，减少“全是 Page 标题”的层级噪声。

对 HTTP agent 调用做并发稳定性测试：

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\scripts\stress_agent_http.py `
  --manifest D:\used-by-codex\ebook_markdown_pipeline\benchmarks\samples.local.json `
  --iterations 20 `
  --concurrency 4 `
  --retries 2 `
  --pdf-pipeline-mode pymupdf4llm
```

压力测试报告会记录成功率、artifact 读取率、平均耗时和最长耗时；HTTP 连接错误、5xx 或 `/call` 返回的 `retryable=true` 错误会按 `--retries` 做有限重试。

如果要验证 Docker 中的 OpenClaw/Hermes 是否能访问本工具的 HTTP `/call`，可以运行：

```powershell
powershell -ExecutionPolicy Bypass -File D:\used-by-codex\ebook_markdown_pipeline\scripts\run_docker_agent_smoke.ps1 `
  -Port 8770 `
  -ReportDir D:\used-by-codex\ebook_markdown_pipeline\benchmarks\runs\docker-agent-smoke-current `
  -ContainerIterations 2
```

该 smoke 会生成 txt、fb2、rtf、epub、odt、azw3、mobi、azw、pdf 小样本，启动本项目 HTTP bridge，并从 `openclaw-openclaw-gateway-1` 和 `hermes-agent` 容器内通过 `host.docker.internal` 调用 `/health`、`/call scan_books`、多轮 `/call start_conversion`、`/call get_job_status` 和 `/call read_artifact`。报告写入 `docker-agent-smoke.json/md`。

转换完成后，HTTP/MCP job 会在 `get_job_status` 中返回 `quality_summary`。Agent 应优先检查 `review_count` 和 `review_items`，再按 `next_actions` 读取 `summary_report`、`review_report` 和代表性 Markdown。桌面 UI 的文件列表也会在转换完成后显示 `质量 / Quality` 和 `建议 / Action` 两列，可点击列头按质量排序；`review / poor / failed` 会有颜色提示，双击行或点击 `执行建议 / Do Action` 会打开报告、复查清单、复制失败原因或启动 PDF 多管道对比。`按推荐执行 / Run Rec` 会先批量转换安全的新文件；如果当前列表只有复查项，它会在所有可重跑 PDF 推荐同一管道时做版本化批量重跑，否则自动选中第一条复查项并执行对应建议。

UI 复查工作台还支持 `只看复查 / Review only`、`上一条 / Prev`、`下一条 / Next`、`原文件 / Source`、`标记验收 / Accept`、`人工评分 / Score` 和 `人工记录 / Manual`。人工验收结果会写入输出目录的 `.reports/manual-review.json` 和 `.reports/manual-review.md`，重新扫描或转换完成后会自动回填到表格，用于后续校准质量评分规则。

Agent 批处理模板在 `examples/agent-batch/`：`batch_manifest.example.json` 定义批处理任务，`agent_batch_http.py --dry-run` 可先校验 manifest 并输出 `agent-batch-plan.md`，正式运行时通过 HTTP `/call` 执行 `process_material -> get_job_status -> read_artifact`，并输出 `agent-batch-results.json` 和 `agent-batch-summary.md`。OpenClaw/Hermes/Codex 可直接复用 `AGENT_PROMPT_TEMPLATE.md` 中的固定调用规则。

## 截图成书重建

如果有一批乱序、重复、部分重叠的截图，可以先用截图重建管道生成可复查的 Markdown 草稿：

桌面 UI 中也可以批量选择或拖入图片，然后点击 `截图成书 / Image Book`。

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\image_book_rebuilder.py build `
  D:\screenshots `
  D:\screenshots-md `
  --recursive
```

输出包括 `book.md`、`order.md`、`structure.md/json`、`review.md`、`pages.jsonl`、`clusters.json`。排序会综合图片内页码、文件名数字、文件时间、文本前后重叠和重复截图分组；`order.md` 会写明排序置信度和排序依据，`structure.md` 会汇总标题候选和推断层级，重复截图会作为排序和复查依据保留在 `review.md`，不会静默丢弃。

如果自动排序不满意，可以直接调整 `order.md` 表格行顺序，然后不重新 OCR、只按人工顺序重建：

```powershell
python D:\used-by-codex\ebook_markdown_pipeline\image_book_rebuilder.py rebuild-from-order `
  D:\screenshots-md\pages.jsonl `
  D:\screenshots-md\order.md `
  D:\screenshots-md-manual `
  --title "人工校正截图书"
```

输出仍然包含新的 `book.md`、`order.md`、`structure.md/json` 和 `review.md`，适合先机器排序、人工拖动表格行、再生成最终 Markdown。

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

## 网页归档视觉校验模式

`web-content-fetcher` 的 archive 已经保留了 DOM、Markdown、截图、图片资产和 `structured.json`。本工具在网页归档流程里只承担“视觉校验层”：从截图或页面图像补充 OCR、版面块、表格候选和图片位置，不覆盖原始 Markdown。

推荐顺序：

```powershell
python -m web_content_fetcher.cli archive rebuild D:\path\to\archive --with-visual-check --format summary

D:\used-by-codex\ebook_markdown_pipeline\process-web-archive.cmd D:\path\to\archive --format summary

python -m web_content_fetcher.cli archive rebuild D:\path\to\archive --with-visual-check --format summary
```

`process-web-archive.cmd` 会读取 `rebuild_input/manifest.json`，优先复用 `image_book_rebuilder` 对页面截图做 OCR/结构推断，并在 archive 下准备：

- `visual_check/layout_ocr.md`：截图 OCR 后的 Markdown。
- `visual_check/visual_blocks.json`：OCR 页面块和结构标题候选。
- `visual_check/table_candidates.json`
- `visual_check/image_positions.json`
- `visual_check/visual_check_result.json`

如果 OCR 引擎不可用或截图不存在，命令会降级为待处理契约文件并在 `visual_check_result.json` 记录 warning，不伪造 OCR 结果。后续可以继续增强表格候选和图片位置识别，只更新 `visual_check/` 下的视觉层文件，然后由 `web-content-fetcher archive rebuild` 生成最终 `final_readable.html`、`final_agent.md`、`final_structured.json` 和 `completeness_report.json`。

## 依赖

- `pandoc`
- `ebook-convert` from calibre
- `mineru`
- `marker_single`
- `docling` 可选安装包，但安装后是 DOCX、PPTX、XLSX、HTML、Markdown、CSV 的默认后端；PDF 只有手动选择 `--pdf-pipeline-mode docling` 时才走 Docling
- Python packages in [requirements.txt](requirements.txt), including `PyMuPDF` and `PyMuPDF4LLM`

Docling 是可选安装依赖，不默认随基础环境安装；需要处理 DOCX、PPTX、XLSX、HTML、Markdown、CSV 或手动对比 PDF Docling 管道时运行：

```powershell
python -m pip install -r D:\used-by-codex\ebook_markdown_pipeline\requirements-docling.txt
```

当前真实样本验证版本为 `docling==2.96.1`。如果你的全局 Python 同时装了其他 agent 框架，建议在独立虚拟环境中安装 Docling，避免与 CrewAI、AutoGen、LiteLLM 等工具的依赖范围互相影响。

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
- `.reports/review-decisions.md` 是批次决策摘要，适合先看哪些文件可接受、哪些需要重跑或人工复查。
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
