# 通用图文材料识别工具技术方向

## 决策结论

本项目的长期定位是：面向 AI agent 调用的通用图文材料识别工具，而不是单一电子书转换工具。

当前架构图、管道路由图和模块边界见 [ARCHITECTURE.md](ARCHITECTURE.md)。

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

## 在线大模型 API 接入路线

后续需要支持把本地大模型能力替换为在线大模型 API，但不改变本项目“调度层/复查层/agent 接口层”的定位。在线化不应让 agent 或 UI 直接调用供应商 API，而应通过统一 provider adapter 接入。

详细设计见 [ONLINE_MODEL_API_INTEGRATION.md](ONLINE_MODEL_API_INTEGRATION.md)。

### 需要的在线模型类型

最小可用组合：

- `ocr_layout`：OCR + layout API，返回文字、坐标、页码、阅读顺序和置信度。用于替代或补强 Umi-OCR、Tesseract、部分 MinerU OCR 能力。
- `vlm_layout`：视觉语言模型 API，用于信息图、复杂截图、扫描页、图文混排页、卡片式版面和低质量 OCR 页补强。用于替代或补强 MinerU VLM、PaddleOCR-VL、Qwen-VL。
- `text_structure_llm`：文本 LLM API，用于 Markdown 标题层级修复、目录对齐、页眉页脚/脚注噪声判断、结构化清洗说明。规则层仍应保留，LLM 只处理疑难段落或复查项。

增强组合：

- `table_parser`：表格识别 API，输出 Markdown table、HTML table 或 JSON table。只对明确表格块启用，不把横向卡片/对比块强行表格化。
- `formula_parser`：公式识别 API，输出 LaTeX。主要用于教材、论文和技术文档。
- `embedding`：文本/图文 embedding API，用于定位索引、相似页去重、截图排序、RAG 检索和跨材料聚类。
- `reranker`：检索重排 API，用于提升定位索引和 agent 查询结果质量。
- `router_classifier`：轻量分类/路由模型，用于判断输入是否为普通电子书、文字层 PDF、扫描 PDF、复杂图文页、表格页、截图书或信息图。

### 本地能力到在线 API 的映射

| 当前本地组件 | 在线 API 替代类型 | 建议策略 |
| --- | --- | --- |
| Umi-OCR / Tesseract | `ocr_layout` | 可替换，但保留本地 fallback。 |
| MinerU pipeline | `ocr_layout` + `vlm_layout` + `table_parser` + `formula_parser` | 只在复杂 PDF 或扫描件启用在线替代，避免整本无差别调用。 |
| MinerU VLM / PaddleOCR-VL / Qwen-VL | `vlm_layout` | 作为疑难页、信息图、截图书补强层。 |
| Marker | `ocr_layout` / `vlm_layout` / 文档解析 API | 可作为在线文档解析 provider 的一种实现。 |
| PyMuPDF / PyMuPDF4LLM | 不建议替换 | 继续本地运行，便宜、快、稳定。 |
| `structure_repair` | `text_structure_llm` 补强 | 规则优先，LLM 只处理低置信度结构。 |
| `document_locator` | `embedding` / `reranker` 可选补强 | 默认仍使用本地 SQLite/FTS，在线 embedding 用于语义检索。 |

### 统一接口设计要求

后续新增在线 API 接口时，应先实现 provider 抽象，而不是在 MinerU、截图成书、定位索引或 UI 中直接写供应商调用：

- `ModelProvider`：读取 provider 名称、模型名、base URL、超时、并发、价格/限额策略和密钥环境变量名。
- `OcrLayoutProvider`：输入图片/PDF 页，输出 `blocks`，字段包括 `text`、`bbox`、`page`、`block_type`、`confidence`、`reading_order`。
- `VlmLayoutProvider`：输入图片/PDF 页和任务提示，输出结构化 Markdown、块列表或复查建议。
- `TextStructureProvider`：输入 Markdown 片段、候选 heading、领域 grammar 和质量问题，输出修复后的 Markdown 片段、决策列表和依据。
- `EmbeddingProvider`：输入文本块或图片说明，输出 embedding 向量和模型元数据。

统一输出必须先转换为项目内部 artifact，而不是把供应商原始响应直接暴露给 UI/agent：

- OCR/VLM 输出进入 `pages.jsonl` 或 `blocks.jsonl`。
- 结构修复输出进入 `structure_repair` report。
- 表格输出进入 `table_candidates.json` 或 Markdown table。
- embedding 输出进入定位索引数据库或可重建的 sidecar 文件。

### 默认调用策略

- 本地轻量预检先运行：文件类型、页数、文本层、扫描比例、图片比例、目录/书签、疑难页比例。
- 有文本层的 PDF、EPUB、Office、HTML 继续优先走本地工具。
- 只有扫描页、复杂图文页、信息图、表格页、公式页、低置信度结构页才调用在线 API。
- 长文档必须支持分段、预算上限、超时、重试、fallback 和可恢复 manifest。
- 所有在线调用必须写入 provider、model、耗时、输入页码、token/图片数量估计、错误原因和 fallback 记录。
- 不把 API key 写入文档、report、manifest、Git 提交或 agent contract；只记录环境变量名。

### 后续 TODO

- `online_providers.py` 已提供 `OcrLayoutProvider`、`VlmLayoutProvider`、`TextStructureProvider`、`TableRepairProvider`、`EmbeddingProvider` 抽象，fake provider 测试，以及 OpenAI-compatible adapter。
- `config/online_providers.example.json` 模板已存在；旧命名 `config/online_models.example.json` 保留为兼容别名。`health_check` / agent contract 已能读取 provider health，`inspect_document` / `process_material` 已能返回 `online_enhancement` 推荐和风险字段，后续让实际管道按显式 `model_mode` 调用 provider。
- `run_online_enhancement` 已提供显式 fake/OpenAI-compatible 调用入口，覆盖 `ocr_layout`、`vlm_layout`、`text_structure`、`table_repair`、`embedding`，真实远程调用需要 `allow_remote=true`。
- 扩展 `health_check`，在已有 provider 配置/缺失密钥检测基础上增加可选真实连通性、预算和隐私风险检查。
- 扩展实际管道，在 `model_mode=hybrid|online|auto` 且用户确认成本/隐私风险后读取 `online_enhancement` 并调用 provider。
- 扩展 `process_material`，支持 `model_mode=local|online|hybrid|auto`。
- 为在线 OCR/VLM/结构修复输出增加 fixture 和 smoke test，先用 fake provider 保证契约稳定。

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
- 真实样本 benchmark 发现、批量评测、PDF 多管道对比和 HTTP agent 压测脚本。
- Tkinter UI，支持拖放、批量文件、定位索引和截图成书。

## 后续路线

优先级从高到低：

1. 用 `benchmarks/samples.local.json` 持续积累 20-50 个真实样本，定期跑 benchmark。
2. 基于 PDF 多管道对比结果，决定 Docling 是否对部分格式默认启用。
3. 扩展 `inspect_document`，逐步读取 Docling 的结构化预检信息。
4. 将 MinerU 保留为复杂文档增强后端，并继续完善分段、超时、复查报告。
5. 继续扩展 UI 的复查包、对比报告和推荐重跑按钮。
6. 继续扩展 `read_artifact`，覆盖更多 artifact 类型和安全读取策略。

## 非目标

- 不从零训练 OCR、layout、table、formula 模型。
- 不把 UI 作为核心依赖。
- 不让 agent 直接操作底层临时目录和模型缓存。
- 不追求一次自动完成所有复杂文档的 100% 正确结构，必须保留复查和人工修正路径。
