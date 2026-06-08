from __future__ import annotations

import os
import json
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import ctypes
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from types import SimpleNamespace

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
    from ebook_markdown_pipeline.environment_report import compare_environment_lock, export_environment_report  # noqa: E402
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
        environment_capability_summary,
        format_health_report,
        find_missing_dependencies,
        normalize_command_options,
        suggested_command_value,
        write_batch_summary,
    )
    from ebook_markdown_pipeline.recommendations import (  # noqa: E402
        normalize_pdf_pipeline,
        pipeline_from_suggestion_text,
        recommended_action_for_plan as plan_recommended_action,
    )
except ModuleNotFoundError:
    from document_locator import (  # noqa: E402
        IMAGE_EXTENSIONS,
        SUPPORTED_LOCATION_EXTENSIONS,
        build_location_index_from_sources,
        collect_location_sources,
    )
    from environment_report import compare_environment_lock, export_environment_report  # noqa: E402
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
        environment_capability_summary,
        format_health_report,
        find_missing_dependencies,
        normalize_command_options,
        suggested_command_value,
        write_batch_summary,
    )
    from recommendations import (  # noqa: E402
        normalize_pdf_pipeline,
        pipeline_from_suggestion_text,
        recommended_action_for_plan as plan_recommended_action,
    )


class BookConverterUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("电子书转换器 / Ebook Converter")
        self.root.geometry("1280x760")
        self.root.minsize(1160, 680)

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.history_var = tk.StringVar()
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
        self.compare_pipeline_timeout_var = tk.StringVar(value="600")
        self.compare_page_ranges_var = tk.StringVar()
        self.review_only_var = tk.BooleanVar(value=False)
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
        self.sort_desc_by_column: dict[str, bool] = {}
        self.detached_review_items: list[str] = []
        self.output_manually_selected = False
        self.history_records: list[dict] = []
        self.one_shot_output_name_suffix = ""
        self.advanced_window: tk.Toplevel | None = None

        self.build_layout()
        self.load_ui_config()
        self.setup_drag_and_drop()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(150, self.poll_queue)
        self.root.after(800, self.startup_health_check_async)

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

        ttk.Label(paths, text="历史批次 / History").grid(row=3, column=0, sticky="w", pady=4)
        self.history_combo = ttk.Combobox(paths, textvariable=self.history_var, state="readonly")
        self.history_combo.grid(row=3, column=1, sticky="ew", padx=8, pady=(4, 0))
        self.history_combo.bind("<<ComboboxSelected>>", lambda _event: self.open_selected_history())
        ttk.Button(paths, text="打开历史 / Open", command=self.open_selected_history).grid(row=3, column=2, padx=4, pady=(4, 0))
        ttk.Button(paths, text="只看问题 / Problems", command=self.open_selected_history_problems).grid(row=3, column=3, padx=4, pady=(4, 0))
        ttk.Button(paths, text="发现历史 / Discover", command=self.discover_history_batches).grid(row=3, column=4, padx=4, pady=(4, 0))
        self.history_detail_var = tk.StringVar()
        ttk.Label(paths, textvariable=self.history_detail_var).grid(row=4, column=1, columnspan=4, sticky="ew", padx=8, pady=(2, 0))

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
        ttk.Label(settings, text="对比超时(s) / Compare").grid(row=3, column=4, sticky="w", pady=4)
        ttk.Entry(settings, textvariable=self.compare_pipeline_timeout_var, width=10).grid(row=3, column=5, sticky="w", padx=8)
        ttk.Label(settings, text="对比页码 / Pages").grid(row=3, column=6, sticky="w", pady=4)
        ttk.Entry(settings, textvariable=self.compare_page_ranges_var, width=18).grid(row=3, column=7, sticky="w", padx=8)

        actions = ttk.Frame(container)
        actions.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        actions.columnconfigure(0, weight=1)
        actions.rowconfigure(0, weight=1)

        preview_box = ttk.LabelFrame(actions, text="检测文件与输出计划 / Detected Files And Planned Output", padding=8)
        preview_box.grid(row=0, column=0, sticky="nsew")
        preview_box.columnconfigure(0, weight=1)
        preview_box.rowconfigure(0, weight=1)

        columns = ("source", "format", "pipeline", "quality", "action", "note", "output_format", "output")
        self.tree = ttk.Treeview(preview_box, columns=columns, show="headings", height=12)
        self.tree.grid(row=0, column=0, sticky="nsew")

        labels = {
            "source": "来源 / Source",
            "format": "格式 / Format",
            "pipeline": "管道 / Pipeline",
            "quality": "质量 / Quality",
            "action": "建议 / Action",
            "note": "说明 / Note",
            "output_format": "输出格式 / Output Format",
            "output": "输出 / Output",
        }
        widths = {
            "source": 300,
            "format": 80,
            "pipeline": 120,
            "quality": 100,
            "action": 180,
            "note": 260,
            "output_format": 100,
            "output": 380,
        }
        for key in columns:
            self.tree.heading(key, text=labels[key], command=lambda col=key: self.sort_tree_by_column(col))
            self.tree.column(key, width=widths[key], minwidth=70, anchor="w", stretch=True)
        self.tree.tag_configure("quality_good", background="#edf7ed")
        self.tree.tag_configure("quality_review", background="#fff7db")
        self.tree.tag_configure("quality_poor", background="#ffe8e3")
        self.tree.tag_configure("quality_failed", background="#ffd9d9")
        self.tree.bind("<Double-1>", lambda _event: self.execute_selected_suggestion())

        scrollbar = ttk.Scrollbar(preview_box, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        xscrollbar = ttk.Scrollbar(preview_box, orient="horizontal", command=self.tree.xview)
        xscrollbar.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=scrollbar.set, xscrollcommand=xscrollbar.set)

        buttons = ttk.Frame(container)
        buttons.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        for column in range(6):
            buttons.columnconfigure(column, weight=0)
        self.scan_button = ttk.Button(buttons, text="扫描 / Scan", command=self.scan)
        self.health_button = ttk.Button(buttons, text="检查环境 / Health", command=self.health_check)
        self.cleanup_button = ttk.Button(buttons, text="清理残留 / Cleanup", command=self.cleanup_mineru_processes)
        self.start_button = ttk.Button(buttons, text="开始 / Start", command=self.start_convert)
        self.run_recommended_button = ttk.Button(buttons, text="按推荐执行 / Run Rec", command=self.run_recommended_actions)
        self.advanced_button = ttk.Button(buttons, text="高级 / Advanced", command=self.open_advanced_tools)
        toolbar_items = [
            self.scan_button,
            self.start_button,
            self.run_recommended_button,
            self.health_button,
            self.cleanup_button,
            ttk.Button(buttons, text="选中输出 / Output", command=self.open_selected_output),
            ttk.Button(buttons, text="选中报告 / Report", command=self.open_selected_report),
            ttk.Button(buttons, text="清空日志 / Clear", command=self.clear_log),
            self.advanced_button,
        ]
        toolbar_rows = self.grid_toolbar_items(buttons, toolbar_items, columns=8)

        status_row = ttk.Frame(buttons)
        status_row.grid(row=toolbar_rows, column=0, columnspan=8, sticky="ew", pady=(6, 0))
        status_row.columnconfigure(2, weight=1)
        self.progress = ttk.Progressbar(status_row, mode="determinate", length=220)
        self.progress.grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Label(status_row, textvariable=self.status_var).grid(row=0, column=1, sticky="w")
        ttk.Label(status_row, textvariable=self.current_stage_var).grid(row=0, column=2, sticky="w", padx=(10, 0))

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

    def grid_toolbar_items(self, parent: ttk.Frame, widgets: list[tk.Widget], *, columns: int) -> int:
        for index, widget in enumerate(widgets):
            row, column = divmod(index, columns)
            widget.grid(row=row, column=column, sticky="w", padx=(0, 8), pady=(0, 4))
        return (len(widgets) + columns - 1) // columns

    def open_advanced_tools(self) -> None:
        if self.advanced_window is not None and self.advanced_window.winfo_exists():
            self.advanced_window.lift()
            self.advanced_window.focus_force()
            return
        window = tk.Toplevel(self.root)
        self.advanced_window = window
        window.title("高级工具 / Advanced Tools")
        window.geometry("760x520")
        window.minsize(680, 460)
        window.transient(self.root)
        window.protocol("WM_DELETE_WINDOW", self.close_advanced_tools)

        container = ttk.Frame(window, padding=12)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.columnconfigure(1, weight=1)

        self.add_advanced_group(
            container,
            "复查与重跑 / Review And Retry",
            0,
            0,
            [
                ("执行建议 / Do Action", self.execute_selected_suggestion),
                ("推荐重跑 / Rerun Rec", self.rerun_selected_recommended),
                ("重跑失败 / Retry Failed", self.retry_failed_items),
                ("复查清单 / Checklist", self.open_review_checklist),
                ("决策摘要 / Decisions", self.open_review_decisions),
                ("人工记录 / Manual", self.open_manual_review),
                ("标记验收 / Accept", self.mark_selected_review_accepted),
                ("人工评分 / Score", self.score_selected_review_item),
                ("上一条 / Prev", lambda: self.select_relative_review_item(-1)),
                ("下一条 / Next", lambda: self.select_relative_review_item(1)),
            ],
        )
        self.add_advanced_group(
            container,
            "PDF 与 Artifact / PDF And Artifacts",
            0,
            1,
            [
                ("PDF对比 / Compare", self.start_pdf_pipeline_compare),
                ("PDF日志 / PDF log", self.open_latest_pdf_log),
                ("打开Artifact / Artifact", self.open_latest_artifact),
                ("原文件 / Source", self.open_selected_source),
                ("复制失败 / Copy Fail", self.copy_selected_failure_reason),
            ],
        )
        self.add_advanced_group(
            container,
            "环境 / Environment",
            1,
            0,
            [
                ("导出环境 / Env Export", self.export_environment_report_ui),
                ("对比环境 / Env Compare", self.compare_environment_lock_ui),
                ("重新启动自检 / Startup Check", self.startup_health_check_async),
            ],
        )
        self.add_advanced_group(
            container,
            "历史与 Agent / History And Agent",
            1,
            1,
            [
                ("加载历史 / History", self.load_history_batch),
                ("只载问题 / Problems", self.load_history_problems),
                ("复制Agent调用 / Copy Agent", self.copy_agent_call),
            ],
        )
        self.add_advanced_group(
            container,
            "图文材料 / Image And Location",
            2,
            0,
            [
                ("定位索引 / Location Index", self.start_location_index),
                ("截图成书 / Image Book", self.start_image_book_rebuild),
            ],
        )

        filters = ttk.LabelFrame(container, text="显示过滤 / Filters", padding=8)
        filters.grid(row=2, column=1, sticky="nsew", padx=(6, 0), pady=(8, 0))
        ttk.Checkbutton(filters, text="只看复查 / Review only", variable=self.review_only_var, command=self.apply_review_filter).grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 4)
        )
        ttk.Label(
            filters,
            text="提示：普通转换只需要主界面的“扫描”和“开始”。这里保留诊断、复查、Agent 调用等低频工具。",
            wraplength=320,
        ).grid(row=1, column=0, sticky="w")

    def close_advanced_tools(self) -> None:
        if self.advanced_window is not None and self.advanced_window.winfo_exists():
            self.advanced_window.destroy()
        self.advanced_window = None

    def add_advanced_group(
        self,
        parent: ttk.Frame,
        title: str,
        row: int,
        column: int,
        actions: list[tuple[str, object]],
    ) -> None:
        frame = ttk.LabelFrame(parent, text=title, padding=8)
        frame.grid(row=row, column=column, sticky="nsew", padx=(0 if column == 0 else 6, 6 if column == 0 else 0), pady=(0 if row == 0 else 8, 0))
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        for index, (text, command) in enumerate(actions):
            button = ttk.Button(frame, text=text, command=command)
            button.grid(row=index // 2, column=index % 2, sticky="ew", padx=(0, 6), pady=(0, 4))

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
            self.set_default_output(path)

    def pick_output_folder(self) -> None:
        initial_dir = self.output_var.get().strip() or self.default_output_initial_dir()
        dialog_options = {"title": "选择输出文件夹 / Choose output folder"}
        if initial_dir and Path(initial_dir).exists():
            dialog_options["initialdir"] = initial_dir
        path = filedialog.askdirectory(**dialog_options)
        if path:
            self.output_var.set(path)
            self.output_manually_selected = True
            self.write_log(f"输出文件夹已设为 / Output folder set to: {path}")

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
            self.set_default_output(str(folders[0]))
            self.write_log(f"已拖入文件夹 / Dropped folder: {folders[0]}")
        elif folders:
            self.selected_input_files = []
            self.input_var.set(str(folders[0]))
            self.set_default_output(str(folders[0]))
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
            output_name_suffix=self.one_shot_output_name_suffix,
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
            self.set_default_output(str(sources[0].parent))
            return
        common_root = Path(os.path.commonpath([str(path.parent) for path in sources]))
        self.set_default_output(str(common_root))

    def set_default_output(self, path: str | Path) -> None:
        if self.output_manually_selected and self.output_var.get().strip():
            return
        self.output_var.set(str(path))

    def default_output_initial_dir(self) -> str:
        if self.selected_input_files:
            return str(self.selected_input_files[0].parent)
        input_text = self.input_var.get().strip()
        if not input_text:
            return ""
        input_path = Path(input_text)
        if input_path.is_dir():
            return str(input_path)
        if input_path.parent:
            return str(input_path.parent)
        return ""

    def scan(self) -> None:
        options = self.build_options()
        input_root, sources = self.resolve_sources(options)
        if not sources:
            image_root, image_sources = self.resolve_image_sources()
            if image_sources:
                self.scan_image_book_inputs(image_root, image_sources)
                return
            messagebox.showerror("缺少输入 / Input missing", "请选择存在的输入文件或文件夹。/ Please choose an existing input file or folder.")
            return
        if not self.output_var.get().strip():
            if self.selected_input_files:
                self.apply_default_output_from_sources(sources)
            elif input_root:
                self.set_default_output(str(input_root if input_root.is_dir() else input_root.parent))
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
            self.set_default_output(str(input_root if input_root.is_dir() else input_root.parent))
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
                    "",
                    "",
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

    def scan_image_book_inputs(self, input_root: Path, sources: list[Path]) -> None:
        if not sources:
            messagebox.showerror("没有图片 / No images", "未找到可识别的图片。/ No image files were found.")
            return
        if not self.output_var.get().strip():
            self.set_default_output(str(input_root if input_root.is_dir() else input_root.parent))
        output_path = Path(self.output_var.get().strip())

        for item in self.tree.get_children():
            self.tree.delete(item)
        book_path = output_path / "book.md"
        for source in sources:
            self.tree.insert(
                "",
                "end",
                values=(
                    str(source),
                    "IMAGE",
                    "image-book",
                    "",
                    "",
                    "Image OCR, dedupe/order, Markdown",
                    "markdown",
                    str(book_path),
                ),
            )
        self.write_log(
            f"已扫描图片识别输入 {len(sources)} 张，默认将生成 Markdown。/ "
            f"Scanned {len(sources)} image recognition input(s); default output is Markdown."
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
        capability_checks = dependency_health_report([], options)
        capabilities = environment_capability_summary(capability_checks)
        if capabilities:
            self.write_log("能力矩阵 / Capability matrix:")
            for item in capabilities:
                self.write_log(
                    f"  - [{item.get('status')}] {item.get('name')}: "
                    f"{item.get('detail')} / {item.get('action')}"
                )
        missing = [item for item in checks if item["status"] == "missing"]
        warnings = [item for item in checks if item["status"] == "warning"]
        degraded_caps = [item for item in capabilities if item.get("status") == "degraded"]
        missing_caps = [item for item in capabilities if item.get("status") == "missing"]
        ready_caps = [item for item in capabilities if item.get("status") == "ok"]
        capability_summary = (
            f"\n\n能力 / Capabilities: 可用 {len(ready_caps)}，降级 {len(degraded_caps)}，缺失 {len(missing_caps)}。"
            if capabilities
            else ""
        )
        if missing:
            messagebox.showwarning("环境检查 / Environment check", f"缺少 {len(missing)} 项。详见日志。/ {len(missing)} missing item(s). See log.{capability_summary}")
        elif warnings:
            messagebox.showinfo("环境检查 / Environment check", f"{len(warnings)} 项警告。详见日志。/ {len(warnings)} warning item(s). See log.{capability_summary}")
        else:
            messagebox.showinfo("环境检查 / Environment check", f"当前选择所需环境检查通过。/ All required checks passed.{capability_summary}")

    def startup_health_check_async(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        def worker() -> None:
            try:
                options = self.build_options()
                checks = dependency_health_report([], options)
                capabilities = environment_capability_summary(checks)
                stall_checks = self.pdf_stall_risk_checks()
                self.queue.put(("startup_health", {"checks": checks, "capabilities": capabilities, "stall_checks": stall_checks}))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("startup_health", {"error": str(exc)}))

        threading.Thread(target=worker, daemon=True).start()

    def pdf_stall_risk_checks(self) -> list[dict[str, str]]:
        checks: list[dict[str, str]] = []
        checks.append(self.windows_commit_memory_check())
        checks.append(self.nvidia_smi_check())
        checks.append(self.mineru_process_check())
        checks.append(self.torch_import_check())
        return checks

    def windows_commit_memory_check(self) -> dict[str, str]:
        if os.name != "nt":
            return {"name": "Windows page file", "status": "skip", "detail": "not Windows"}
        try:
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                raise OSError("GlobalMemoryStatusEx failed")
            avail_commit_gb = status.ullAvailPageFile / (1024**3)
            total_commit_gb = status.ullTotalPageFile / (1024**3)
            avail_phys_gb = status.ullAvailPhys / (1024**3)
            if avail_commit_gb < 8:
                level = "warning"
            elif avail_commit_gb < 16:
                level = "caution"
            else:
                level = "ok"
            return {
                "name": "Windows page file / commit",
                "status": level,
                "detail": f"available commit {avail_commit_gb:.1f} GB / total {total_commit_gb:.1f} GB; available RAM {avail_phys_gb:.1f} GB",
            }
        except Exception as exc:  # noqa: BLE001
            return {"name": "Windows page file / commit", "status": "unknown", "detail": str(exc)}

    def nvidia_smi_check(self) -> dict[str, str]:
        try:
            completed = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.total,memory.used,memory.free,utilization.gpu",
                    "--format=csv,noheader,nounits",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
            )
        except Exception as exc:  # noqa: BLE001
            return {"name": "NVIDIA GPU", "status": "missing", "detail": f"nvidia-smi unavailable: {exc}"}
        if completed.returncode != 0:
            return {"name": "NVIDIA GPU", "status": "missing", "detail": (completed.stdout or "").strip()[:240]}
        first = (completed.stdout or "").strip().splitlines()[0] if (completed.stdout or "").strip() else ""
        try:
            total_mb, used_mb, free_mb, util = [int(part.strip()) for part in first.split(",")[:4]]
            free_gb = free_mb / 1024
            status = "warning" if free_gb < 3 else "caution" if free_gb < 6 else "ok"
            return {
                "name": "NVIDIA GPU memory",
                "status": status,
                "detail": f"free {free_gb:.1f} GB / total {total_mb / 1024:.1f} GB; used {used_mb / 1024:.1f} GB; util {util}%",
            }
        except Exception:
            return {"name": "NVIDIA GPU memory", "status": "unknown", "detail": first[:240]}

    def mineru_process_check(self) -> dict[str, str]:
        if os.name != "nt":
            return {"name": "MinerU residual processes", "status": "skip", "detail": "not Windows"}
        command = (
            "Get-Process python,pythonw,mineru -ErrorAction SilentlyContinue | "
            "Where-Object { $_.Path -like '*mineru*' } | "
            "Select-Object Id,CPU,StartTime,Path | ConvertTo-Json -Compress"
        )
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
            )
        except Exception as exc:  # noqa: BLE001
            return {"name": "MinerU residual processes", "status": "unknown", "detail": str(exc)}
        output = (completed.stdout or "").strip()
        if completed.returncode != 0:
            return {"name": "MinerU residual processes", "status": "unknown", "detail": output[:240]}
        if not output:
            return {"name": "MinerU residual processes", "status": "ok", "detail": "none detected"}
        try:
            payload = json.loads(output)
            count = len(payload) if isinstance(payload, list) else 1
        except Exception:
            count = 1
        return {"name": "MinerU residual processes", "status": "warning", "detail": f"{count} MinerU-related python process(es) detected"}

    def torch_import_check(self) -> dict[str, str]:
        code = (
            "import json\n"
            "try:\n"
            " import torch\n"
            " print(json.dumps({'ok': True, 'version': torch.__version__, 'cuda': bool(torch.cuda.is_available()), 'cuda_version': getattr(torch.version, 'cuda', '')}))\n"
            "except Exception as e:\n"
            " print(json.dumps({'ok': False, 'error': str(e)}))\n"
        )
        try:
            completed = subprocess.run(
                [sys.executable, "-B", "-c", code],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=12,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"name": "torch startup", "status": "warning", "detail": "torch import timed out after 12s"}
        except Exception as exc:  # noqa: BLE001
            return {"name": "torch startup", "status": "unknown", "detail": str(exc)}
        output = (completed.stdout or "").strip()
        try:
            payload = json.loads(output.splitlines()[-1])
        except Exception:
            return {"name": "torch startup", "status": "unknown", "detail": output[:240]}
        if not payload.get("ok"):
            detail = str(payload.get("error") or "")
            status = "warning" if "WinError 1455" in detail or "Error loading" in detail else "missing"
            return {"name": "torch startup", "status": status, "detail": detail[:240]}
        return {
            "name": "torch startup",
            "status": "ok" if payload.get("cuda") else "caution",
            "detail": f"torch {payload.get('version')}; cuda={payload.get('cuda')}; cuda_version={payload.get('cuda_version')}",
        }

    def handle_startup_health(self, payload: dict) -> None:
        if payload.get("error"):
            self.write_log(f"启动自检失败 / Startup health check failed: {payload.get('error')}")
            return
        checks = payload.get("checks") or []
        capabilities = payload.get("capabilities") or []
        stall_checks = payload.get("stall_checks") or []
        risky = [
            item
            for item in [*checks, *stall_checks]
            if str(item.get("status")) in {"missing", "warning", "caution", "degraded", "unknown"}
        ]
        missing_caps = [item for item in capabilities if item.get("status") == "missing"]
        degraded_caps = [item for item in capabilities if item.get("status") == "degraded"]
        self.write_log("启动自检 / Startup health check:")
        for item in stall_checks:
            self.write_log(f"  - [{item.get('status')}] {item.get('name')}: {item.get('detail')}")
        if missing_caps or degraded_caps:
            self.write_log(
                f"  - 能力风险 / Capability risks: missing={len(missing_caps)}, degraded={len(degraded_caps)}"
            )
        if risky or missing_caps or degraded_caps:
            self.status_var.set("启动自检发现风险 / Startup health risks")
            self.current_stage_var.set("详见日志 / See log")
            self.write_log("  建议 / Action: PDF 批量任务优先用 auto 或 PyMuPDF4LLM；MinerU 失败会自动降级。")
            if any(item.get("name") == "MinerU residual processes" and item.get("status") == "warning" for item in stall_checks):
                self.write_log("  建议 / Action: 如无正在运行的转换任务，可点击“清理残留 / Cleanup”。")
        else:
            self.write_log("  - [ok] 未发现明显 PDF 卡顿风险 / No obvious PDF stall risk detected.")

    def cleanup_mineru_processes(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("忙碌 / Busy", "已有任务正在运行，暂不清理进程。/ A task is running; cleanup is disabled.")
            return
        if os.name != "nt":
            messagebox.showinfo("不支持 / Unsupported", "当前只实现了 Windows MinerU 残留清理。/ Cleanup is implemented for Windows only.")
            return
        if not messagebox.askyesno(
            "清理 MinerU 残留 / Cleanup MinerU",
            "将终止路径包含 mineru 的 python/pythonw/mineru 进程。\n"
            "如果你确认没有正在跑 MinerU 转换，可以继续。\n\n"
            "Stop python/pythonw/mineru processes whose path contains mineru?",
            parent=self.root,
        ):
            return
        command = (
            "$targets = Get-Process python,pythonw,mineru -ErrorAction SilentlyContinue | "
            "Where-Object { $_.Path -like '*mineru*' }; "
            "$items = @($targets | Select-Object Id,ProcessName,CPU,Path); "
            "$count = $items.Count; "
            "$targets | Stop-Process -Force -ErrorAction SilentlyContinue; "
            "[pscustomobject]@{ stopped = $count; items = $items } | ConvertTo-Json -Depth 4 -Compress"
        )
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
                check=False,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("清理失败 / Cleanup failed", str(exc), parent=self.root)
            return
        output = (completed.stdout or "").strip()
        self.write_log(f"清理 MinerU 残留 / Cleanup MinerU residuals: {output or completed.returncode}")
        if completed.returncode != 0:
            messagebox.showerror("清理失败 / Cleanup failed", output or f"exit {completed.returncode}", parent=self.root)
            return
        try:
            stopped = int((json.loads(output) or {}).get("stopped") or 0)
        except Exception:
            stopped = 0
        self.status_var.set(f"已清理 MinerU 残留 / Cleaned {stopped}")
        messagebox.showinfo("清理完成 / Cleanup finished", f"已终止 {stopped} 个 MinerU 残留进程。/ Stopped {stopped} process(es).", parent=self.root)
        self.startup_health_check_async()

    def export_environment_report_ui(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("忙碌 / Busy", "已有任务正在运行。/ A task is already running.")
            return
        output_root = self.environment_output_root()
        input_path = self.environment_input_path()
        self.set_running_state(True)
        self.total_files = 1
        self.progress.configure(maximum=1, value=0.15)
        self.status_var.set("导出环境报告 / Exporting environment")
        self.current_stage_var.set(str(output_root))
        self.write_log(f"导出环境报告 / Export environment report: {output_root}")

        def worker() -> None:
            try:
                payload = export_environment_report(
                    input_path,
                    output_root,
                    recursive=bool(self.recursive_var.get()),
                    include_hidden=bool(self.include_hidden_var.get()),
                )
                self.queue.put(
                    (
                        "artifact_done",
                        {
                            "message": "Environment report exported",
                            "artifacts": [
                                {"path": str(payload.get("markdown_report"))},
                                {"path": str(payload.get("json_report"))},
                                {"path": str(payload.get("lock_report"))},
                                {"path": str(payload.get("requirements_lock"))},
                            ],
                        },
                    )
                )
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("error", str(exc)))

        self.worker = threading.Thread(target=worker, daemon=True)
        self.worker.start()

    def compare_environment_lock_ui(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("忙碌 / Busy", "已有任务正在运行。/ A task is already running.")
            return
        initial_dir = self.environment_output_root()
        path = filedialog.askopenfilename(
            title="选择 environment-lock.json / Choose environment-lock.json",
            initialdir=str(initial_dir if initial_dir.exists() else Path.home()),
            filetypes=[("Environment lock", "environment-lock.json *.json"), ("JSON", "*.json"), ("All", "*.*")],
        )
        if not path:
            return
        output_root = self.environment_compare_output_root()
        self.set_running_state(True)
        self.total_files = 1
        self.progress.configure(maximum=1, value=0.15)
        self.status_var.set("对比环境锁 / Comparing environment")
        self.current_stage_var.set(str(output_root))
        self.write_log(f"对比环境锁 / Compare environment lock: {path}")

        def worker() -> None:
            try:
                payload = compare_environment_lock(Path(path), output_root)
                self.queue.put(
                    (
                        "artifact_done",
                        {
                            "message": f"Environment comparison finished: {payload.get('severity')} ({payload.get('difference_count')} differences)",
                            "artifacts": [
                                {"path": str(payload.get("markdown_report"))},
                                {"path": str(payload.get("json_report"))},
                            ],
                        },
                    )
                )
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("error", str(exc)))

        self.worker = threading.Thread(target=worker, daemon=True)
        self.worker.start()

    def environment_output_root(self) -> Path:
        output_text = self.output_var.get().strip()
        if output_text:
            return Path(output_text) / ".reports" / "environment"
        input_path = self.environment_input_path()
        if input_path:
            base = input_path if input_path.is_dir() else input_path.parent
            return base / ".reports" / "environment"
        return Path.home() / "ebook-markdown-pipeline-environment"

    def environment_compare_output_root(self) -> Path:
        output_text = self.output_var.get().strip()
        if output_text:
            return Path(output_text) / ".reports" / "environment-compare"
        return self.environment_output_root() / "compare"

    def environment_input_path(self) -> Path | None:
        if self.selected_input_files:
            return self.selected_input_files[0].parent
        input_text = self.input_var.get().strip()
        if input_text:
            return Path(input_text)
        return None

    def load_history_batch(self) -> None:
        output_text = self.output_var.get().strip()
        if not output_text:
            messagebox.showwarning("缺少输出 / Output missing", "请先选择输出文件夹。/ Please choose an output folder first.")
            return
        summary_path = Path(output_text) / ".reports" / "summary.json"
        if not summary_path.exists():
            messagebox.showwarning("没有历史 / No history", f"未找到历史批次：{summary_path}")
            return
        try:
            entries = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("历史读取失败 / History load failed", str(exc))
            return
        if not isinstance(entries, list):
            messagebox.showerror("历史格式错误 / Invalid history", "summary.json 应该是数组。/ summary.json should be an array.")
            return
        self.populate_history_rows(entries, source_label="summary")

    def load_history_problems(self) -> None:
        output_text = self.output_var.get().strip()
        if not output_text:
            messagebox.showwarning("缺少输出 / Output missing", "请先选择输出文件夹。/ Please choose an output folder first.")
            return
        checklist_path = Path(output_text) / ".reports" / "review-checklist.json"
        if not checklist_path.exists():
            messagebox.showwarning("没有问题清单 / No problems", f"未找到复查清单：{checklist_path}")
            return
        try:
            entries = json.loads(checklist_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("问题清单读取失败 / Checklist load failed", str(exc))
            return
        if not isinstance(entries, list):
            messagebox.showerror("问题清单格式错误 / Invalid checklist", "review-checklist.json 应该是数组。/ review-checklist.json should be an array.")
            return
        self.populate_history_rows(entries, source_label="review-checklist")

    def open_selected_history(self) -> None:
        record = self.selected_history_record()
        if not record:
            return
        output = str(record.get("output") or "")
        if not output:
            return
        self.output_var.set(output)
        self.output_manually_selected = True
        self.load_history_batch()

    def open_selected_history_problems(self) -> None:
        record = self.selected_history_record()
        if not record:
            return
        output = str(record.get("output") or "")
        if not output:
            return
        self.output_var.set(output)
        self.output_manually_selected = True
        self.load_history_problems()

    def selected_history_record(self) -> dict | None:
        selected = self.history_var.get().strip()
        if not selected:
            messagebox.showinfo("未选择历史 / No history selected", "请先选择一个历史批次。/ Please select a history batch first.")
            return None
        for record in self.history_records:
            if self.history_display_label(record) == selected:
                self.update_history_detail(record)
                return record
        messagebox.showwarning("历史不存在 / History missing", "该历史批次记录已不存在。/ This history record is no longer available.")
        return None

    def discover_history_batches(self) -> None:
        roots = self.history_discovery_roots()
        records = []
        seen: set[str] = set()
        for root in roots:
            for summary_path in self.find_summary_files(root):
                output_path = summary_path.parent.parent
                key = str(output_path)
                if key in seen:
                    continue
                seen.add(key)
                record = self.history_record_from_summary(summary_path)
                if record:
                    records.append(record)
        if not records:
            messagebox.showinfo("没有发现历史 / No history found", "未在当前输入/输出/下载目录发现历史批次。/ No history batch found.")
            return
        self.merge_history_records(records)
        self.update_history_combo()
        self.save_ui_config()
        self.write_log(f"发现历史批次 {len(records)} 个。/ Discovered {len(records)} history batch(es).")
        messagebox.showinfo("发现历史 / History discovered", f"发现 {len(records)} 个历史批次。/ Discovered {len(records)} history batch(es).")

    def auto_discover_history_batches(self) -> None:
        records = []
        existing_outputs = {str(record.get("output") or "") for record in self.history_records}
        for root in self.history_discovery_roots():
            direct = root / ".reports" / "summary.json"
            if not direct.exists():
                continue
            output = str(direct.parent.parent)
            if output in existing_outputs:
                continue
            record = self.history_record_from_summary(direct)
            if record:
                records.append(record)
        if not records:
            return
        self.merge_history_records(records)
        self.update_history_combo()

    def history_discovery_roots(self) -> list[Path]:
        candidates: list[Path] = []
        for value in (self.output_var.get().strip(), self.input_var.get().strip()):
            if value:
                path = Path(value)
                candidates.append(path if path.is_dir() else path.parent)
        for value in (Path.home() / "Downloads", Path("D:/downloads"), Path("D:/BaiduSyncdisk/电子书")):
            candidates.append(value)
        unique: list[Path] = []
        seen: set[str] = set()
        for path in candidates:
            key = str(path)
            if key in seen or not path.exists():
                continue
            seen.add(key)
            unique.append(path)
        return unique

    def find_summary_files(self, root: Path) -> list[Path]:
        direct = root / ".reports" / "summary.json"
        if direct.exists():
            return [direct]
        found: list[Path] = []
        try:
            for reports_dir in root.glob("**/.reports"):
                summary = reports_dir / "summary.json"
                if summary.exists():
                    found.append(summary)
        except Exception:
            return found
        return found[:50]

    def history_record_from_summary(self, summary_path: Path) -> dict | None:
        try:
            entries = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(entries, list):
            return None
        problem_count = sum(1 for entry in entries if isinstance(entry, dict) and self.history_entry_is_problem(entry))
        try:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(summary_path.stat().st_mtime))
        except Exception:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        output_path = summary_path.parent.parent
        return {
            "output": str(output_path),
            "summary": str(summary_path),
            "review_checklist": str(summary_path.parent / "review-checklist.json"),
            "last_used": timestamp,
            "item_count": len(entries),
            "problem_count": problem_count,
            "source": "discovered",
        }

    def merge_history_records(self, records: list[dict]) -> None:
        merged: dict[str, dict] = {}
        for record in self.history_records:
            output = str(record.get("output") or "")
            if output:
                merged[output] = record
        for record in records:
            output = str(record.get("output") or "")
            if output:
                merged[output] = record
        self.history_records = sorted(merged.values(), key=lambda item: str(item.get("last_used") or ""), reverse=True)[:30]

    def populate_history_rows(self, entries: list[dict], *, source_label: str) -> None:
        for item in list(self.detached_review_items):
            try:
                self.tree.delete(item)
            except tk.TclError:
                pass
        self.detached_review_items = []
        for item in self.tree.get_children():
            self.tree.delete(item)

        self.latest_results = [self.history_entry_to_result(entry) for entry in entries]
        self.latest_artifacts = self.collect_history_artifacts(entries)
        for entry in entries:
            row = self.history_row_values(entry)
            quality_label = str(row[3])
            self.tree.insert("", "end", values=row, tags=(self.quality_tag_for_label(quality_label),))
        self.apply_manual_review_records()
        self.apply_review_filter()
        problem_count = sum(1 for entry in entries if self.history_entry_is_problem(entry))
        self.status_var.set(f"已加载历史 / History: {len(entries)}")
        self.current_stage_var.set(f"问题项 / Problems: {problem_count}")
        self.write_log(
            f"已从 {source_label} 加载历史 {len(entries)} 条，问题项 {problem_count} 条。/ "
            f"Loaded {len(entries)} history item(s) from {source_label}; {problem_count} problem item(s)."
        )
        output_text = self.output_var.get().strip()
        if output_text:
            self.remember_history_batch(Path(output_text), item_count=len(entries), problem_count=problem_count, source_label=source_label)

    def remember_history_batch(self, output_path: Path, *, item_count: int, problem_count: int, source_label: str) -> None:
        summary_path = output_path / ".reports" / "summary.json"
        checklist_path = output_path / ".reports" / "review-checklist.json"
        record = {
            "output": str(output_path),
            "summary": str(summary_path),
            "review_checklist": str(checklist_path),
            "last_used": time.strftime("%Y-%m-%d %H:%M:%S"),
            "item_count": item_count,
            "problem_count": problem_count,
            "source": source_label,
        }
        existing = [item for item in self.history_records if str(item.get("output") or "") != str(output_path)]
        self.history_records = [record, *existing][:30]
        self.update_history_combo()
        self.history_var.set(self.history_display_label(record))
        self.save_ui_config()

    def update_history_combo(self) -> None:
        if not hasattr(self, "history_combo"):
            return
        labels = [self.history_display_label(record) for record in self.history_records]
        self.history_combo.configure(values=labels)
        if labels and not self.history_var.get().strip():
            self.history_var.set(labels[0])
            self.update_history_detail(self.history_records[0])

    def history_display_label(self, record: dict) -> str:
        timestamp = str(record.get("last_used") or "")
        output = str(record.get("output") or "")
        item_count = record.get("item_count", "")
        problem_count = record.get("problem_count", "")
        folder = Path(output).name or output
        return f"{timestamp} | {item_count}项/{problem_count}问题 | {folder}"

    def update_history_detail(self, record: dict) -> None:
        if not hasattr(self, "history_detail_var"):
            return
        output = str(record.get("output") or "")
        summary = str(record.get("summary") or "")
        self.history_detail_var.set(f"输出: {output}    summary: {summary}")

    def history_row_values(self, entry: dict) -> tuple[str, str, str, str, str, str, str, str]:
        source = str(entry.get("source") or "")
        quality = entry.get("quality") or {}
        level = entry.get("quality_level") or quality.get("level") or entry.get("status") or ""
        score = entry.get("quality_score") if entry.get("quality_score") not in {None, ""} else quality.get("score")
        quality_label = f"{level} {score}" if score not in {None, ""} else str(level)
        detected_format = str(entry.get("detected_format") or self.detect_format_from_path(source))
        pipeline = str(entry.get("pipeline") or "")
        action = str(entry.get("suggested_action") or self.suggest_action_from_report(entry))
        note = self.history_note(entry)
        output_format = self.detect_output_format_from_path(str(entry.get("output") or ""))
        output = str(entry.get("output") or "")
        return (source, detected_format, pipeline, quality_label.strip(), action, note, output_format, output)

    def history_note(self, entry: dict) -> str:
        reasons = entry.get("quality_reasons") or (entry.get("quality") or {}).get("reasons") or []
        pdf_reasons = entry.get("pdf_reasons") or ((entry.get("pdf_preflight") or {}).get("reasons") if entry.get("pdf_preflight") else []) or []
        parts = [*reasons[:2], *pdf_reasons[:2]]
        if entry.get("message"):
            parts.insert(0, str(entry.get("message")))
        return "; ".join(str(item) for item in parts if item)

    def history_entry_to_result(self, entry: dict):
        return SimpleNamespace(
            source=str(entry.get("source") or ""),
            output=str(entry.get("output") or ""),
            status=str(entry.get("status") or ""),
            pipeline=str(entry.get("pipeline") or ""),
            message=str(entry.get("message") or ""),
            detected_format=str(entry.get("detected_format") or self.detect_format_from_path(str(entry.get("source") or ""))),
            duration_seconds=float(entry.get("duration_seconds") or 0.0),
            started_at=str(entry.get("started_at") or ""),
            finished_at=str(entry.get("finished_at") or ""),
            report=str(entry.get("report") or ""),
        )

    def collect_history_artifacts(self, entries: list[dict]) -> list[Path]:
        artifacts: list[Path] = []
        output_text = self.output_var.get().strip()
        if output_text:
            report_root = Path(output_text) / ".reports"
            artifacts.extend([report_root / "summary.md", report_root / "review-checklist.md", report_root / "manual-review.md"])
        for entry in entries:
            for key in ("output", "report"):
                value = entry.get(key)
                if value:
                    artifacts.append(Path(str(value)))
        seen: set[str] = set()
        unique: list[Path] = []
        for path in artifacts:
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            unique.append(path)
        return unique

    def history_entry_is_problem(self, entry: dict) -> bool:
        level = str(entry.get("quality_level") or (entry.get("quality") or {}).get("level") or "").lower()
        return level in {"poor", "review"} or str(entry.get("status") or "").lower() == "failed"

    def result_is_problem(self, result) -> bool:
        if str(getattr(result, "status", "") or "").lower() == "failed":
            return True
        report = getattr(result, "report", None)
        if not report:
            return False
        try:
            payload = json.loads(Path(report).read_text(encoding="utf-8"))
        except Exception:
            return False
        return self.history_entry_is_problem(payload)

    def detect_format_from_path(self, value: str) -> str:
        suffix = Path(value).suffix.lower().lstrip(".")
        return suffix.upper() if suffix else ""

    def detect_output_format_from_path(self, value: str) -> str:
        suffix = Path(value).suffix.lower()
        if suffix in {".md", ".markdown"}:
            return "markdown"
        if suffix == ".html":
            return "html"
        if suffix == ".txt":
            return "text"
        return ""

    def refresh_tree(self, input_path: Path, output_path: Path, options, sources: list[Path]) -> None:
        for item in list(self.detached_review_items):
            try:
                self.tree.delete(item)
            except tk.TclError:
                pass
        self.detached_review_items = []
        for item in self.tree.get_children():
            self.tree.delete(item)
        plans = analyze_sources(sources, input_path, output_path, options)
        for plan in plans:
            action = self.recommended_action_for_plan(plan)
            self.tree.insert(
                "",
                "end",
                values=(
                    plan.source,
                    plan.detected_format,
                    plan.pipeline,
                    "",
                    action,
                    plan.note,
                    plan.output_format,
                    plan.output,
                ),
            )
        self.apply_manual_review_records()
        self.apply_review_filter()

    def recommended_action_for_plan(self, plan) -> str:
        return plan_recommended_action(plan)

    def run_recommended_actions(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("忙碌 / Busy", "已有任务正在运行。/ A task is already running.")
            return
        selected = self.selected_tree_values() if self.tree.selection() else None
        if selected:
            quality = selected.get("quality", "").lower()
            action = selected.get("action", "").lower()
            if any(token in quality for token in ("review", "poor", "failed")) or any(token in action for token in ("rerun", "重跑", "compare", "对比")):
                self.execute_selected_suggestion()
                return
        planned_items = [(item_id, self.tree_row_values(item_id)) for item_id in self.tree.get_children("")]
        planned_rows = [row for _item_id, row in planned_items]
        convertible = [
            Path(row["source"])
            for row in planned_rows
            if row.get("source")
            and Path(row["source"]).exists()
            and ("直接转换" in row.get("action", "") or "Convert" in row.get("action", ""))
        ]
        if convertible:
            self.selected_input_files = convertible
            self.input_var.set(self.format_selected_files(convertible))
            self.overwrite_var.set(False)
            self.write_log(f"按推荐执行：转换 {len(convertible)} 个未处理文件。/ Run recommended: converting {len(convertible)} planned file(s).")
            self.start_convert()
            return
        review_rows = [
            (item_id, row)
            for item_id, row in planned_items
            if any(token in row.get("quality", "").lower() for token in ("review", "poor", "failed"))
        ]
        if review_rows:
            if self.run_safe_batch_review_rerun(review_rows):
                return
            first_item, first_row = review_rows[0]
            self.tree.selection_set(first_item)
            self.tree.focus(first_item)
            self.tree.see(first_item)
            self.write_log(
                "按推荐执行：自动选中第一条复查项并执行建议。/ "
                f"Run recommended: selected first review item: {first_row.get('source', '')}"
            )
            self.execute_selected_suggestion()
            return
        messagebox.showinfo("没有推荐动作 / No action", "当前没有可自动执行的安全推荐动作。/ No safe recommended action is available.")

    def run_safe_batch_review_rerun(self, review_rows: list[tuple[str, dict[str, str]]]) -> bool:
        candidates = []
        for _item_id, row in review_rows:
            source = Path(row.get("source", ""))
            if source.suffix.lower() != ".pdf" or not source.exists():
                continue
            pipeline = self.recommended_rerun_pipeline_for_row(row)
            if pipeline and pipeline != "auto":
                candidates.append((source, pipeline))
        if len(candidates) < 2:
            return False
        pipelines = {pipeline for _source, pipeline in candidates}
        if len(pipelines) != 1:
            self.write_log(
                "按推荐执行：复查项推荐了多个不同管道，已改为逐条处理以避免误跑。/ "
                f"Run recommended: multiple pipelines found: {', '.join(sorted(pipelines))}"
            )
            return False
        pipeline = next(iter(pipelines))
        self.rerun_sources_versioned([source for source, _pipeline in candidates], pipeline)
        return True

    def recommended_rerun_pipeline_for_row(self, row: dict[str, str]) -> str:
        report_payload = self.selected_report_payload(row)
        next_actions = self.next_actions_from_report_payload(report_payload) if report_payload else []
        for next_action in self.prioritize_next_actions(next_actions):
            name = str(next_action.get("action") or next_action.get("tool") or "")
            if name == "compare_pdf_pipelines":
                return "auto"
            if name == "rerun":
                pipeline = normalize_pdf_pipeline(str(next_action.get("pipeline") or next_action.get("pdf_pipeline_mode") or ""))
                if pipeline:
                    return pipeline
        if report_payload:
            for item in (((report_payload.get("quality_summary") or {}).get("review_items")) or []):
                pipeline = pipeline_from_suggestion_text(str(item.get("suggested_action") or ""))
                if pipeline:
                    return pipeline
        return normalize_pdf_pipeline(row.get("pipeline", ""))

    def tree_row_values(self, item_id: str) -> dict[str, str]:
        values = self.tree.item(item_id, "values")
        return dict(zip(("source", "format", "pipeline", "quality", "action", "note", "output_format", "output"), values))

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
        self.one_shot_output_name_suffix = ""
        if options.resume and options.manifest is None:
            options.manifest = output_path / "manifest.json"
        input_root, sources = self.resolve_sources(options)
        if not sources:
            _, image_sources = self.resolve_image_sources()
            if image_sources:
                self.start_image_book_rebuild()
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
            self.set_default_output(str(input_root if input_root.is_dir() else input_root.parent))
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
            self.set_default_output(str(input_root if input_root.is_dir() else input_root.parent))
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
                    self.update_quality_columns(payload)
                    output_text = self.output_var.get().strip()
                    if output_text:
                        problem_count = sum(1 for result in payload if self.result_is_problem(result))
                        self.remember_history_batch(Path(output_text), item_count=len(payload), problem_count=problem_count, source_label="conversion")
                    self.write_log(f"完成 / Finished. 成功 / Success: {ok_count}/{len(payload)}")
                    self.write_log(f"汇总 / Summary: {Path(self.output_var.get().strip()) / '.reports' / 'summary.md'}")
                    self.write_log(f"复查清单 / Review checklist: {Path(self.output_var.get().strip()) / '.reports' / 'review-checklist.md'}")
                    self.notify_task_finished(
                        "转换完成 / Conversion finished",
                        f"成功 / Success: {ok_count}/{len(payload)}\n"
                        f"输出 / Output: {self.output_var.get().strip()}",
                    )
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
                    self.notify_task_finished(
                        "定位索引完成 / Location index finished",
                        f"SQLite: {payload.get('sqlite')}\nJSONL: {payload.get('jsonl')}",
                    )
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
                    self.notify_task_finished(
                        "截图成书完成 / Image book finished",
                        f"Book: {payload.get('book')}\nReview: {payload.get('review')}",
                    )
                elif kind == "artifact_done":
                    self.set_running_state(False)
                    self.worker = None
                    self.progress.configure(value=self.total_files)
                    self.latest_artifacts = self.artifact_paths_from_payload(payload)
                    self.status_var.set("Artifact 已生成 / Artifact finished")
                    self.current_stage_var.set(str(payload.get("message") or ""))
                    self.write_log(str(payload.get("message") or "Artifact finished"))
                    for path in self.latest_artifacts:
                        self.write_log(f"Artifact: {path}")
                    artifact_text = "\n".join(str(path) for path in self.latest_artifacts[:3])
                    self.notify_task_finished(
                        "任务完成 / Task finished",
                        f"{payload.get('message') or 'Artifact finished'}"
                        + (f"\n{artifact_text}" if artifact_text else ""),
                    )
                elif kind == "compare_progress":
                    completed = int(payload.get("completed") or 0)
                    total = int(payload.get("total") or 4)
                    self.progress.configure(maximum=max(total, 1), value=min(completed, total))
                    self.status_var.set(f"PDF 管道对比 / Compare {completed}/{total}")
                    self.current_stage_var.set(str(payload.get("summary") or ""))
                    partial = payload.get("partial")
                    self.write_log(
                        f"PDF 对比进度 / Compare progress {completed}/{total}: "
                        f"{payload.get('summary') or ''}"
                        + (f"; partial={partial}" if partial else "")
                    )
                elif kind == "image_book_progress":
                    self.handle_image_book_progress(payload)
                elif kind == "startup_health":
                    self.handle_startup_health(payload)
                elif kind == "error":
                    self.set_running_state(False)
                    self.status_var.set("执行失败 / Failed")
                    self.current_stage_var.set("任务异常中断 / Interrupted")
                    self.worker = None
                    self.write_log(f"错误 / Error: {payload}")
                    self.notify_task_failed("任务失败 / Task failed", str(payload))
        except queue.Empty:
            pass
        finally:
            self.root.after(150, self.poll_queue)

    def notify_task_finished(self, title: str, message: str) -> None:
        self.show_task_notification(title, message, kind="info")

    def notify_task_failed(self, title: str, message: str) -> None:
        self.show_task_notification(title, message, kind="error")

    def show_task_notification(self, title: str, message: str, *, kind: str) -> None:
        try:
            self.root.bell()
            self.root.lift()
            self.root.focus_force()
            self.root.attributes("-topmost", True)
            self.root.after(500, lambda: self.root.attributes("-topmost", False))
            if kind == "error":
                messagebox.showerror(title, message, parent=self.root)
            else:
                messagebox.showinfo(title, message, parent=self.root)
        except Exception:
            self.write_log(f"{title}: {message}")

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

    def open_review_decisions(self) -> None:
        output_text = self.output_var.get().strip()
        if not output_text:
            messagebox.showwarning("缺少输出 / Output missing", "请先选择输出文件夹。/ Please choose an output folder first.")
            return
        decisions_md = Path(output_text) / ".reports" / "review-decisions.md"
        decisions_json = Path(output_text) / ".reports" / "review-decisions.json"
        self.open_path(decisions_md if decisions_md.exists() else decisions_json)

    def open_manual_review(self) -> None:
        output_text = self.output_var.get().strip()
        if not output_text:
            messagebox.showwarning("缺少输出 / Output missing", "请先选择输出文件夹。/ Please choose an output folder first.")
            return
        manual_md = Path(output_text) / ".reports" / "manual-review.md"
        manual_json = Path(output_text) / ".reports" / "manual-review.json"
        self.open_path(manual_md if manual_md.exists() else manual_json)

    def open_selected_output(self) -> None:
        selected = self.selected_tree_values()
        if not selected:
            return
        self.open_path(Path(selected.get("output", "")))

    def open_selected_report(self) -> None:
        selected = self.selected_tree_values()
        if not selected:
            return
        report = self.report_path_for_selected(selected)
        if report:
            self.open_path(report)

    def report_path_for_selected(self, selected: dict[str, str]) -> Path | None:
        source = selected.get("source", "")
        for result in self.latest_results:
            if str(getattr(result, "source", "")) == source and getattr(result, "report", None):
                return Path(result.report)
        output = Path(selected.get("output", ""))
        if not output:
            return None
        report = output.parent / ".reports" / f"{output.stem[:140].rstrip(' ._-')}.report.json"
        return report

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
            artifacts.extend([report_root / "summary.md", report_root / "review-checklist.md", report_root / "review-decisions.md"])
        return artifacts

    def artifact_paths_from_payload(self, payload: dict) -> list[Path]:
        artifacts = []
        for item in payload.get("artifacts", []) or []:
            path = item.get("path")
            if path:
                artifacts.append(Path(path))
        for key in ("book", "structure", "structure_json", "review", "order", "jsonl", "sqlite"):
            if payload.get(key):
                artifacts.append(Path(payload[key]))
        return artifacts

    def selected_tree_values(self) -> dict[str, str] | None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("未选择 / No selection", "请先在检测文件列表中选择一个文件。/ Please select a file first.")
            return None
        values = self.tree.item(selection[0], "values")
        columns = ("source", "format", "pipeline", "quality", "action", "note", "output_format", "output")
        return dict(zip(columns, values))

    def update_quality_columns(self, results) -> None:
        by_source = {str(getattr(result, "source", "")): result for result in results}
        for item_id in self.tree.get_children():
            values = list(self.tree.item(item_id, "values"))
            if len(values) < 8:
                continue
            source = str(values[0])
            result = by_source.get(source)
            if result is None:
                continue
            quality, action = self.quality_and_action_for_result(result)
            values[3] = quality
            values[4] = action
            self.tree.item(item_id, values=values, tags=(self.quality_tag_for_label(quality),))
        self.apply_manual_review_records()
        self.apply_review_filter()

    def load_manual_review_records(self) -> dict[str, dict]:
        output_text = self.output_var.get().strip()
        if not output_text:
            return {}
        path = Path(output_text) / ".reports" / "manual-review.json"
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        records = payload.get("records", []) if isinstance(payload, dict) else []
        return {str(item.get("source", "")): item for item in records if item.get("source")}

    def apply_manual_review_records(self) -> None:
        records = self.load_manual_review_records()
        if not records:
            return
        columns = ("source", "format", "pipeline", "quality", "action", "note", "output_format", "output")
        for item_id in self.tree.get_children(""):
            values = list(self.tree.item(item_id, "values"))
            row = dict(zip(columns, values))
            record = records.get(str(row.get("source", "")))
            if not record or len(values) < 5:
                continue
            status = str(record.get("human_status") or "")
            score = record.get("human_score")
            if status == "accepted":
                values[3] = "good manual" if score in {None, ""} else f"good manual {score}"
                values[4] = "已验收 / Accepted"
                tag = "quality_good"
            else:
                values[3] = f"manual {score}" if score not in {None, ""} else "manual review"
                values[4] = "人工复查 / Manual review"
                tag = "quality_review"
            self.tree.item(item_id, values=values, tags=(tag,))

    def quality_tag_for_label(self, quality: str) -> str:
        lowered = quality.lower()
        if lowered.startswith("failed"):
            return "quality_failed"
        if lowered.startswith("poor"):
            return "quality_poor"
        if lowered.startswith("review"):
            return "quality_review"
        if lowered.startswith("good"):
            return "quality_good"
        return ""

    def quality_and_action_for_result(self, result) -> tuple[str, str]:
        status = str(getattr(result, "status", "") or "")
        if status == "failed":
            return "failed", "复制失败原因 / Copy fail"
        report_path = getattr(result, "report", None)
        if not report_path:
            return status, ""
        try:
            payload = json.loads(Path(report_path).read_text(encoding="utf-8"))
        except Exception:
            return status, ""
        quality = payload.get("quality") or {}
        level = str(quality.get("level") or status or "")
        score = quality.get("score")
        label = f"{level} {score}" if score not in {None, ""} else level
        action = self.suggest_action_from_report(payload)
        return label.strip(), action

    def suggest_action_from_report(self, payload: dict) -> str:
        if payload.get("status") == "failed":
            return "复制失败原因 / Copy fail"
        quality = payload.get("quality") or {}
        reasons = " ".join(quality.get("reasons") or [])
        source = str(payload.get("source") or "")
        pipeline = str(payload.get("pipeline") or "")
        level = quality.get("level")
        if level == "good":
            return "可用 / OK"
        next_actions = payload.get("next_actions") or self.next_actions_from_report_payload(payload)
        if next_actions:
            return self.compact_next_actions(next_actions)
        if source.lower().endswith(".pdf"):
            if "标题" in reasons or "页码" in reasons or "重复短行" in reasons:
                return "PDF对比或推荐重跑 / Compare"
            if "HTML" in reasons and "pymupdf" in pipeline.lower():
                return "换 Umi/MinerU 对比 / Compare"
            return "打开复查清单 / Review"
        if "标题" in reasons:
            return "检查原目录 / TOC review"
        return "打开报告 / Report"

    def next_actions_from_report_payload(self, payload: dict) -> list[dict]:
        from ebook_markdown_pipeline.batch_convert_books import suggest_review_next_actions  # noqa: PLC0415

        try:
            return suggest_review_next_actions(payload)
        except Exception:
            return []

    def compact_next_actions(self, actions: list[dict], limit: int = 2) -> str:
        actions = self.prioritize_next_actions(actions)
        labels = []
        label_map = {
            "read_report": "读报告 / Report",
            "open_output": "看输出 / Output",
            "compare_pdf_pipelines": "PDF对比 / Compare",
            "rerun": "重跑 / Rerun",
            "export_location_review_pack": "导出复查包 / Review pack",
            "inspect_pdf_outline": "查书签 / Outline",
            "inspect_toc": "查目录 / TOC",
            "manual_accept_or_score": "人工评分 / Score",
        }
        for action in actions[:limit]:
            name = str(action.get("action") or action.get("tool") or "")
            label = label_map.get(name, name or "action")
            pipeline = action.get("pipeline") or action.get("pdf_pipeline_mode")
            if pipeline:
                label = f"{label}:{pipeline}"
            labels.append(label)
        suffix = " ..." if len(actions) > limit else ""
        return " -> ".join(labels) + suffix

    def prioritize_next_actions(self, actions: list[dict]) -> list[dict]:
        priority = {
            "compare_pdf_pipelines": 0,
            "rerun": 1,
            "export_location_review_pack": 2,
            "inspect_toc": 3,
            "manual_accept_or_score": 4,
            "read_report": 8,
            "open_output": 9,
        }

        def sort_key(item: dict) -> tuple[int, str]:
            name = str(item.get("action") or item.get("tool") or "")
            return (priority.get(name, 5), name)

        return sorted(actions, key=sort_key)

    def sort_tree_by_column(self, column: str) -> None:
        columns = ("source", "format", "pipeline", "quality", "action", "note", "output_format", "output")
        index = columns.index(column)
        descending = not self.sort_desc_by_column.get(column, False)
        self.sort_desc_by_column[column] = descending
        rows = []
        for item_id in self.tree.get_children(""):
            values = self.tree.item(item_id, "values")
            value = values[index] if index < len(values) else ""
            rows.append((self.sort_key_for_column(column, str(value)), item_id))
        rows.sort(reverse=descending)
        for position, (_key, item_id) in enumerate(rows):
            self.tree.move(item_id, "", position)

    def sort_key_for_column(self, column: str, value: str):
        if column == "quality":
            match = re.search(r"\b(\d{1,3})\b", value)
            score = int(match.group(1)) if match else -1
            level_rank = {"good": 0, "review": 1, "poor": 2, "failed": 3}
            level = value.split()[0].lower() if value.strip() else ""
            return (level_rank.get(level, -1), 100 - score)
        return value.lower()

    def execute_selected_suggestion(self) -> None:
        selected = self.selected_tree_values()
        if not selected:
            return
        quality = selected.get("quality", "")
        action = selected.get("action", "")
        source = Path(selected.get("source", ""))
        action_text = f"{quality} {action}".lower()
        report_payload = self.selected_report_payload(selected)
        next_actions = self.next_actions_from_report_payload(report_payload) if report_payload else []
        for next_action in self.prioritize_next_actions(next_actions):
            if self.execute_next_action(next_action, selected):
                return
        if next_actions:
            return
        if "failed" in action_text or "copy fail" in action_text or "复制失败" in action:
            self.copy_selected_failure_reason()
            return
        if source.suffix.lower() == ".pdf" and ("compare" in action_text or "pdf对比" in action or "重跑" in action):
            self.start_pdf_pipeline_compare()
            return
        if "review" in action_text or "复查" in action:
            self.open_review_checklist()
            return
        if "report" in action_text or "报告" in action or "toc" in action_text:
            self.open_selected_report()
            return
        self.open_selected_output()

    def selected_report_payload(self, selected: dict[str, str]) -> dict | None:
        report = self.report_path_for_selected(selected)
        if not report or not report.exists():
            return None
        try:
            payload = json.loads(report.read_text(encoding="utf-8"))
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def execute_next_action(self, action: dict, selected: dict[str, str]) -> bool:
        name = str(action.get("action") or action.get("tool") or "")
        if name == "read_report":
            self.open_selected_report()
            return True
        if name == "open_output":
            self.open_selected_output()
            return True
        if name == "compare_pdf_pipelines":
            self.start_pdf_pipeline_compare()
            return True
        if name == "rerun":
            pipeline = str(action.get("pipeline") or "")
            source = Path(selected.get("source", ""))
            if source.suffix.lower() == ".pdf" and pipeline:
                self.pdf_mode_var.set(pipeline)
            self.rerun_selected_recommended()
            return True
        if name == "export_location_review_pack":
            self.start_location_index()
            return True
        if name == "inspect_pdf_outline":
            self.open_selected_report()
            return True
        if name == "inspect_toc":
            self.open_selected_report()
            return True
        if name == "manual_accept_or_score":
            self.score_selected_review_item()
            return True
        return False

    def apply_review_filter(self) -> None:
        for item_id in list(self.detached_review_items):
            try:
                self.tree.move(item_id, "", "end")
            except tk.TclError:
                pass
        self.detached_review_items = []
        if not self.review_only_var.get():
            return
        for item_id in list(self.tree.get_children("")):
            values = self.tree.item(item_id, "values")
            row = dict(zip(("source", "format", "pipeline", "quality", "action", "note", "output_format", "output"), values))
            if not self.is_review_row(row):
                self.tree.detach(item_id)
                self.detached_review_items.append(item_id)

    def is_review_row(self, row: dict[str, str]) -> bool:
        quality = row.get("quality", "").lower()
        action = row.get("action", "").lower()
        if "accepted" in action or "已验收" in action:
            return False
        return quality.startswith(("review", "poor", "failed")) or "review" in action or "复查" in action

    def select_relative_review_item(self, direction: int) -> None:
        items = list(self.tree.get_children(""))
        if not items:
            messagebox.showinfo("没有复查项 / No review item", "当前没有可导航的行。/ No visible row to navigate.")
            return
        current = self.tree.selection()
        if current and current[0] in items:
            index = items.index(current[0])
            next_index = max(0, min(len(items) - 1, index + direction))
        else:
            next_index = 0 if direction >= 0 else len(items) - 1
        item_id = items[next_index]
        self.tree.selection_set(item_id)
        self.tree.focus(item_id)
        self.tree.see(item_id)

    def open_selected_source(self) -> None:
        selected = self.selected_tree_values()
        if not selected:
            return
        self.open_path(Path(selected.get("source", "")))

    def mark_selected_review_accepted(self) -> None:
        selected = self.selected_tree_values()
        if not selected:
            return
        self.write_manual_review_record(selected, human_status="accepted")
        self.update_selected_review_state("accepted", "已验收 / Accepted")
        self.apply_review_filter()
        self.write_log(f"已标记验收 / Accepted: {selected.get('source', '')}")

    def score_selected_review_item(self) -> None:
        selected = self.selected_tree_values()
        if not selected:
            return
        value = simpledialog.askinteger(
            "人工评分 / Manual score",
            "请输入 0-100 的人工评分。/ Enter a manual score from 0 to 100.",
            parent=self.root,
            minvalue=0,
            maxvalue=100,
        )
        if value is None:
            return
        status = "accepted" if value >= 85 else "review"
        self.write_manual_review_record(selected, human_status=status, human_score=value)
        action = f"人工评分 {value} / Manual {value}"
        self.update_selected_review_state(status, action)
        self.apply_review_filter()
        self.write_log(f"已记录人工评分 / Manual score saved: {value} -> {selected.get('source', '')}")

    def update_selected_review_state(self, human_status: str, action: str) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        item_id = selection[0]
        values = list(self.tree.item(item_id, "values"))
        if len(values) >= 5:
            if human_status == "accepted":
                values[3] = "good manual"
                tag = "quality_good"
            else:
                tag = self.quality_tag_for_label(str(values[3]))
            values[4] = action
            self.tree.item(item_id, values=values, tags=(tag,))

    def write_manual_review_record(self, row: dict[str, str], *, human_status: str, human_score: int | None = None) -> None:
        output_text = self.output_var.get().strip()
        if not output_text:
            messagebox.showwarning("缺少输出 / Output missing", "请先选择输出文件夹。/ Please choose an output folder first.")
            return
        report_root = Path(output_text) / ".reports"
        report_root.mkdir(parents=True, exist_ok=True)
        path = report_root / "manual-review.json"
        records = []
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                records = payload.get("records", []) if isinstance(payload, dict) else []
            except Exception:
                records = []
        record = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source": row.get("source", ""),
            "output": row.get("output", ""),
            "quality": row.get("quality", ""),
            "action": row.get("action", ""),
            "human_status": human_status,
            "human_score": human_score,
        }
        records = [item for item in records if item.get("source") != record["source"]]
        records.append(record)
        path.write_text(json.dumps({"records": records}, ensure_ascii=False, indent=2), encoding="utf-8")
        self.write_manual_review_markdown(report_root / "manual-review.md", records)

    def write_manual_review_markdown(self, path: Path, records: list[dict]) -> None:
        lines = [
            "# Manual Review",
            "",
            f"- Updated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"- Records: {len(records)}",
            "",
            "| Status | Score | Source | Output |",
            "| --- | ---: | --- | --- |",
        ]
        for item in sorted(records, key=lambda row: str(row.get("source", "")).lower()):
            lines.append(
                f"| {self.markdown_cell(str(item.get('human_status', '')))} | "
                f"{item.get('human_score') if item.get('human_score') is not None else ''} | "
                f"{self.markdown_cell(Path(str(item.get('source', ''))).name)} | "
                f"{self.markdown_cell(str(item.get('output', '')))} |"
            )
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def markdown_cell(self, text: str) -> str:
        return text.replace("|", "\\|").replace("\n", " ")[:300]

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

    def copy_selected_failure_reason(self) -> None:
        selected = self.selected_tree_values()
        if not selected:
            return
        source = selected.get("source", "")
        reason = ""
        for result in self.latest_results:
            if str(getattr(result, "source", "")) == source:
                status = str(getattr(result, "status", ""))
                message = str(getattr(result, "message", "") or "")
                report = str(getattr(result, "report", "") or "")
                reason = "\n".join(
                    part
                    for part in [
                        f"source: {source}",
                        f"status: {status}" if status else "",
                        f"message: {message}" if message else "",
                        f"report: {report}" if report else "",
                    ]
                    if part
                )
                break
        if not reason:
            output = Path(selected.get("output", ""))
            report = output.parent / ".reports" / f"{output.stem[:140].rstrip(' ._-')}.report.json"
            reason = self.failure_reason_from_report(report) or f"未找到失败原因 / No failure reason found for: {source}"
        self.root.clipboard_clear()
        self.root.clipboard_append(reason)
        self.write_log("已复制失败原因 / Copied failure reason:")
        self.write_log(reason)
        messagebox.showinfo("已复制 / Copied", "失败原因已复制到剪贴板。/ Failure reason copied to clipboard.")

    def failure_reason_from_report(self, report: Path) -> str:
        if not report.exists():
            return ""
        try:
            payload = json.loads(report.read_text(encoding="utf-8"))
        except Exception:
            return ""
        source = payload.get("source", "")
        status = payload.get("status", "")
        message = payload.get("message", "")
        output = payload.get("output", "")
        return "\n".join(
            part
            for part in [
                f"source: {source}" if source else "",
                f"status: {status}" if status else "",
                f"message: {message}" if message else "",
                f"output: {output}" if output else "",
                f"report: {report}",
            ]
            if part
        )

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

    def rerun_selected_recommended(self) -> None:
        selected = self.selected_tree_values()
        if not selected:
            return
        source = Path(selected.get("source", ""))
        if not source.exists():
            messagebox.showwarning("文件不存在 / File not found", str(source))
            return
        pipeline = selected.get("pipeline", "").lower()
        for candidate in ("mineru", "pymupdf4llm", "umi", "docling", "marker"):
            if candidate in pipeline:
                self.pdf_mode_var.set(candidate)
                break
        recommended_pipeline = self.recommended_rerun_pipeline_for_row(selected)
        if recommended_pipeline and recommended_pipeline != "auto":
            self.pdf_mode_var.set(recommended_pipeline)
        self.rerun_sources_versioned([source], self.pdf_mode_var.get())

    def rerun_sources_versioned(self, sources: list[Path], pipeline: str) -> None:
        sources = [source for source in sources if source.exists()]
        if not sources:
            messagebox.showwarning("文件不存在 / File not found", "没有可重跑的源文件。/ No source files are available.")
            return
        original_output = Path(self.output_var.get().strip()) if self.output_var.get().strip() else sources[0].parent
        rerun_output = self.normalize_rerun_output_root(original_output, sources[0])
        suffix = f"-{time.strftime('%Y%m%d-%H%M%S')}"
        self.selected_input_files = sources
        self.input_var.set(self.format_selected_files(sources))
        self.output_var.set(str(rerun_output))
        self.one_shot_output_name_suffix = suffix
        self.output_manually_selected = True
        self.overwrite_var.set(False)
        self.resume_var.set(False)
        if pipeline:
            self.pdf_mode_var.set(pipeline)
        self.write_log(
            "安全推荐重跑 / Safe recommended rerun: "
            f"{self.pdf_mode_var.get()} -> {len(sources)} file(s); output_dir={rerun_output}; filename_suffix={suffix}"
        )
        self.write_log("原主输出不会被覆盖；重跑结果会在原输出目录中追加时间后缀。/ Main output will not be overwritten.")
        self.current_stage_var.set(f"版本化文件名 / Versioned filename suffix: {suffix}")
        self.start_convert()

    def normalize_rerun_output_root(self, output_root: Path, source: Path) -> Path:
        parts = output_root.parts
        lowered = [part.lower() for part in parts]
        try:
            reports_idx = lowered.index(".reports")
        except ValueError:
            return output_root
        if reports_idx + 1 < len(lowered) and lowered[reports_idx + 1] == "reruns":
            base = Path(*parts[:reports_idx])
            return base if str(base) else source.parent
        return output_root

    def start_pdf_pipeline_compare(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("忙碌 / Busy", "已有任务正在运行。/ A task is already running.")
            return
        selected = self.selected_tree_values()
        if not selected:
            return
        source = Path(selected.get("source", ""))
        if source.suffix.lower() != ".pdf" or not source.exists():
            messagebox.showwarning("请选择 PDF / PDF required", "请先选择一个 PDF 文件。/ Please select a PDF file first.")
            return
        try:
            pipeline_timeout = float(self.compare_pipeline_timeout_var.get().strip() or "0")
        except ValueError:
            messagebox.showwarning("超时无效 / Invalid timeout", "PDF 对比超时必须是数字。/ Compare timeout must be numeric.")
            return
        page_ranges = self.compare_page_ranges_var.get().strip()
        if page_ranges:
            page_ranges = page_ranges.replace("，", ",")
            if not self.valid_page_ranges(page_ranges):
                messagebox.showwarning(
                    "页码范围无效 / Invalid pages",
                    "页码范围示例：1-3,100,600-602。/ Example: 1-3,100,600-602.",
                )
                return
        output_text = self.output_var.get().strip() or str(source.parent)
        compare_dir = Path(output_text) / ".reports" / "pipeline-compare" / source.stem[:80]
        self.set_running_state(True)
        self.total_files = 4
        self.progress.configure(maximum=4, value=0)
        self.status_var.set("PDF 管道对比中 / Comparing PDF pipelines")
        self.current_stage_var.set(str(compare_dir))
        page_note = f" pages={page_ranges}" if page_ranges else ""
        self.write_log(f"开始 PDF 管道对比 / Start PDF pipeline compare: {source}{page_note}")
        self.write_log(f"对比输出目录 / Compare output: {compare_dir}")
        self.write_log("将依次试跑 pymupdf4llm、mineru、umi、docling；过程中会刷新 partial 报告。/ Running pipelines and polling partial reports.")

        def worker() -> None:
            try:
                cmd = [
                    sys.executable,
                    str(Path(__file__).resolve().parent / "scripts" / "compare_pipelines.py"),
                    "--input",
                    str(source),
                    "--output",
                    str(compare_dir),
                    "--pipelines",
                    "pymupdf4llm",
                    "mineru",
                    "umi",
                    "docling",
                    "--overwrite",
                    "--pipeline-timeout",
                    str(pipeline_timeout),
                ]
                if page_ranges:
                    cmd.extend(["--page-ranges", page_ranges])
                process = subprocess.Popen(
                    cmd,
                    cwd=Path(__file__).resolve().parent,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                partial_json = compare_dir / "pipeline-comparison.partial.json"
                seen_count = -1
                while process.poll() is None:
                    seen_count = self.poll_pdf_compare_partial(partial_json, seen_count)
                    time.sleep(2)
                stdout, stderr = process.communicate()
                seen_count = self.poll_pdf_compare_partial(partial_json, seen_count, force=True)
                completed = SimpleNamespace(returncode=process.returncode, stdout=stdout, stderr=stderr)
                if completed.returncode not in {0, 3}:
                    raise RuntimeError((completed.stderr or completed.stdout or "").strip() or f"compare_pipelines exited {completed.returncode}")
                self.queue.put(
                    (
                        "artifact_done",
                        {
                            "message": "PDF pipeline comparison finished",
                            "artifacts": [
                                {"path": str(compare_dir / "pipeline-comparison.md")},
                                {"path": str(compare_dir / "pipeline-comparison.json")},
                                {"path": str(compare_dir / "pipeline-comparison.partial.md")},
                            ],
                        },
                    )
                )
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("error", str(exc)))

        self.worker = threading.Thread(target=worker, daemon=True)
        self.worker.start()

    def poll_pdf_compare_partial(self, partial_json: Path, seen_count: int, *, force: bool = False) -> int:
        if not partial_json.exists():
            if force:
                self.queue.put(("compare_progress", {"completed": 0, "total": 4, "summary": "等待 partial 报告 / Waiting for partial report"}))
            return seen_count
        try:
            payload = json.loads(partial_json.read_text(encoding="utf-8"))
        except Exception:
            return seen_count
        comparisons = payload.get("comparisons") or []
        completed = len(comparisons)
        if not force and completed == seen_count:
            return seen_count
        counts: dict[str, int] = {}
        latest = ""
        for item in comparisons:
            status = str(item.get("status") or "unknown")
            counts[status] = counts.get(status, 0) + 1
            latest = f"{item.get('pipeline')}: {status}"
        summary = ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "running"
        if latest:
            summary = f"{summary}; latest {latest}"
        self.queue.put(("compare_progress", {"completed": completed, "total": 4, "summary": summary, "partial": str(partial_json)}))
        return completed

    def valid_page_ranges(self, value: str) -> bool:
        parts = [part.strip() for part in value.split(",") if part.strip()]
        if not parts:
            return False
        for part in parts:
            if "-" in part:
                bounds = [item.strip() for item in part.split("-", 1)]
                if len(bounds) != 2 or not all(item.isdigit() and int(item) > 0 for item in bounds):
                    return False
                continue
            if not part.isdigit() or int(part) <= 0:
                return False
        return True

    def set_running_state(self, is_running: bool) -> None:
        state = "disabled" if is_running else "normal"
        self.scan_button.configure(state=state)
        self.health_button.configure(state=state)
        self.cleanup_button.configure(state=state)
        self.start_button.configure(state=state)

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
            "output_format": self.output_format_var,
            "pdf_mode": self.pdf_mode_var,
            "pandoc": self.pandoc_var,
            "calibre": self.calibre_var,
            "marker": self.marker_var,
            "mineru": self.mineru_var,
            "marker_extra": self.marker_extra_var,
            "pdf_idle_timeout": self.pdf_idle_timeout_var,
            "pdf_finalize_timeout": self.pdf_finalize_timeout_var,
            "compare_pipeline_timeout": self.compare_pipeline_timeout_var,
            "compare_page_ranges": self.compare_page_ranges_var,
        }.items():
            if key in data and data[key] is not None:
                variable.set(str(data[key]))
        # Do not restore the last output directory as a default. New batches should
        # follow the selected source path unless the user explicitly browses here.
        self.output_var.set("")
        self.output_manually_selected = False
        for key, variable in {
            "recursive": self.recursive_var,
            "include_hidden": self.include_hidden_var,
            "overwrite": self.overwrite_var,
            "resume": self.resume_var,
        }.items():
            if key in data:
                variable.set(bool(data[key]))
        records = data.get("history_records")
        if isinstance(records, list):
            self.history_records = [item for item in records if isinstance(item, dict) and item.get("output")]
            self.update_history_combo()
        self.auto_discover_history_batches()

    def save_ui_config(self) -> None:
        data = {
            "input": self.input_var.get(),
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
            "compare_pipeline_timeout": self.compare_pipeline_timeout_var.get(),
            "compare_page_ranges": self.compare_page_ranges_var.get(),
            "history_records": self.history_records,
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
