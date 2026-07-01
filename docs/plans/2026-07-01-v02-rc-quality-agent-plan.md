# v0.2 RC 收口、质量队列与 Agent 工作流计划

更新时间：2026-07-01 10:19:51
更新工具/模型：Codex GPT-5

## 背景

当前项目已经具备多格式转换、PDF/OCR 多管道、质量报告、质量队列、HTTP/MCP/CLI 入口和在线 provider 抽象。下一阶段重点不是继续接更多本地大模型，而是把当前改动收口，并让真实质量问题稳定进入可复现、可解释、可回退的改进队列。

默认策略保持不变：local-first。重后端、在线 API、GPU/VLM 都是显式增强；HTTP 是 on-demand bridge，CLI/MCP 是稳定入口。

## P0：当前工作树收口

目标：先让当前 dirty 状态变成可验证、可提交、可回滚的 v0.2 RC 基线。

待完成动作：

- 审查 dirty 内容，只允许源码、文档、测试进入提交；不提交真实电子书、PDF/图片样本、OCR/VLM 缓存、模型权重、API key、商业化材料。
- 当前 dirty 分为三组：运行稳定性修复、RapidOCR runtime/兼容修复、Unlimited-OCR 暂缓决策文档。
- 轻量验证优先使用不依赖重模型和不依赖本机 `tempfile.TemporaryDirectory` 的命令。
- `test_rapidocr_provider.py` 依赖 `tempfile.TemporaryDirectory`，当前 Codex sandbox 下会卡住或拒写；在可见 PowerShell/正常终端里再跑完整脚本。

已验证命令：

```powershell
python scripts\test_docs_contract.py
python scripts\check_public_release.py
python -m py_compile batch_convert_books.py image_book_rebuilder.py ocr_providers.py scripts\check_project_readiness.py scripts\paddleocr_vl_image_to_md.py scripts\run_benchmarks.py scripts\test_rapidocr_provider.py
```

下一步验证命令：

```powershell
python scripts\test_rapidocr_provider.py
python scripts\run_quality_gate.py --profile minimal --sample-timeout 60 --no-update-latest
git diff --check
```

提交建议：

1. `fix: make subprocess output decoding utf-8 safe on windows`
2. `fix: report rapidocr runtime device readiness`
3. `docs: record unlimited-ocr as deferred heavy backend candidate`
4. `docs: add v0.2 rc quality and agent plan`

## P1：质量队列驱动真实改进

目标：后续开发不再以“想接哪个后端”为中心，而是以 poor/review 项的可复现质量问题为中心。

固定分类：

- `structure_repair`：标题层级弱、中文编号父子关系错误、目录与正文标题不对齐。
- `ocr_cleanup`：页眉页脚、页码、重复行、断行、低置信度短行。
- `markdown_cleanup`：HTML 残留、目录残留、注释/脚注混入正文。
- `table_layout_review`：真实表格丢失、表格被拆散、横向卡片被误判为表格。
- `manual_review`：模型/规则都不确定，需要人工对比原图或 PDF 页。

执行规则：

- 公开仓库只放自造或开源 fixture；真实版权样本只保留在本地未提交 manifest。
- 每个规则修复必须留下证据：fixture 或本地样本编号、修复前问题、修复后变化、是否影响 minimal/release gate。
- `structure_repair` report 继续记录：哪些行被提升、降级、删除、合并，原因、置信度、是否需要人工复查。
- 优先修规则层，不先换后端；只有规则层无法解决时才进入 provider compare。

下一批具体修复候选：

1. 中文编号层级：`第五条` 下的 `（一）`、`（二）` 应自动降为子标题。
2. OCR 短行合并：连续短行、页脚页码、重复页眉的删除/合并要写入 report。
3. 目录残留：早期目录页内容不应污染正文结构。
4. 表格判定：只转换真实表格，不把横向卡片、步骤块、对比块强行转 Markdown table。

## P3：UI / Agent 工作流减负

目标：普通用户和 Agent 都不需要理解 MinerU、Marker、Docling、PaddleOCR-VL、Qwen-VL 等后端名。

UI 普通模式：

- 保留：选择输入、输出目录、扫描、开始识别、按推荐执行、打开输出、打开报告。
- 隐藏到高级设置：PDF compare、OCR provider compare、后端 scorecard、重型 VLM/OCR wrapper、健康诊断细节。
- 每个文件只显示人话建议：直接识别、建议 OCR、建议结构增强、建议 PDF 对比、需要人工复查。
- 每个建议必须说明：为什么、是否覆盖原文件、输出位置、下一步点什么。

Agent 合约：

- `next_actions` 必须包含 `tool`、`arguments`、`safe_default`、`destructive=false`。
- HTTP 未启动但 CLI/MCP 可用时，状态是 `on-demand`，不是 `blocked`。
- Agent 默认走 CLI/MCP；HTTP 只作为 Docker/OpenClaw/Hermes 的 on-demand bridge。
- 长 PDF 继续使用分段、超时、中止、fallback，不让单个文件阻塞批量任务。

## 可选后端替换评测：先网络线索，不本地安装

用户决策：可选后端做“替换评测”可能需要大量空间安装本地大模型和环境，因此先从网络论坛、社区、论文和上游 issue 收集线索，再决定是否下载或接入。

Unlimited-OCR 当前结论：暂不接入、不下载、不进入默认或高级路由。只作为候选替换项记录。

已观察到的正向线索：

- 上游论文声称通过 Reference Sliding Window Attention 降低长输出 KV cache 成本，并可在 32K 最大长度内一次转写几十页文档。
- GitHub README 显示支持 Transformers、vLLM、SGLang，且 2026-06-28 已加入 vLLM 推理支持。
- Hugging Face model card 标记 MIT license，并提供 vLLM/SGLang/OpenAI-compatible 风格服务路径。

已观察到的风险线索：

- 上游 Transformers 示例测试环境是 Python 3.12.3、CUDA 12.9、torch 2.10、GPU `.cuda()` 路径，完整本地环境很重。
- Hugging Face 社区讨论反馈：高密度长图在整图输入时可能只读顶部、重复输出；切片/裁剪可改善，但这意味着仍需要客户端分页/切块策略。
- 社区用户反馈低质量/低分辨率法律表单中存在“读不清时编造合理内容”的风险；这对法律、医疗、金融材料是高风险失败模式。
- 另有 PR 指出模型代码硬编码 CUDA，MPS/CPU 会崩溃；这意味着它不适合作为普通本机默认后端。
- 一篇 OCR-VLM 压力测试论文提示，专用 OCR-VLM 在退化输入和真实扫描上可能非常脆弱，不能只看干净页面 benchmark。

替换评测准入条件：

- 不允许新增本地模型下载作为第一步。
- 先找可用远程 demo/API 或已有他人评测；只有证据足够才考虑本机环境。
- 如果要接入，优先通过 `VlmLayoutProvider` 或 OpenAI-compatible remote endpoint，不直接把上游代码塞进主流程。
- 必须和现有 PaddleOCR-VL、Qwen-VL、MinerU VLM、olmOCR、DeepSeek-OCR、GOT-OCR 做同样样本对比。
- 只有当 Unlimited-OCR 明显提升截图书、信息图、多页图文 PDF 的 fidelity，并能替换一个现有重型模块时，才进入接入开发。

## 下一步执行顺序

1. 在正常 PowerShell 中补跑 `python scripts\test_rapidocr_provider.py` 和 minimal quality gate。
2. 将当前 dirty 按运行修复、RapidOCR runtime、Unlimited-OCR 文档、计划文档拆分提交。
3. 给质量队列增加“下一步动作说明”字段，优先服务 UI/Agent，而不是后端名。
4. 从本地真实样本 manifest 生成 poor/review 分类汇总，但只提交去标识化统计，不提交样本路径。
5. 针对中文编号层级、OCR 噪声、目录残留各做一个 fixture 修复。
6. 可选后端继续只做网络线索和公开 benchmark 收集，不下载 Unlimited-OCR。

## 参考来源

- Unlimited-OCR GitHub README: https://github.com/baidu/Unlimited-OCR
- Unlimited OCR Works arXiv: https://arxiv.org/abs/2606.23050
- Hugging Face model card and discussions: https://huggingface.co/baidu/Unlimited-OCR
- Hugging Face discussion #3, poor official Space OCR and tiling workaround: https://huggingface.co/baidu/Unlimited-OCR/discussions/3
- Hugging Face discussion #4, ParseBench result caveat and hallucination report: https://huggingface.co/baidu/Unlimited-OCR/discussions/4
- Hugging Face discussion #5, CUDA hardcoding/MPS/CPU issue: https://huggingface.co/baidu/Unlimited-OCR/discussions/5
- OCR-VLM stress-test benchmark: https://arxiv.org/abs/2606.29213
