# 通用图文材料识别工具技术方向

## 决策结论

本项目的长期定位是：面向 AI agent 调用的通用图文材料识别工具，而不是单一电子书转换器。

核心策略：

- 以本项目作为稳定调度层、复查层、artifact 管理层和 agent 接口层。
- 以 Docling 作为未来默认通用文档理解后端。
- 以 MinerU 作为复杂 PDF、中文扫描件、复杂版面、表格、公式和结构化 Markdown/JSON 的增强后端。
- 以 Umi-OCR/PaddleOCR 作为本地图片 OCR 和扫描件 fallback。
- 以 Marker 作为 PDF 到 Markdown 的高质量备选后端。
- 保留 Pandoc/Calibre 作为电子书和传统文档格式转换底座。

## 为什么不是只选一个工具

“通用图文材料识别”不是单一 OCR 问题。它至少包含：

- 文件格式识别。
- PDF 文本层读取。
- 扫描件 OCR。
- 图片 OCR。
- 版面分析。
- 阅读顺序恢复。
- 表格和公式识别。
- 标题层级识别。
- 重复页、乱序页、缺页和跨页内容复查。
- Markdown/JSON/SQLite/report 等多种 artifact 输出。
- AI agent 可稳定调用的 CLI/MCP/HTTP 接口。

现有开源工具各有强项，但没有一个完全覆盖所有本地工作流、人工复查和 agent 稳定调用需求。因此本项目不重复造底层识别模型，而是做工具优先的集成和调度层。

## 后端工具分工

### Docling

定位：默认通用文档理解后端。

适合：

- 多格式文档解析。
- PDF、Office、HTML、图片等通用输入。
- Markdown、HTML、JSON 输出。
- 表格、阅读顺序、版面结构、OCR 和 agent 集成。
- 需要 MIT 许可证友好、生态较完整的场景。

项目策略：

- 已作为可选后端接入 `inspect_document` 和转换路由；未安装时 health/check 会明确提示。
- 当前先覆盖 DOCX、PPTX、XLSX、HTML、Markdown、CSV，并允许 PDF 手动选择 `docling` 管道。
- 后续再评估是否把 Docling 升为通用默认后端。
- 保持输出 artifact schema 与现有 MCP/HTTP/CLI 一致。

### MinerU

定位：复杂文档增强后端。

适合：

- 中文复杂 PDF。
- 扫描件。
- 多栏版面。
- 表格、公式、页眉页脚、脚注、跨页表格。
- 需要 LLM/RAG/Agent-ready Markdown/JSON 的场景。

项目策略：

- 继续作为复杂 PDF 高质量管道。
- 对长文档继续保留超时、分段、fallback 和复查报告。
- VLM/hybrid 模式作为高质量增强，不作为默认轻量模式。

### Umi-OCR / PaddleOCR

定位：本地 OCR fallback。

适合：

- 图片批量 OCR。
- 扫描版 PDF 的快速 OCR。
- 截图成书重建。
- 需要离线、本地、可控的中文 OCR 场景。

项目策略：

- 继续作为图片定位索引和截图成书的 OCR 后端。
- OCR 结果必须写入 `pages.jsonl` 或类似中间文件，便于复查和重跑。

### Marker

定位：高质量 PDF Markdown 备选后端。

适合：

- 对 Markdown 可读性要求高的 PDF。
- 技术文档、论文、带公式/表格的文档。
- 可以接受模型下载、GPU 或较长耗时的场景。

项目策略：

- 不作为长文档默认后端。
- 保留超时、失败回退和日志。

### Pandoc / Calibre

定位：传统格式转换底座。

适合：

- EPUB、AZW、MOBI、FB2、TXT、RTF、ODT 等电子书和文本格式。
- 原始文档已有结构，主要目标是格式转换和 Markdown 清洗。

项目策略：

- 继续作为电子书转换主路径。
- 对 EPUB/AZW3 优先利用 TOC 信息增强标题层级。

## 对外能力边界

最终稳定能力应收敛为以下工具，而不是让 agent 直接调用底层 OCR/PDF 库：

- `inspect_document`：预检输入类型、页数、文本层、扫描比例、图片比例、推荐管道和风险。
- `convert_document`：把电子书、PDF、Office、HTML 等转换为 Markdown/HTML/Text。
- `build_location_index`：对 PDF/图片建立页级/图级搜索索引。
- `query_location_index`：查询关键词在哪个 PDF 页或哪张图片。
- `rebuild_image_book`：从乱序、重复、局部重叠截图重建 Markdown 草稿。
- `health_check`：检查依赖、模型、GPU、OCR、外部命令。
- `read_artifact`：读取报告、日志、Markdown、JSONL、SQLite 查询结果等 artifact。
- `process_material`：agent 默认高层入口，自动预检并分流到转换、定位索引或截图成书重建。

## 接口优先级

稳定性优先级：

1. Python core functions：唯一业务逻辑来源。
2. CLI：最稳定、最通用、便于脚本和 Docker 调用。
3. MCP：AI agent 原生入口。
4. HTTP bridge：跨容器、跨语言和远程 agent 调用入口。
5. UI：人工操作、拖放、配置和复查入口。

约束：

- CLI/MCP/HTTP/UI 必须复用同一层 Python core functions。
- 不允许在 agent 插件或 UI 里复制转换逻辑。
- 对外 JSON 字段只能新增，避免删除或重命名。
- 所有长任务必须支持进度、日志、错误、artifact 路径和可复查报告。

## Artifact 标准

所有工具应尽量返回统一字段：

- `status`
- `input`
- `output`
- `artifacts`
- `warnings`
- `errors`
- `report`
- `logs`

当前最小实现为 `artifact-schema-v1`，已接入 `start_conversion`、`build_location_index` 和 `rebuild_image_book`。新工具应优先复用同一 schema，旧工具在保持兼容的前提下逐步补齐。

常见 artifact 类型：

- `markdown`
- `html`
- `text`
- `location_index_sqlite`
- `location_index_jsonl`
- `pages_jsonl`
- `order_report`
- `review_report`
- `clusters_json`
- `tool_log`
- `health_report`

## 当前项目已覆盖

当前已经具备：

- 电子书和 PDF 转 Markdown/HTML/Text。
- PDF 预检和多管道选择。
- Marker/MinerU 超时日志和 fallback。
- Umi-OCR PDF/图片 OCR fallback。
- PDF/图片页级定位索引。
- 关键词查询定位到 PDF 页或图片。
- 乱序截图成书重建。
- Docling 可选后端路由。
- MCP stdio server。
- HTTP bridge。
- `process_material` 高层 agent 路由入口。
- `read_artifact` 和统一 artifact schema。
- Dockerfile、docker compose 示例和固定 `/health` / `/tools` / `/call` HTTP 接口。
- Tkinter UI，支持拖放、批量文件、定位索引和截图成书。

## 后续路线

优先级从高到低：

1. 继续评估 Docling 真实样本效果，再决定是否升为通用默认后端。
2. 扩展 `inspect_document`，逐步读取 Docling 的结构化预检信息。
3. 将 MinerU 保留为复杂文档增强后端，并继续完善分段、超时、复查报告。
4. 将 `rebuild_image_book` 的排序结果支持人工修正后重跑。
5. 为 OpenClaw、Hermes Agent、Codex 等 agent 提供更完整的真实样例和失败恢复样例。
6. 继续扩展 `read_artifact`，覆盖更多 artifact 类型和安全读取策略。

## 非目标

- 不从零训练 OCR、layout、table、formula 模型。
- 不把 UI 作为核心依赖。
- 不让 agent 直接操作底层临时目录和模型缓存。
- 不追求一次自动完成所有复杂文档的 100% 正确结构，必须保留复查和人工修正路径。
