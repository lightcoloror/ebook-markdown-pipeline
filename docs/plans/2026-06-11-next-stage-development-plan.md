# 下一阶段开发计划：图文材料转换器

更新时间：2026-06-11 12:12:57

执行者：Codex GPT-5

## 当前判断

项目已经从“电子书转 Markdown 脚本”发展成可用的本地图文材料转换器，具备 UI、CLI、HTTP、MCP、质量报告、Agent handoff、PDF/图片/Office/电子书多管道路由等基础能力。

下一阶段不建议继续无边界地增加底层模型或解析器，而应优先把当前调度层做稳：固定质量回归、增强结构修复、稳定 Agent 调用、把在线模型 API 做成可选 provider，而不是把供应商接口散落到各模块。

## 已完成的近期收口

- MarkItDown 已作为可选 baseline backend 接入，用于快速对比和低成本 Markdown 形态检查，不作为默认高质量管道。
- OCRmyPDF 已作为可选扫描 PDF 预处理后端接入，边界是生成 searchable PDF 后再交给现有 PDF 转换链。
- pdfplumber/Camelot 方向已收束为 PDF layout diagnostics、表格候选和复查信号，不作为默认 PDF-to-Markdown 主转换器。
- RapidOCR 已作为可选 image OCR provider 接入，并开始支持与 Umi-OCR 的 provider comparison benchmark。
- 公开质量 fixture 已开始覆盖 OCR provider 分类，当前正在补 PDF 表格 fixture 与表格保留率指标。
- `run_quality_gate.py --profile backend-compare` 已改为三段式：默认 baseline、MarkItDown candidate、`backend-comparison/benchmark-quality-comparison.*` 差异报告。
- README、安装文档、开源项目清单、架构图、Agent contract 已经具备对外解释基础，但仍需要持续压缩本机化痕迹和降低新用户上手成本。

## P0：完成当前未提交质量回归改动

目标：让 main 分支重新回到“可测试、可解释、可推送”的状态。

任务：

- 收口当前 PDF table fixture 和 `table_retention_ratio` 指标。
- 在 benchmark comparison 里加入表格保留率对比，避免只在单次 summary 里可见。
- 恢复因重新生成 fixture 而产生的无意义二进制漂移，只保留必要的新表格 fixture 和 manifest 变更。
- 跑核心测试：质量门禁、benchmark 工具、docs contract、diff check。
- 单独提交并推送，建议提交信息：`test: add table retention quality metric`。

涉及文件：

- `scripts/generate_quality_fixtures.py`
- `scripts/run_benchmarks.py`
- `scripts/compare_benchmark_quality.py`
- `scripts/test_quality_gate.py`
- `scripts/test_benchmark_tools.py`
- `benchmarks/fixtures/generated/quality-full.json`
- `benchmarks/fixtures/generated/pdf/table.pdf`
- `README.md`
- `docs/AGENT_INTEGRATION.md`

验收标准：

- `python scripts/test_quality_gate.py` 通过。
- `python scripts/test_benchmark_tools.py` 通过。
- `python scripts/test_docs_contract.py` 通过。
- `git diff --check` 通过。
- `git status --short` 只包含预期文件，且已提交推送。

## P1：把质量评估做成固定回归

目标：项目的核心价值不只是“能转”，而是“知道转得好不好”，并且每次改动都能量化风险。

任务：

- 固定公开 fixture 集，不使用版权书，覆盖 EPUB、FB2、TXT、RTF、ODT、文本层 PDF、扫描 PDF、双栏 PDF、表格 PDF、图片信息图、PPT 导出 PDF。
- 固定质量指标：成功率、标题数量、目录匹配率、页码/脚注噪声、OCR 字符量、review/poor 数、运行时间、fallback 是否合理、表格保留率。
- 将 `python scripts/run_quality_gate.py --profile minimal` 作为普通开发前后必跑命令。
- 维护 `backend-compare` 和 `full` 两档，用于改 PDF/OCR/结构修复时跑更完整的回归。
- 保持私人真实样本评测为本地未提交 manifest，不进入公开仓库。

涉及文件：

- `scripts/run_quality_gate.py`
- `scripts/run_benchmarks.py`
- `scripts/compare_benchmark_quality.py`
- `benchmarks/fixtures/generated/`
- `docs/REAL_SAMPLE_EVALUATION_STATUS.md`

验收标准：

- minimal fixture 可在普通开发机 3 分钟内跑完。
- 每次质量门禁输出机器可读 JSON 和人类可读 Markdown。
- comparison report 能直接指出候选版本相对 baseline 的退化指标。
- 新增质量指标必须先进入测试，再进入 README/Agent docs。

## P2：PDF / 图片结构质量增强

目标：先提升结构和复查能力，不盲目堆模型。

任务：

- PDF 结构增强：读取 PDF bookmark、目录页、字体大小、标题位置，辅助修复 Markdown 标题层级。
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
- 表格 fixture 能捕捉“表格丢成纯文字”的退化。

## P3：在线模型 API 抽象

目标：支持在线大模型增强，但保持 local-first，避免项目变成“没有 key 就不能用”。

任务：

- 不在 MinerU、PaddleOCR、截图书、structure repair 等模块里直接写供应商 API。
- 统一 provider 抽象：`OcrLayoutProvider`、`VlmLayoutProvider`、`TextStructureProvider`、`EmbeddingProvider`。
- 先做 fake provider 测试，再接 OpenAI-compatible API。
- 第一批在线能力只覆盖：文本结构修复、图片/信息图 VLM 补强、表格修复。
- 所有远程调用必须有显式开关、隐私/成本提示、artifact 记录和失败降级。

涉及文件：

- `online_providers.py`
- `config/online_providers.example.json`
- `scripts/test_online_providers.py`
- `docs/ONLINE_MODEL_API_INTEGRATION.md`
- `docs/TOOL_CONTRACT.md`

验收标准：

- 未配置 API key 时，health 只报告 optional missing，不阻塞本地识别。
- fake provider 覆盖每类 provider 的输入输出 schema。
- Agent 只能通过项目工具触发在线增强，不能绕过 provider 抽象直接调用供应商 API。

## P4：Agent 调用产品化

目标：让 OpenClaw、Hermes Agent、Codex 等外部 Agent 稳定调用，不需要猜命令、猜端口、猜输出路径。

任务：

- 固定三种入口：CLI 给人类和批处理，HTTP 给 Docker/跨进程，MCP 给支持 tool schema 的 Agent。
- `/health` 返回配置来源、端口、可用管道、可选后端状态、模型/GPU/OCR 风险。
- `process_material` 返回更稳定的 `next_actions`，包括失败重跑、review 重跑、pipeline compare、read_report、read_artifact。
- 每次任务生成 `run_summary.md`，方便其他会话接手。
- 增加 agent batch 模板：单文件识别、批量文件夹、失败重跑、复查清单、Docker agent 调用。

涉及文件：

- `ebook_converter_mcp_server.py`
- `ebook_converter_http.py`
- `agent_contract.py`
- `examples/agent-recipes/`
- `examples/agent-batch/`
- `docs/AGENT_INTEGRATION.md`
- `docs/TOOL_CONTRACT.md`

验收标准：

- Agent 不需要读取 UI 状态即可完成一次识别任务。
- 所有长任务都有 job id、status、progress、artifacts、errors、next_actions。
- 失败任务能通过机器可读参数自动重跑，而不是靠人读日志猜。
- Docker/OpenClaw/Hermes 场景至少有一个可重复 smoke 测试。

## P5：UI 和便携分发体验

目标：让普通用户默认只看到“识别、查看、按建议处理”，把复杂控制收进高级设置。

任务：

- UI 默认路径是“只识别”，定位索引作为单独功能，不再误触。
- 输出路径默认使用源文件旁边的版本化命名，避免覆盖旧输出。
- 任务完成弹窗、失败原因复制、打开输出/报告/日志继续保持可见。
- 高级按钮只保留诊断、复查、人工重跑、环境检查，不作为日常入口。
- 便携/U 盘分发只包含项目代码、启动脚本、许可说明和可选依赖说明；私人商业化策略、本机路径、版权样本不进入公开仓库。

涉及文件：

- `book_converter_ui.py`
- `launch_ui.cmd`
- `config.example.env`
- `docs/INSTALLATION.md`
- `THIRD_PARTY_NOTICES.md`

验收标准：

- 新用户按 README 可以完成最小安装和一次转换。
- 公开仓库不包含本机路径、私人样本、商业策略、token、模型缓存。
- 可选重后端不会让用户误以为必须一次装齐。

## 建议执行顺序

1. 先完成 P0，把当前质量回归改动提交推送。
2. 立即推进 P1，因为质量门禁会保护后续所有 PDF/OCR/结构修复改动。
3. 再做 P2，优先解决“输出没有层级、表格丢失、信息图结构差”这些真实痛点。
4. P3 只做 provider 抽象和 fake tests，等 schema 稳定后再接具体供应商。
5. P4 和 P5 穿插做，每次新增能力都同时补 UI/CLI/HTTP/MCP 的最小一致入口。

## 暂不建议做的事

- 不建议把 MinerU、PaddleOCR、Qwen-VL 等上游项目代码 vendoring 到本仓库。
- 不建议把 UI 做成复杂控制台，普通入口仍应是“扫描、按推荐执行、查看结果”。
- 不建议默认调用在线大模型 API；在线能力应保持 local-first 之后的显式增强。
- 不建议把私人商业化计划、真实版权书评测、个人路径配置提交到公开仓库。
