# ebook_markdown_pipeline 增量架构与开源复审

日期：2026-07-15

状态：proposal-only；不改变默认 backend、不安装依赖或模型、不启动服务、不处理新私有文档、不写共享 registry、不推送。

## 本轮边界与证据

这是 2026-07-10 深度审计后的增量复审，不重述既有项目清单。先查询 `SOURCE_INVENTORY.json`：MinerU、Docling、Marker、PaddleOCR、Surya、MarkItDown、PyMuPDF4LLM、Camelot、Tabula、RapidOCR、Tesseract、Unstructured 等均已有本地来源或源码账本，禁止为本轮重新克隆。`gmft`、OmniDocBench、OpenDataLoader PDF、GLM-OCR、OCRFlux、Chandra 尚无 source-ledger 条目，因此本轮只读取官方公开文档，不将它们视为本机已审计或已接入。

本轮的本地事实来自：

- 当前 `main` 为 `0dfce91`，工作树未被本轮改动。
- `batch_convert_books.py --health-check`：最小链路可用；MinerU 3.1.15、Marker、PyMuPDF/PyMuPDF4LLM、MarkItDown、RapidOCR 可用；Docling 因 `tokenizers` 版本不匹配不可用；Camelot、Tabula、OCRmyPDF、Surya 等为缺失或候选状态。
- `docs/MINERU_API_SERVICE.md`：MinerU 只能通过固定 `127.0.0.1:8000` API 调用，API 不可用时必须在报告中诚实降级，绝不回落到临时 `LocalAPIServer`。
- `docs/OFFLINE_STAGE_QUALITY_CONTRACT.md` 与 `docs/HTTP_STATUS_CONTRACT.md`：artifact 存在不等于质量通过；停止的 HTTP 也不等于 CLI 不可用。
- 2026-07-10 的审计提出 artifact registry、pytest 兼容层、dots.mocr CLI 漂移和固定 MinerU API 等风险。当前已存在 `artifact_registry.py`、`tests/test_legacy_script_contracts.py`、离线质量路由和固定 MinerU 契约，因此这些不再列为新增候选。

## 增量结论

项目应继续保持“本地文档转换编排层”定位。下一步最有价值的工作不是叠加另一套全能 OCR/VLM，而是补足三个当前没有统一证据的空洞：数字 PDF 表格结构、跨 backend 的质量比较、以及可追溯的结构化文档 artifact。

保留与组合建议：

| 角色 | 当前可保留组合 | 当前缺口 | 增量建议 |
| --- | --- | --- | --- |
| 快速 Markdown baseline | Pandoc/Calibre、PyMuPDF4LLM、MarkItDown | PyMuPDF4LLM 运行时兼容性可能降级 | 保留现有 `pymupdf-text(fallback from pymupdf4llm)` 命名；MarkItDown 继续只做比较基线 |
| Office/PDF 结构化解析 | MinerU、Marker、Docling | Docling 当前依赖漂移；其 rich document 没有作为 artifact 输出 | 不改默认；依赖修复后优先导出 DoclingDocument JSON/provenance sidecar |
| OCR/版面增强 | RapidOCR、Tesseract worker、Surya/PaddleOCR-VL 等候选 | 可运行的轻 OCR 与重 layout/VLM 之间缺共同的 page/block 证据 | RapidOCR 保持轻量 OCR；Surya 不升级或接入新模型，先做 schema 兼容 plan |
| 表格提取 | pdfplumber 诊断；Camelot/Tabula/pdf_table 候选；table_to_xlsx 独立 lane | 文本层 PDF 没有独立结构识别 baseline；`pdf_table` 仍是重且输出解析靠 glob 的 legacy worker | 新增候选只评估 gmft；照片/扫描表格继续留在 Paddle/img2table/RapidTable lane |
| 图片、公式、脚注、阅读顺序 | MinerU/Marker/PyMuPDF 后处理，Surya/DocLayout-YOLO candidate sidecar | 页面 provenance、reading-order、formula/table 指标未汇总成同一 benchmark | 先引入 OmniDocBench 风格的评估 adapter，不新增解析默认 |
| 生命周期、缓存、回退、质量 | 固定 MinerU API、报告诊断、offline quality router、HTTP stopped-by-design | backend 版本/输出 schema 升级会绕过现有 sidecar 解析 | 每个候选先通过 plan/fake、health、output resolver、scorecard，再讨论 execute |
| Agent/MCP | CLI/UI/MCP/HTTP 共享 Python core | 入口仍不应拥有 parser 语义 | Agent/MCP 只读 capability、plan、artifact 和 benchmark 结果；不能替代后端或触发模型下载 |

## 现有链路中应立刻保护的事实

1. MinerU 是复杂 PDF 的可用重后端，但不是自动启动的服务。继续传递 `--api-url`，并把 API 不可用归类为 `MinerUAPIUnavailableError`。
2. Docling 的缺口是“当前不可 import”，不是“缺另一个 Office parser”。应先处理依赖一致性；修复后再暴露已有 `DoclingDocument` 的 JSON、bbox 和 provenance，而不是只保留 Markdown/heading 候选。
3. 表格要按输入类型分流：文本层 PDF 用表格检测/结构识别，扫描或拍照表格走 OCR/XLSX worker。两者不能共享一个无条件 fallback。
4. `dots_mocr_worker.py` 的命令构造已相对 7 月 10 日审计修正为 `dots_mocr/parser.py`、位置输入和 `--output`；但其 health 仍硬编码 `weights/DotsMOCR` 假设且 root 未配置，不能宣称 execute-ready。
5. `pdf_table_worker.py` 的 execute 路径仍会用第一个匹配文件推断 Markdown/HTML/cells/overlay；其输出 resolver 不够确定，因此保持 legacy comparison，不扩展到默认路由。

## 新增或新版候选的判断

### 1. gmft：数字 PDF 表格的首选新增 baseline

官方 PyPI/文档显示 gmft 以 Microsoft Table Transformer 为核心，使用 PyPDFium2 文本和坐标，在 CPU 上输出 DataFrame、Markdown、HTML、CSV 和裁剪图；v0.3 起有多级表头、跨列单元格和旋转表支持，v0.4 文档已将旧顶层 import 标为 deprecated。它不做 OCR，且对 OCR 错误、合并单元格和误检仍有明确失败模式。

结论：**保留为 P1 candidate-only table worker**。它填补的是“文本层 PDF 的结构表格 baseline”，不是拍照表格 OCR，也不应直接替换 `table_to_xlsx`。

### 2. OmniDocBench：应优先借鉴评测而不是下载全量数据

官方仓库提供文本、表格、公式、layout 和 reading-order 的模块及端到端评估；数据集含 1,651 页和多语言/多版式标注。完整公式指标依赖 TeX Live、ImageMagick、Ghostscript，且官方推荐 Docker，因此不适合本轮安装或完整运行。

结论：**P1 benchmark adapter，非 backend**。先用本项目已有 synthetic/公开 fixture 对齐其输入/输出字段，缺工具时将公式指标标记为 `not_evaluated`，不能伪造总分。

### 3. OpenDataLoader PDF：可比的快速结构/坐标 baseline，但不进入默认

官方仓库的近期 v2.3.0 发布包含页脚/表格修复与 auto-tagging；其 fast 模式要求 Java 11+，可输出 Markdown、JSON bbox 和 HTML。它的 hybrid OCR/复杂页模式需要独立本地服务，和本项目“不自动启动服务”的边界冲突。

结论：**P2 fast-mode-only candidate**。仅在已有 Java 11 的机器上做纯本地 digital-PDF 比较；禁止在本项目内启动 hybrid service。若其 JSON/bbox 在 reading order 或 provenance 上不能明显优于现有 PyMuPDF/Docling/MinerU sidecar，则退出，不增加运行时。

### 不晋级的新增观察

- GLM-OCR：官方项目新增 SDK/Skill 入口并支持 vLLM、SGLang、Ollama，但仍要求模型/API 或手动服务。它应复用现有 online-provider abstraction，只有能替换一个已有重 VLM 才进入试验。
- Chandra OCR 2：官方宣称 tables/forms/handwriting/layout 能力，并支持 HF 或 vLLM；模型权重有额外 OpenRAIL 限制且吞吐证据来自 H100。保留为远程专项对比，不引入本机默认。
- Surya OCR 2 已发布；现有 wrapper 未针对新 schema 做兼容验证。先做零模型输出-schema fixture，再决定是否升级，不把版本号当质量证明。
- Table Transformer 不单独新接：gmft 已提供更小的 adapter 边界。pdf_table 保留历史对比即可。
- Kreuzberg、Open Parse、deepdoctection、Unstructured：与现有多格式 baseline/编排层高度重叠。Kreuzberg 虽在 source ledger 中有 clone，但没有可复用审计结论；本轮不晋级。

## Fallback 冲突与维护成本

| 冲突 | 风险 | 约束 |
| --- | --- | --- |
| MinerU -> PyMuPDF4LLM/PyMuPDF | 重结构结果失败后产生可读但低结构 Markdown | 保持现有 pipeline 名和 fallback diagnostics；quality gate 必须看到结构风险 |
| Docling -> Pandoc/MarkItDown | Office/PDF 结构失败被快速文本输出掩盖 | 报告 `from_pipeline`/`to_pipeline`；不以 `status=ok` 代替结构质量通过 |
| 文本 PDF 表格 -> OCR table | 已有文字坐标却再 OCR，可能损失字符或改变单元格 | 先用 `text_layer_present`、table candidates 和页级证据决定，不做盲目串行 fallback |
| 多个 VLM/OCR 候选并存 | 模型、CUDA、服务、输出 schema 和缓存维护成本叠加 | 新重模型必须替换 MinerU VLM、PaddleOCR-VL、Surya、olmOCR、dots 或 MonkeyOCR 中至少一个；否则只停在 plan |
| layout detector -> Markdown | bbox detector 不能恢复语义、脚注、公式或阅读顺序 | DocLayout-YOLO 只写 overlay/layout sidecar，不得成为 Markdown converter |
| candidate worker 的 glob output | 模型升级时读到错误 `.json`/`.md` | 新 worker 必须声明 output resolver 和 artifact schema；`pdf_table` 不可作为模板 |

## Top 3 最小试验计划

### A. gmft table worker

范围：6 个公开或合成的文本层 PDF 表格页，覆盖有线框、无边框、多级表头、跨列、旋转和非表格卡片布局；不含真实私有文件。

前置：人手安装依赖和模型缓存后才可 execute；本轮只保留 `plan`。输入必须先由 `pdfplumber` 确认有文本层。

成功标准：输出 per-table Markdown、HTML、cells JSON、裁剪图/overlay；同页与 pdfplumber/Camelot/Tabula 的表数、行列数和单元格覆盖可比较；多级表头不静默降扁；scorecard 显示比现有最低可用 baseline 更少 review 项。

失败/退出：需要 OCR 才能工作、模型下载或 PyTorch 环境不可控、误检卡片布局、无稳定 cell schema、或未显著优于现有诊断组合时，删除试验产物，不注册 backend，不改路由。

### B. OmniDocBench-style evaluation adapter

范围：不下载完整数据集。将已有 synthetic/public fixture 和已有 candidate sidecar 映射为一个最小 `layout/text/table/formula/reading_order` manifest。

成功标准：adapter 能对已有产物报告可计算项和 `not_evaluated` 项；文本差异、表格结构、阅读顺序分别出具结果；无 reference 或缺 TeX/GS 时明确跳过相应指标；结果能写入现有 backend scorecard。

失败/退出：为了得到一个总分而要求 Docker、全量数据或隐藏缺失指标；不能和现有 `table_review_matrix`/`formula_review_matrix` 对齐时，保持为设计文档，不添加依赖。

### C. OpenDataLoader PDF fast-mode comparison

范围：3 个公开/合成 digital PDF：双栏、带表格、页眉页脚各一个；只运行 fast local `markdown,json`，禁止 hybrid、OCR 和服务进程。

成功标准：Java 11 preflight 通过；得到 Markdown 与每 element 的页号/bbox JSON；相对 PyMuPDF4LLM 和可用的 Docling/MinerU sidecar，reading-order 或 provenance 至少一项有可审计改善；外部进程在限定时间内退出。

失败/退出：Java/JVM 生命周期不稳定、输出 schema 无法适配 artifact registry、无指标改善、或需要 hybrid server 才有价值时，不增加候选 worker，也不进入 Local Tools registry。

## 给 Local Tools 的 registry/discovery 提案

以下是精确 proposal，不直接修改 `D:\used-by-codex\tool-registry.json`：

```json
{
  "schema_version": "ebook-incremental-backend-discovery-proposal-v1",
  "status": "proposal_only",
  "apply": false,
  "registry_write": false,
  "reason": "All three items remain uninstalled or benchmark-only; no stable local command, health contract, or promotion evidence exists.",
  "proposed_project_discovery": {
    "owner_tool": "ebook_markdown_pipeline",
    "read_only_actions": [
      "show_backend_capabilities",
      "show_candidate_readiness",
      "show_latest_quality_gate"
    ],
    "candidate_notes": [
      {
        "key": "gmft_table",
        "state": "proposal_only",
        "discovery": "text-layer PDF table benchmark candidate; requires explicit model/dependency preparation",
        "no_auto_install": true,
        "no_auto_start": true
      },
      {
        "key": "omnidocbench_adapter",
        "state": "proposal_only",
        "discovery": "offline benchmark adapter; not a parsing backend and not a service",
        "no_auto_install": true
      },
      {
        "key": "opendataloader_pdf_fast",
        "state": "proposal_only",
        "discovery": "Java 11 local fast-mode comparison only; hybrid server is explicitly out of scope",
        "no_auto_start": true
      }
    ]
  },
  "promotion_preconditions": [
    "source-ledger entry with official-source evidence",
    "stable local command or Python adapter",
    "health/plan/execute/output-resolver contract",
    "artifact schema and scorecard evidence",
    "no default-route change without explicit approval"
  ]
}
```

## 重复排除项与仍需真实样本的缺口

重复排除：MinerU fixed API、Marker、Docling/MarkItDown baseline、PaddleOCR、Surya、PyMuPDF4LLM、Open Parse、deepdoctection、pdf_table、Table Transformer direct integration、MonkeyOCR/dots.mocr/DocLayout-YOLO 的现有 plan/fake wrappers。这些没有因为新一轮搜索而自动获得晋级资格。

仍需显式授权后才可验证的真实缺口：中文扫描书目录/脚注、手机拍摄的倾斜表格、金融报表的合并单元格、含公式和双栏的学术 PDF、手写/勾选表单、复杂阅读顺序。这些应使用脱敏或公开样本，逐项进入 scorecard；单份私有样本或 README 指标均不能改变默认路由。

## 官方来源

- gmft PyPI / 文档：https://pypi.org/project/gmft/ 、https://gmft.readthedocs.io/en/latest/
- OmniDocBench：https://github.com/opendatalab/OmniDocBench
- OpenDataLoader PDF：https://github.com/opendataloader-project/opendataloader-pdf
- Docling Document：https://docling-project.github.io/docling/concepts/docling_document/
- Surya：https://github.com/datalab-to/surya
- GLM-OCR：https://github.com/zai-org/GLM-OCR
- Chandra：https://github.com/datalab-to/chandra
