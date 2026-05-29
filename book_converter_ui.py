from __future__ import annotations

import os
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
    )
except ModuleNotFoundError:
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
    )


class BookConverterUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Ebook Converter UI")
        self.root.geometry("1100x700")
        self.root.minsize(980, 620)

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
        self.status_var = tk.StringVar(value="就绪")
        self.current_stage_var = tk.StringVar(value="")
        self.selected_input_files: list[Path] = []

        self.plan_rows: list[Path] = []
        self.worker: threading.Thread | None = None
        self.queue: queue.Queue = queue.Queue()
        self.total_files = 0
        self.file_start_times: dict[str, float] = {}
        self.file_estimates: dict[str, float | None] = {}

        self.build_layout()
        self.setup_drag_and_drop()
        self.root.after(150, self.poll_queue)

    def build_layout(self) -> None:
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(2, weight=1)
        container.rowconfigure(4, weight=1)

        paths = ttk.LabelFrame(container, text="Paths", padding=10)
        paths.grid(row=0, column=0, sticky="ew")
        paths.columnconfigure(1, weight=1)

        ttk.Label(paths, text="Input file/folder").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(paths, textvariable=self.input_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(paths, text="Files", command=self.pick_input_files).grid(row=0, column=2, padx=4)
        ttk.Button(paths, text="Folder", command=self.pick_input_folder).grid(row=0, column=3, padx=4)
        ttk.Label(paths, text="也可以直接把文件/文件夹拖到窗口里").grid(
            row=2, column=1, sticky="w", padx=8, pady=(2, 0)
        )

        ttk.Label(paths, text="Output folder").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(paths, textvariable=self.output_var).grid(row=1, column=1, sticky="ew", padx=8)
        ttk.Button(paths, text="Browse", command=self.pick_output_folder).grid(row=1, column=2, padx=4)

        settings = ttk.LabelFrame(container, text="Options", padding=10)
        settings.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        settings.columnconfigure(1, weight=1)
        settings.columnconfigure(3, weight=1)

        ttk.Label(settings, text="Output format").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Combobox(
            settings,
            textvariable=self.output_format_var,
            values=list(OUTPUT_FORMATS),
            state="readonly",
            width=16,
        ).grid(row=0, column=1, sticky="w", padx=8)

        ttk.Label(settings, text="PDF mode").grid(row=0, column=5, sticky="w", pady=4)
        ttk.Combobox(
            settings,
            textvariable=self.pdf_mode_var,
            values=list(PDF_PIPELINE_MODES),
            state="readonly",
            width=14,
        ).grid(row=0, column=6, sticky="w", padx=8)

        ttk.Checkbutton(settings, text="Recursive", variable=self.recursive_var).grid(
            row=0, column=2, sticky="w", padx=8
        )
        ttk.Checkbutton(settings, text="Include hidden", variable=self.include_hidden_var).grid(
            row=0, column=3, sticky="w", padx=8
        )
        ttk.Checkbutton(settings, text="Overwrite output", variable=self.overwrite_var).grid(
            row=0, column=4, sticky="w", padx=8
        )
        ttk.Checkbutton(settings, text="Resume manifest", variable=self.resume_var).grid(
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

        ttk.Label(settings, text="Marker extra args").grid(row=2, column=2, sticky="w", pady=4)
        ttk.Entry(settings, textvariable=self.marker_extra_var).grid(
            row=2, column=3, columnspan=3, sticky="ew", padx=8
        )

        actions = ttk.Frame(container)
        actions.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        actions.columnconfigure(0, weight=1)
        actions.rowconfigure(0, weight=1)

        preview_box = ttk.LabelFrame(actions, text="Detected Files And Planned Output", padding=8)
        preview_box.grid(row=0, column=0, sticky="nsew")
        preview_box.columnconfigure(0, weight=1)
        preview_box.rowconfigure(0, weight=1)

        columns = ("source", "format", "pipeline", "note", "output_format", "output")
        self.tree = ttk.Treeview(preview_box, columns=columns, show="headings", height=12)
        self.tree.grid(row=0, column=0, sticky="nsew")

        labels = {
            "source": "Source",
            "format": "Detected",
            "pipeline": "Pipeline",
            "note": "Note",
            "output_format": "Output Format",
            "output": "Output",
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
        self.scan_button = ttk.Button(buttons, text="扫描文件", command=self.scan)
        self.scan_button.pack(side="left")
        self.health_button = ttk.Button(buttons, text="检查环境", command=self.health_check)
        self.health_button.pack(side="left", padx=(8, 0))
        self.start_button = ttk.Button(buttons, text="开始执行", command=self.start_convert)
        self.start_button.pack(side="left", padx=8)
        ttk.Button(buttons, text="清空日志", command=self.clear_log).pack(side="left")

        self.progress = ttk.Progressbar(buttons, mode="determinate", length=220)
        self.progress.pack(side="left", padx=(18, 8))
        ttk.Label(buttons, textvariable=self.status_var).pack(side="left")
        ttk.Label(buttons, textvariable=self.current_stage_var).pack(side="left", padx=(10, 0))

        log_box = ttk.LabelFrame(container, text="Log", padding=8)
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
        filetypes = [("Supported", " ".join(f"*{ext}" for ext in sorted(SUPPORTED_FORMATS))), ("All", "*.*")]
        paths = filedialog.askopenfilenames(title="Choose input file(s)", filetypes=filetypes)
        if paths:
            self.selected_input_files = [Path(path) for path in paths]
            self.input_var.set(self.format_selected_files(self.selected_input_files))
            self.apply_default_output_from_sources(self.selected_input_files)

    def pick_input_folder(self) -> None:
        path = filedialog.askdirectory(title="Choose input folder")
        if path:
            self.selected_input_files = []
            self.input_var.set(path)
            self.output_var.set(path)

    def pick_output_folder(self) -> None:
        path = filedialog.askdirectory(title="Choose output folder")
        if path:
            self.output_var.set(path)

    def setup_drag_and_drop(self) -> None:
        if DND_FILES is None or not hasattr(self.root, "drop_target_register"):
            self.write_log("Drag-and-drop disabled: tkinterdnd2 is not available in this Python environment.")
            return
        self.root.drop_target_register(DND_FILES)
        self.root.dnd_bind("<<Drop>>", self.handle_drop)

    def handle_drop(self, event) -> None:
        paths = [Path(item) for item in self.root.tk.splitlist(event.data)]
        if not paths:
            return

        files = [path for path in paths if path.is_file() and path.suffix.lower() in SUPPORTED_FORMATS]
        folders = [path for path in paths if path.is_dir()]
        unsupported = [path for path in paths if path.is_file() and path.suffix.lower() not in SUPPORTED_FORMATS]

        if files:
            self.selected_input_files = files
            self.input_var.set(self.format_selected_files(files))
            self.apply_default_output_from_sources(files)
            self.write_log(f"Dropped {len(files)} supported file(s).")
        elif len(folders) == 1:
            self.selected_input_files = []
            self.input_var.set(str(folders[0]))
            self.output_var.set(str(folders[0]))
            self.write_log(f"Dropped folder: {folders[0]}")
        elif folders:
            self.selected_input_files = []
            self.input_var.set(str(folders[0]))
            self.output_var.set(str(folders[0]))
            self.write_log(f"Dropped multiple folders; using first folder: {folders[0]}")
        else:
            messagebox.showwarning("Unsupported drop", "No supported ebook/PDF files were dropped.")
            return

        if unsupported:
            self.write_log(f"Ignored {len(unsupported)} unsupported file(s).")
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
        )
        return normalize_command_options(options)

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
            messagebox.showerror("Input missing", "Please choose an existing input file or folder.")
            return
        if not self.output_var.get().strip():
            if self.selected_input_files:
                self.apply_default_output_from_sources(sources)
            elif input_root:
                self.output_var.set(str(input_root if input_root.is_dir() else input_root.parent))
        if not self.output_var.get().strip():
            messagebox.showerror("Output missing", "Please choose an output folder.")
            return
        output_path = Path(self.output_var.get().strip())

        self.plan_rows = sources
        self.refresh_tree(input_root, output_path, options, sources)
        plans = analyze_sources(sources, input_root, output_path, options)

        missing = find_missing_dependencies(sources, options)
        self.write_log(f"Scanned {len(sources)} supported file(s).")
        if any(path.suffix.lower() == ".pdf" for path in sources):
            if self.pdf_mode_var.get() == "auto":
                self.write_log("Note: Auto mode uses Marker for short PDFs and switches long PDFs to MinerU structured parsing by default.")
            elif self.pdf_mode_var.get() == "marker":
                self.write_log("Note: Marker mode is higher quality but slower on long PDFs.")
            elif self.pdf_mode_var.get() == "mineru":
                self.write_log("Note: MinerU mode targets structured PDF parsing with headings, page furniture, tables, and footnotes.")
            elif self.pdf_mode_var.get() == "umi":
                self.write_log("Note: Umi-OCR mode is faster for long/scanned PDFs but structure quality is lower.")
            self.write_log("Note: If Marker fails because of model/network issues, the pipeline will automatically fall back to PyMuPDF4LLM.")
            for plan in plans:
                if plan.detected_format == "PDF" and plan.note:
                    self.write_log(f"PDF plan: {Path(plan.source).name} -> {plan.pipeline}; {plan.note}")
        for item in missing:
            self.write_log(item)

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
            messagebox.showwarning("Environment check", f"{len(missing)} missing item(s). See log for details.")
        elif warnings:
            messagebox.showinfo("Environment check", f"{len(warnings)} warning item(s). See log for details.")
        else:
            messagebox.showinfo("Environment check", "All required checks passed for the current selection.")

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
            messagebox.showinfo("Busy", "A conversion task is already running.")
            return

        input_text = self.input_var.get().strip()
        output_text = self.output_var.get().strip()
        if not input_text or not output_text:
            messagebox.showerror("Missing paths", "Please choose both input and output paths.")
            return

        output_path = Path(output_text)
        options = self.build_options()
        if options.resume and options.manifest is None:
            options.manifest = output_path / "manifest.json"
        input_root, sources = self.resolve_sources(options)
        if not sources:
            messagebox.showerror("No files", "No supported files were found.")
            return

        missing = find_missing_dependencies(sources, options)
        if missing:
            self.write_log("Dependency check failed:")
            for item in missing:
                self.write_log(item)
            messagebox.showerror("Dependencies missing", "\n".join(missing))
            return

        self.refresh_tree(input_root, output_path, options, sources)
        self.write_log(f"Starting conversion for {len(sources)} file(s)...")
        self.set_running_state(True)
        self.total_files = len(sources)
        self.file_start_times.clear()
        self.file_estimates.clear()
        self.progress.configure(maximum=max(len(sources), 1), value=0)
        self.status_var.set(f"准备开始，0/{len(sources)}")
        self.current_stage_var.set("等待任务启动")

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
                self.queue.put(("done", results))
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
                    ok_count = 0
                    for result in payload:
                        if result.status == "ok":
                            ok_count += 1
                    self.progress.configure(value=self.total_files)
                    self.status_var.set(f"已完成，成功 {ok_count}/{len(payload)}")
                    self.current_stage_var.set("全部任务完成")
                    self.set_running_state(False)
                    self.worker = None
                    self.write_log(f"Finished. Success: {ok_count}/{len(payload)}")
                elif kind == "error":
                    self.set_running_state(False)
                    self.status_var.set("执行失败")
                    self.current_stage_var.set("任务异常中断")
                    self.worker = None
                    self.write_log(f"Error: {payload}")
                    messagebox.showerror("Conversion error", payload)
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
            self.status_var.set(f"处理中 {index}/{total}: {source_name} {timing}")
            self.current_stage_var.set("准备任务")
            self.write_log(f"Processing {index}/{total}: {source} {timing}")
            return

        if event == "stage":
            stage_info = payload["result"] or {}
            stage_text = self.describe_stage(stage_info.get("stage", ""), stage_info.get("detail", ""))
            base_value = max(index - 1, 0)
            phase_offset = self.stage_progress_offset(stage_info.get("stage", ""))
            self.progress.configure(value=min(base_value + phase_offset, self.total_files))
            self.status_var.set(f"处理中 {index}/{total}: {source_name} {self.format_timing(source)}")
            self.current_stage_var.set(stage_text)
            self.write_log(f"  - {stage_text}")
            return

        result = payload["result"]
        self.progress.configure(value=index)
        self.status_var.set(f"已完成 {index}/{total}: {source_name} {self.format_timing(source)}")
        self.current_stage_var.set("当前文件已完成")
        self.write_log(f"[{result.status}] {result.source} -> {result.output or '-'}")
        if result.message:
            self.write_log(result.message)

    def set_running_state(self, is_running: bool) -> None:
        state = "disabled" if is_running else "normal"
        self.scan_button.configure(state=state)
        self.health_button.configure(state=state)
        self.start_button.configure(state=state)

    def stage_progress_offset(self, stage: str) -> float:
        mapping = {
            "prepare": 0.08,
            "calibre": 0.22,
            "marker": 0.28,
            "mineru": 0.34,
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
            "prepare": "准备输出文件",
            "calibre": "Calibre 转 EPUB",
            "marker": "Marker 解析 PDF",
            "mineru": "MinerU 结构化解析 PDF",
            "fallback": "切换到 PyMuPDF4LLM",
            "pymupdf": "PyMuPDF4LLM 解析 PDF",
            "umi": "Umi-OCR 解析 PDF",
            "umi_page": "Umi-OCR 逐页识别",
            "pandoc": "Pandoc 转换",
            "collect": "收集转换结果",
            "copy": "写入 Markdown 文件",
            "quality": "生成 PDF 质量报告",
            "postprocess": "清洗 Markdown",
            "footnotes": "提取脚注与尾注",
        }
        label = labels.get(stage, stage or "处理中")
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
            return f"(已用 {self.format_duration(elapsed)} / 预计 {self.format_duration(estimate)}，约剩 {self.format_duration(remaining)})"
        return f"(已用 {self.format_duration(elapsed)})"

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
            self.status_var.set("就绪")
            self.current_stage_var.set("")

    def write_log(self, text: str) -> None:
        self.log.insert("end", text + "\n")
        self.log.see("end")


def main() -> None:
    root = TkinterDnD.Tk() if TkinterDnD is not None else tk.Tk()
    root.option_add("*Font", "{Segoe UI} 10")
    BookConverterUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
