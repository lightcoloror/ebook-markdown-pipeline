# 开源项目清单与调研分层

本文档用于记录图文材料转换器相关的开源项目、参考项目和许可证注意事项。它面向两个用途：

- 开源发布时说明本项目参考、调用、对标了哪些项目。
- 做 U 盘/离线包/商业分发前，逐项检查哪些组件可以直接打包，哪些只适合引导安装，哪些需要商业授权或更严格的源码交付。

更新时间：2026-06-09 08:30:00  
更新工具/模型：Codex GPT-5

> 注意：本文是工程调研和合规排查清单，不是法律意见。许可证、模型授权、商用条款可能变化；真实分发前必须重新打开上游仓库的 LICENSE、NOTICE、模型卡和发布包逐项确认。

## 当前项目已直接调用或支持的开源工具

| 项目 | 本项目中的角色 | 当前集成方式 | 许可证/分发风险 | U 盘分发建议 |
| --- | --- | --- | --- | --- |
| Pandoc | EPUB、FB2、TXT、ODT、Markdown、HTML、text 等格式转换 | 外部命令 | GPL-family，需携带许可证和源码获取方式 | 可以引导安装；若内置，附许可证和源码获取说明 |
| Calibre / `ebook-convert` | AZW/AZW3/MOBI/RTF 中间转换 | 外部命令 | GPL-family，整包分发要合规 | 可引导安装；内置时单独放许可证和源码获取说明 |
| PyMuPDF | PDF 预检、文本层、图片、书签/outline、渲染 | Python 包 API | AGPL-3.0 或商业授权 | U 盘商业包若内置，建议购买商业授权或严格 AGPL 交付 |
| PyMuPDF4LLM | 文本层 PDF 快速转 Markdown | Python 包 | 基于 PyMuPDF 生态，AGPL/商业授权风险同上 | 同 PyMuPDF |
| MinerU | 复杂/扫描 PDF 结构化解析 | 可选外部后端 | 上游公开信息曾包含 AGPL/强 copyleft 约束，需复核 | 不建议默认内置模型；更适合引导安装或单独合规包 |
| Marker | 版面感知 PDF/文档解析 | 可选外部后端 | GPL-3.0 级别/商业授权风险需复核 | 不建议混入闭源包；内置需按 GPL 交付 |
| Docling | Office、HTML、CSV、部分文档/PDF 结构化后端 | 可选 Python 后端 | 官方仓库标注 MIT，但模型/扩展依赖仍需复核 | 适合作为优先内置候选，仍需附许可证 |
| Umi-OCR / PaddleOCR-json | 图片、扫描页、本地 OCR 兜底 | 外部本地程序/模块路径 | 需检查程序、模型、PaddleOCR-json 各自许可证 | 很适合 U 盘场景，但必须分清程序与模型许可 |
| PaddleOCR-VL | 信息图、复杂版面、layout-heavy 图片补强 | 可选 wrapper/命令 | 需检查代码、模型权重、商用条款 | 建议作为可选增强包，不默认强依赖 |
| Qwen-VL | 重型 VLM 图文理解补强 | 可选 wrapper/API | 模型许可和商用条款需逐模型复核 | 建议默认在线/远程可选，不随盘混装 |
| tkinterdnd2 | UI 拖放文件 | Python 包 | 需按包许可证附带声明 | 可随基础依赖安装 |

## 建议优先调研的成熟开源项目

这些项目与本项目定位重叠度高，或能补足现有弱项。优先级按“对当前产品价值”和“复用可能性”排序。

| 优先级 | 项目 | 适合借鉴/接入的层 | 为什么值得看 | 初步许可证判断 | 建议动作 |
| --- | --- | --- | --- | --- | --- |
| P0 | Microsoft MarkItDown | 多格式轻量 baseline、MCP/CLI/API 参考 | 格式覆盖广，LLM-friendly Markdown，MIT，生态热度高 | MIT | 做成可选 fast path 或对标 benchmark |
| P0 | Docling | 结构化文档对象、Office/PDF/HTML 解析 | MIT，本地优先，输出 Markdown/JSON/DoclingDocument | MIT | 已集成，继续加强质量对比和默认策略 |
| P0 | Unstructured | 企业级 ingest、partition、chunking 工作流 | RAG/Agent 文档摄取成熟样板，格式覆盖广 | Apache-2.0 | 重点研究其 partition/chunking/report 设计 |
| P0 | OCRmyPDF | 扫描 PDF 预处理为 searchable PDF | 可先给扫描件加文本层，再走 fast path | MPL-2.0 常见，需复核 | 作为扫描 PDF 预处理候选 |
| P0 | PaddleOCR / PP-Structure | 中文 OCR、表格、版面结构 | 中文场景强，生态成熟 | Apache-2.0 常见，模型另查 | 重点实测中文扫描件和表格 |
| P1 | Apache Tika | 格式嗅探、元数据、兜底抽文本 | 格式识别/抽文本覆盖极广 | Apache-2.0 | 可作为 inspect/fallback 参考 |
| P1 | pdfplumber | 文本层 PDF 表格/坐标调试 | 适合 text-based PDF 的表格和坐标分析 | MIT | 用于表格/坐标诊断，不做主转换 |
| P1 | Camelot | text-based PDF 表格抽取 | 专项表格 fallback | MIT 常见，需复核依赖 | 作为表格 repair 候选 |
| P1 | Tabula / tabula-py | PDF 表格抽取和 GUI 参考 | 老牌表格提取，小白 UI 思路可借鉴 | MIT/Apache 等需复核 | 可参考交互式表格选择 |
| P1 | GROBID | 学术论文结构、参考文献、TEI | 论文专项解析成熟 | Apache-2.0 常见 | 作为论文专项 heavy path |
| P1 | RapidOCR | 轻量本地 OCR 部署 | 比完整 PaddleOCR 更易打包 | Apache-2.0 常见，模型另查 | 低配 CPU OCR 候选 |
| P1 | Tesseract | 经典离线 OCR | 兜底稳定、部署资料多 | Apache-2.0 | 可作为 OCRmyPDF 依赖或兜底 |
| P1 | Surya | OCR/layout/reading order/table | Marker 生态底层能力之一，适合视觉版面 | 需复核 | 复杂版面研究候选 |
| P1 | Crawl4AI | 网页资料转 Markdown | Agent/RAG 网页摄取成熟 | Apache-2.0 常见 | Web archive/URL 输入方向参考 |
| P1 | Trafilatura | 网页正文/metadata 抽取 | 轻量网页正文抽取 | Apache-2.0/GPL 组件需复核 | 可作为网页 fast path |
| P2 | MegaParse | LLM ingest 多格式 parser | 对标“no information loss”解析思路 | Apache-2.0 常见 | 调研输出 schema 和质量报告 |
| P2 | OmniParse | 本地多模态 ingest + UI | 多模态、本地、Gradio UI 与 U 盘形态接近 | 需复核 | 研究 UI/打包/多模态流水线 |
| P2 | pdf-craft | 扫描书籍到 Markdown/EPUB | 和“截图书/扫描书”场景高度相关 | 需复核 | 实测扫描书目录/脚注/公式 |
| P2 | olmOCR | 扫描文档 OCR/VLM | 扫描文档质量候选 | 需复核模型许可 | 作为 VLM OCR 对比项 |
| P2 | GOT-OCR 2.0 | 轻量视觉 OCR | 单机 GPU/较小模型路线 | 需复核模型许可 | 作为低成本 VLM 候选 |
| P2 | Pix2Text | 中文社区 OCR/公式/版面 | 中文图文、公式、表格场景可测 | 需复核 | 中文专项候选 |
| P2 | paperless-ngx | 文档归档/OCR/检索产品形态 | 虽不主打 Markdown，但适合学习资料管理闭环 | GPL 系需复核 | 产品化参考，不建议直接混入 |

## Agent / MCP 生态参考项目

| 项目 | 参考价值 | 建议 |
| --- | --- | --- |
| MarkItDown MCP | 多格式转 Markdown 的 MCP 入口参考 | 对比本项目 MCP tool schema、artifact 返回方式 |
| Docling MCP | 文档转换/处理 MCP 服务参考 | 学习缓存、异步任务、结果对象设计 |
| Markdownify MCP Server | 面向 Agent 的多格式 Markdown 化入口 | 对比工具命名、参数、Docker 用法 |
| MCP-PDF2MD / MinerU MCP 类项目 | PDF 到 Markdown 的专用 MCP 服务 | 学习“远程 heavy parser + 本地 agent contract”边界 |
| official PDF/Document MCP servers | 轻量 PDF 阅读、分页、缓存、搜索 | 本项目可保留差异化：批处理、质量报告、人工复查、版本化重跑 |

## 商业或云端对标项目

这些不一定是开源项目，但能验证市场需求、API 形态和质量基准。

| 产品 | 对标点 | 对本项目启示 |
| --- | --- | --- |
| LlamaParse | Agentic document parser，layout-aware OCR，Markdown/JSON | 可作为在线增强层高质量 baseline |
| Mistral OCR | 文档 OCR、表格、结构保持 | 表格/手写/复杂版式的质量标杆 |
| Azure AI Document Intelligence | 文本、表格、bbox、confidence、Markdown output | 在线 provider schema 可参考 confidence/bbox |
| Google Document AI | OCR、layout、表单、表格、checkbox | 企业文档抽取 API 对标 |
| Amazon Textract | 表格、表单、layout elements | 结构化抽取对标 |
| ABBYY | 老牌 OCR/文档智能 | 商业 OCR 质量和产品包装参考 |
| Mathpix | 数学公式、科学文档 OCR | 论文/公式场景对标 |
| Reducto | 多模型文档解析与抽取流程 | 学习 parse/classify/split/extract/edit 分层 |

## 分发风险分层

### 低风险优先内置候选

通常是 MIT / Apache-2.0 / BSD / MPL 等相对宽松许可证的项目，但仍需附带许可证文本和 NOTICE：

- Docling
- MarkItDown
- Unstructured
- Apache Tika
- pdfplumber
- Tesseract
- OCRmyPDF
- RapidOCR
- Crawl4AI

### 中风险：依赖或模型需要单独检查

代码许可证可能宽松，但模型权重、训练数据、二进制依赖或 GPU runtime 可能有额外条款：

- PaddleOCR / PaddleOCR-VL
- Umi-OCR / PaddleOCR-json
- Qwen-VL
- Surya
- olmOCR
- GOT-OCR 2.0
- Pix2Text
- Docling 模型包

### 高风险：强 copyleft 或商业授权边界明显

这些不是不能用，而是不能当闭源商品随意混装：

- PyMuPDF / PyMuPDF4LLM：AGPL-3.0 或商业授权。
- Marker：GPL-3.0 级别/商业授权风险需复核。
- MinerU：公开信息曾出现 AGPL/强 copyleft 约束，必须复核当前版本。
- Calibre / Pandoc：GPL-family，分发时要保留许可证、源码获取方式和对应义务。
- paperless-ngx：GPL 系产品形态参考，不建议直接打包进闭源商业壳。

## U 盘商品化建议

### 推荐形态

- U 盘里放本项目源码、启动脚本、文档、许可证、第三方声明、离线安装说明。
- 基础包只内置本项目和低风险依赖。
- 强 copyleft 或模型较大的工具做成“可选安装包/用户自行安装/首次启动下载”。
- 每个第三方组件独立目录放 `LICENSE`、`NOTICE`、版本号、下载来源、源码链接。
- 不附带任何版权电子书、测试书库、来源不明模型、来源不清训练数据。

### 不推荐形态

- 把所有第三方二进制和模型混成一个闭源 exe 或压缩包，不附许可证。
- 用 AGPL/GPL 工具做核心能力，但禁止用户复制、修改、再分发。
- 把模型权重当“普通依赖”一起卖，未检查模型卡和商用条款。
- 宣称“完全自研解析引擎”，但实际主要调用开源项目。

## 下一步调研队列

1. MarkItDown：跑公开 fixture，对比 fast path、MCP、Office/HTML/图片能力。
2. OCRmyPDF：验证扫描 PDF 先加文本层后再走 PyMuPDF/Docling 的效果。
3. PaddleOCR / RapidOCR：验证中文扫描件、截图、表格块坐标。
4. pdfplumber / Camelot：验证 text-based PDF 表格检测和表格 repair。
5. Apache Tika：验证格式嗅探和非主流格式抽文本。
6. Unstructured：研究 partition/chunking 和企业 ingest 报告。
7. GROBID：研究论文/参考文献专项路径。

## 已核验来源

- Microsoft MarkItDown GitHub：MIT license。
- Docling GitHub / IBM 资料：Docling codebase under MIT license。
- Unstructured GitHub：Apache-2.0 license。
- PyMuPDF / MuPDF 官方资料：AGPL-3.0 或商业授权路线。
- 本项目现有文档：`THIRD_PARTY_NOTICES.md`、`docs/REFERENCES_AND_REUSE.md`、`requirements.txt`。
