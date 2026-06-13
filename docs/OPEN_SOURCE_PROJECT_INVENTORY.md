# 开源项目清单与调研分层

本文档用于记录图文材料转换器相关的开源项目、参考项目和许可证注意事项。它面向两个用途：

- 开源发布时说明本项目参考、调用、对标了哪些项目。
- 后续接入新后端前，先明确许可证、依赖成本、模型授权和适合的整合边界。

更新时间：2026-06-13 12:11:45
更新工具/模型：Codex GPT-5

> 注意：本文是工程调研和合规排查清单，不是法律意见。许可证、模型授权、商用条款可能变化；真实分发前必须重新打开上游仓库的 LICENSE、NOTICE、模型卡和发布包逐项确认。

本轮源码审计使用的是本机未提交的第三方源码缓存目录。该目录只用于审计，不属于本仓库发布内容。本轮重点补齐此前只停留在候选阶段的项目：Tabula、Surya、Pix2Text、olmOCR、GOT-OCR、pdf-craft、paperless-ngx，以及已经被本项目调用但文档中没有源码级结论的 Pandoc、Calibre、PyMuPDF、PyMuPDF4LLM、MinerU、Marker、Docling、Umi-OCR、PaddleOCR-json、PaddleOCR/Qwen-VL、tkinterdnd2 等。

## 当前项目已直接调用或支持的开源工具

| 项目 | 本项目中的角色 | 当前集成方式 | 许可证/分发风险 | 公开项目中的处理建议 |
| --- | --- | --- | --- | --- |
| Pandoc | EPUB、FB2、TXT、ODT、Markdown、HTML、text 等格式转换 | 外部命令 | 源码审计版本 `f751000`：`pandoc.cabal` 标注 GPL-2.0-or-later | 作为可选外部命令记录，不混淆为本项目自研能力 |
| Calibre / `ebook-convert` | AZW/AZW3/MOBI/RTF 中间转换 | 外部命令 | 源码审计版本 `7b7875d`：`pyproject.toml` 标注 GPL-3.0-only；整包分发要合规 | 作为可选外部命令记录，不混淆为本项目自研能力 |
| PyMuPDF | PDF 预检、文本层、图片、书签/outline、渲染 | Python 包 API | AGPL-3.0 或商业授权 | 明确许可证边界，保留第三方声明 |
| PyMuPDF4LLM | 文本层 PDF 快速转 Markdown | Python 包 | 基于 PyMuPDF 生态，AGPL/商业授权风险同上 | 同 PyMuPDF |
| MinerU | 复杂/扫描 PDF 结构化解析 | 可选外部后端 | 源码审计版本 `cee1fe1`：`LicenseRef-MinerU-Open-Source-License`，基于 Apache-2.0 但有额外商业阈值/署名要求；模型授权另查 | 保持可选重后端，版本、模型来源和商业边界单独记录 |
| Marker | 版面感知 PDF/文档解析 | 可选外部后端 | 源码审计版本 `d3739db`：`marker-pdf` 标注 GPL-3.0-or-later；README 说明模型权重另有 modified AI Pubs Open Rail-M 条款 | 保持可选后端，避免把代码许可证和模型权重条款混写 |
| Docling | Office、HTML、CSV、部分文档/PDF 结构化后端 | 可选 Python 后端 | 源码审计版本 `6e031d9`：`docling-slim` MIT；VLM/OCR 模型和扩展包另查 | 继续作为结构化后端候选并记录版本 |
| Microsoft MarkItDown | EPUB/DOCX/PPTX/XLSX/HTML/PDF 的轻量 Markdown baseline | 可选 Python 后端，显式选择后启用 | MIT，仍需记录为独立安装依赖 | 作为 fast comparison/backend-compare 使用，不替代默认推荐管道 |
| OCRmyPDF | 扫描 PDF 预处理为 searchable PDF | 可选外部命令，显式选择后启用 | MPL-2.0，Tesseract/语言包另需记录 | 作为扫描 PDF 预处理，不直接输出 Markdown，不覆盖原 PDF |
| pdfplumber | PDF 版面、坐标、表格候选诊断 | 可选 Python 后端，report 诊断层启用 | MIT，仍需记录为独立安装依赖 | 用于解释质量差、表格页、双栏、页眉页脚噪声，不作为主转换器 |
| Umi-OCR / PaddleOCR-json | 图片、扫描页、本地 OCR 兜底 | 外部本地程序/模块路径 | 源码审计：Umi-OCR `83173ef` 为 MIT；PaddleOCR-json `1beac1c` 为 Apache-2.0；具体 OCR 模型/发布包另查 | 保持外部工具接入，程序和模型分别记录 |
| PaddleOCR-VL | 信息图、复杂版面、layout-heavy 图片补强 | 可选 wrapper/命令 | 源码审计版本 `c166448`：PaddleOCR 代码 Apache-2.0；PaddleOCR-VL/模型权重条款另查 | 作为可选增强后端，模型条款单独复核 |
| Qwen-VL | 重型 VLM 图文理解补强 | 可选 wrapper/API | 源码审计版本 `9658872`：代码 Apache-2.0；Qwen2/Qwen2.5/Qwen3-VL 模型卡和权重条款逐模型复核 | 作为可选增强后端，模型条款单独复核 |
| tkinterdnd2 | UI 拖放文件 | Python 包 | 源码审计版本 `28bcf1c`：MIT；封装 tkDnD/TkinterDnD2 | 保留第三方声明 |

## 建议优先调研的成熟开源项目

这些项目与本项目定位重叠度高，或能补足现有弱项。优先级按“对当前产品价值”和“复用可能性”排序。

| 优先级 | 项目 | 适合借鉴/接入的层 | 为什么值得看 | 初步许可证判断 | 建议动作 |
| --- | --- | --- | --- | --- | --- |
| P0 | Microsoft MarkItDown | 多格式轻量 baseline、MCP/CLI/API 参考 | 格式覆盖广，LLM-friendly Markdown，MIT，生态热度高 | MIT | 做成可选 fast path 或对标 benchmark |
| P0 | Docling | 结构化文档对象、Office/PDF/HTML 解析 | MIT，本地优先，输出 Markdown/JSON/DoclingDocument | MIT | 已集成，继续加强质量对比和默认策略 |
| P0 | Unstructured | 企业级 ingest、partition、chunking 工作流 | RAG/Agent 文档摄取成熟样板，格式覆盖广 | Apache-2.0 | 重点研究其 partition/chunking/report 设计 |
| P0 | OCRmyPDF | 扫描 PDF 预处理为 searchable PDF | 可先给扫描件加文本层，再走 fast path | 源码审计 `32013f4`：MPL-2.0 | 已接入可选预处理入口；继续补 fixture、fallback 和质量对比 |
| P0 | PaddleOCR / PP-Structure | 中文 OCR、表格、版面结构 | 中文场景强，生态成熟 | 源码审计 `c166448`：Apache-2.0，模型另查 | 重点实测中文扫描件和表格 |
| P1 | Apache Tika | 格式嗅探、元数据、兜底抽文本 | 格式识别/抽文本覆盖极广 | Apache-2.0 | 可作为 inspect/fallback 参考 |
| P1 | pdfplumber | 文本层 PDF 表格/坐标调试 | 适合 text-based PDF 的表格和坐标分析 | MIT | 用于表格/坐标诊断，不做主转换 |
| P1 | Camelot | text-based PDF 表格抽取 | 专项表格 fallback | 源码审计 `a136fc0`：MIT | 作为表格 repair 候选 |
| P1 | Tabula / tabula-py | PDF 表格抽取和 GUI 参考 | 老牌表格提取，小白 UI 思路可借鉴 | 源码审计：Tabula Java `2cdf3b4` MIT，tabula-py `d7a233b` MIT | 可参考交互式表格选择；优先级低于 Camelot/pdfplumber |
| P1 | GROBID | 学术论文结构、参考文献、TEI | 论文专项解析成熟 | 源码审计 `8ca2585`：Apache-2.0 | 作为论文专项 heavy path |
| P1 | RapidOCR | 轻量本地 OCR 部署 | 比完整 PaddleOCR 更易部署 | 源码审计 `7b2d368`：Apache-2.0，模型另查 | 低配 CPU OCR 候选 |
| P1 | Tesseract | 经典离线 OCR | 兜底稳定、部署资料多 | 源码审计 `f4afb2c`：Apache-2.0 | 可作为 OCRmyPDF 依赖或兜底 |
| P1 | Surya | OCR/layout/reading order/table | Marker 生态底层能力之一，适合视觉版面 | 源码审计 `17452f3`：Apache-2.0，模型另查 | 复杂版面研究候选 |
| P1 | Crawl4AI | 网页资料转 Markdown | Agent/RAG 网页摄取成熟 | Apache-2.0 + 额外 attribution 要求 | 只作参考；网页抓取统一复用 `web-content-fetcher` |
| P1 | Trafilatura | 网页正文/metadata 抽取 | 轻量网页正文抽取 | Apache-2.0 | 只作参考；网页抓取统一复用 `web-content-fetcher` |
| P2 | MegaParse | LLM ingest 多格式 parser | 对标“no information loss”解析思路 | 源码审计 `ba9a24a`：Apache-2.0，云模型依赖另查 | 参考输出 schema 和质量报告 |
| P2 | OmniParse | 本地多模态 ingest + UI | 多模态、本地、Gradio UI 形态可参考 | 源码审计 `9d1ae83`：Apache-style，adapted code/模型另查 | 产品/服务形态参考，不建议直接混入 |
| P2 | pdf-craft | 扫描书籍到 Markdown/EPUB | 和“截图书/扫描书”场景高度相关 | 源码审计 `f463a4e`：MIT，DeepSeek OCR/LLM 配置另查 | 实测扫描书目录/脚注/公式 |
| P2 | olmOCR | 扫描文档 OCR/VLM | 扫描文档质量候选 | 源码审计 `f7cfe4c`：Apache-2.0，模型许可另查 | 作为 VLM OCR 对比项 |
| P2 | GOT-OCR 2.0 | 轻量视觉 OCR | 单机 GPU/较小模型路线 | 源码审计 `179ed08`：demo/模型授权需分别复核 | 作为低成本 VLM 实验候选 |
| P2 | Pix2Text | 中文社区 OCR/公式/版面 | 中文图文、公式、表格场景可测 | 源码审计 `f881e9d`：MIT，模型依赖另查 | 中文专项候选 |
| P2 | paperless-ngx | 文档归档/OCR/检索产品形态 | 虽不主打 Markdown，但适合学习资料管理闭环 | 源码审计 `82aefe5`：GPL-3.0-only | 产品化参考，不建议直接混入 |

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
- Tabula / tabula-py
- Pix2Text
- PaddleOCR-json
- tkinterdnd2

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
- pdf-craft 的 DeepSeek OCR/LLM 配置

### 高风险：强 copyleft 或授权边界明显

这些不是不能用，而是必须在公开项目文档里明确标注许可证边界：

- PyMuPDF / PyMuPDF4LLM：AGPL-3.0 或商业授权。
- Marker：GPL-3.0-or-later；模型权重条款和商业自托管边界另查。
- MinerU：当前源码为 `LicenseRef-MinerU-Open-Source-License`，基于 Apache-2.0 但带额外商业阈值/署名要求；模型条款另查。
- Calibre / Pandoc：GPL-family，分发时要保留许可证、源码获取方式和对应义务。
- paperless-ngx：GPL 系产品形态参考，不建议直接作为本项目组件混入。

## 下一步实验队列

源码审计后，下一步不再是“看项目主页”，而是用公开 fixture 和真实低风险样本跑质量对比：

1. Pix2Text：验证中文图片、公式、截图页到 Markdown 的质量和安装成本。
2. pdf-craft：验证扫描书/截图书的目录、脚注、公式和 TOC 假设恢复能力。
3. Surya：验证 layout-heavy 图片、表格、reading order，重点看本机或远程 GPU 成本。
4. PaddleOCR / PaddleOCR-VL：验证中文扫描件、截图、表格块坐标和信息图补强质量。
5. Tabula / Camelot / pdfplumber：验证 text-based PDF 表格抽取差异，决定是否还需要 Tabula。
6. Apache Tika：验证格式嗅探和非主流格式抽文本。
7. GROBID：只在论文/参考文献场景明确时验证专项路径。

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

## 本地源码审计结果（第二批：已接入重后端与候选项目）

本节记录 2026-06-13 对此前未落文档的项目进行源码级补充审计的结果。审计证据来自本地 clone 的 `LICENSE`、`pyproject.toml`、`setup.py`、`pom.xml`、README 和关键入口源码；重点判断“适合直接整合、只适合作为外部可选后端，还是只适合作为产品/架构参考”。

### 已接入或已调用项目的源码审计补充

| 项目 | 审计版本 | 源码里确认的入口/形态 | 许可证观察 | 适合整合的模块 | 判断 |
| --- | --- | --- | --- | --- | --- |
| Pandoc | `f751000` | Haskell 多格式转换器；`pandoc.cabal` 包含 EPUB/Markdown reader/writer 模块 | GPL-2.0-or-later | EPUB/FB2/TXT/ODT/HTML/Markdown 的外部转换器 | 继续只作为外部命令调用，不 vendor，不包装成自研解析能力。 |
| Calibre / `ebook-convert` | `7b7875d` | `src/calibre/ebooks/conversion/cli.py` 暴露 conversion subsystem；插件覆盖 MOBI/EPUB/FB2/RTF/PDF 等 | GPL-3.0-only | AZW/AZW3/MOBI/RTF 到 EPUB/中间格式转换 | 继续只调用用户安装的 `ebook-convert`。分发 U 盘或安装包时不能悄悄捆绑整包。 |
| PyMuPDF | `7dd4608` | `pymupdf`/legacy `fitz` Python API；PDF 渲染、文本、图片、表格、OCR 支持 | AGPL-3.0 或 Artifex Commercial License | PDF 预检、文本层、outline、渲染和分页 | 已是核心 Python 依赖；公开发布继续使用 AGPL-3.0 项目许可证和第三方声明。 |
| PyMuPDF4LLM | `2bad214` | `to_markdown`、`to_json`、`to_text`，基于 PyMuPDF 和 pymupdf-layout；包含 header/TOC 识别 | AGPL-3.0 | 文本层 PDF 快速 Markdown baseline | 保持 fast fallback；不用它处理扫描件主流程。 |
| MinerU | `cee1fe1` | CLI `mineru`、`mineru-api`、`mineru-router`、VLM/OpenAI server；pipeline 与 VLM engine 分离 | `LicenseRef-MinerU-Open-Source-License`，Apache-2.0-based 但有额外商业阈值/署名要求；模型另查 | 复杂 PDF、扫描 PDF、结构化 Markdown | 继续作为可选重后端。默认路径不强依赖；健康检查要记录版本、模型和 GPU 状态。 |
| Marker | `d3739db` | CLI `marker`、`marker_single`、server、chunk convert；内部有 Providers/Builders/Processors/Renderers/Converters | GPL-3.0-or-later；模型权重另有 modified AI Pubs Open Rail-M 条款 | 版面感知 PDF/图片/Office 解析，LLM 表格/结构修复模式参考 | 保持可选后端；吸收其可插拔 LLM service 模式到本项目 provider 抽象。 |
| Docling | `6e031d9` | CLI `docling`、`DocumentConverter`、`DoclingDocument`、VLM pipeline、Docling serve/client | MIT；VLM/OCR 模型和扩展依赖另查 | Office/HTML/CSV/PDF 结构化后端，document object 参考 | 适合继续做结构化后端和对象模型参考；默认仍 local-first、轻依赖优先。 |
| PaddleOCR / PP-Structure / PaddleOCR-VL | `c166448` | Python 包 `paddleocr`；导出 `PaddleOCR`、`PaddleOCRVL`、`PPStructureV3`、official API client/async client | Apache-2.0；模型权重、官方 API、Paddle runtime 另查 | 中文 OCR、表格、版面、信息图补强 | 适合做可选 OCR/layout provider；不要在主路径硬依赖 PaddlePaddle/GPU。 |
| Umi-OCR | `83173ef` | Windows/local GUI OCR 工具；README 说明可输出 txt/jsonl/md/csv，并有插件/引擎分发形态 | MIT；打包发布中的 OCR 引擎和模型另查 | 本机人工 OCR 与快速兜底 | 继续作为外部工具路径配置，不把它当 Python 库嵌入。 |
| PaddleOCR-json | `1beac1c` | `PaddleOCR-json.exe -image_path=...`；Python/Node/PowerShell API 通过子进程 stdin/stdout 或端口传 JSON | Apache-2.0；PaddleOCR 模型和发布包另查 | Umi-OCR 兼容 OCR engine、图片 OCR JSON 块 | 适合作为 Windows 本地 OCR 外部进程；本项目只写 wrapper、日志和失败恢复。 |
| Qwen-VL | `9658872` | Transformers/vLLM/SGLang/OpenAI-style API 示例；代码含 fine-tune、utils、Docker/web demo | 代码 Apache-2.0；Qwen2/Qwen2.5/Qwen3-VL 模型权重条款逐模型复核 | 信息图、复杂图片、视觉结构补强 | 只作为可选 VLM provider/远程 API；没有模型或 key 时项目必须完全可用。 |
| tkinterdnd2 | `28bcf1c` | Python wrapper for TkinterDnD2/tkDnD；README 展示安装与 Tk 拖放扩展形态 | MIT | UI 文件/文件夹拖放 | 可作为轻量 UI 依赖；缺失时保留普通文件选择按钮。 |

### 候选/参考项目的源码审计补充

| 项目 | 审计版本 | 源码里确认的入口/形态 | 许可证观察 | 适合整合的模块 | 判断 |
| --- | --- | --- | --- | --- | --- |
| Unstructured | `5ead69a` | CLI `unstructured`、`partition`/`partition_pdf`/`partition_text`、chunking、OCR agents、ingest connectors | Apache-2.0；可选 extras 依赖很重 | partition/chunking/report 设计、企业 ingest 参考 | 不进默认路径。适合学习 chunk by title/page、OCR agent 和 ingest 状态设计。 |
| Tabula Java | `2cdf3b4` | Maven main class `technology.tabula.CommandLineApp`；`BasicExtractionAlgorithm`、`SpreadsheetExtractionAlgorithm`、CSV/JSON/TSV writers | MIT | text-based PDF 表格抽取 | 可作为表格专项 fallback，但 Camelot/pdfplumber 已覆盖大部分当前需求，优先级低。 |
| tabula-py | `d7a233b` | Python wrapper；`read_pdf`、`convert_into`、`convert_into_by_batch`，可走 Java subprocess 或 jpype | MIT | Python 表格抽取 wrapper | 如果接 Tabula，优先通过 tabula-py 或外部 jar，不直接改 Java 源码。 |
| Tesseract | `f4afb2c` | C/C++ `TessBaseAPI`、C API、CLI；可输出 UTF8、HOCR、TSV、ALTO、PAGE 等 | Apache-2.0 | OCRmyPDF 依赖、经典 OCR 兜底 | 作为依赖健康检查和兜底 OCR 参考；当前机器上配置坏时不应阻塞主流程。 |
| Surya | `17452f3` | CLI `surya_ocr`、`surya_layout`、`surya_table`、`surya_gui`；VLM backend 可用 vLLM/llama.cpp 或 `SURYA_INFERENCE_URL` | Apache-2.0；模型运行与权重另查 | OCR/layout/reading-order/table、Marker 生态底层能力 | 值得作为信息图/复杂版面实验项，但模型服务较重，不进入默认路径。 |
| MegaParse | `ba9a24a` | Python `MegaParse`、`MegaParseVision`；依赖 Unstructured、LlamaParse、LangChain/OpenAI/Anthropic、Playwright 等 | Apache-2.0 | 多格式 LLM ingest schema 参考 | 依赖云模型和重 ingest 生态，不适合直接整合；可参考“无信息损失”评估口径。 |
| OmniParse | `9d1ae83` | FastAPI/Gradio server；`/parse_document`、`/parse_image`、`/parse_media`、`/parse_website`；依赖 Marker、Surya、Crawl4AI 等 | Apache-style；部分 adapted code/模型另查 | 多模态服务和 UI 产品形态参考 | 不直接整合，因为它已经是另一层 orchestration，会和本项目调度层重复。 |
| pdf-craft | `f463a4e` | Python API `transform_markdown`、`transform_epub`；面向扫描书，支持 `ocr_size`、`toc_llm`、`toc_assumed` | MIT；DeepSeek OCR/LLM/API/model 另查 | 扫描书、截图书、目录/TOC 重建 | 很值得实测，但不进默认路径；优先吸收 TOC/章节假设和分段恢复思路。 |
| olmOCR | `f7cfe4c` | CLI `olmocr` / `python -m olmocr.pipeline`；支持大规模 PDF batch、VLLM/SGLang、bench runner | Apache-2.0；模型和运行时另查 | 重型 VLM OCR benchmark、远程 GPU OCR | 不适合本地默认；适合作为云/GPU provider 的质量对标。 |
| GOT-OCR 2.0 | `179ed08` | Demo 脚本 `run_ocr_2.0.py` / crop/multi-page；`AutoModelForCausalLM` + `trust_remote_code=True` + CUDA | 代码/模型条款需分别复核；demo 默认 CUDA | 轻量视觉 OCR 实验项 | 研究/demo 属性强，不建议整合默认；只可做显式实验 provider。 |
| Pix2Text | `f881e9d` | CLI `predict`、Python `Pix2Text.recognize`、server；支持 PDF/page/text_formula/formula/text 等类型 | MIT；CnOCR/EasyOCR/模型另查 | 中文图片、公式、版面、PDF 到 Markdown 专项 | 值得列入中文专项 benchmark；是否接入取决于真实样本质量和安装成本。 |
| paperless-ngx | `82aefe5` | Django/Celery/Redis 文档归档系统；consume folder、OCRmyPDF/Tesseract、REST/UI | GPL-3.0-only | 文档归档、批处理、人工复查产品形态参考 | 不是 Markdown 转换组件，不建议作为依赖混入；可学习“导入-识别-索引-复查”产品闭环。 |

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
| 格式预检 / inspect | PyMuPDF、pdfplumber、自研 PDF 预检、质量评分 | Apache Tika、kreuzberg | Tika 可补超多格式嗅探；pdfplumber 已用于 PDF 表格/坐标诊断。 |

### 电子书、Office 与通用文档转换

| 模块 | 已整合项目/能力 | 未整合候选 | 下一步建议 |
| --- | --- | --- | --- |
| EPUB / FB2 / TXT / ODT | Pandoc | MarkItDown | MarkItDown 可作为轻量多格式 baseline，对比 Pandoc 输出质量。 |
| AZW / AZW3 / MOBI / RTF | Calibre `ebook-convert` + Pandoc | MarkItDown、Apache Tika | Calibre 仍是主力；Tika 更适合兜底抽文本和格式识别。 |
| DOCX / PPTX / XLSX / HTML / CSV | Docling 可选后端，Pandoc fallback | MarkItDown、Unstructured、Mammoth、LibreOffice headless | Docling 继续做主结构化后端；MarkItDown 可作为更轻的可选后端。 |

### PDF 解析与结构增强

| 模块 | 已整合项目/能力 | 未整合候选 | 下一步建议 |
| --- | --- | --- | --- |
| PDF fast path | PyMuPDF、PyMuPDF4LLM、自研 PyMuPDF text fallback、pdfplumber diagnostics | pypdf、pdfminer.six、PDFBox | pdfplumber 已进入诊断层；pypdf/pdfminer 可做轻量兜底。 |
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
| 1 | Pix2Text | 中文图片/公式/版面专项 | 源码入口清楚，和中文截图、公式、图片到 Markdown 场景重合度高，需要真实样本验证质量。 |
| 2 | pdf-craft | 扫描书/截图书 TOC 重建 | 与“扫描书转 Markdown/EPUB”目标高度相关，先实测再决定是否写 wrapper。 |
| 3 | Surya | layout-heavy OCR/table/reading order | 能补信息图和复杂版面，但运行时更重，适合先做可选实验 provider。 |
| 4 | Tabula | text-based PDF 表格专项 fallback | 只有在 Camelot/pdfplumber 覆盖不足时才接，避免增加 Java 依赖。 |
| 5 | Apache Tika / GROBID | 格式嗅探与论文专项 | Tika 适合兜底 inspect，GROBID 只在论文/参考文献需求明确时接入。 |

MarkItDown 已完成第一步可选接入，后续任务转为扩大对比样本和记录质量差异，而不是继续作为待接入候选。
OCRmyPDF 已完成可选预处理入口，后续任务转为补前后文本层质量指标、失败 fallback 和公开扫描 PDF fixture。
pdfplumber 已完成 report 诊断入口，后续任务转为补 Camelot 专项抽取、UI 复查清单显示和表格保留率质量指标。

## 已核验来源

- 本机未提交的第三方源码缓存目录。
- 首批源码审计：MarkItDown、OCRmyPDF、pdfplumber、Camelot、RapidOCR、Apache Tika、GROBID、Crawl4AI、Trafilatura。
- 第二批源码审计：Pandoc、Calibre、PyMuPDF、PyMuPDF4LLM、MinerU、Marker、Docling、PaddleOCR、Umi-OCR、PaddleOCR-json、Qwen-VL、tkinterdnd2、Unstructured、Tabula Java、tabula-py、Tesseract、Surya、MegaParse、OmniParse、pdf-craft、olmOCR、GOT-OCR 2.0、Pix2Text、paperless-ngx。
- 本项目现有文档：`THIRD_PARTY_NOTICES.md`、`docs/REFERENCES_AND_REUSE.md`、`requirements.txt`。
