# 开源项目清单与调研分层

本文档用于记录图文材料转换器相关的开源项目、参考项目和许可证注意事项。它面向两个用途：

- 开源发布时说明本项目参考、调用、对标了哪些项目。
- 后续接入新后端前，先明确许可证、依赖成本、模型授权和适合的整合边界。

更新时间：2026-06-09 12:17:00  
更新工具/模型：Codex GPT-5

> 注意：本文是工程调研和合规排查清单，不是法律意见。许可证、模型授权、商用条款可能变化；真实分发前必须重新打开上游仓库的 LICENSE、NOTICE、模型卡和发布包逐项确认。

## 当前项目已直接调用或支持的开源工具

| 项目 | 本项目中的角色 | 当前集成方式 | 许可证/分发风险 | 公开项目中的处理建议 |
| --- | --- | --- | --- | --- |
| Pandoc | EPUB、FB2、TXT、ODT、Markdown、HTML、text 等格式转换 | 外部命令 | GPL-family，需携带许可证和源码获取方式 | 作为可选外部命令记录，不混淆为本项目自研能力 |
| Calibre / `ebook-convert` | AZW/AZW3/MOBI/RTF 中间转换 | 外部命令 | GPL-family，整包分发要合规 | 作为可选外部命令记录，不混淆为本项目自研能力 |
| PyMuPDF | PDF 预检、文本层、图片、书签/outline、渲染 | Python 包 API | AGPL-3.0 或商业授权 | 明确许可证边界，保留第三方声明 |
| PyMuPDF4LLM | 文本层 PDF 快速转 Markdown | Python 包 | 基于 PyMuPDF 生态，AGPL/商业授权风险同上 | 同 PyMuPDF |
| MinerU | 复杂/扫描 PDF 结构化解析 | 可选外部后端 | 上游公开信息曾包含 AGPL/强 copyleft 约束，需复核 | 保持可选后端，版本和模型来源单独记录 |
| Marker | 版面感知 PDF/文档解析 | 可选外部后端 | GPL-3.0 级别/商业授权风险需复核 | 保持可选后端，避免把许可证边界写模糊 |
| Docling | Office、HTML、CSV、部分文档/PDF 结构化后端 | 可选 Python 后端 | 官方仓库标注 MIT，但模型/扩展依赖仍需复核 | 继续作为结构化后端候选并记录版本 |
| Microsoft MarkItDown | EPUB/DOCX/PPTX/XLSX/HTML/PDF 的轻量 Markdown baseline | 可选 Python 后端，显式选择后启用 | MIT，仍需记录为独立安装依赖 | 作为 fast comparison/backend-compare 使用，不替代默认推荐管道 |
| OCRmyPDF | 扫描 PDF 预处理为 searchable PDF | 可选外部命令，显式选择后启用 | MPL-2.0，Tesseract/语言包另需记录 | 作为扫描 PDF 预处理，不直接输出 Markdown，不覆盖原 PDF |
| pdfplumber | PDF 版面、坐标、表格候选诊断 | 可选 Python 后端，report 诊断层启用 | MIT，仍需记录为独立安装依赖 | 用于解释质量差、表格页、双栏、页眉页脚噪声，不作为主转换器 |
| Umi-OCR / PaddleOCR-json | 图片、扫描页、本地 OCR 兜底 | 外部本地程序/模块路径 | 需检查程序、模型、PaddleOCR-json 各自许可证 | 保持外部工具接入，程序和模型分别记录 |
| PaddleOCR-VL | 信息图、复杂版面、layout-heavy 图片补强 | 可选 wrapper/命令 | 需检查代码、模型权重、商用条款 | 作为可选增强后端，模型条款单独复核 |
| Qwen-VL | 重型 VLM 图文理解补强 | 可选 wrapper/API | 模型许可和商用条款需逐模型复核 | 作为可选增强后端，模型条款单独复核 |
| tkinterdnd2 | UI 拖放文件 | Python 包 | 需按包许可证附带声明 | 保留第三方声明 |

## 建议优先调研的成熟开源项目

这些项目与本项目定位重叠度高，或能补足现有弱项。优先级按“对当前产品价值”和“复用可能性”排序。

| 优先级 | 项目 | 适合借鉴/接入的层 | 为什么值得看 | 初步许可证判断 | 建议动作 |
| --- | --- | --- | --- | --- | --- |
| P0 | Microsoft MarkItDown | 多格式轻量 baseline、MCP/CLI/API 参考 | 格式覆盖广，LLM-friendly Markdown，MIT，生态热度高 | MIT | 做成可选 fast path 或对标 benchmark |
| P0 | Docling | 结构化文档对象、Office/PDF/HTML 解析 | MIT，本地优先，输出 Markdown/JSON/DoclingDocument | MIT | 已集成，继续加强质量对比和默认策略 |
| P0 | Unstructured | 企业级 ingest、partition、chunking 工作流 | RAG/Agent 文档摄取成熟样板，格式覆盖广 | Apache-2.0 | 重点研究其 partition/chunking/report 设计 |
| P0 | OCRmyPDF | 扫描 PDF 预处理为 searchable PDF | 可先给扫描件加文本层，再走 fast path | MPL-2.0 常见，需复核 | 已接入可选预处理入口；继续补 fixture、fallback 和质量对比 |
| P0 | PaddleOCR / PP-Structure | 中文 OCR、表格、版面结构 | 中文场景强，生态成熟 | Apache-2.0 常见，模型另查 | 重点实测中文扫描件和表格 |
| P1 | Apache Tika | 格式嗅探、元数据、兜底抽文本 | 格式识别/抽文本覆盖极广 | Apache-2.0 | 可作为 inspect/fallback 参考 |
| P1 | pdfplumber | 文本层 PDF 表格/坐标调试 | 适合 text-based PDF 的表格和坐标分析 | MIT | 用于表格/坐标诊断，不做主转换 |
| P1 | Camelot | text-based PDF 表格抽取 | 专项表格 fallback | MIT 常见，需复核依赖 | 作为表格 repair 候选 |
| P1 | Tabula / tabula-py | PDF 表格抽取和 GUI 参考 | 老牌表格提取，小白 UI 思路可借鉴 | MIT/Apache 等需复核 | 可参考交互式表格选择 |
| P1 | GROBID | 学术论文结构、参考文献、TEI | 论文专项解析成熟 | Apache-2.0 常见 | 作为论文专项 heavy path |
| P1 | RapidOCR | 轻量本地 OCR 部署 | 比完整 PaddleOCR 更易部署 | Apache-2.0 常见，模型另查 | 低配 CPU OCR 候选 |
| P1 | Tesseract | 经典离线 OCR | 兜底稳定、部署资料多 | Apache-2.0 | 可作为 OCRmyPDF 依赖或兜底 |
| P1 | Surya | OCR/layout/reading order/table | Marker 生态底层能力之一，适合视觉版面 | 需复核 | 复杂版面研究候选 |
| P1 | Crawl4AI | 网页资料转 Markdown | Agent/RAG 网页摄取成熟 | Apache-2.0 + 额外 attribution 要求 | 只作参考；网页抓取统一复用 `web-content-fetcher` |
| P1 | Trafilatura | 网页正文/metadata 抽取 | 轻量网页正文抽取 | Apache-2.0 | 只作参考；网页抓取统一复用 `web-content-fetcher` |
| P2 | MegaParse | LLM ingest 多格式 parser | 对标“no information loss”解析思路 | Apache-2.0 常见 | 调研输出 schema 和质量报告 |
| P2 | OmniParse | 本地多模态 ingest + UI | 多模态、本地、Gradio UI 形态可参考 | 需复核 | 研究 UI/打包/多模态流水线 |
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

## 云端与闭源对标项目

这些不一定是开源项目，但能验证市场需求、API 形态和质量基准。

| 产品 | 对标点 | 对本项目启示 |
| --- | --- | --- |
| LlamaParse | Agentic document parser，layout-aware OCR，Markdown/JSON | 可作为在线增强层高质量 baseline |
| Mistral OCR | 文档 OCR、表格、结构保持 | 表格/手写/复杂版式的质量标杆 |
| Azure AI Document Intelligence | 文本、表格、bbox、confidence、Markdown output | 在线 provider schema 可参考 confidence/bbox |
| Google Document AI | OCR、layout、表单、表格、checkbox | 企业文档抽取 API 对标 |
| Amazon Textract | 表格、表单、layout elements | 结构化抽取对标 |
| ABBYY | 老牌 OCR/文档智能 | OCR 质量和产品体验参考 |
| Mathpix | 数学公式、科学文档 OCR | 论文/公式场景对标 |
| Reducto | 多模型文档解析与抽取流程 | 学习 parse/classify/split/extract/edit 分层 |

## 许可证与依赖风险分层

### 相对低风险候选

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

### 高风险：强 copyleft 或授权边界明显

这些不是不能用，而是必须在公开项目文档里明确标注许可证边界：

- PyMuPDF / PyMuPDF4LLM：AGPL-3.0 或商业授权。
- Marker：GPL-3.0 级别/商业授权风险需复核。
- MinerU：公开信息曾出现 AGPL/强 copyleft 约束，必须复核当前版本。
- Calibre / Pandoc：GPL-family，分发时要保留许可证、源码获取方式和对应义务。
- paperless-ngx：GPL 系产品形态参考，不建议直接作为本项目组件混入。

## 下一步调研队列

1. MarkItDown：跑公开 fixture，对比 fast path、MCP、Office/HTML/图片能力。
2. OCRmyPDF：基础入口已接入；继续验证扫描 PDF 先加文本层后再走 PyMuPDF/Docling 的效果。
3. PaddleOCR / RapidOCR：验证中文扫描件、截图、表格块坐标。
4. pdfplumber / Camelot：验证 text-based PDF 表格检测和表格 repair。
5. Apache Tika：验证格式嗅探和非主流格式抽文本。
6. Unstructured：研究 partition/chunking 和企业 ingest 报告。
7. GROBID：研究论文/参考文献专项路径。

## 本地源码审计结果（首批）

本节记录 2026-06-09 对首批候选项目的本地源码审计结果。审计重点不是“项目主页写了什么”，而是看仓库里的入口、依赖、许可证、构建形态和适合本项目复用的边界。结论遵循本项目的工具优先原则：优先复用成熟工具，只写调度层、wrapper、配置、日志、质量评估和恢复逻辑。

| 项目 | 审计版本 | 源码里确认的入口/形态 | 许可证观察 | 适合整合的模块 | 判断 |
| --- | --- | --- | --- | --- | --- |
| MarkItDown | `e144e0a` | `MarkItDown` Python 类、CLI、`markitdown-mcp` 包；支持本地文件、URL、stream、URI、response 多入口 | MIT | 多格式轻量 baseline、MCP schema 参考、Office/HTML/图片的快速对照组 | 推荐 P0 可选接入。不要替代现有总控和质量评估，作为 `markitdown_backend` fast path 与 benchmark 更稳。 |
| OCRmyPDF | `32013f4` | CLI `ocrmypdf`，核心目标是给扫描 PDF 增加 OCR 文本层；依赖 Tesseract、pikepdf、pypdfium2、pdfminer.six 等 | MPL-2.0 | 扫描 PDF 预处理 | 推荐 P0 接入。最稳路径是 `scanned.pdf -> searchable.pdf -> 现有 PDF 管道`，而不是直接让它输出 Markdown。 |
| pdfplumber | `9804153` | Python API + CLI；暴露 `chars`、`lines`、`rects`、`images`、table extraction、visual debugging | MIT | PDF 预检、表格/坐标诊断、疑难页解释 | 推荐 P1 接入。适合 text-based PDF 的结构诊断，不适合作为整本 Markdown 主转换器。 |
| Camelot | `a136fc0` | CLI + Python API；`lattice`、`stream`、`network`、`hybrid`、`auto` parser；表格可导出 Markdown/CSV/JSON/Excel | MIT | text-based PDF 表格专项抽取和 repair | 推荐 P1 可选接入。只在表格页或用户明确要求表格时触发，避免拖慢普通文档。 |
| RapidOCR | `7b2d368` | `python/rapidocr/main.py` 中 `RapidOCR` 类，`__call__` 返回 OCR 结果；支持 ONNXRuntime、TensorRT、Paddle、OpenVINO、PyTorch、MNN 等推理后端 | Apache-2.0 | 低配离线 OCR、Umi-OCR 的 Python 轻量补充 | 推荐 P1 接入。适合 CPU 离线环境，但模型文件和具体推理后端仍需单独记录版本与许可。 |
| Apache Tika | `8a7728a` | Java 17 + Maven 多模块；`tika-app`、`tika-server`、format detect、metadata、structured text extraction | Apache-2.0 | 格式嗅探、metadata、非主流格式兜底抽文本 | 推荐 P1 只做外部服务/外部 jar 调用。不要把 Java/Maven 构建塞进基础包；可配置 `tika-app.jar` 或 Tika Server。 |
| GROBID | `8ca2585` | Java/Gradle 服务，Web service API、Docker、fulltext/header/reference TEI；专注技术/科学 PDF | Apache-2.0 | 学术论文、参考文献、TEI、论文结构专项 | 推荐 P2 专项接入。不是通用 PDF 转 Markdown；Windows 源码 checkout 出现长路径问题，且上游说明 Windows 支持不稳定，适合 Docker/HTTP heavy backend。 |
| Crawl4AI | `cdf2ead` | `AsyncWebCrawler`、CLI `crwl`、Docker server、MCP SSE/WebSocket/schema；依赖 Playwright/Patchright/LiteLLM 等 | Apache-2.0，LICENSE 额外要求显著 attribution | Web 抓取/下载/MCP 设计参考 | 不直接整合。网页内容获取、抓取、下载、归档统一复用已有 `web-content-fetcher`；Crawl4AI 只作为 MCP/API/异步爬虫设计参考。 |
| Trafilatura | `2f4702d` | Python API `fetch_url` / `extract`，CLI `trafilatura`，输出 CSV/JSON/HTML/Markdown/TXT/XML | Apache-2.0 | 轻量网页正文抽取参考 | 不直接整合。若未来 `web-content-fetcher` 需要轻量正文抽取增强，应在该项目里接入，而不是在本项目重复实现网页抓取。 |

### 网页抓取相关的明确决策

网页内容获取、抓取、下载、登录态复用、归档和重建，不在本项目重复造轮子。本项目只处理两类输入：

- `web-content-fetcher` 已生成的 archive/rebuild 输入：本项目只做视觉复查、OCR 补强、版面块、表格候选和图片位置证据。
- 普通 HTML/网页导出的本地文件：仍按本地文件转换处理，不主动爬取 URL。

这样可以避免 Crawl4AI、Trafilatura、浏览器自动化、下载归档、登录态管理在两个项目里重复维护。后续如果要增强网页抓取，应优先改 `web-content-fetcher`，本项目只消费它的稳定产物。

## 按模块的整合状态矩阵

本节用于区分“已经进入当前代码管道的开源项目”和“仍是候选/参考项目”。这里的“已整合”指当前项目已有直接命令调用、Python API 调用、wrapper、配置入口、测试或 agent 契约；“未整合”指目前主要停留在调研、对标或待实验状态。

### 总控、路由与 Agent 入口

| 模块 | 已整合项目/能力 | 未整合候选 | 下一步建议 |
| --- | --- | --- | --- |
| CLI / UI / HTTP / MCP | 自研 CLI、Tkinter UI、HTTP API、MCP stdio | MarkItDown MCP、Docling MCP、Markdownify MCP | 保持自研统一入口，借鉴它们的工具 schema、安装体验和缓存机制。 |
| 批处理 / handoff / `next_actions` | 自研 manifest、`run_summary`、agent recipes、handoff bundle | Unstructured workflow、Unstract | 学习 pipeline/任务状态和企业化 ingest 设计，不急着引入。 |
| 格式预检 / inspect | PyMuPDF、自研 PDF 预检、质量评分 | Apache Tika、pdfplumber、kreuzberg | Tika 可补超多格式嗅探；pdfplumber 可补 PDF 表格/坐标预检。 |

### 电子书、Office 与通用文档转换

| 模块 | 已整合项目/能力 | 未整合候选 | 下一步建议 |
| --- | --- | --- | --- |
| EPUB / FB2 / TXT / ODT | Pandoc | MarkItDown | MarkItDown 可作为轻量多格式 baseline，对比 Pandoc 输出质量。 |
| AZW / AZW3 / MOBI / RTF | Calibre `ebook-convert` + Pandoc | MarkItDown、Apache Tika | Calibre 仍是主力；Tika 更适合兜底抽文本和格式识别。 |
| DOCX / PPTX / XLSX / HTML / CSV | Docling 可选后端，Pandoc fallback | MarkItDown、Unstructured、Mammoth、LibreOffice headless | Docling 继续做主结构化后端；MarkItDown 可作为更轻的可选后端。 |

### PDF 解析与结构增强

| 模块 | 已整合项目/能力 | 未整合候选 | 下一步建议 |
| --- | --- | --- | --- |
| PDF fast path | PyMuPDF、PyMuPDF4LLM、自研 PyMuPDF text fallback | pdfplumber、pypdf、pdfminer.six、PDFBox | 优先评估 pdfplumber，用于表格/坐标诊断；pypdf/pdfminer 可做轻量兜底。 |
| 复杂 PDF / 结构化 PDF | MinerU、Marker、Docling 可选管道 | RAGFlow DeepDoc、Surya、MegaParse | 先用真实样本压测现有三条重管道，再决定是否接新后端。 |
| PDF bookmark / 字体标题修复 | PyMuPDF outline、font candidates、自研 `structure_repair` | GROBID、pdf-craft | GROBID 只适合论文专项；pdf-craft 适合扫描书/截图书专项。 |
| 扫描 PDF | OCRmyPDF 预处理、Umi-OCR、MinerU、Marker、Docling fallback | PaddleOCR、RapidOCR、Tesseract | OCRmyPDF 已作为显式预处理入口；下一步补扫描 PDF fixture 和失败 fallback。 |

### 图片、信息图与截图书

| 模块 | 已整合项目/能力 | 未整合候选 | 下一步建议 |
| --- | --- | --- | --- |
| 普通图片 OCR | Umi-OCR / PaddleOCR-json | RapidOCR、Tesseract、CnOCR | RapidOCR 适合低配离线包；Tesseract 可做经典兜底。 |
| 信息图 / layout-heavy 图片 | PaddleOCR-VL wrapper、Qwen-VL wrapper、MinerU VLM 路由 | Surya、GOT-OCR 2.0、olmOCR、Pix2Text | 先继续打磨 PaddleOCR-VL/Qwen-VL；Pix2Text 值得测中文公式和图片。 |
| 截图乱序/重复重建 | 自研 `image_book_rebuilder` | pdf-craft、paperless-ngx | pdf-craft 可参考扫描书目录/脚注；paperless-ngx 只作为产品形态参考。 |

### 表格、公式与学术专项

| 模块 | 已整合项目/能力 | 未整合候选 | 下一步建议 |
| --- | --- | --- | --- |
| 表格检测 / 表格修复 | Docling/MinerU/Marker 输出 + 自研质量判断 | Camelot、Tabula、pdfplumber、PaddleOCR PP-Structure | text-based PDF 表格优先接 Camelot/pdfplumber；扫描表格看 PaddleOCR。 |
| 公式 / 科研 PDF | Marker/MinerU/Docling 可选 | GROBID、Nougat、Pix2Text、Mathpix 对标 | GROBID 适合论文结构，不是通用 PDF；Nougat/GPU 成本较高。 |
| 参考文献 / DOI / 论文结构 | 暂无专项管道 | GROBID | 若真实用户有论文场景，再做 `academic_pdf` 专项路由。 |

### 网页、URL 与 Web Archive

| 模块 | 已整合项目/能力 | 未整合候选 | 下一步建议 |
| --- | --- | --- | --- |
| Web archive 视觉复查 | 自研 `process_web_archive` + 复用 `web-content-fetcher` archive 产物 | Crawl4AI、Trafilatura、Jina Reader | 网页抓取/下载/归档统一放在 `web-content-fetcher`；本项目只做 archive 的视觉复查和图文补强。 |

### 在线 API 与云端增强

| 模块 | 已整合项目/能力 | 未整合候选 | 下一步建议 |
| --- | --- | --- | --- |
| Provider 抽象 | `OcrLayoutProvider`、`VlmLayoutProvider`、`TextStructureProvider`、`EmbeddingProvider`，OpenAI-compatible 示例 | LlamaParse、Mistral OCR、Azure Document Intelligence、Google Document AI、Amazon Textract | 先保持 OpenAI-compatible 抽象，再按真实需求接具体供应商。 |
| 文本结构修复 | 本地 `structure_repair` + online enhancement 接口 | Marker LLM service 模式、Reducto | 不要在每个管道里分散写 API，继续走统一 provider。 |

### 建议的下一批整合优先级

| 优先级 | 项目 | 对应模块 | 理由 |
| --- | --- | --- | --- |
| 1 | Camelot | PDF 表格专项抽取 | pdfplumber 诊断已接入；Camelot 继续补 text-based PDF 表格专项抽取。 |
| 2 | RapidOCR | 低配本地 OCR | 适合 CPU 机器和轻量 OCR fallback。 |
| 3 | Apache Tika | 格式识别和兜底抽文本 | 补非主流格式嗅探和 metadata/text fallback。 |
| 4 | GROBID | 学术论文专项 | 只在论文/参考文献场景明确时接入。 |
| 5 | Crawl4AI / Trafilatura | 网页资料采集 | 不在本项目直接接入；作为 `web-content-fetcher` 的参考候选。 |

MarkItDown 已完成第一步可选接入，后续任务转为扩大对比样本和记录质量差异，而不是继续作为待接入候选。
OCRmyPDF 已完成可选预处理入口，后续任务转为补前后文本层质量指标、失败 fallback 和公开扫描 PDF fixture。
pdfplumber 已完成 report 诊断入口，后续任务转为补 Camelot 专项抽取、UI 复查清单显示和表格保留率质量指标。

## 已核验来源

- Microsoft MarkItDown GitHub：MIT license。
- Docling GitHub / IBM 资料：Docling codebase under MIT license。
- Unstructured GitHub：Apache-2.0 license。
- PyMuPDF / MuPDF 官方资料：AGPL-3.0 或商业授权路线。
- 本项目现有文档：`THIRD_PARTY_NOTICES.md`、`docs/REFERENCES_AND_REUSE.md`、`requirements.txt`。
