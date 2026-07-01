# 可选 OCR/VLM 后端替换评测：网络线索阶段

更新时间：2026-07-01 10:45:00
更新工具/模型：Codex GPT-5

## 结论先行

本阶段不安装任何新本地大模型，不下载权重，不扩展默认路由。先做网络、社区、论文、上游 README 和已接入 wrapper 的证据评估，目的是判断哪些后端值得进入下一轮真实样本对比，哪些只保留为显式实验入口。

当前推荐排序：

1. **PaddleOCR-VL**：最值得作为信息图、表格、公式、中文/多语言复杂版面补强的优先候选；如果本机空间和环境允许，优先评测它，而不是 Unlimited-OCR。
2. **Surya**：适合做 OCR + layout + reading order + table 的轻量-ish 视觉版面候选；但模型权重商业条款要单独看，不应默认进入分发包。
3. **Pix2Text**：适合中文截图、公式、图片页到 Markdown；不是通用 VLM 替代项，但安装和目标场景更贴近日常中文材料。
4. **MinerU VLM / hybrid**：已有强文档解析路线，适合复杂 PDF；继续保留，但不要无差别整本默认调用。
5. **olmOCR**：适合英文/学术/复杂 PDF 的 benchmark 和远程 GPU 对比；本机完整安装成本高，但它的 benchmark 很有参考价值。
6. **Qwen-VL**：适合通过在线/远程 `VlmLayoutProvider` 做视觉理解和结构补强；不建议本地默认部署。
7. **DeepSeek-OCR**：技术线索强，但环境重、社区/压力测试提示灾难性重复风险；保留显式实验入口。
8. **GOT-OCR**：研究/demo 属性更强，适合单图/局部/格式化 OCR 实验，不建议进入推荐路由。

Unlimited-OCR 继续保持“候选但暂缓”：除非它能在同一组样本上明显超过 PaddleOCR-VL / Surya / MinerU VLM / olmOCR，并能替换掉一个现有重后端，否则不接入。

## 对比矩阵

| 后端 | 最适合场景 | 网络/论文质量线索 | 空间/环境成本 | 当前接入状态 | 下一步建议 |
| --- | --- | --- | --- | --- | --- |
| PaddleOCR-VL | 多语言复杂文档、信息图、表格、公式、图表、扫描/拍照文档 | 官方 README 标称 PaddleOCR-VL-1.6 在 OmniDocBench v1.6 达到 96.3%，并强调表格、公式、图表等复杂元素；论文线索显示 0.9B 模型、109+ 语言、Real5 鲁棒评测 | 中到重；Paddle/PaddleOCR 环境、模型缓存、可能需要 GPU | 已有 wrapper 和文档 | 第一优先级进入公开 fixture/真实样本对比；如果效果稳定，可替换部分 Qwen-VL/DeepSeek/GOT 显式入口 |
| Surya | 版面分析、阅读顺序、表格、OCR 块结构、layout-heavy 图片 | 官方 README：650M、olmOCR-bench 83.3、RTX 5090 约 5 pages/s、91 语言内部 benchmark 87.2；支持 OCR/layout/table/reading order | 中到重；pip 安装相对简单，但模型权重另有 modified AI Pubs Open Rail-M 条款 | 已有 wrapper 和 health 检查 | 第二优先级；重点测阅读顺序和真实表格，不用于普通 OCR 默认 |
| Pix2Text | 中文截图、公式、图片页 Markdown、轻量 Mathpix 替代 | 官方 README：小模型、布局/表格/公式/文本到 Markdown，80+ 语言；中文和英文使用 CnOCR，其它语言走 EasyOCR | 中；多模型但比大 VLM 轻；公式模型会占用额外缓存 | 已有 wrapper 和 dry-run 测试 | 日常中文图片/公式优先候选；不作为通用复杂 PDF 解析替代 |
| MinerU VLM / hybrid | 复杂 PDF、扫描 PDF、图文混排、跨页表格、图片/图表解析 | 官方 README：VLM+OCR 双引擎、pipeline/hybrid/vlm 多模式；MinerU2.5-Pro 论文报告 1.2B 架构在 OmniDocBench v1.6 达 95.69；官方 changelog 强调 2605 稳定性和 hybrid 加速 | 重；本地模型、GPU/VRAM、长任务卡住风险；pipeline CPU 可用但 VLM/hybrid 重 | 已有 PDF 管道与 fallback 逻辑 | 保留作为复杂 PDF 主力之一；继续做分段/超时/fallback，不继续盲目扩大默认使用 |
| olmOCR | 英文/学术 PDF、复杂扫描、benchmark 对照、远程 GPU OCR | 官方 README：olmOCR-bench 超 7,000 tests / 1,400 docs；olmOCR v0.4.0 总分 82.4，PaddleOCR-VL 80.0、MinerU 75.2、DeepSeek-OCR 75.7；论文强调表格、多栏、公式提升 | 重；本地 GPU 需 12GB+ VRAM、约 30GB free disk；远程 inference 安装较轻 | 已有显式 PDF backend | 保留 benchmark/远程 GPU 候选；不本地默认安装 |
| Qwen-VL / Qwen3-VL | 通用视觉理解、长文档语义理解、坐标/grounding、在线 VLM 补强 | 官方 README：Qwen3-VL 支持 256K context 可扩展到 1M，OCR 32 语言，文档解析包括 layout position 和 Qwen HTML；Devanagari 压测中 Qwen3-VL-8B 在真实扫描上明显强于多数开源/专用 OCR-VLM | 重；本地模型大，远程/API 更合适 | 已有 wrapper/online provider 方向 | 优先走远程 `VlmLayoutProvider`；不放进本机默认链路 |
| DeepSeek-OCR | VLM OCR、视觉-文本压缩、表格/图表/长上下文压缩实验 | 论文报告压缩比 <10x 时 97% decode accuracy，20x 约 60%；官方 README 支持 vLLM/Transformers；压力测试提示 DeepSeek-OCR 在退化输入下可能出现灾难性重复 | 重；CUDA 11.8 + torch 2.6 + vLLM/flash-attn，A100 指标多，不适合普通 Windows 默认 | 已有显式 wrapper | 保留显式实验；除非真实样本证明明显优于 PaddleOCR-VL/Surya，否则不升级推荐 |
| GOT-OCR 2.0 | 单图 OCR、局部/坐标交互、公式/谱/几何等“广义 OCR”研究 | 论文：580M、OCR-2.0、支持 plain/formatted 输出、whole/slice/page、多页和区域交互 | 中到重；demo 脚本、CUDA、`trust_remote_code`、模型授权需复核 | 已有显式 wrapper | 保持研究/demo 入口；不进入推荐路径 |

## 替换关系建议

### 最可能替换现有重模块

- **PaddleOCR-VL 替换部分 Qwen-VL / DeepSeek-OCR / GOT-OCR 显式图片 OCR 入口**：如果它在信息图、表格、公式和中文扫描页上稳定输出结构化 Markdown，优先保留 PaddleOCR-VL，减少其它 VLM wrapper 的日常暴露。
- **Surya 替换一部分 layout/table 诊断逻辑**：如果它的 reading order/table 结果比当前规则层更稳定，可用于生成复查建议，但不直接覆盖主 Markdown。
- **Pix2Text 替换中文公式/截图专项流程**：如果中文截图和公式材料表现稳定，它应成为中文视觉材料的第一补强，而不是先上大 VLM。

### 不建议替换的部分

- **不要用 Qwen-VL 替换 PyMuPDF/PyMuPDF4LLM/Pandoc/Calibre**：这些轻路径便宜、稳定、可解释。
- **不要用 DeepSeek-OCR/GOT-OCR 替换 Umi-OCR/RapidOCR 快速 OCR**：快速 OCR 的价值是便宜和可批量，不是最强 VLM。
- **不要让 olmOCR 替换普通 PDF 默认路线**：它更适合 benchmark 和远程 GPU 对比。
- **不要让 MinerU VLM 整本默认跑长 PDF**：已有卡住历史，继续坚持分段、超时、fallback。

## 下一轮真实评测设计

不装新模型的前提下，先定义样本和指标，后面只在必要时跑远程/已有环境。

样本类别：

- 中文信息图图片：卡片式/流程图/多块文字，无真实表格。
- 中文保险/合同编号结构：`第五条`、`（一）`、`1.` 父子层级。
- 扫描 PDF：含页眉页脚、页码、断行。
- PPT 拼接 PDF：标题、项目符号、图表混排。
- 表格 PDF/图片：只考真实表格，不把横向卡片误转表格。
- 英文学术/技术 PDF：多栏、公式、表格、脚注。

指标：

- 输出是否成功。
- 标题层级是否正确。
- 阅读顺序是否正确。
- 表格是否保留为表格。
- 页眉页脚/页码噪声。
- 是否有重复、漏读、幻觉。
- Markdown 可读性。
- 耗时和是否卡住。
- 模型/环境/磁盘成本。

准入门槛：

- 一个后端只有在至少两个高频样本类别明显优于当前默认链路，且不会引入不可接受的空间/环境成本时，才进入 UI/Agent 推荐动作。
- 对高风险材料（法律、医疗、金融、保险条款），任何 VLM 输出都必须保留原图页码和复查标记，不能直接信任。
- 新后端优先替换旧重后端，而不是叠加更多按钮。

## 网络来源摘要

- PaddleOCR 官方 README：PaddleOCR-VL-1.6、OmniDocBench v1.6、复杂元素、100+ 语言、PP-OCRv6 CPU/GPU 速度线索。
- PaddleOCR-VL 系列论文：0.9B 文档解析 VLM、Real5 鲁棒性、OmniDocBench v1.5/v1.6。
- Qwen3-VL README：OCR 32 语言、长上下文、文档解析、layout position、Qwen HTML。
- MinerU README / MinerU2.5-Pro 论文：VLM+OCR dual engine、pipeline/hybrid/vlm、OmniDocBench v1.6、VRAM/RAM 信息、3.3/3.4 changelog。
- olmOCR README / olmOCR 2 论文：olmOCR-bench、安装成本、远程 inference、本地 GPU 要求。
- DeepSeek-OCR README / 论文 / OCR-VLM stress-test：vLLM/Transformers、压缩率、A100 指标、退化输入重复风险。
- GOT-OCR 2.0 论文：580M OCR-2.0、plain/formatted 输出、whole/slice/page 和交互式 OCR。
- Surya README：650M、olmOCR-bench、5 pages/s RTX 5090、90+ 语言、Apache code 与模型权重商业条款。
- Pix2Text README：小模型、layout/table/formula/text、80+ 语言、Markdown/PDF、MIT。

## 远程评测入口

本项目提供一个不下载本地模型的远程评测入口：

```powershell
python scripts\run_remote_ocr_vlm_eval.py --manifest config\remote_ocr_vlm_eval.example.json --output benchmarks\runs\remote-ocr-vlm-eval-plan
```

默认只写 dry-run plan，不会访问网络。真实调用必须显式提供本地 provider 配置，并同时传 `--execute --allow-remote`：

```powershell
python scripts\run_remote_ocr_vlm_eval.py `
  --manifest path\to\remote_ocr_vlm_eval.local.json `
  --provider-config config\online_providers.local.json `
  --execute --allow-remote `
  --output benchmarks\runs\remote-ocr-vlm-eval-current
```

测试/合同验证可使用 fake provider，不访问远程服务：

```powershell
python scripts\run_remote_ocr_vlm_eval.py --execute --fake --output benchmarks\runs\remote-ocr-vlm-eval-fake
```

## 当前决策

- 先不安装任何新模型。
- 下一步优先完善质量队列和样本指标。
- 如果要试重后端，优先顺序为：PaddleOCR-VL、Surya、Pix2Text、MinerU VLM/hybrid、olmOCR remote、Qwen remote、DeepSeek-OCR、GOT-OCR。
- Unlimited-OCR 继续只保留为候选，不进入下一轮本地安装。
