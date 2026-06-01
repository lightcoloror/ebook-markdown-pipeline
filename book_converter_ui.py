from __future__ import annotations

import os
import json
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:  # Drag-and-drop is optional; buttons still work without it.
    DND_FILES = None
    TkinterDnD = None

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from ebook_markdown_pipeline.document_locator import (  # noqa: E402
        IMAGE_EXTENSIONS,
        SUPPORTED_LOCATION_EXTENSIONS,
        build_location_index_from_sources,
        collect_location_sources,
    )
    from ebook_markdown_pipeline.image_book_rebuilder import rebuild_image_book_from_sources  # noqa: E402
    from ebook_markdown_pipeline import (
        OUTPUT_FORMATS,
        PDF_PIPELINE_MODES,
        SUPPORTED_FORMATS,
        analyze_sources,
        collect_sources,
        convert_sources,
        default_options,
        dependency_health_report,
        format_health_report,
        find_missing_dependencies,
        normalize_command_options,
        suggested_command_value,
        write_batch_summary,
    )
except ModuleNotFoundError:
    from document_locator import (  # noqa: E402
        IMAGE_EXTENSIONS,
        SUPPORTED_LOCATION_EXTENSIONS,
        build_location_index_from_sources,
        collect_location_sources,
    )
    from image_book_rebuilder import rebuild_image_book_from_sources  # noqa: E402
    from batch_convert_books import (
        OUTPUT_FORMATS,
        PDF_PIPELINE_MODES,
        SUPPORTED_FORMATS,
        analyze_sources,
        collect_sources,
        convert_sources,
        default_options,
        dependency_health_report,
        format_health_report,
        find_missing_dependencies,
        normalize_command_options,
        suggested_command_value,
        write_batch_summary,
    )


class BookConverterUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("电子书转换器 / Ebook Converter")
        self.root.geometry("1280x760")
        self.root.minsize(1160, 680)

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.output_format_var = tk.StringVar(value="markdown")
        self.pdf_mode_var = tk.StringVar(value="auto")
        self.recursive_var = tk.BooleanVar(value=True)
        self.include_hidden_var = tk.BooleanVar(value=False)
        self.overwrite_var = tk.BooleanVar(value=False)
        self.resume_var = tk.BooleanVar(value=True)
        self.pandoc_var = tk.StringVar(value=suggested_command_value("pandoc"))
        self.calibre_var = tk.StringVar(value=suggested_command_value("ebook-convert"))
        self.marker_var = tk.StringVar(value=suggested_command_value("marker_single"))
        self.mineru_var = tk.StringVar(value=suggested_command_value("mineru"))
        self.marker_extra_var = tk.StringVar()
        self.pdf_idle_timeout_var = tk.StringVar(value="1800")
        self.pdf_finalize_timeout_var = tk.StringVar(value="480")
        self.status_var = tk.StringVar(value="就绪 / Ready")
        self.current_stage_var = tk.StringVar(value="")
        self.selected_input_files: list[Path] = []

        self.plan_rows: list[Path] = []
        self.worker: threading.Thread | None = None
        self.queue: queue.Queue = queue.Queue()
        self.total_files = 0
        self.file_start_times: dict[str, float] = {}
        self.file_estimates: dict[str, float | None] = {}
        self.latest_results = []
        self.latest_artifacts: list[Path] = []
        self.config_path = Path.home() / ".ebook_markdown_pipeline_ui.json"

        self.build_layout()
        self.load_ui_config()
        self.setup_drag_and_drop()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(150, self.poll_queue)

    def build_layout(self) -> None:
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(2, weight=1)
        container.rowconfigure(4, weight=1)

        paths = ttk.LabelFrame(container, text="路径 / Paths", padding=10)
        paths.grid(row=0, column=0, sticky="ew")
        paths.columnconfigure(1, weight=1)

        ttk.Label(paths, text="输入文件/文件夹 / Input").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(paths, textvariable=self.input_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(paths, text="文件 / Files", command=self.pick_input_files).grid(row=0, column=2, padx=4)
        ttk.Button(paths, text="文件夹 / Folder", command=self.pick_input_folder).grid(row=0, column=3, padx=4)
        ttk.Label(paths, text="也可以直接把文件/文件夹拖到窗口里 / Drag files or folders here").grid(
            row=2, column=1, sticky="w", padx=8, pady=(2, 0)
        )

        ttk.Label(paths, text="输出文件夹 / Output").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(paths, textvariable=self.output_var).grid(row=1, column=1, sticky="ew", padx=8)
        ttk.Button(paths, text="浏览 / Browse", command=self.pick_output_folder).grid(row=1, column=2, padx=4)

        settings = ttk.LabelFrame(container, text="选项 / Options", padding=10)
        settings.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        settings.columnconfigure(1, weight=1)
        settings.columnconfigure(3, weight=1)

        ttk.Label(settings, text="输出格式 / Format").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Combobox(
            settings,
            textvariable=self.output_format_var,
            values=list(OUTPUT_FORMATS),
            state="readonly",
            width=16,
        ).grid(row=0, column=1, sticky="w", padx=8)

        ttk.Label(settings, text="PDF 模式 / PDF mode").grid(row=0, column=5, sticky="w", pady=4)
        ttk.Combobox(
            settings,
            textvariable=self.pdf_mode_var,
            values=list(PDF_PIPELINE_MODES),
            state="readonly",
            width=14,
        ).grid(row=0, column=6, sticky="w", padx=8)

        ttk.Checkbutton(settings, text="递归 / Recursive", variable=self.recursive_var).grid(
            row=0, column=2, sticky="w", padx=8
        )
        ttk.Checkbutton(settings, text="含隐藏 / Hidden", variable=self.include_hidden_var).grid(
            row=0, column=3, sticky="w", padx=8
        )
        ttk.Checkbutton(settings, text="覆盖 / Overwrite", variable=self.overwrite_var).grid(
            row=0, column=4, sticky="w", padx=8
        )
        ttk.Checkbutton(settings, text="续跑 / Resume", variable=self.resume_var).grid(
            row=0, column=7, sticky="w", padx=8
        )

        ttk.Label(settings, text="Pandoc").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(settings, textvariable=self.pandoc_var).grid(row=1, column=1, sticky="ew", padx=8)
        ttk.Label(settings, text="Calibre").grid(row=1, column=2, sticky="w", pady=4)
        ttk.Entry(settings, textvariable=self.calibre_var).grid(row=1, column=3, sticky="ew", padx=8)
        ttk.Label(settings, text="Marker").grid(row=1, column=4, sticky="w", pady=4)
        ttk.Entry(settings, textvariable=self.marker_var, width=20).grid(row=1, column=5, sticky="ew", padx=8)
        ttk.Label(settings, text="MinerU").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(settings, textvariable=self.mineru_var).grid(row=2, column=1, sticky="ew", padx=8)

        ttk.Label(settings, text="Marker 参数 / Args").grid(row=2, column=2, sticky="w", pady=4)
        ttk.Entry(settings, textvariable=self.marker_extra_var).grid(
            row=2, column=3, columnspan=3, sticky="ew", padx=8
        )
        ttk.Label(settings, text="无输出超时(s) / Idle").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(settings, textvariable=self.pdf_idle_timeout_var, width=10).grid(row=3, column=1, sticky="w", padx=8)
        ttk.Label(settings, text="收尾超时(s) / Finalize").grid(row=3, column=2, sticky="w", pady=4)
        ttk.Entry(settings, textvariable=self.pdf_finalize_timeout_var, width=10).grid(row=3, column=3, sticky="w", padx=8)

        actions = ttk.Frame(container)
        actions.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        actions.columnconfigure(0, weight=1)
        actions.rowconfigure(0, weight=1)

        preview_box = ttk.LabelFrame(actions, text="检测文件与输出计划 / Detected Files And Planned Output", padding=8)
        preview_box.grid(row=0, column=0, sticky="nsew")
        preview_box.columnconfigure(0, weight=1)
        preview_box.rowconfigure(0, weight=1)

        columns = ("source", "format", "pipeline", "note", "output_format", "output")
        self.tree = ttk.Treeview(preview_box, columns=columns, show="headings", height=12)
        self.tree.grid(row=0, column=0, sticky="nsew")

        labels = {
            "source": "来源 / Source",
            "format": "格式 / Format",
            "pipeline": "管道 / Pipeline",
            "note": "说明 / Note",
            "output_format": "输出格式 / Output Format",
            "output": "输出 / Output",
        }
        widths = {
            "source": 300,
            "format": 80,
            "pipeline": 120,
            "note": 260,
            "output_format": 100,
            "output": 380,
        }
        for key in columns:
            self.tree.heading(key, text=labels[key])
            self.tree.column(key, width=widths[key], anchor="w")

        scrollbar = ttk.Scrollbar(preview_box, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)

        buttons = ttk.Frame(container)
        buttons.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.scan_button = ttk.Button(buttons, text="扫描 / Scan", command=self.scan)
        self.scan_button.pack(side="left")
        self.health_button = ttk.Button(buttons, text="检查环境 / Health", command=self.health_check)
        self.health_button.pack(side="left", padx=(8, 0))
        self.start_button = ttk.Button(buttons, text="开始 / Start", command=self.start_convert)
        self.start_button.pack(side="left", padx=8)
        self.location_button = ttk.Button(buttons, text="定位索引 / Location Index", command=self.start_location_index)
        self.location_button.pack(side="left", padx=(0, 8))
        self.image_book_button = ttk.Button(buttons, text="截图成书 / Image Book", command=self.start_image_book_rebuild)
        self.image_book_button.pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="复查清单 / Checklist", command=self.open_review_checklist).pack(side="left")
        ttk.Button(buttons, text="选中输出 / Output", command=self.open_selected_output).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="选中报告 / Report", command=self.open_selected_report).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="打开Artifact / Artifact", command=self.open_latest_artifact).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="PDF日志 / PDF log", command=self.open_latest_pdf_log).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="复制Agent调用 / Copy Agent", command=self.copy_agent_call).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="重跑失败 / Retry Failed", command=self.retry_failed_items).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="清空日志 / Clear", command=self.clear_log).pack(side="left")

        self.progress = ttk.Progressbar(buttons, mode="determinate", length=220)
        self.progress.pack(side="left", padx=(18, 8))
        ttk.Label(buttons, textvariable=self.status_var).pack(side="left")
        ttk.Label(buttons, textvariable=self.current_stage_var).pack(side="left", padx=(10, 0))

        log_box = ttk.LabelFrame(container, text="日志 / Log", padding=8)
        log_box.grid(row=4, column=0, sticky="nsew", pady=(10, 0))
        log_box.columnconfigure(0, weight=1)
        log_box.rowconfigure(0, weight=1)
        container.rowconfigure(4, weight=1)

        self.log = tk.Text(log_box, wrap="word", height=8)
        self.log.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_box, orient="vertical", command=self.log.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=log_scroll.set)

    def pick_input_files(self) -> None:
        all_supported = SUPPORTED_FORMATS | IMAGE_EXTENSIONS
        filetypes = [
            ("电子书/PDF/图片 / Ebook PDF Images", " ".join(f"*{ext}" for ext in sorted(all_supported))),
            ("电子书/PDF / Ebook PDF", " ".join(f"*{ext}" for ext in sorted(SUPPORTED_FORMATS))),
            ("图片 / Images", " ".join(f"*{ext}" for ext in sorted(IMAGE_EXTENSIONS))),
            ("全部 / All", "*.*"),
        ]
        paths = filedialog.askopenfilenames(title="选择输入文件 / Choose input file(s)", filetypes=filetypes)
        if paths:
            self.selected_input_files = [Path(path) for path in paths]
            self.input_var.set(self.format_selected_files(self.selected_input_files))
            self.apply_default_output_from_sources(self.selected_input_files)

    def pick_input_folder(self) -> None:
        path = filedialog.askdirectory(title="选择输入文件夹 / Choose input folder")
        if path:
            self.selected_input_files = []
            self.input_var.set(path)
            self.output_var.set(path)

    def pick_output_folder(self) -> None:
        path = filedialog.askdirectory(title="选择输出文件夹 / Choose output folder")
        if path:
            self.output_var.set(path)

    def setup_drag_and_drop(self) -> None:
        if DND_FILES is None or not hasattr(self.root, "drop_target_register"):
            self.write_log("拖放不可用：当前 Python 环境缺少 tkinterdnd2。/ Drag-and-drop disabled: tkinterdnd2 is not available.")
            return
        self.root.drop_target_register(DND_FILES)
        self.root.dnd_bind("<<Drop>>", self.handle_drop)

    def handle_drop(self, event) -> None:
        paths = [Path(item) for item in self.root.tk.splitlist(event.data)]
        if not paths:
            return

        accepted_extensions = SUPPORTED_FORMATS | IMAGE_EXTENSIONS
        files = [path for path in paths if path.is_file() and path.suffix.lower() in accepted_extensions]
        folders = [path for path in paths if path.is_dir()]
        unsupported = [path for path in paths if path.is_file() and path.suffix.lower() not in accepted_extensions]

        if files:
            self.selected_input_files = files
            self.input_var.set(self.format_selected_files(files))
            self.apply_default_output_from_sources(files)
            self.write_log(f"已拖入 {len(files)} 个支持文件。/ Dropped {len(files)} supported file(s).")
        elif len(folders) == 1:
            self.selected_input_files = []
            self.input_var.set(str(folders[0]))
            self.output_var.set(str(folders[0]))
            self.write_log(f"已拖入文件夹 / Dropped folder: {folders[0]}")
        elif folders:
            self.selected_input_files = []
            self.input_var.set(str(folders[0]))
            self.output_var.set(str(folders[0]))
            self.write_log(f"拖入多个文件夹，使用第一个。/ Dropped multiple folders; using first: {folders[0]}")
        else:
            messagebox.showwarning("不支持的拖放 / Unsupported drop", "没有拖入支持的电子书/PDF文件。/ No supported ebook/PDF files were dropped.")
            return

        if unsupported:
            self.write_log(f"已忽略 {len(unsupported)} 个不支持文件。/ Ignored {len(unsupported)} unsupported file(s).")
        if any(path.suffix.lower() in IMAGE_EXTENSIONS for path in files):
            self.scan_location_inputs()
        else:
            self.scan()

    def build_options(self):
        marker_extra = [item for item in self.marker_extra_var.get().split() if item]
        options = default_options(
            recursive=self.recursive_var.get(),
            include_hidden=self.include_hidden_var.get(),
            output_format=self.output_format_var.get(),
            pdf_pipeline_mode=self.pdf_mode_var.get(),
            overwrite=self.overwrite_var.get(),
            resume=self.resume_var.get(),
            pandoc_command=self.pandoc_var.get().strip() or "pandoc",
            calibre_command=self.calibre_var.get().strip() or "ebook-convert",
            marker_command=self.marker_var.get().strip() or "marker_single",
            mineru_command=self.mineru_var.get().strip() or "mineru",
            marker_extra_args=marker_extra,
            pdf_tool_idle_timeout=self.parse_timeout(self.pdf_idle_timeout_var.get(), 1800.0),
            pdf_tool_finalize_timeout=self.parse_timeout(self.pdf_finalize_timeout_var.get(), 480.0),
        )
        return normalize_command_options(options)

    def parse_timeout(self, value: str, default: float) -> float:
        try:
            return max(float(value.strip()), 0.0)
        except Exception:
            return default

    def format_selected_files(self, paths: list[Path]) -> str:
        if not paths:
            return ""
        if len(paths) == 1:
            return str(paths[0])
        preview = ", ".join(path.name for path in paths[:3])
        if len(paths) > 3:
            preview += f", ... ({len(paths)} files)"
        return preview

    def resolve_sources(self, options) -> tuple[Path, list[Path]]:
        if self.selected_input_files:
            sources = [
                path
                for path in self.selected_input_files
                if path.exists() and path.is_file() and path.suffix.lower() in SUPPORTED_FORMATS
            ]
            if not sources:
                return Path(), []

            common_root = Path(os.path.commonpath([str(path.parent) for path in sources]))
            return common_root, sorted(sources)

        input_text = self.input_var.get().strip()
        if not input_text:
            return Path(), []

        input_path = Path(input_text)
        sources = collect_sources(
            input_path,
            recursive=options.recursive,
            include_hidden=options.include_hidden,
        )
        return input_path, sources

    def resolve_location_sources(self) -> tuple[Path, list[Path]]:
        if self.selected_input_files:
            sources = [
                path
                for path in self.selected_input_files
                if path.exists() and path.is_file() and path.suffix.lower() in SUPPORTED_LOCATION_EXTENSIONS
            ]
            if not sources:
                return Path(), []
            common_root = Path(os.path.commonpath([str(path.parent) for path in sources]))
            return common_root, sorted(sources)

        input_text = self.input_var.get().strip()
        if not input_text:
            return Path(), []

        input_path = Path(input_text)
        sources = collect_location_sources(
            input_path,
            recursive=self.recursive_var.get(),
            include_hidden=self.include_hidden_var.get(),
        )
        return input_path, sources

    def resolve_image_sources(self) -> tuple[Path, list[Path]]:
        input_root, sources = self.resolve_location_sources()
        return input_root, [source for source in sources if source.suffix.lower() in IMAGE_EXTENSIONS]

    def apply_default_output_from_sources(self, sources: list[Path]) -> None:
        if not sources:
            return
        if len(sources) == 1:
            self.output_var.set(str(sources[0].parent))
            return
        common_root = Path(os.path.commonpath([str(path.parent) for path in sources]))
        self.output_var.set(str(common_root))

    def scan(self) -> None:
        options = self.build_options()
        input_root, sources = self.resolve_sources(options)
        if not sources:
            _, location_sources = self.resolve_location_sources()
            if location_sources:
                self.scan_location_inputs()
                return
            messagebox.showerror("缺少输入 / Input missing", "请选择存在的输入文件或文件夹。/ Please choose an existing input file or folder.")
            return
        if not self.output_var.get().strip():
            if self.selected_input_files:
                self.apply_default_output_from_sources(sources)
            elif input_root:
                self.output_var.set(str(input_root if input_root.is_dir() else input_root.parent))
        if not self.output_var.get().strip():
            messagebox.showerror("缺少输出 / Output missing", "请选择输出文件夹。/ Please choose an output folder.")
            return
        output_path = Path(self.output_var.get().strip())

        self.plan_rows = sources
        self.refresh_tree(input_root, output_path, options, sources)
        plans = analyze_sources(sources, input_root, output_path, options)

        missing = find_missing_dependencies(sources, options)
        self.write_log(f"已扫描 {len(sources)} 个支持文件。/ Scanned {len(sources)} supported file(s).")
        if any(path.suffix.lower() == ".pdf" for path in sources):
            if self.pdf_mode_var.get() == "auto":
                self.write_log("提示：自动模式短 PDF 用 Marker，长 PDF 默认切换到 MinerU 结构化解析。/ Auto mode uses Marker for short PDFs and MinerU for long PDFs.")
            elif self.pdf_mode_var.get() == "marker":
                self.write_log("提示：Marker 质量较高，但长 PDF 更慢。/ Marker mode is higher quality but slower on long PDFs.")
            elif self.pdf_mode_var.get() == "mineru":
                self.write_log("提示：MinerU 面向标题、页眉页脚、表格、脚注等结构化解析。/ MinerU targets structured PDF parsing.")
            elif self.pdf_mode_var.get() == "umi":
                self.write_log("提示：Umi-OCR 对长/扫描 PDF 更快，但结构质量较低。/ Umi-OCR is faster for scanned PDFs but lower-structure.")
            self.write_log("提示：Marker/MinerU 失败或超时时会自动回退到 PyMuPDF4LLM。/ Marker/MinerU failures or timeouts fall back to PyMuPDF4LLM.")
            for plan in plans:
                if plan.detected_format == "PDF" and plan.note:
                    self.write_log(f"PDF 计划 / PDF plan: {Path(plan.source).name} -> {plan.pipeline}; {plan.note}")
        for item in missing:
            self.write_log(item)

    def scan_location_inputs(self) -> None:
        input_root, sources = self.resolve_location_sources()
        if not sources:
            messagebox.showerror("没有图片/PDF / No images or PDFs", "未找到可建定位索引的 PDF 或图片。/ No PDF or image files were found.")
            return
        if not self.output_var.get().strip():
            self.output_var.set(str(input_root if input_root.is_dir() else input_root.parent))
        output_path = Path(self.output_var.get().strip())

        for item in self.tree.get_children():
            self.tree.delete(item)
        for source in sources:
            suffix = source.suffix.lower()
            detected_format = "PDF" if suffix == ".pdf" else "IMAGE"
            note = "PDF page/image location index" if suffix == ".pdf" else "Image OCR location index"
            self.tree.insert(
                "",
                "end",
                values=(
                    str(source),
                    detected_format,
                    "location-index",
                    note,
                    "sqlite/jsonl",
                    str(output_path / "document_locations.sqlite"),
                ),
            )

        pdf_count = sum(1 for source in sources if source.suffix.lower() == ".pdf")
        image_count = len(sources) - pdf_count
        self.write_log(
            f"已扫描定位文件 {len(sources)} 个：PDF {pdf_count}，图片 {image_count}。/ "
            f"Scanned {len(sources)} location file(s): {pdf_count} PDF, {image_count} image(s)."
        )

    def health_check(self) -> None:
        options = self.build_options()
        input_root, sources = self.resolve_sources(options)
        if not sources:
            input_text = self.input_var.get().strip()
            if input_text:
                input_root = Path(input_text)
            sources = []
        checks = dependency_health_report(sources, options)
        report = format_health_report(checks)
        self.write_log(report)
        missing = [item for item in checks if item["status"] == "missing"]
        warnings = [item for item in checks if item["status"] == "warning"]
        if missing:
            messagebox.showwarning("环境检查 / Environment check", f"缺少 {len(missing)} 项。详见日志。/ {len(missing)} missing item(s). See log.")
        elif warnings:
            messagebox.showinfo("环境检查 / Environment check", f"{len(warnings)} 项警告。详见日志。/ {len(warnings)} warning item(s). See log.")
        else:
            messagebox.showinfo("环境检查 / Environment check", "当前选择所需环境检查通过。/ All required checks passed.")

    def refresh_tree(self, input_path: Path, output_path: Path, options, sources: list[Path]) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        plans = analyze_sources(sources, input_path, output_path, options)
        for plan in plans:
            self.tree.insert(
                "",
                "end",
                values=(
                    plan.source,
                    plan.detected_format,
                    plan.pipeline,
                    plan.note,
                    plan.output_format,
                    plan.output,
                ),
            )

    def start_convert(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("忙碌 / Busy", "已有转换任务正在运行。/ A conversion task is already running.")
            return

        input_text = self.input_var.get().strip()
        output_text = self.output_var.get().strip()
        if not input_text or not output_text:
            messagebox.showerror("缺少路径 / Missing paths", "请选择输入和输出路径。/ Please choose both input and output paths.")
            return

        output_path = Path(output_text)
        options = self.build_options()
        if options.resume and options.manifest is None:
            options.manifest = output_path / "manifest.json"
        input_root, sources = self.resolve_sources(options)
        if not sources:
            _, location_sources = self.resolve_location_sources()
            if location_sources:
                messagebox.showinfo(
                    "这是定位索引输入 / Location index input",
                    "当前选择的是 PDF/图片定位索引输入，请点击“定位索引 / Location Index”。/ "
                    "The current input is for PDF/image location indexing. Please click Location Index.",
                )
                return
            messagebox.showerror("没有文件 / No files", "未找到支持的文件。/ No supported files were found.")
            return

        missing = find_missing_dependencies(sources, options)
        if missing:
            self.write_log("依赖检查失败 / Dependency check failed:")
            for item in missing:
                self.write_log(item)
            messagebox.showerror("缺少依赖 / Dependencies missing", "\n".join(missing))
            return

        self.refresh_tree(input_root, output_path, options, sources)
        self.write_log(f"开始转换 {len(sources)} 个文件... / Starting conversion for {len(sources)} file(s)...")
        self.set_running_state(True)
        self.total_files = len(sources)
        self.file_start_times.clear()
        self.file_estimates.clear()
        self.progress.configure(maximum=max(len(sources), 1), value=0)
        self.status_var.set(f"准备开始 / Ready, 0/{len(sources)}")
        self.current_stage_var.set("等待任务启动 / Waiting")

        def worker() -> None:
            try:
                output_path.mkdir(parents=True, exist_ok=True)
                def progress_callback(event, source, index, total, result) -> None:
                    payload = {
                        "event": event,
                        "source": str(source),
                        "index": index,
                        "total": total,
                        "result": result,
                    }
                    self.queue.put(("progress", payload))

                results = convert_sources(
                    sources,
                    input_root,
                    output_path,
                    options,
                    progress_callback=progress_callback,
                )
                if options.manifest:
                    options.manifest.parent.mkdir(parents=True, exist_ok=True)
                    import json
                    from dataclasses import asdict

                    options.manifest.write_text(
                        json.dumps([asdict(item) for item in results], ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                options.output = output_path
                write_batch_summary(results, options)
                self.queue.put(("done", results))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("error", str(exc)))

        self.worker = threading.Thread(target=worker, daemon=True)
        self.worker.start()

    def start_location_index(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("忙碌 / Busy", "已有任务正在运行。/ A task is already running.")
            return

        input_root, sources = self.resolve_location_sources()
        if not sources:
            messagebox.showerror("没有图片/PDF / No images or PDFs", "请选择或拖入 PDF/图片文件。/ Please choose or drop PDF/image files.")
            return
        if not self.output_var.get().strip():
            self.output_var.set(str(input_root if input_root.is_dir() else input_root.parent))
        output_path = Path(self.output_var.get().strip())

        self.scan_location_inputs()
        self.write_log(f"开始建立定位索引 {len(sources)} 个文件... / Building location index for {len(sources)} file(s)...")
        self.set_running_state(True)
        self.total_files = len(sources)
        self.progress.configure(maximum=max(len(sources), 1), value=0)
        self.status_var.set(f"建立定位索引 / Indexing 0/{len(sources)}")
        self.current_stage_var.set("读取 PDF 文本层，必要时调用 Umi-OCR / Reading text layers and OCR if needed")

        def worker() -> None:
            try:
                result = build_location_index_from_sources(
                    sources,
                    output_path,
                    input_label=str(input_root),
                    ocr_mode="auto",
                )
                self.queue.put(("location_done", result))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("error", str(exc)))

        self.worker = threading.Thread(target=worker, daemon=True)
        self.worker.start()

    def start_image_book_rebuild(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("忙碌 / Busy", "已有任务正在运行。/ A task is already running.")
            return

        input_root, sources = self.resolve_image_sources()
        if not sources:
            messagebox.showerror("没有图片 / No images", "请选择或拖入图片文件。/ Please choose or drop image files.")
            return
        if not self.output_var.get().strip():
            self.output_var.set(str(input_root if input_root.is_dir() else input_root.parent))
        output_path = Path(self.output_var.get().strip())

        self.write_log(f"开始截图成书 {len(sources)} 张图片... / Rebuilding image book from {len(sources)} image(s)...")
        self.set_running_state(True)
        self.total_files = len(sources)
        self.progress.configure(maximum=max(len(sources), 1), value=0)
        self.status_var.set(f"截图成书 / Image Book 0/{len(sources)}")
        self.current_stage_var.set("OCR、去重、排序、生成 Markdown / OCR, dedupe, order, Markdown")

        def worker() -> None:
            try:
                def progress_callback(event: dict) -> None:
                    self.queue.put(("image_book_progress", event))

                result = rebuild_image_book_from_sources(
                    sources,
                    output_path,
                    input_label=str(input_root),
                    title=input_root.name or "Rebuilt Image Book",
                    ocr_mode="auto",
                    progress_callback=progress_callback,
                )
                self.queue.put(("image_book_done", result))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("error", str(exc)))

        self.worker = threading.Thread(target=worker, daemon=True)
        self.worker.start()

    def poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "progress":
                    self.handle_progress(payload)
                elif kind == "done":
                    self.latest_results = payload
                    ok_count = 0
                    for result in payload:
                        if result.status == "ok":
                            ok_count += 1
                    self.progress.configure(value=self.total_files)
                    self.status_var.set(f"已完成 / Finished，成功 / Success {ok_count}/{len(payload)}")
                    self.current_stage_var.set("全部任务完成 / All done")
                    self.set_running_state(False)
                    self.worker = None
                    self.latest_artifacts = self.collect_conversion_artifacts(payload)
                    self.write_log(f"完成 / Finished. 成功 / Success: {ok_count}/{len(payload)}")
                    self.write_log(f"汇总 / Summary: {Path(self.output_var.get().strip()) / '.reports' / 'summary.md'}")
                    self.write_log(f"复查清单 / Review checklist: {Path(self.output_var.get().strip()) / '.reports' / 'review-checklist.md'}")
                elif kind == "location_done":
                    self.progress.configure(value=self.total_files)
                    self.status_var.set("定位索引完成 / Location index finished")
                    self.current_stage_var.set("可用 query_location_index 或 CLI 查询 / Ready for query")
                    self.set_running_state(False)
                    self.worker = None
                    self.latest_artifacts = self.artifact_paths_from_payload(payload)
                    self.write_log("定位索引完成 / Location index finished.")
                    self.write_log(f"SQLite: {payload.get('sqlite')}")
                    self.write_log(f"JSONL: {payload.get('jsonl')}")
                    self.write_log(f"状态统计 / Status: {payload.get('status_counts')}")
                elif kind == "image_book_done":
                    self.progress.configure(value=self.total_files)
                    self.status_var.set("截图成书完成 / Image book finished")
                    self.current_stage_var.set("请检查 book.md 和 review.md / Check book.md and review.md")
                    self.set_running_state(False)
                    self.worker = None
                    self.latest_artifacts = self.artifact_paths_from_payload(payload)
                    self.write_log("截图成书完成 / Image book finished.")
                    self.write_log(f"Book: {payload.get('book')}")
                    self.write_log(f"Order: {payload.get('order')}")
                    self.write_log(f"Review: {payload.get('review')}")
                elif kind == "image_book_progress":
                    self.handle_image_book_progress(payload)
                elif kind == "error":
                    self.set_running_state(False)
                    self.status_var.set("执行失败 / Failed")
                    self.current_stage_var.set("任务异常中断 / Interrupted")
                    self.worker = None
                    self.write_log(f"错误 / Error: {payload}")
                    messagebox.showerror("转换错误 / Conversion error", payload)
        except queue.Empty:
            pass
        finally:
            self.root.after(150, self.poll_queue)

    def handle_progress(self, payload) -> None:
        event = payload["event"]
        source = payload["source"]
        index = payload["index"]
        total = payload["total"]
        source_name = Path(source).name
        if event == "start":
            start_time = time.monotonic()
            self.file_start_times[source] = start_time
            estimate = (payload.get("result") or {}).get("estimate_seconds")
            self.file_estimates[source] = estimate
            timing = self.format_timing(source)
            self.progress.configure(value=max(index - 0.5, 0.2))
            self.status_var.set(f"处理中 / Processing {index}/{total}: {source_name} {timing}")
            self.current_stage_var.set("准备任务 / Preparing")
            self.write_log(f"处理中 / Processing {index}/{total}: {source} {timing}")
            return

        if event == "stage":
            stage_info = payload["result"] or {}
            stage_text = self.describe_stage(stage_info.get("stage", ""), stage_info.get("detail", ""))
            base_value = max(index - 1, 0)
            phase_offset = self.stage_progress_offset(stage_info.get("stage", ""))
            self.progress.configure(value=min(base_value + phase_offset, self.total_files))
            self.status_var.set(f"处理中 / Processing {index}/{total}: {source_name} {self.format_timing(source)}")
            self.current_stage_var.set(stage_text)
            self.write_log(f"  - {stage_text}")
            return

        result = payload["result"]
        self.progress.configure(value=index)
        self.status_var.set(f"已完成 / Done {index}/{total}: {source_name} {self.format_timing(source)}")
        self.current_stage_var.set("当前文件已完成 / Current file done")
        self.write_log(f"[{result.status}] {result.source} -> {result.output or '-'}")
        if result.message:
            self.write_log(result.message)
        if getattr(result, "report", None):
            self.write_log(f"报告 / Report: {result.report}")

    def handle_image_book_progress(self, payload: dict) -> None:
        stage = payload.get("stage", "")
        message = payload.get("message", "")
        index = payload.get("index")
        total = payload.get("total") or self.total_files or 1
        if isinstance(index, int) and index > 0:
            self.progress.configure(value=min(index, total))
            self.status_var.set(f"截图成书 / Image Book {index}/{total}")
        elif stage in {"dedupe", "order", "write"}:
            offset = {"dedupe": 0.65, "order": 0.78, "write": 0.9}.get(stage, 0.5)
            self.progress.configure(value=max(1, self.total_files * offset))
        self.current_stage_var.set(str(message or stage))
        if message:
            self.write_log(f"  - {message}")

    def open_review_checklist(self) -> None:
        output_text = self.output_var.get().strip()
        if not output_text:
            messagebox.showwarning("缺少输出 / Output missing", "请先选择输出文件夹。/ Please choose an output folder first.")
            return
        self.open_path(Path(output_text) / ".reports" / "review-checklist.md")

    def open_selected_output(self) -> None:
        selected = self.selected_tree_values()
        if not selected:
            return
        self.open_path(Path(selected.get("output", "")))

    def open_selected_report(self) -> None:
        selected = self.selected_tree_values()
        if not selected:
            return
        source = selected.get("source", "")
        for result in self.latest_results:
            if str(getattr(result, "source", "")) == source and getattr(result, "report", None):
                self.open_path(Path(result.report))
                return
        output = Path(selected.get("output", ""))
        report = output.parent / ".reports" / f"{output.stem[:140].rstrip(' ._-')}.report.json"
        self.open_path(report)

    def open_latest_pdf_log(self) -> None:
        output_text = self.output_var.get().strip()
        if not output_text:
            messagebox.showwarning("缺少输出 / Output missing", "请先选择输出文件夹。/ Please choose an output folder first.")
            return
        log_dir = Path(output_text) / ".reports" / "pdf-tool-logs"
        logs = sorted(log_dir.glob("*.log"), key=lambda path: path.stat().st_mtime, reverse=True) if log_dir.exists() else []
        if not logs:
            messagebox.showinfo("没有 PDF 日志 / No PDF logs", "尚未找到 PDF 工具日志。/ No PDF tool logs found yet.")
            return
        self.open_path(logs[0])

    def open_latest_artifact(self) -> None:
        artifacts = [path for path in self.latest_artifacts if path.exists()]
        if not artifacts:
            selected = self.selected_tree_values() if self.tree.selection() else None
            if selected:
                candidate = Path(selected.get("output", ""))
                if candidate.exists():
                    self.open_path(candidate)
                    return
            messagebox.showinfo("没有 Artifact / No artifact", "尚未找到可打开的 artifact。/ No artifact found yet.")
            return
        preferred_order = {".md": 0, ".markdown": 0, ".html": 1, ".txt": 2, ".json": 3, ".jsonl": 4, ".log": 5}
        artifacts.sort(key=lambda path: (preferred_order.get(path.suffix.lower(), 9), str(path).lower()))
        self.open_path(artifacts[0])

    def collect_conversion_artifacts(self, results) -> list[Path]:
        artifacts = []
        for result in results:
            output = getattr(result, "output", None)
            report = getattr(result, "report", None)
            if output:
                artifacts.append(Path(output))
            if report:
                artifacts.append(Path(report))
        output_text = self.output_var.get().strip()
        if output_text:
            report_root = Path(output_text) / ".reports"
            artifacts.extend([report_root / "summary.md", report_root / "review-checklist.md"])
        return artifacts

    def artifact_paths_from_payload(self, payload: dict) -> list[Path]:
        artifacts = []
        for item in payload.get("artifacts", []) or []:
            path = item.get("path")
            if path:
                artifacts.append(Path(path))
        for key in ("book", "review", "order", "jsonl", "sqlite"):
            if payload.get(key):
                artifacts.append(Path(payload[key]))
        return artifacts

    def selected_tree_values(self) -> dict[str, str] | None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("未选择 / No selection", "请先在检测文件列表中选择一个文件。/ Please select a file first.")
            return None
        values = self.tree.item(selection[0], "values")
        columns = ("source", "format", "pipeline", "note", "output_format", "output")
        return dict(zip(columns, values))

    def open_path(self, path: Path) -> None:
        if not path.exists():
            messagebox.showwarning("文件不存在 / File not found", str(path))
            return
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("打开失败 / Open failed", str(exc))

    def copy_agent_call(self) -> None:
        output_text = self.output_var.get().strip()
        if not output_text:
            messagebox.showwarning("缺少输出 / Output missing", "请先选择输出文件夹。/ Please choose an output folder first.")
            return
        selected = None
        if self.tree.selection():
            selected = self.selected_tree_values()
        input_text = selected.get("source") if selected else self.input_var.get().strip()
        if not input_text:
            messagebox.showwarning("缺少输入 / Input missing", "请先选择输入。/ Please choose input first.")
            return
        payload = {
            "name": "process_material",
            "arguments": {
                "input": input_text,
                "output": output_text,
                "recursive": bool(self.recursive_var.get()),
                "include_hidden": bool(self.include_hidden_var.get()),
                "output_format": self.output_format_var.get(),
                "pdf_pipeline_mode": self.pdf_mode_var.get(),
            },
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.write_log("已复制 Agent 调用 JSON / Copied agent call JSON:")
        self.write_log(text)
        messagebox.showinfo("已复制 / Copied", "Agent 调用 JSON 已复制到剪贴板。/ Agent call JSON copied to clipboard.")

    def retry_failed_items(self) -> None:
        failed = [
            Path(str(getattr(result, "source", "")))
            for result in self.latest_results
            if getattr(result, "status", "") == "failed" and getattr(result, "source", "")
        ]
        failed = [path for path in failed if path.exists()]
        if not failed:
            messagebox.showinfo("没有失败项 / No failures", "当前没有可重跑的失败文件。/ No failed files to retry.")
            return
        self.selected_input_files = failed
        self.input_var.set(self.format_selected_files(failed))
        self.overwrite_var.set(True)
        self.resume_var.set(False)
        self.write_log(f"准备重跑失败项 {len(failed)} 个；已自动开启覆盖并关闭续跑。/ Retrying {len(failed)} failed item(s); overwrite on, resume off.")
        self.start_convert()

    def set_running_state(self, is_running: bool) -> None:
        state = "disabled" if is_running else "normal"
        self.scan_button.configure(state=state)
        self.health_button.configure(state=state)
        self.start_button.configure(state=state)
        self.location_button.configure(state=state)
        self.image_book_button.configure(state=state)

    def stage_progress_offset(self, stage: str) -> float:
        mapping = {
            "prepare": 0.08,
            "calibre": 0.22,
            "marker": 0.28,
            "mineru": 0.34,
            "marker_progress": 0.38,
            "mineru_progress": 0.42,
            "fallback": 0.34,
            "pymupdf": 0.62,
            "umi": 0.20,
            "umi_page": 0.55,
            "pandoc": 0.52,
            "collect": 0.68,
            "copy": 0.78,
            "quality": 0.82,
            "postprocess": 0.86,
            "footnotes": 0.93,
        }
        return mapping.get(stage, 0.4)

    def describe_stage(self, stage: str, detail: str) -> str:
        labels = {
            "prepare": "准备输出文件 / Prepare output",
            "calibre": "Calibre 转 EPUB / Convert to EPUB",
            "marker": "Marker 解析 PDF / Parse PDF",
            "mineru": "MinerU 结构化解析 PDF / Structured PDF parse",
            "marker_progress": "Marker 运行进度 / Progress",
            "mineru_progress": "MinerU 运行进度 / Progress",
            "fallback": "切换到 PyMuPDF4LLM / Fallback",
            "pymupdf": "PyMuPDF4LLM 解析 PDF / Parse PDF",
            "umi": "Umi-OCR 解析 PDF / OCR PDF",
            "umi_page": "Umi-OCR 逐页识别 / Page OCR",
            "pandoc": "Pandoc 转换 / Convert",
            "collect": "收集转换结果 / Collect output",
            "copy": "写入 Markdown 文件 / Write Markdown",
            "quality": "生成 PDF 质量报告 / Quality report",
            "postprocess": "清洗 Markdown / Clean Markdown",
            "footnotes": "提取脚注与尾注 / Extract notes",
        }
        label = labels.get(stage, stage or "处理中 / Processing")
        if detail and detail != label:
            return f"{label} - {detail}"
        return label

    def format_timing(self, source: str) -> str:
        started = self.file_start_times.get(source)
        if started is None:
            return ""
        elapsed = max(0.0, time.monotonic() - started)
        estimate = self.file_estimates.get(source)
        if estimate and estimate > 0:
            remaining = max(0.0, estimate - elapsed)
            return f"(已用/elapsed {self.format_duration(elapsed)} / 预计/est {self.format_duration(estimate)}，剩余/left {self.format_duration(remaining)})"
        return f"(已用/elapsed {self.format_duration(elapsed)})"

    def format_duration(self, seconds: float) -> str:
        seconds_int = int(round(seconds))
        minutes, seconds_int = divmod(seconds_int, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}h{minutes:02d}m"
        if minutes:
            return f"{minutes}m{seconds_int:02d}s"
        return f"{seconds_int}s"

    def clear_log(self) -> None:
        self.log.delete("1.0", "end")
        if not (self.worker and self.worker.is_alive()):
            self.status_var.set("就绪 / Ready")
            self.current_stage_var.set("")

    def write_log(self, text: str) -> None:
        self.log.insert("end", text + "\n")
        self.log.see("end")

    def load_ui_config(self) -> None:
        if not self.config_path.exists():
            return
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception:
            return
        for key, variable in {
            "input": self.input_var,
            "output": self.output_var,
            "output_format": self.output_format_var,
            "pdf_mode": self.pdf_mode_var,
            "pandoc": self.pandoc_var,
            "calibre": self.calibre_var,
            "marker": self.marker_var,
            "mineru": self.mineru_var,
            "marker_extra": self.marker_extra_var,
            "pdf_idle_timeout": self.pdf_idle_timeout_var,
            "pdf_finalize_timeout": self.pdf_finalize_timeout_var,
        }.items():
            if key in data and data[key] is not None:
                variable.set(str(data[key]))
        for key, variable in {
            "recursive": self.recursive_var,
            "include_hidden": self.include_hidden_var,
            "overwrite": self.overwrite_var,
            "resume": self.resume_var,
        }.items():
            if key in data:
                variable.set(bool(data[key]))

    def save_ui_config(self) -> None:
        data = {
            "input": self.input_var.get(),
            "output": self.output_var.get(),
            "output_format": self.output_format_var.get(),
            "pdf_mode": self.pdf_mode_var.get(),
            "recursive": self.recursive_var.get(),
            "include_hidden": self.include_hidden_var.get(),
            "overwrite": self.overwrite_var.get(),
            "resume": self.resume_var.get(),
            "pandoc": self.pandoc_var.get(),
            "calibre": self.calibre_var.get(),
            "marker": self.marker_var.get(),
            "mineru": self.mineru_var.get(),
            "marker_extra": self.marker_extra_var.get(),
            "pdf_idle_timeout": self.pdf_idle_timeout_var.get(),
            "pdf_finalize_timeout": self.pdf_finalize_timeout_var.get(),
        }
        try:
            self.config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            self.write_log(f"无法保存 UI 配置 / Could not save UI config: {exc}")

    def on_close(self) -> None:
        self.save_ui_config()
        self.root.destroy()


def main() -> None:
    root = TkinterDnD.Tk() if TkinterDnD is not None else tk.Tk()
    root.option_add("*Font", "{Segoe UI} 10")
    BookConverterUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
