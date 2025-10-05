"""Minimal Tkinter-based GUI for the talks reducer pipeline."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Iterable, List, Optional

from .cli import gather_input_files
from .ffmpeg import FFmpegNotFoundError
from .models import ProcessingOptions
from .pipeline import speed_up_video
from .progress import ProgressHandle, SignalProgressReporter


class _GuiProgressHandle(ProgressHandle):
    """Simple progress handle that records totals but only logs milestones."""

    def __init__(self, log_callback: Callable[[str], None], desc: str) -> None:
        self._log_callback = log_callback
        self._desc = desc
        self._current = 0
        self._total: Optional[int] = None
        if desc:
            self._log_callback(f"{desc} started")

    @property
    def current(self) -> int:
        return self._current

    def ensure_total(self, total: int) -> None:
        if self._total is None or total > self._total:
            self._total = total

    def advance(self, amount: int) -> None:
        if amount > 0:
            self._current += amount

    def finish(self) -> None:
        if self._total is not None:
            self._current = self._total
        if self._desc:
            self._log_callback(f"{self._desc} completed")

    def __enter__(self) -> "_GuiProgressHandle":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self.finish()
        return False


class _TkProgressReporter(SignalProgressReporter):
    """Progress reporter that forwards updates to the GUI thread."""

    def __init__(self, log_callback: Callable[[str], None]) -> None:
        self._log_callback = log_callback

    def log(self, message: str) -> None:
        self._log_callback(message)

    def task(
        self, *, desc: str = "", total: Optional[int] = None, unit: str = ""
    ) -> _GuiProgressHandle:
        del total, unit
        return _GuiProgressHandle(self._log_callback, desc)


class TalksReducerGUI:
    """Tkinter application mirroring the CLI options with form controls."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Talks Reducer")
        self.root.geometry("760x640")

        self._processing_thread: Optional[threading.Thread] = None
        self._last_output: Optional[Path] = None

        self.input_files: List[str] = []

        self._build_layout()

    # ------------------------------------------------------------------ UI --
    def _build_layout(self) -> None:
        main = ttk.Frame(self.root, padding=16)
        main.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        # Input selection frame
        input_frame = ttk.LabelFrame(main, text="Input files or folders", padding=12)
        input_frame.grid(row=0, column=0, sticky="nsew")
        input_frame.columnconfigure(0, weight=1)

        self.input_list = tk.Listbox(input_frame, height=5)
        self.input_list.grid(row=0, column=0, columnspan=3, sticky="nsew")
        scrollbar = ttk.Scrollbar(
            input_frame, orient=tk.VERTICAL, command=self.input_list.yview
        )
        scrollbar.grid(row=0, column=3, sticky="ns")
        self.input_list.configure(yscrollcommand=scrollbar.set)

        ttk.Button(input_frame, text="Add files", command=self._add_files).grid(
            row=1, column=0, pady=8, sticky="w"
        )
        ttk.Button(input_frame, text="Add folder", command=self._add_directory).grid(
            row=1, column=1, pady=8
        )
        ttk.Button(
            input_frame, text="Remove selected", command=self._remove_selected
        ).grid(row=1, column=2, pady=8, sticky="e")

        # Options frame
        options = ttk.LabelFrame(main, text="Options", padding=12)
        options.grid(row=1, column=0, pady=(16, 0), sticky="nsew")
        options.columnconfigure(1, weight=1)

        self.output_var = tk.StringVar()
        self._add_entry(options, "Output file", self.output_var, row=0, browse=True)

        self.temp_var = tk.StringVar(value="TEMP")
        self._add_entry(options, "Temp folder", self.temp_var, row=1, browse=True)

        self.silent_threshold_var = tk.StringVar()
        self._add_entry(options, "Silent threshold", self.silent_threshold_var, row=2)

        self.sounded_speed_var = tk.StringVar()
        self._add_entry(options, "Sounded speed", self.sounded_speed_var, row=3)

        self.silent_speed_var = tk.StringVar()
        self._add_entry(options, "Silent speed", self.silent_speed_var, row=4)

        self.frame_margin_var = tk.StringVar()
        self._add_entry(options, "Frame margin", self.frame_margin_var, row=5)

        self.sample_rate_var = tk.StringVar()
        self._add_entry(options, "Sample rate", self.sample_rate_var, row=6)

        self.small_var = tk.BooleanVar()
        ttk.Checkbutton(
            options, text="Small file optimizations", variable=self.small_var
        ).grid(row=7, column=0, columnspan=2, pady=8, sticky="w")

        # Action buttons and log output
        actions = ttk.Frame(main)
        actions.grid(row=2, column=0, pady=(16, 0), sticky="ew")
        actions.columnconfigure(1, weight=1)

        self.run_button = ttk.Button(actions, text="Run", command=self._start_run)
        self.run_button.grid(row=0, column=0, sticky="w")

        self.open_button = ttk.Button(
            actions,
            text="Open last output",
            command=self._open_last_output,
            state=tk.DISABLED,
        )
        self.open_button.grid(row=0, column=1, sticky="e")

        log_frame = ttk.LabelFrame(main, text="Log", padding=12)
        log_frame.grid(row=3, column=0, pady=(16, 0), sticky="nsew")
        main.rowconfigure(3, weight=1)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, wrap="word", height=10, state=tk.DISABLED)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(
            log_frame, orient=tk.VERTICAL, command=self.log_text.yview
        )
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set)

    def _add_entry(
        self,
        parent: ttk.LabelFrame,
        label: str,
        variable: tk.StringVar,
        *,
        row: int,
        browse: bool = False,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=1, sticky="ew", pady=4)
        if browse:
            button = ttk.Button(
                parent,
                text="Browse",
                command=lambda var=variable: self._browse_path(var, label),
            )
            button.grid(row=row, column=2, padx=(8, 0))

    # -------------------------------------------------------------- actions --
    def _add_files(self) -> None:
        files = filedialog.askopenfilenames(
            title="Select input files",
            filetypes=[
                ("Video files", "*.mp4 *.mkv *.mov *.avi *.m4v"),
                ("All", "*.*"),
            ],
        )
        self._extend_inputs(files)

    def _add_directory(self) -> None:
        directory = filedialog.askdirectory(title="Select input folder")
        if directory:
            self._extend_inputs([directory])

    def _extend_inputs(self, paths: Iterable[str]) -> None:
        for path in paths:
            if path and path not in self.input_files:
                self.input_files.append(path)
                self.input_list.insert(tk.END, path)

    def _remove_selected(self) -> None:
        selection = list(self.input_list.curselection())
        for index in reversed(selection):
            self.input_list.delete(index)
            del self.input_files[index]

    def _browse_path(self, variable: tk.StringVar, label: str) -> None:
        if "folder" in label.lower():
            result = filedialog.askdirectory()
        else:
            initial = variable.get() or os.getcwd()
            result = filedialog.asksaveasfilename(initialfile=os.path.basename(initial))
        if result:
            variable.set(result)

    def _start_run(self) -> None:
        if self._processing_thread and self._processing_thread.is_alive():
            messagebox.showinfo("Processing", "A job is already running.")
            return

        if not self.input_files:
            messagebox.showwarning(
                "Missing input", "Please add at least one file or folder."
            )
            return

        try:
            args = self._collect_arguments()
        except ValueError as exc:
            messagebox.showerror("Invalid value", str(exc))
            return

        self._append_log("Starting processing…")
        self.run_button.configure(state=tk.DISABLED)

        def worker() -> None:
            reporter = _TkProgressReporter(self._append_log)
            try:
                files = gather_input_files(self.input_files)
                if not files:
                    self._notify(
                        lambda: messagebox.showwarning(
                            "No files", "No supported media files were found."
                        )
                    )
                    return

                for index, file in enumerate(files, start=1):
                    self._append_log(
                        f"Processing {index}/{len(files)}: {os.path.basename(file)}"
                    )
                    options = self._build_options(Path(file), args)
                    result = speed_up_video(options, reporter=reporter)
                    self._last_output = result.output_file
                    self._append_log(f"Completed: {result.output_file}")
                    self._notify(
                        lambda path=result.output_file: self._open_in_file_manager(path)
                    )

                self._append_log("All jobs finished successfully.")
                self._notify(lambda: self.open_button.configure(state=tk.NORMAL))
            except FFmpegNotFoundError as exc:
                self._notify(lambda: messagebox.showerror("FFmpeg not found", str(exc)))
            except Exception as exc:  # pragma: no cover - GUI level safeguard
                self._notify(
                    lambda: messagebox.showerror("Error", f"Processing failed: {exc}")
                )
            finally:
                self._notify(lambda: self.run_button.configure(state=tk.NORMAL))

        self._processing_thread = threading.Thread(target=worker, daemon=True)
        self._processing_thread.start()

    def _collect_arguments(self) -> dict[str, object]:
        args: dict[str, object] = {}

        if self.output_var.get():
            args["output_file"] = Path(self.output_var.get())
        if self.temp_var.get():
            args["temp_folder"] = Path(self.temp_var.get())
        if self.silent_threshold_var.get():
            args["silent_threshold"] = self._parse_float(
                self.silent_threshold_var.get(), "Silent threshold"
            )
        if self.sounded_speed_var.get():
            args["sounded_speed"] = self._parse_float(
                self.sounded_speed_var.get(), "Sounded speed"
            )
        if self.silent_speed_var.get():
            args["silent_speed"] = self._parse_float(
                self.silent_speed_var.get(), "Silent speed"
            )
        if self.frame_margin_var.get():
            args["frame_spreadage"] = int(
                round(self._parse_float(self.frame_margin_var.get(), "Frame margin"))
            )
        if self.sample_rate_var.get():
            args["sample_rate"] = int(
                round(self._parse_float(self.sample_rate_var.get(), "Sample rate"))
            )
        if self.small_var.get():
            args["small"] = True

        return args

    def _parse_float(self, value: str, label: str) -> float:
        try:
            return float(value)
        except ValueError as exc:  # pragma: no cover - input validation
            raise ValueError(f"{label} must be a number.") from exc

    def _build_options(
        self, input_file: Path, args: dict[str, object]
    ) -> ProcessingOptions:
        options = dict(args)
        options["input_file"] = input_file

        if "temp_folder" in options:
            options["temp_folder"] = Path(options["temp_folder"])

        return ProcessingOptions(**options)

    def _open_last_output(self) -> None:
        if self._last_output is not None:
            self._open_in_file_manager(self._last_output)

    def _open_in_file_manager(self, path: Path) -> None:
        target = Path(path)
        if sys.platform.startswith("win"):
            command = ["explorer", f"/select,{target}"]
        elif sys.platform == "darwin":
            command = ["open", "-R", os.fspath(target)]
        else:
            command = [
                "xdg-open",
                os.fspath(target.parent if target.exists() else target),
            ]
        try:
            subprocess.Popen(command)
        except OSError:
            self._append_log(f"Could not open file manager for {target}")

    def _append_log(self, message: str) -> None:
        def updater() -> None:
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.insert(tk.END, message + "\n")
            self.log_text.see(tk.END)
            self.log_text.configure(state=tk.DISABLED)

        self.log_text.after(0, updater)

    def _notify(self, callback: Callable[[], None]) -> None:
        self.root.after(0, callback)

    def run(self) -> None:
        """Start the Tkinter event loop."""

        self.root.mainloop()


def main() -> None:
    """Entry-point used by the ``talks-reducer-gui`` console script."""

    app = TalksReducerGUI()
    app.run()


__all__ = ["TalksReducerGUI", "main"]
