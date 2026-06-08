# 在线大模型 API 接入设计

本项目后续会支持把部分本地大模型能力替换为在线大模型 API。接入原则是：统一 provider 抽象优先，不在 MinerU、PaddleOCR、截图成书、`structure_repair` 等具体管道里分别写供应商 API 调用。

当前状态：`online_providers.py` 已提供 provider 抽象、fake provider、OpenAI-compatible adapter、配置健康检查和离线契约测试。默认转换流程仍然 local-first，不会自动调用远程 API。

## 核心原则

- 本项目继续作为调度层、复查层、artifact 管理层和 agent 接口层。
- 在线模型只能通过统一 provider adapter 接入，不能让 UI、MCP、HTTP 或具体管道直接绑定某个供应商 SDK。
- 所有在线模型输出必须先归一化为项目内部 artifact，再交给后续转换、复查、索引或 agent 读取。
- 本地工具仍然是默认基础能力；在线 API 用于扫描页、复杂图文页、信息图、低置信度结构、表格/公式等疑难区域。
- API key 只通过环境变量或本地未提交配置读取，不写入文档、report、manifest、agent contract 或 Git 提交。

## Provider 抽象

`online_providers.py` 已定义以下接口：

- `ModelProvider`：读取 provider 名称、模型名、base URL、超时、并发、价格/限额策略和密钥环境变量名。
- `OcrLayoutProvider`：输入图片或 PDF 页，输出 OCR/layout blocks。
- `VlmLayoutProvider`：输入图片或 PDF 页和任务提示，输出结构化 Markdown、块列表或复查建议。
- `TextStructureProvider`：输入 Markdown 片段、候选 heading、领域 grammar 和质量问题，输出修复后的 Markdown 片段、决策列表和依据。
- `TableRepairProvider`：输入真实表格候选，输出修复后的 Markdown table、表格 JSON 和决策依据。
- `EmbeddingProvider`：输入文本块或图片说明，输出 embedding 向量和模型元数据。

## 配置草案

仓库已提供 [../config/online_models.example.json](../config/online_models.example.json) 作为配置模板，只保存 provider 配置和环境变量名，不保存密钥。真实 provider adapter 尚未实现；当前模板用于提前固定配置形状：

```json
{
  "default_mode": "hybrid",
  "providers": {
    "openai_compatible_vlm": {
      "type": "vlm_layout",
      "base_url": "https://example.com/v1",
      "model": "qwen-vl-ocr",
      "api_key_env": "VLM_API_KEY",
      "timeout_seconds": 120
    },
    "openai_compatible_text": {
      "type": "text_structure_llm",
      "base_url": "https://example.com/v1",
      "model": "gpt-4.1-mini",
      "api_key_env": "TEXT_LLM_API_KEY",
      "timeout_seconds": 60
    },
    "openai_compatible_embedding": {
      "type": "embedding",
      "base_url": "https://example.com/v1",
      "model": "text-embedding-model",
      "api_key_env": "EMBEDDING_API_KEY",
      "timeout_seconds": 30
    },
    "openai_compatible_table": {
      "type": "table_repair",
      "base_url": "https://example.com/v1",
      "model": "gpt-4.1-mini",
      "api_key_env": "TABLE_LLM_API_KEY",
      "timeout_seconds": 60
    }
  }
}
```

## 借鉴的开源项目模式

- Marker 模式：`llm_service` 可插拔，适合文本结构修复、表格修复和 Markdown 清洗。
- MinerU 模式：OpenAI-compatible remote VLM backend，适合把重模型移到云端或远程 GPU。
- PaddleOCR MCP 模式：同一个工具契约支持 local、official API、cloud platform、self-hosted，适合 agent 稳定调用。
- Docling 模式：先统一成 document object/artifact，再交给 LLM/RAG，不让 LLM 直接碰杂乱文件。

## 当前本地组件到在线 API 的映射

| 当前本地组件 | 在线 API 替代类型 | 接入策略 |
| --- | --- | --- |
| Umi-OCR / Tesseract | `OcrLayoutProvider` | 可替换，但保留本地 fallback。 |
| MinerU pipeline | `OcrLayoutProvider` + `VlmLayoutProvider` + 表格/公式 provider | 只在复杂 PDF 或扫描件启用在线替代，避免整本无差别调用。 |
| MinerU VLM / PaddleOCR-VL / Qwen-VL | `VlmLayoutProvider` | 作为疑难页、信息图、截图书补强层。 |
| Marker | `TextStructureProvider` 或在线文档解析 provider | 参考其 service 插拔模式，不直接复制供应商绑定。 |
| PyMuPDF / PyMuPDF4LLM | 不建议替换 | 继续本地运行，便宜、快、稳定。 |
| `structure_repair` | `TextStructureProvider` 补强 | 规则优先，LLM 只处理低置信度结构。 |
| `document_locator` | `EmbeddingProvider` / reranker 可选补强 | 默认仍使用本地 SQLite/FTS，在线 embedding 用于语义检索。 |

## 内部 Artifact 规范

- OCR/VLM 输出进入 `pages.jsonl` 或 `blocks.jsonl`。
- 结构修复输出进入 `structure_repair` report。
- 表格输出进入 `table_candidates.json` 或 Markdown table。
- embedding 输出进入定位索引数据库或可重建 sidecar 文件。
- 每次在线调用都记录 provider、model、输入页码、耗时、失败原因、fallback 状态和粗略成本风险。

## 默认调用策略

- `model_mode=local`：只使用本地工具。
- `model_mode=online`：优先使用在线 provider，但仍保留本地 fallback。
- `model_mode=hybrid`：本地预检和轻量解析优先，只把疑难页/疑难块发给在线 provider。
- `model_mode=auto`：根据依赖健康检查、隐私风险、成本风险、文档类型和质量评分自动选择。

默认推荐 `hybrid`：本地先做文件类型、页数、文本层、扫描比例、图片比例、目录/书签、疑难页比例预检；只有扫描页、复杂图文页、信息图、表格页、公式页、低置信度结构页才调用在线 API。

## Agent 接口约束

- Agent 仍然优先调用 `process_material`。
- Agent 不直接调用 OpenAI、Qwen、Claude、Gemini、Paddle 官方 API 或其他供应商 API。
- `process_material` 后续增加 `model_mode=local|online|hybrid|auto`。当前还不会自动调用在线 API。
- `health_check` 已暴露 online provider 配置健康和缺失密钥状态；真实连通性、预算和隐私确认仍待接入。
- `inspect_document` 后续返回 `online_api_recommended`、`estimated_pages`、`estimated_cost_risk` 和 `privacy_risk`。

## 开发顺序

1. 已完成：provider 抽象、fake provider 测试、OpenAI-compatible adapter、配置健康检查。
2. 下一步：扩展 `inspect_document`，返回 `online_api_recommended`、`estimated_pages`、`estimated_cost_risk` 和 `privacy_risk`。
3. 下一步：在 `structure_repair` 低置信度片段中可选调用 OpenAI-compatible `TextStructureProvider`。
4. 下一步：在信息图、PPT PDF、截图书疑难页中可选调用 OpenAI-compatible `VlmLayoutProvider`。
5. 下一步：接入 `OcrLayoutProvider`，用于云 OCR/layout 替代本地 OCR。
6. 下一步：接入 `EmbeddingProvider`，增强定位索引和语义检索。
7. 下一步：加入预算、并发、重试、超时、隐私确认和 report 记录。
