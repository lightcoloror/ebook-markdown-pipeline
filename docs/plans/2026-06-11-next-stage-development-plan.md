# 下一阶段开发计划：图文材料转换器

更新时间：2026-06-11 21:30:00

执行者：Codex GPT-5

## 当前判断

项目已经从“电子书转 Markdown 脚本”发展成可用的本地图文材料转换器，具备 UI、CLI、HTTP、MCP、质量报告、Agent handoff、PDF/图片/Office/电子书多管道路由等基础能力。

下一阶段不建议继续无边界地增加底层模型或解析器，而应优先把当前调度层做稳：未完成改动收口、质量回归固定、Agent 调用稳定、可选增强后端插件化。

## 阶段 0：先收口当前未完成改动

目标：在继续开发前，让 main 分支重新回到可测试、可提交、可解释的状态。

任务：

- 完成 `batch_convert_books.py` 中 PDF layout 复查信号的辅助函数，避免当前半成品改动造成运行时报错。
- 给 PDF layout review checklist 加单元测试，覆盖疑似表格页、双栏页、页眉页脚噪声和 artifact 提示。
- 明确 pdfplumber/Camelot 的边界：只做诊断、表格候选 artifact、复查建议，不作为默认 PDF-to-Markdown 主转换器。
- 跑核心测试和最小质量门禁，确认未破坏 CLI、MCP、HTTP contract。
- 单独提交这一批收口改动，提交信息建议：`feat: surface pdf layout review signals`。

涉及文件：

- `batch_convert_books.py`
- `pdf_layout_diagnostics.py`
- `scripts/test_pdf_layout_diagnostics.py`
- `scripts/test_pdf_layout_review_checklist.py`
- `docs/TOOL_CONTRACT.md`

验收标准：

- `python scripts/test_pdf_layout_review_checklist.py` 通过。
- `python scripts/test_pdf_layout_diagnostics.py` 通过。
- `python scripts/test_agent_fast_contract.py` 通过。
- `python scripts/test_docs_contract.py` 通过。
- `git diff --check` 无空白错误。

## 阶段 1：可选后端补齐但不扩大默认复杂度

目标：继续遵守“工具优先、只做调度粘合层”的原则，把 OCRmyPDF、MarkItDown、pdfplumber 等后端收成稳定可选能力。

任务：

- OCRmyPDF：保留为 `pdf_pipeline_mode=ocrmypdf`，用于生成 searchable PDF，再交给快速文本层转换；原文件永不覆盖。
- MarkItDown：保留为 baseline comparison backend，不作为默认高质量转换管道。
- pdfplumber/Camelot：输出 `table-diagnostics.json`、CSV、Markdown 表格候选，用于复查和专项抽取。
- RapidOCR：作为可选 OCR provider 接入，先提供 health/capability 和 fake-provider 测试，再接真实路径。
- 在线模型 API：先做 provider 抽象和 fake provider，不急着绑定具体供应商。

涉及文件：

- `markitdown_backend.py`
- `ocrmypdf_preprocessor.py`
- `pdf_layout_diagnostics.py`
- `online_providers.py`
- `config/online_providers.example.json`
- `docs/ONLINE_MODEL_API_INTEGRATION.md`

验收标准：

- 未安装可选后端时，health 报告为 optional missing，不阻塞默认工作流。
- 安装后端时，CLI/UI/HTTP/MCP 都通过同一个 core function 调用，不复制逻辑。
- 每个可选后端至少有一个 missing-dependency 测试和一个 fake/smoke 测试。

## 阶段 2：质量评估变成固定回归

目标：项目的核心价值不只是“能转”，而是“知道转得好不好”。下一阶段要把质量判断从经验规则变成可重复回归。

任务：

- 建立公开 fixture 集，不使用版权书，覆盖 EPUB、FB2、TXT、RTF、ODT、文本层 PDF、扫描 PDF、双栏 PDF、图片信息图、PPT 导出 PDF。
- 固定质量指标：成功率、标题数量、目录匹配率、页码/脚注噪声、OCR 字符量、review/poor 数、运行时间、fallback 是否合理。
- 增加 `python scripts/run_quality_gate.py`，支持 minimal、backend-compare、full 三档。
- 将私人真实样本评测继续保留在本地未提交 manifest，不进入公开仓库。

涉及文件：

- `fixtures/`
- `scripts/run_quality_gate.py`
- `scripts/quality_metrics.py`
- `docs/REAL_SAMPLE_EVALUATION_STATUS.md`

验收标准：

- 最小 fixture 可在普通开发机 3 分钟内跑完。
- 每次质量门禁输出机器可读 JSON 和人类可读 Markdown。
- 回归结果能指出具体失败文件、管道、原因和建议下一步。

## 阶段 3：PDF / 图片结构质量增强

目标：先提升结构与复查能力，不盲目堆模型。

任务：

- PDF 结构增强：读取 PDF bookmark、目录页、字体大小、标题位置，修复 Markdown 标题层级。
- PDF layout 复查：把双栏页、表格页、图片重页、页眉页脚噪声写入 report 和 review checklist。
- 图片/信息图：默认只识别，不进入定位索引；疑似 layout-heavy 时再建议 PaddleOCR-VL、Qwen-VL、MinerU VLM 补强。
- 结构修复 report：记录哪些行被提升为标题、为什么提升、置信度、触发信号。
- 表格处理：只对真实表格转 Markdown table，不把横向卡片、对比块、步骤块强行表格化。

涉及文件：

- `structure_repair.py`
- `pdf_outline.py`
- `pdf_layout_diagnostics.py`
- `image_book_rebuilder.py`
- `book_converter_ui.py`

验收标准：

- 对文本层 PDF 能利用 bookmark/目录页辅助生成层级。
- 图片默认路径是识别 Markdown，不要求用户理解 location index。
- report 能解释结构修复决策，而不是只给最终 Markdown。

## 阶段 4：Agent 调用产品化

目标：让 OpenClaw、Hermes Agent、Codex 等外部 Agent 稳定调用，不需要猜命令、猜端口、猜输出路径。

任务：

- 固定三种入口：CLI 给人类和批处理，HTTP 给 Docker/跨进程，MCP 给支持 tool schema 的 Agent。
- `/health` 返回配置来源、端口、可用管道、可选后端状态、模型/GPU/OCR 风险。
- `process_material` 返回更稳定的 `next_actions`，包括失败重跑、review 重跑、pipeline compare、read_report、read_artifact。
- 每次任务生成 `run_summary.md`，方便其他会话接手。
- 增加 `examples/agent-recipes/`：单文件识别、批量文件夹、失败重跑、复查清单、Docker agent 调用。

涉及文件：

- `ebook_converter_mcp_server.py`
- `http_server.py`
- `agent_contract.py`
- `scripts/agent_batch_template.*`
- `examples/agent-recipes/`
- `docs/AGENT_INTEGRATION.md`
- `docs/TOOL_CONTRACT.md`

验收标准：

- Agent 不需要读取 UI 状态即可完成一次识别任务。
- 所有长任务都有 job id、status、progress、artifacts、errors、next_actions。
- 失败任务能通过机器可读参数自动重跑，而不是靠人读日志猜。

## 阶段 5：开源可用性与 U 盘分发边界

目标：让外部用户能用最小路径跑起来，同时把商业/私有资料和公开仓库边界分清。

任务：

- 保持 README 顶部的 5 分钟上手路径：clone、install、start UI、batch CLI。
- 继续清理公开仓库里的私人绝对路径，只保留泛化示例。
- `docs/INSTALLATION.md` 分成最小可用、PDF 增强、本地大模型/VLM、Agent/API 四档。
- `THIRD_PARTY_NOTICES.md` 和 `docs/OPEN_SOURCE_PROJECT_INVENTORY.md` 保持更新，列出直接集成、可选集成、参考但未集成项目。
- 商业化建议、U 盘分发策略、私人样本评测留在本地文档，不提交公开仓库。

涉及文件：

- `README.md`
- `docs/INSTALLATION.md`
- `THIRD_PARTY_NOTICES.md`
- `docs/OPEN_SOURCE_PROJECT_INVENTORY.md`
- `.gitignore`

验收标准：

- 新用户按 README 可以完成最小安装和一次转换。
- 公开仓库不包含本机路径、私人样本、商业策略、token、模型缓存。
- 可选重后端不会让用户误以为必须一次装齐。

## 建议执行顺序

1. 先完成阶段 0，把当前半成品代码收口并提交。
2. 再做阶段 2 的最小 fixture 和质量门禁，因为它会保护后续所有改动。
3. 然后推进阶段 3 的 PDF/图片结构增强，这是最能改善用户实际输出质量的部分。
4. 同步推进阶段 4 的 Agent contract，但每次只增加可测试字段，不破坏既有 JSON。
5. 阶段 1 和阶段 5 穿插做：每接一个可选后端，就补 health、docs、tests、license boundary。

## 不建议现在做的事

- 不建议把 MinerU、PaddleOCR、Qwen-VL 等上游项目代码 vendoring 到本仓库。
- 不建议把 UI 做成复杂控制台，普通入口仍应是“扫描、按推荐执行、查看结果”。
- 不建议默认调用在线大模型 API；在线能力应保持 local-first 之后的显式增强。
- 不建议把私人商业化计划、真实版权书评测、个人路径配置提交到公开仓库。

