# 服务契约与模块降级链

更新时间：2026-07-16 Asia/Shanghai
执行者：Codex（GPT-5）

## 当前结论

- 项目真实路径：`D:\used-by-codex\ebook_markdown_pipeline`。
- 当前 HTTP 配置源：`config/http.env`；配置 URL 为 `http://127.0.0.1:9241`。
- `8765` 是过期契约观察值，不是当前权威端口。`8765` 未监听不能证明项目故障。
- 本轮只读检查中，`8765` 与 `9241` 都未监听。HTTP 是按需 adapter 且 `auto_start=false`，普通本机任务状态为 `stopped-by-design`；只有 Docker/OpenClaw 明确需要 HTTP 时才是 `needs_manual_start`。
- CLI health 为 `degraded_optional`、`minimal_ok=true`。核心 EPUB/Office、文本层 PDF、Marker、RapidOCR、MarkItDown 路径可用；可选缺失项不阻塞核心 CLI。
- MinerU 命令、模型缓存和 CUDA 可用，但固定 API `http://127.0.0.1:8000` 当前为 `stopped`。MinerU 的有效状态是 `needs_manual_start`，而不是可立即执行；禁止退回上游隐式临时 API。
- Docling 因 `tokenizers` 版本冲突不可用；PaddleOCR、Surya、GMFT/Table Transformer 未准备好。GMFT、pdf_table、table_to_xlsx 保持 candidate-only 的 `plan/fake` 状态，不下载模型。

## 统一只读状态入口

```powershell
python scripts\check_dispatch_contract.py
```

输出 schema 为 `ebook-dispatch-contract-v1`，包含项目路径、端口判定、入口状态、模块有效状态、确定性路由、失败分类、人工审核条件，以及 OpenClaw、Telegram、Local Tools、总控台的消费方式。该命令不启动 HTTP/MinerU、不下载模型、不转换文档。

任务明确只能通过 HTTP 调用时，使用：

```powershell
python scripts\check_dispatch_contract.py --require-http
```

## 入口发现顺序

| 调用方 | 首选入口 | HTTP 未监听时 | 状态口径 |
| --- | --- | --- | --- |
| Windows OpenClaw/Codex/Claude | `start_mcp.cmd` 的 stdio MCP | 改用本机 CLI 和 artifact handoff | `ready` 或 `degraded` |
| Docker OpenClaw/Hermes | 配置端口对应的 `host.docker.internal` HTTP | 请求人工启动 HTTP，或宿主机 CLI/MCP 处理后交付结果 artifact | `needs_manual_start` |
| Telegram | 只作为消息/任务入口，不作为解析后端 | 返回 route plan 或人工启动请求；不自动发送、不自动启动 | `plan_only` |
| Local Tools | `local-tools.ps1 discover ebook_markdown_pipeline` | 调统一 contract 后选择 MCP/CLI | 不猜端口 |
| 本机总控台 | 读取 `ebook-dispatch-contract-v1` | 显示状态与 fallback，不执行启动 | `read_only` |

## 模块职责与当前有效状态

| 模块 | 职责 | 本轮状态 | 降级规则 |
| --- | --- | --- | --- |
| PyMuPDF4LLM | 文本层 PDF 快速 Markdown | `ready` | 空输出/质量失败转 MarkItDown、短篇 Marker 或复杂 PDF 路由 |
| MinerU | 复杂 PDF 结构恢复 | `needs_manual_start` | 固定 API 停止时跳过，转 Marker/PyMuPDF4LLM；绝不隐式启动临时 API |
| Marker | 短篇、版式复杂 PDF | `ready` | 超时/质量失败转 PyMuPDF4LLM；长文档不作为默认 |
| Docling | 结构化文档/PDF 对比与 provenance | `missing` | 依赖冲突时用 Pandoc/MarkItDown；不自动修包 |
| RapidOCR | 轻量图片 OCR fallback | `ready` | OCR 字符量低或结构丢失时必须人工复核 |
| PaddleOCR | 扫描/照片表格、图片布局候选 | `missing` | 不下载模型；当前仅保留计划，RapidOCR 只能抢救文本 |
| Surya | OCR、layout、reading order 专项 | `missing` | 不下载模型；公式/阅读顺序交人工复核 |
| pdfplumber | PDF 表格/版面诊断 | `ready` | 只作为诊断证据，不冒充最终结构恢复 |
| GMFT/Table Transformer | 文本层 PDF 表格候选 | `planned_only` | 仅 plan/fake；模型/runtime 未人工准备前不 execute |
| pdf_table | 历史重型表格对比 | `planned_only` | 只在明确实验中使用，不进入整本默认路由 |
| table_to_xlsx | 扫描表格到 XLSX 草稿 | `planned_only` | 未就绪时不可宣称恢复真实单元格；XLSX 永远需人工验收 |

## 确定性路由摘要

| 材料 | 首选 | 次级 | 人工审核闸门 |
| --- | --- | --- | --- |
| EPUB/Office/文本 | Pandoc/Calibre | MarkItDown；Docling 修复后显式比较 | 标题、图片、表格明显缺失 |
| 普通文本层 PDF | PyMuPDF4LLM | MarkItDown；短篇版式问题转 Marker | 阅读顺序、表格/公式、低文本覆盖 |
| 复杂版式 PDF | MinerU（API ready 时） | Marker（短篇）→ PyMuPDF4LLM → MarkItDown | fallback 丢版式、多栏冲突、公式/表格不完整 |
| 扫描/图片 PDF | MinerU（API ready 时） | RapidOCR 页图 OCR → 短篇 Marker 比较 | OCR 量低、页序不确定、手写/公式/表格 |
| 文本层表格 PDF | PyMuPDF4LLM + pdfplumber | GMFT 仅候选实验；pdf_table 仅历史比较 | 合并单元格、边界冲突、卡片误检 |
| 拍照/扫描 Excel 表 | PaddleOCR 结构路线（当前未就绪） | RapidOCR 仅抢救文本；table_to_xlsx 仅候选草稿 | 始终人工验收，尤其公式、合并格、旋转文本、样式 |

完整 route、每步有效状态和失败分类以统一 JSON 为准，本文不复制运行时状态。

## Source ledger 与共享 registry

- `SOURCE_INVENTORY.json` 已有 MinerU、Docling、Marker、PaddleOCR、Surya、PyMuPDF4LLM 的本地源码记录，无需重复 clone。
- 本轮未找到 GMFT、Table Transformer、OpenDataLoader PDF 的 ledger 条目；精确 proposal 在 `SOURCE_LEDGER_ROUTING_PROPOSAL_2026-07-16.json`，不直接写共享账本。
- `tool-registry.json` 已正确声明项目路径、`config/http.env`、`stopped-by-design` 和 `auto_start=false`，但尚未登记统一 dispatch CLI。精确 proposal 在 `HTTP_STATUS_DISCOVERY_PROPOSAL.json`，由 Local Tools owner 决定是否合并。
