"""Minimal Tkinter-based GUI for the talks reducer pipeline."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterable, List, Optional, Sequence

if TYPE_CHECKING:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

try:
    from .cli import gather_input_files
    from .cli import main as cli_main
    from .ffmpeg import FFmpegNotFoundError
    from .models import ProcessingOptions
    from .pipeline import speed_up_video
    from .progress import ProgressHandle, SignalProgressReporter
except ImportError:  # pragma: no cover - handled at runtime
    if __package__ not in (None, ""):
        raise

    PACKAGE_ROOT = Path(__file__).resolve().parent.parent
    if str(PACKAGE_ROOT) not in sys.path:
        sys.path.insert(0, str(PACKAGE_ROOT))

    from talks_reducer.cli import gather_input_files
    from talks_reducer.cli import main as cli_main
    from talks_reducer.ffmpeg import FFmpegNotFoundError
    from talks_reducer.models import ProcessingOptions
    from talks_reducer.pipeline import speed_up_video
    from talks_reducer.progress import ProgressHandle, SignalProgressReporter


def _check_tkinter_available() -> tuple[bool, str]:
    """Check if tkinter can create windows without importing it globally."""
    # Test in a subprocess to avoid crashing the main process
    test_code = """
import json

def run_check():
    try:
        import tkinter as tk  # noqa: F401 - imported for side effect
    except Exception as exc:  # pragma: no cover - runs in subprocess
        return {
            "status": "import_error",
            "error": f"{exc.__class__.__name__}: {exc}",
        }

    try:
        import tkinter as tk

        root = tk.Tk()
        root.destroy()
    except Exception as exc:  # pragma: no cover - runs in subprocess
        return {
            "status": "init_error",
            "error": f"{exc.__class__.__name__}: {exc}",
        }

    return {"status": "ok"}


if __name__ == "__main__":
    print(json.dumps(run_check()))
"""

    try:
        result = subprocess.run(
            [sys.executable, "-c", test_code], capture_output=True, text=True, timeout=5
        )

        output = result.stdout.strip() or result.stderr.strip()

        if not output:
            return False, "Window creation failed"

        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            return False, output

        status = payload.get("status")

        if status == "ok":
            return True, ""

        if status == "import_error":
            return (
                False,
                f"tkinter is not installed ({payload.get('error', 'unknown error')})",
            )

        if status == "init_error":
            return (
                False,
                f"tkinter could not open a window ({payload.get('error', 'unknown error')})",
            )

        return False, output
    except Exception as e:  # pragma: no cover - defensive fallback
        return False, f"Error testing tkinter: {e}"


try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ModuleNotFoundError:  # pragma: no cover - runtime dependency
    DND_FILES = None  # type: ignore[assignment]
    TkinterDnD = None  # type: ignore[assignment]


STATUS_COLORS = {
    "idle": "#9ca3af",
    "processing": "#facc15",
    "success": "#22c55e",
    "error": "#f87171",
}

LIGHT_THEME = {
    "background": "#f5f5f5",
    "foreground": "#1f2933",
    "accent": "#2563eb",
    "surface": "#ffffff",
    "border": "#cbd5e1",
    "hover": "#1d4ed8",
    "selection_background": "#2563eb",
    "selection_foreground": "#ffffff",
}

DARK_THEME = {
    "background": "#1e1e28",
    "foreground": "#f3f4f6",
    "accent": "#60a5fa",
    "surface": "#2b2b3c",
    "border": "#4b5563",
    "hover": "#333333",
    "selection_background": "#333333",
    "selection_foreground": "#f3f4f6",
}


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
        # Import tkinter here to avoid loading it at module import time
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk

        # Store references for use in methods
        self.tk = tk
        self.filedialog = filedialog
        self.messagebox = messagebox
        self.ttk = ttk

        if TkinterDnD is not None:
            self.root = TkinterDnD.Tk()  # type: ignore[call-arg]
        else:
            self.root = tk.Tk()
        self.root.title("Talks Reducer")
        self._apply_window_icon()

        self._full_size = (760, 680)
        self._simple_size = (245, 300)
        self.root.geometry(f"{self._full_size[0]}x{self._full_size[1]}")
        self.style = self.ttk.Style(self.root)

        self._processing_thread: Optional[threading.Thread] = None
        self._last_output: Optional[Path] = None
        self._status_state = "Idle"
        self.status_var = tk.StringVar(value=self._status_state)
        self._status_animation_job: Optional[str] = None
        self._status_animation_phase = 0

        self.input_files: List[str] = []

        self._dnd_available = TkinterDnD is not None and DND_FILES is not None

        self.simple_mode_var = tk.BooleanVar(value=True)
        self.run_after_drop_var = tk.BooleanVar(value=True)
        self.small_var = tk.BooleanVar(value=True)
        self.theme_var = tk.StringVar(value="os")
        self.theme_var.trace_add("write", self._on_theme_change)

        self._build_layout()
        self._apply_simple_mode(initial=True)
        self._apply_status_style(self._status_state)
        self._apply_theme()

        if not self._dnd_available:
            self._append_log(
                "Drag and drop requires the tkinterdnd2 package. Install it to enable the drop zone."
            )

    # ------------------------------------------------------------------ UI --
    def _apply_window_icon(self) -> None:
        """Configure the application icon when the asset is available."""

        base_path = Path(
            getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)
        )

        icon_candidates: list[tuple[Path, str]] = []
        if sys.platform.startswith("win"):
            icon_candidates.append((base_path / "docs" / "assets" / "icon.ico", "ico"))
        icon_candidates.append((base_path / "docs" / "assets" / "icon.png", "png"))

        for icon_path, icon_type in icon_candidates:
            if not icon_path.is_file():
                continue

            try:
                if icon_type == "ico" and sys.platform.startswith("win"):
                    # On Windows, iconbitmap works better without the 'default' parameter
                    self.root.iconbitmap(str(icon_path))
                else:
                    self.root.iconphoto(False, self.tk.PhotoImage(file=str(icon_path)))
                # If we got here without exception, icon was set successfully
                return
            except (self.tk.TclError, Exception) as e:
                # Missing Tk image support or invalid icon format - try next candidate
                continue

    def _build_layout(self) -> None:
        main = self.ttk.Frame(self.root, padding=16)
        main.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        # Input selection frame
        input_frame = self.ttk.LabelFrame(main, text="Input files", padding=12)
        input_frame.grid(row=0, column=0, sticky="nsew")
        main.rowconfigure(0, weight=1)
        for column in range(4):
            input_frame.columnconfigure(column, weight=1)

        self.input_list = self.tk.Listbox(input_frame, height=5)
        self.input_list.grid(row=0, column=0, columnspan=4, sticky="nsew", pady=(0, 12))
        self.input_scrollbar = self.ttk.Scrollbar(
            input_frame, orient=self.tk.VERTICAL, command=self.input_list.yview
        )
        self.input_scrollbar.grid(row=0, column=4, sticky="ns", pady=(0, 12))
        self.input_list.configure(yscrollcommand=self.input_scrollbar.set)

        self.drop_zone = self.tk.Label(
            input_frame,
            text="Drop files or folders here",
            relief=self.tk.RIDGE,
            borderwidth=2,
            padx=16,
            pady=16,
            highlightthickness=1,
        )
        self.drop_zone.grid(row=1, column=0, columnspan=4, sticky="nsew")
        input_frame.rowconfigure(1, weight=1)
        self._configure_drop_targets(self.drop_zone)
        self._configure_drop_targets(self.input_list)

        self.add_files_button = self.ttk.Button(
            input_frame, text="Add files", command=self._add_files
        )
        self.add_files_button.grid(row=2, column=0, pady=8, sticky="w")
        self.add_folder_button = self.ttk.Button(
            input_frame, text="Add folder", command=self._add_directory
        )
        self.add_folder_button.grid(row=2, column=1, pady=8)
        self.remove_selected_button = self.ttk.Button(
            input_frame, text="Remove selected", command=self._remove_selected
        )
        self.remove_selected_button.grid(row=2, column=2, pady=8, sticky="w")
        self.run_after_drop_check = self.ttk.Checkbutton(
            input_frame,
            text="Run after drop",
            variable=self.run_after_drop_var,
        )
        self.run_after_drop_check.grid(row=2, column=3, pady=8, sticky="e")

        # Options frame
        options = self.ttk.LabelFrame(main, text="Options", padding=12)
        options.grid(row=1, column=0, pady=(16, 0), sticky="nsew")
        options.columnconfigure(0, weight=1)

        self.simple_mode_check = self.ttk.Checkbutton(
            options,
            text="Simple mode",
            variable=self.simple_mode_var,
            command=self._toggle_simple_mode,
        )
        self.simple_mode_check.grid(row=0, column=0, sticky="w")

        self.ttk.Checkbutton(options, text="Small video", variable=self.small_var).grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )

        self.advanced_visible = self.tk.BooleanVar(value=False)
        self.advanced_button = self.ttk.Button(
            options,
            text="Advanced",
            command=self._toggle_advanced,
        )
        self.advanced_button.grid(row=0, column=1, sticky="e")

        self.advanced_frame = self.ttk.Frame(options, padding=(0, 12, 0, 0))
        self.advanced_frame.grid(row=2, column=0, columnspan=2, sticky="nsew")
        self.advanced_frame.columnconfigure(1, weight=1)

        self.output_var = self.tk.StringVar()
        self._add_entry(
            self.advanced_frame, "Output file", self.output_var, row=0, browse=True
        )

        self.temp_var = self.tk.StringVar(value="TEMP")
        self._add_entry(
            self.advanced_frame, "Temp folder", self.temp_var, row=1, browse=True
        )

        self.silent_threshold_var = self.tk.StringVar()
        self._add_entry(
            self.advanced_frame,
            "Silent threshold",
            self.silent_threshold_var,
            row=2,
        )

        self.sounded_speed_var = self.tk.StringVar()
        self._add_entry(
            self.advanced_frame, "Sounded speed", self.sounded_speed_var, row=3
        )

        self.silent_speed_var = self.tk.StringVar()
        self._add_entry(
            self.advanced_frame, "Silent speed", self.silent_speed_var, row=4
        )

        self.frame_margin_var = self.tk.StringVar()
        self._add_entry(
            self.advanced_frame, "Frame margin", self.frame_margin_var, row=5
        )

        self.sample_rate_var = self.tk.StringVar()
        self._add_entry(self.advanced_frame, "Sample rate", self.sample_rate_var, row=6)

        self.ttk.Label(self.advanced_frame, text="Theme").grid(
            row=7, column=0, sticky="w", pady=(8, 0)
        )
        theme_choice = self.ttk.Frame(self.advanced_frame)
        theme_choice.grid(row=7, column=1, columnspan=2, sticky="w", pady=(8, 0))
        for value, label in ("os", "OS"), ("light", "Light"), ("dark", "Dark"):
            self.ttk.Radiobutton(
                theme_choice,
                text=label,
                value=value,
                variable=self.theme_var,
                command=self._apply_theme,
            ).pack(side=self.tk.LEFT, padx=(0, 8))

        self._toggle_advanced(initial=True)

        # Action buttons and log output
        self.actions_frame = self.ttk.Frame(main)
        self.actions_frame.grid(row=2, column=0, pady=(16, 0), sticky="ew")
        self.actions_frame.columnconfigure(1, weight=1)

        self.run_button = self.ttk.Button(
            self.actions_frame, text="Run", command=self._start_run
        )
        self.run_button.grid(row=0, column=0, sticky="w")

        self.open_button = self.ttk.Button(
            self.actions_frame,
            text="Open last output",
            command=self._open_last_output,
            state=self.tk.DISABLED,
        )
        self.open_button.grid(row=0, column=1, sticky="e")
        self.open_button.grid_remove()

        status_frame = self.ttk.Frame(main, padding=(0, 8, 0, 0))
        status_frame.grid(row=3, column=0, sticky="ew")
        status_frame.columnconfigure(1, weight=1)
        self.ttk.Label(status_frame, text="Status:").grid(row=0, column=0, sticky="w")
        self.status_label = self.tk.Label(status_frame, textvariable=self.status_var)
        self.status_label.grid(row=0, column=1, sticky="w")

        self.log_frame = self.ttk.LabelFrame(main, text="Log", padding=12)
        self.log_frame.grid(row=4, column=0, pady=(16, 0), sticky="nsew")
        main.rowconfigure(4, weight=1)
        self.log_frame.columnconfigure(0, weight=1)
        self.log_frame.rowconfigure(0, weight=1)

        self.log_text = self.tk.Text(
            self.log_frame, wrap="word", height=10, state=self.tk.DISABLED
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_scroll = self.ttk.Scrollbar(
            self.log_frame, orient=self.tk.VERTICAL, command=self.log_text.yview
        )
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set)

    def _add_entry(
        self,
        parent,  # type: tk.Misc
        label: str,
        variable,  # type: tk.StringVar
        *,
        row: int,
        browse: bool = False,
    ) -> None:
        self.ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        entry = self.ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=1, sticky="ew", pady=4)
        if browse:
            button = self.ttk.Button(
                parent,
                text="Browse",
                command=lambda var=variable: self._browse_path(var, label),
            )
            button.grid(row=row, column=2, padx=(8, 0))

    def _toggle_simple_mode(self) -> None:
        self._apply_simple_mode()

    def _apply_simple_mode(self, *, initial: bool = False) -> None:
        simple = self.simple_mode_var.get()
        widgets = [
            self.input_list,
            self.input_scrollbar,
            self.add_files_button,
            self.add_folder_button,
            self.remove_selected_button,
            self.run_after_drop_check,
        ]

        if simple:
            for widget in widgets:
                widget.grid_remove()
            self.log_frame.grid_remove()
            self.run_button.grid_remove()
            self.advanced_button.grid_remove()
            self.advanced_frame.grid_remove()
            self.actions_frame.grid_remove()
            self.run_after_drop_var.set(True)
            self._apply_window_size(simple=True)
            if self.status_var.get().lower() == "success":
                self.actions_frame.grid()
                self.open_button.grid()
        else:
            for widget in widgets:
                widget.grid()
            self.log_frame.grid()
            self.actions_frame.grid()
            self.run_button.grid()
            self.advanced_button.grid()
            if self.advanced_visible.get():
                self.advanced_frame.grid()
            self._apply_window_size(simple=False)

        if initial and simple:
            # Ensure the hidden widgets do not retain focus outlines on start.
            self.drop_zone.focus_set()

    def _apply_window_size(self, *, simple: bool) -> None:
        width, height = self._simple_size if simple else self._full_size
        self.root.update_idletasks()
        self.root.minsize(width, height)
        if simple:
            self.root.geometry(f"{width}x{height}")
        else:
            current_width = self.root.winfo_width()
            current_height = self.root.winfo_height()
            if current_width < width or current_height < height:
                self.root.geometry(f"{width}x{height}")

    def _toggle_advanced(self, *, initial: bool = False) -> None:
        if not initial:
            self.advanced_visible.set(not self.advanced_visible.get())
        visible = self.advanced_visible.get()
        if visible:
            self.advanced_frame.grid()
            self.advanced_button.configure(text="Hide advanced")
        else:
            self.advanced_frame.grid_remove()
            self.advanced_button.configure(text="Advanced")

    def _on_theme_change(self, *_: object) -> None:
        self._apply_theme()

    def _apply_theme(self) -> None:
        preference = self.theme_var.get().lower()
        if preference not in {"light", "dark"}:
            mode = self._detect_system_theme()
        else:
            mode = preference

        palette = LIGHT_THEME if mode == "light" else DARK_THEME

        self.root.configure(bg=palette["background"])
        self.style.theme_use("clam")
        self.style.configure(
            ".", background=palette["background"], foreground=palette["foreground"]
        )
        self.style.configure("TFrame", background=palette["background"])
        self.style.configure(
            "TLabelframe",
            background=palette["background"],
            foreground=palette["foreground"],
        )
        self.style.configure(
            "TLabelframe.Label",
            background=palette["background"],
            foreground=palette["foreground"],
        )
        self.style.configure(
            "TLabel", background=palette["background"], foreground=palette["foreground"]
        )
        self.style.configure(
            "TCheckbutton",
            background=palette["background"],
            foreground=palette["foreground"],
        )
        self.style.configure(
            "TRadiobutton",
            background=palette["background"],
            foreground=palette["foreground"],
        )
        self.style.configure(
            "TButton",
            background=palette["surface"],
            foreground=palette["foreground"],
            padding=6,
        )
        self.style.map(
            "TButton",
            background=[
                ("active", palette.get("hover", palette["accent"])),
                ("disabled", palette["surface"]),
            ],
            foreground=[
                ("active", palette["surface"]),
                ("disabled", palette["foreground"]),
            ],
        )
        self.style.configure(
            "TEntry",
            fieldbackground=palette["surface"],
            foreground=palette["foreground"],
        )
        self.style.configure(
            "TCombobox",
            fieldbackground=palette["surface"],
            foreground=palette["foreground"],
        )

        self.drop_zone.configure(
            bg=palette["surface"],
            fg=palette["foreground"],
            highlightbackground=palette["border"],
            highlightcolor=palette["border"],
        )
        self.input_list.configure(
            bg=palette["surface"],
            fg=palette["foreground"],
            selectbackground=palette.get("selection_background", palette["accent"]),
            selectforeground=palette.get("selection_foreground", palette["surface"]),
            highlightbackground=palette["border"],
            highlightcolor=palette["border"],
        )
        self.log_text.configure(
            bg=palette["surface"],
            fg=palette["foreground"],
            insertbackground=palette["foreground"],
            highlightbackground=palette["border"],
            highlightcolor=palette["border"],
        )
        self.status_label.configure(bg=palette["background"])

        self._apply_status_style(self._status_state)

    def _detect_system_theme(self) -> str:
        if sys.platform.startswith("win"):
            try:
                import winreg  # type: ignore

                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                ) as key:
                    value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return "light" if int(value) else "dark"
            except OSError:
                return "light"
        if sys.platform == "darwin":
            try:
                result = subprocess.run(
                    ["defaults", "read", "-g", "AppleInterfaceStyle"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode == 0 and result.stdout.strip().lower() == "dark":
                    return "dark"
            except Exception:
                pass
            return "light"

        theme = os.environ.get("GTK_THEME", "").lower()
        if "dark" in theme:
            return "dark"
        return "light"

    def _configure_drop_targets(self, widget) -> None:  # type: tk.Widget
        if not self._dnd_available:
            return
        widget.drop_target_register(DND_FILES)  # type: ignore[arg-type]
        widget.dnd_bind("<<Drop>>", self._on_drop)  # type: ignore[attr-defined]

    # -------------------------------------------------------------- actions --
    def _add_files(self) -> None:
        files = self.filedialog.askopenfilenames(
            title="Select input files",
            filetypes=[
                ("Video files", "*.mp4 *.mkv *.mov *.avi *.m4v"),
                ("All", "*.*"),
            ],
        )
        self._extend_inputs(files)

    def _add_directory(self) -> None:
        directory = self.filedialog.askdirectory(title="Select input folder")
        if directory:
            self._extend_inputs([directory])

    def _extend_inputs(self, paths: Iterable[str], *, auto_run: bool = False) -> None:
        added = False
        for path in paths:
            if path and path not in self.input_files:
                self.input_files.append(path)
                self.input_list.insert(self.tk.END, path)
                added = True
        if auto_run and added and self.run_after_drop_var.get():
            self._start_run()

    def _remove_selected(self) -> None:
        selection = list(self.input_list.curselection())
        for index in reversed(selection):
            self.input_list.delete(index)
            del self.input_files[index]

    def _on_drop(self, event: object) -> None:
        data = getattr(event, "data", "")
        if not data:
            return
        paths = self.root.tk.splitlist(data)
        cleaned = [path.strip("{}") for path in paths]
        self._extend_inputs(cleaned, auto_run=True)

    def _browse_path(
        self, variable, label: str
    ) -> None:  # type: (tk.StringVar, str) -> None
        if "folder" in label.lower():
            result = self.filedialog.askdirectory()
        else:
            initial = variable.get() or os.getcwd()
            result = self.filedialog.asksaveasfilename(
                initialfile=os.path.basename(initial)
            )
        if result:
            variable.set(result)

    def _start_run(self) -> None:
        if self._processing_thread and self._processing_thread.is_alive():
            self.messagebox.showinfo("Processing", "A job is already running.")
            return

        if not self.input_files:
            self.messagebox.showwarning(
                "Missing input", "Please add at least one file or folder."
            )
            return

        try:
            args = self._collect_arguments()
        except ValueError as exc:
            self.messagebox.showerror("Invalid value", str(exc))
            return

        self._append_log("Starting processing…")
        self.run_button.configure(state=self.tk.DISABLED)

        def worker() -> None:
            reporter = _TkProgressReporter(self._append_log)
            try:
                files = gather_input_files(self.input_files)
                if not files:
                    self._notify(
                        lambda: self.messagebox.showwarning(
                            "No files", "No supported media files were found."
                        )
                    )
                    self._set_status("Idle")
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
                self._notify(lambda: self.open_button.configure(state=self.tk.NORMAL))
            except FFmpegNotFoundError as exc:
                self._notify(
                    lambda: self.messagebox.showerror("FFmpeg not found", str(exc))
                )
                self._set_status("Error")
            except Exception as exc:  # pragma: no cover - GUI level safeguard
                self._notify(
                    lambda: self.messagebox.showerror(
                        "Error", f"Processing failed: {exc}"
                    )
                )
                self._set_status("Error")
            finally:
                self._notify(lambda: self.run_button.configure(state=self.tk.NORMAL))

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
        self._update_status_from_message(message)

        def updater() -> None:
            self.log_text.configure(state=self.tk.NORMAL)
            self.log_text.insert(self.tk.END, message + "\n")
            self.log_text.see(self.tk.END)
            self.log_text.configure(state=self.tk.DISABLED)

        self.log_text.after(0, updater)

    def _update_status_from_message(self, message: str) -> None:
        normalized = message.strip().lower()
        if "all jobs finished successfully" in normalized:
            self._set_status("Success")
        elif normalized.startswith("starting processing") or normalized.startswith(
            "processing"
        ):
            self._set_status("Processing")

    def _apply_status_style(self, status: str) -> None:
        color = STATUS_COLORS.get(status.lower())
        if color:
            self.status_label.configure(fg=color)
        else:
            self.status_label.configure(fg="")

    def _set_status(self, status: str) -> None:
        def apply() -> None:
            self._stop_status_animation()
            self._status_state = status
            self.status_var.set(status)
            self._apply_status_style(status)
            lowered = status.lower()
            if lowered == "processing":
                self.run_button.configure(state=self.tk.DISABLED)
                self._start_status_animation()
            else:
                if not self.simple_mode_var.get():
                    self.run_button.configure(state=self.tk.NORMAL)

            if lowered == "success":
                if self.simple_mode_var.get():
                    self.actions_frame.grid()
                self.open_button.grid()
            else:
                self.open_button.grid_remove()
                if self.simple_mode_var.get():
                    self.actions_frame.grid_remove()

        self.root.after(0, apply)

    def _start_status_animation(self) -> None:
        self._status_animation_phase = 0
        self._schedule_status_animation()

    def _schedule_status_animation(self) -> None:
        if self._status_state.lower() != "processing":
            return

        dots = self._status_animation_phase % 4
        suffix = "." * dots
        text = "Processing" + suffix
        self.status_var.set(text)
        self._status_animation_phase = (self._status_animation_phase + 1) % 4
        self._status_animation_job = self.root.after(
            400, self._schedule_status_animation
        )

    def _stop_status_animation(self) -> None:
        if self._status_animation_job is not None:
            self.root.after_cancel(self._status_animation_job)
            self._status_animation_job = None
        if self._status_state.lower() != "processing":
            self.status_var.set(self._status_state)

    def _notify(self, callback: Callable[[], None]) -> None:
        self.root.after(0, callback)

    def run(self) -> None:
        """Start the Tkinter event loop."""

        self.root.mainloop()


def main(argv: Optional[Sequence[str]] = None) -> bool:
    """Launch the GUI when run without arguments, otherwise defer to the CLI.

    Returns ``True`` if the GUI event loop started successfully. ``False``
    indicates that execution was delegated to the CLI or aborted early.
    """

    if argv is None:
        argv = sys.argv[1:]

    if argv:
        cli_main(argv)
        return False

    # Skip tkinter check if running as a PyInstaller frozen app
    # In that case, tkinter is bundled and the subprocess check would fail
    is_frozen = getattr(sys, "frozen", False)

    if not is_frozen:
        # Check if tkinter is available before creating GUI (only when not frozen)
        tkinter_available, error_msg = _check_tkinter_available()

        if not tkinter_available:
            # Use ASCII-safe output for Windows console compatibility
            try:
                print("Talks Reducer GUI")
                print("=" * 50)
                print("X GUI not available on this system")
                print(f"Error: {error_msg}")
                print()
                print("! Alternative: Use the command-line interface")
                print()
                print("The CLI provides all the same functionality:")
                print("  python3 -m talks_reducer <input_file> [options]")
                print()
                print("Examples:")
                print("  python3 -m talks_reducer video.mp4")
                print("  python3 -m talks_reducer video.mp4 --small")
                print("  python3 -m talks_reducer video.mp4 -o output.mp4")
                print()
                print("Run 'python3 -m talks_reducer --help' for all options.")
                print()
                print("This is likely a macOS/Tkinter compatibility issue.")
                print("The CLI interface works perfectly and is recommended.")
            except UnicodeEncodeError:
                # Fallback for extreme encoding issues
                sys.stderr.write("GUI not available. Use CLI mode instead.\n")
            return False

    # Catch and report any errors during GUI initialization
    try:
        app = TalksReducerGUI()
        app.run()
        return True
    except Exception as e:
        import traceback

        sys.stderr.write(f"Error starting GUI: {e}\n")
        sys.stderr.write(traceback.format_exc())
        sys.stderr.write("\nPlease use the CLI mode instead:\n")
        sys.stderr.write("  python3 -m talks_reducer <input_file> [options]\n")
        sys.exit(1)


if __name__ == "__main__":
    main()


__all__ = ["TalksReducerGUI", "main"]
