"""Minimal Tkinter-based GUI for the talks reducer pipeline."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterable, List, Optional, Sequence

if TYPE_CHECKING:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

try:
    from .cli import gather_input_files
    from .cli import main as cli_main
    from .ffmpeg import FFmpegNotFoundError
    from .models import ProcessingOptions, default_temp_folder
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
    from talks_reducer.models import ProcessingOptions, default_temp_folder
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
    "processing": "#af8e0e",
    "success": "#178941",
    "error": "#ad4f4f",
    "aborted": "#6d727a",
}

LIGHT_THEME = {
    "background": "#f5f5f5",
    "foreground": "#1f2933",
    "accent": "#2563eb",
    "surface": "#ffffff",
    "border": "#cbd5e1",
    "hover": "#efefef",
    "hover_text": "#000000",
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
    "hover_text": "#ffffff",
    "selection_background": "#333333",
    "selection_foreground": "#f3f4f6",
}


_TRAY_LOCK = threading.Lock()
_TRAY_PROCESS: Optional[subprocess.Popen[Any]] = None


def _ensure_server_tray_running(extra_args: Optional[Sequence[str]] = None) -> None:
    """Start the server tray in a background process if one is not active."""

    global _TRAY_PROCESS

    with _TRAY_LOCK:
        if _TRAY_PROCESS is not None and _TRAY_PROCESS.poll() is None:
            return

        command = [sys.executable, "-m", "talks_reducer.server_tray"]
        if extra_args:
            command.extend(extra_args)

        try:
            _TRAY_PROCESS = subprocess.Popen(command)
        except Exception as exc:  # pragma: no cover - best-effort fallback
            _TRAY_PROCESS = None
            sys.stderr.write(
                f"Warning: failed to launch Talks Reducer server tray: {exc}\n"
            )


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

    def __init__(
        self,
        log_callback: Callable[[str], None],
        process_callback: Optional[Callable] = None,
    ) -> None:
        self._log_callback = log_callback
        self.process_callback = process_callback

    def log(self, message: str) -> None:
        self._log_callback(message)
        print(message, flush=True)

    def task(
        self, *, desc: str = "", total: Optional[int] = None, unit: str = ""
    ) -> _GuiProgressHandle:
        del total, unit
        return _GuiProgressHandle(self._log_callback, desc)


class TalksReducerGUI:
    """Tkinter application mirroring the CLI options with form controls."""

    PADDING = 10

    def _determine_config_path(self) -> Path:
        if sys.platform == "win32":
            appdata = os.environ.get("APPDATA")
            base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        elif sys.platform == "darwin":
            base = Path.home() / "Library" / "Application Support"
        else:
            xdg_config = os.environ.get("XDG_CONFIG_HOME")
            base = Path(xdg_config) if xdg_config else Path.home() / ".config"
        return base / "talks-reducer" / "settings.json"

    def _load_settings(self) -> dict[str, object]:
        try:
            with self._config_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return data
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError):
            return {}
        return {}

    def _save_settings(self) -> None:
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            with self._config_path.open("w", encoding="utf-8") as handle:
                json.dump(self._settings, handle, indent=2, sort_keys=True)
        except OSError:
            pass

    def _get_setting(self, key: str, default: object) -> object:
        value = self._settings.get(key, default)
        if key not in self._settings:
            self._settings[key] = value
        return value

    def _update_setting(self, key: str, value: object) -> None:
        if self._settings.get(key) == value:
            return
        self._settings[key] = value
        self._save_settings()

    def __init__(
        self,
        initial_inputs: Optional[Sequence[str]] = None,
        *,
        auto_run: bool = False,
    ) -> None:
        self._config_path = self._determine_config_path()
        self._settings = self._load_settings()

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

        # Set window title with version
        try:
            app_version = version("talks-reducer")
            self.root.title(f"Talks Reducer v{app_version}")
        except Exception:
            self.root.title("Talks Reducer")

        self._apply_window_icon()

        self._full_size = (1000, 800)
        self._simple_size = (300, 270)
        self.root.geometry(f"{self._full_size[0]}x{self._full_size[1]}")
        self.style = self.ttk.Style(self.root)

        self._processing_thread: Optional[threading.Thread] = None
        self._last_output: Optional[Path] = None
        self._last_time_ratio: Optional[float] = None
        self._last_size_ratio: Optional[float] = None
        self._status_state = "Idle"
        self.status_var = tk.StringVar(value=self._status_state)
        self._status_animation_job: Optional[str] = None
        self._status_animation_phase = 0
        self._video_duration_seconds: Optional[float] = None
        self._encode_target_duration_seconds: Optional[float] = None
        self._encode_total_frames: Optional[int] = None
        self._encode_current_frame: Optional[int] = None
        self.progress_var = tk.IntVar(value=0)
        self._ffmpeg_process: Optional[subprocess.Popen] = None
        self._stop_requested = False

        self.input_files: List[str] = []

        self._dnd_available = TkinterDnD is not None and DND_FILES is not None

        self.simple_mode_var = tk.BooleanVar(
            value=self._get_setting("simple_mode", True)
        )
        self.run_after_drop_var = tk.BooleanVar(value=True)
        self.small_var = tk.BooleanVar(value=self._get_setting("small_video", True))
        self.open_after_convert_var = tk.BooleanVar(
            value=self._get_setting("open_after_convert", True)
        )
        self.theme_var = tk.StringVar(value=self._get_setting("theme", "os"))
        self.theme_var.trace_add("write", self._on_theme_change)
        self.small_var.trace_add("write", self._on_small_video_change)
        self.open_after_convert_var.trace_add(
            "write", self._on_open_after_convert_change
        )

        self._build_layout()
        self._apply_simple_mode(initial=True)
        self._apply_status_style(self._status_state)
        self._apply_theme()
        self._save_settings()
        self._hide_stop_button()

        if not self._dnd_available:
            self._append_log(
                "Drag and drop requires the tkinterdnd2 package. Install it to enable the drop zone."
            )

        if initial_inputs:
            self._populate_initial_inputs(initial_inputs, auto_run=auto_run)

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
        main = self.ttk.Frame(self.root, padding=self.PADDING)
        main.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        # Input selection frame
        input_frame = self.ttk.Frame(main, padding=self.PADDING)
        input_frame.grid(row=0, column=0, sticky="nsew")
        main.rowconfigure(0, weight=1)
        main.columnconfigure(0, weight=1)
        for column in range(5):
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
            text="Drop video here",
            relief=self.tk.FLAT,
            borderwidth=0,
            padx=self.PADDING,
            pady=self.PADDING,
            highlightthickness=0,
        )
        self.drop_zone.grid(row=1, column=0, columnspan=5, sticky="nsew")
        input_frame.rowconfigure(1, weight=1)
        self._configure_drop_targets(self.drop_zone)
        self._configure_drop_targets(self.input_list)
        self.drop_zone.configure(cursor="hand2", takefocus=1)
        self.drop_zone.bind("<Button-1>", self._on_drop_zone_click)
        self.drop_zone.bind("<Return>", self._on_drop_zone_click)
        self.drop_zone.bind("<space>", self._on_drop_zone_click)

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
        options = self.ttk.Frame(main, padding=self.PADDING)
        options.grid(row=2, column=0, pady=(0, 0), sticky="ew")
        options.columnconfigure(0, weight=1)

        checkbox_frame = self.ttk.Frame(options)
        checkbox_frame.grid(row=0, column=0, columnspan=2, sticky="w")

        self.ttk.Checkbutton(
            checkbox_frame,
            text="Small video",
            variable=self.small_var,
        ).grid(row=0, column=0, sticky="w")

        self.ttk.Checkbutton(
            checkbox_frame,
            text="Open after convert",
            variable=self.open_after_convert_var,
        ).grid(row=0, column=1, sticky="w", padx=(12, 0))

        self.simple_mode_check = self.ttk.Checkbutton(
            checkbox_frame,
            text="Simple mode",
            variable=self.simple_mode_var,
            command=self._toggle_simple_mode,
        )
        self.simple_mode_check.grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(8, 0)
        )

        self.advanced_visible = self.tk.BooleanVar(value=False)
        self.advanced_button = self.ttk.Button(
            options,
            text="Advanced",
            command=self._toggle_advanced,
        )
        self.advanced_button.grid(row=1, column=1, sticky="e")

        self.advanced_frame = self.ttk.Frame(options, padding=self.PADDING)
        self.advanced_frame.grid(row=2, column=0, columnspan=2, sticky="nsew")
        self.advanced_frame.columnconfigure(1, weight=1)

        self.output_var = self.tk.StringVar()
        self._add_entry(
            self.advanced_frame, "Output file", self.output_var, row=0, browse=True
        )

        self.temp_var = self.tk.StringVar(value=str(default_temp_folder()))
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

        self.sample_rate_var = self.tk.StringVar(value="48000")
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
        status_frame = self.ttk.Frame(main, padding=self.PADDING)
        status_frame.grid(row=1, column=0, sticky="ew")
        status_frame.columnconfigure(0, weight=0)
        status_frame.columnconfigure(1, weight=1)
        status_frame.columnconfigure(2, weight=0)

        self.ttk.Label(status_frame, text="Status:").grid(row=0, column=0, sticky="w")
        self.status_label = self.tk.Label(
            status_frame, textvariable=self.status_var, anchor="e"
        )
        self.status_label.grid(row=0, column=1, sticky="e")

        # Progress bar
        self.progress_bar = self.ttk.Progressbar(
            status_frame,
            variable=self.progress_var,
            maximum=100,
            mode="determinate",
            style="Idle.Horizontal.TProgressbar",
        )
        self.progress_bar.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 0))

        self.stop_button = self.ttk.Button(
            status_frame, text="Stop", command=self._stop_processing
        )
        self.stop_button.grid(
            row=2, column=0, columnspan=3, sticky="ew", pady=self.PADDING
        )
        self.stop_button.grid_remove()  # Hidden by default

        self.open_button = self.ttk.Button(
            status_frame,
            text="Open last",
            command=self._open_last_output,
            state=self.tk.DISABLED,
        )
        self.open_button.grid(
            row=2, column=0, columnspan=3, sticky="ew", pady=self.PADDING
        )
        self.open_button.grid_remove()

        # Button shown when no other action buttons are visible
        self.drop_hint_button = self.ttk.Button(
            status_frame,
            text="Drop video to convert",
            state=self.tk.DISABLED,
        )
        self.drop_hint_button.grid(
            row=2, column=0, columnspan=3, sticky="ew", pady=self.PADDING
        )
        self.drop_hint_button.grid_remove()  # Hidden by default
        self._configure_drop_targets(self.drop_hint_button)

        self.log_frame = self.ttk.Frame(main, padding=self.PADDING)
        self.log_frame.grid(row=3, column=0, pady=(16, 0), sticky="nsew")
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
        self._update_setting("simple_mode", self.simple_mode_var.get())
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
            self.stop_button.grid_remove()
            self.advanced_button.grid_remove()
            self.advanced_frame.grid_remove()
            if hasattr(self, "status_frame"):
                self.status_frame.grid_remove()
            self.run_after_drop_var.set(True)
            self._apply_window_size(simple=True)
            if self.status_var.get().lower() == "success" and hasattr(
                self, "status_frame"
            ):
                self.status_frame.grid()
                self.open_button.grid()
                self.drop_hint_button.grid_remove()
        else:
            for widget in widgets:
                widget.grid()
            self.log_frame.grid()
            if hasattr(self, "status_frame"):
                self.status_frame.grid()
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
        self._update_setting("theme", self.theme_var.get())
        self._apply_theme()

    def _on_small_video_change(self, *_: object) -> None:
        self._update_setting("small_video", bool(self.small_var.get()))

    def _on_open_after_convert_change(self, *_: object) -> None:
        self._update_setting(
            "open_after_convert", bool(self.open_after_convert_var.get())
        )

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
            borderwidth=0,
            relief="flat",
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
        self.style.map(
            "TCheckbutton",
            background=[("active", palette.get("hover", palette["background"]))],
        )
        self.style.configure(
            "TRadiobutton",
            background=palette["background"],
            foreground=palette["foreground"],
        )
        self.style.map(
            "TRadiobutton",
            background=[("active", palette.get("hover", palette["background"]))],
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
                ("active", palette.get("hover_text", "#000000")),
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

        # Configure progress bar styles for different states
        self.style.configure(
            "Idle.Horizontal.TProgressbar",
            background=STATUS_COLORS["idle"],
            troughcolor=palette["surface"],
            borderwidth=0,
            thickness=20,
        )
        self.style.configure(
            "Processing.Horizontal.TProgressbar",
            background=STATUS_COLORS["processing"],
            troughcolor=palette["surface"],
            borderwidth=0,
            thickness=20,
        )
        self.style.configure(
            "Success.Horizontal.TProgressbar",
            background=STATUS_COLORS["success"],
            troughcolor=palette["surface"],
            borderwidth=0,
            thickness=20,
        )
        self.style.configure(
            "Error.Horizontal.TProgressbar",
            background=STATUS_COLORS["error"],
            troughcolor=palette["surface"],
            borderwidth=0,
            thickness=20,
        )
        self.style.configure(
            "Aborted.Horizontal.TProgressbar",
            background=STATUS_COLORS["aborted"],
            troughcolor=palette["surface"],
            borderwidth=0,
            thickness=20,
        )

        self.drop_zone.configure(
            bg=palette["surface"],
            fg=palette["foreground"],
            highlightthickness=0,
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

    def _populate_initial_inputs(
        self, inputs: Sequence[str], *, auto_run: bool = False
    ) -> None:
        """Seed the GUI with preselected inputs and optionally start processing."""

        normalized: list[str] = []
        for path in inputs:
            if not path:
                continue
            resolved = os.fspath(Path(path))
            if resolved not in self.input_files:
                self.input_files.append(resolved)
                self.input_list.insert(self.tk.END, resolved)
                normalized.append(resolved)

        if auto_run and normalized:
            # Kick off processing once the event loop becomes idle so the
            # interface has a chance to render before the work starts.
            self.root.after_idle(self._start_run)

    # -------------------------------------------------------------- actions --
    def _ask_for_input_files(self) -> tuple[str, ...]:
        """Prompt the user to select input files for processing."""

        return self.filedialog.askopenfilenames(
            title="Select input files",
            filetypes=[
                ("Video files", "*.mp4 *.mkv *.mov *.avi *.m4v"),
                ("All", "*.*"),
            ],
        )

    def _add_files(self) -> None:
        files = self._ask_for_input_files()
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

    def _clear_input_files(self) -> None:
        """Clear all input files from the list."""
        self.input_files.clear()
        self.input_list.delete(0, self.tk.END)

    def _on_drop(self, event: object) -> None:
        data = getattr(event, "data", "")
        if not data:
            return
        paths = self.root.tk.splitlist(data)
        cleaned = [path.strip("{}") for path in paths]
        # Clear existing files before adding dropped files
        self.input_files.clear()
        self.input_list.delete(0, self.tk.END)
        self._extend_inputs(cleaned, auto_run=True)

    def _on_drop_zone_click(self, event: object) -> str | None:
        """Open a file selection dialog when the drop zone is activated."""

        files = self._ask_for_input_files()
        if not files:
            return "break"
        self._clear_input_files()
        self._extend_inputs(files, auto_run=True)
        return "break"

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
        self._stop_requested = False
        open_after_convert = bool(self.open_after_convert_var.get())

        def worker() -> None:
            def set_process(proc: subprocess.Popen) -> None:
                self._ffmpeg_process = proc

            reporter = _TkProgressReporter(
                self._append_log, process_callback=set_process
            )
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
                    self._last_time_ratio = result.time_ratio
                    self._last_size_ratio = result.size_ratio

                    # Create completion message with ratios if available
                    completion_msg = f"Completed: {result.output_file}"
                    if result.time_ratio is not None and result.size_ratio is not None:
                        completion_msg += f" (Time: {result.time_ratio:.2%}, Size: {result.size_ratio:.2%})"

                    self._append_log(completion_msg)
                    if open_after_convert:
                        self._notify(
                            lambda path=result.output_file: self._open_in_file_manager(
                                path
                            )
                        )

                self._append_log("All jobs finished successfully.")
                self._notify(lambda: self.open_button.configure(state=self.tk.NORMAL))
                self._notify(self._clear_input_files)
            except FFmpegNotFoundError as exc:
                self._notify(
                    lambda: self.messagebox.showerror("FFmpeg not found", str(exc))
                )
                self._set_status("Error")
            except Exception as exc:  # pragma: no cover - GUI level safeguard
                # If stop was requested, don't show error (FFmpeg termination is expected)
                if self._stop_requested:
                    self._append_log("Processing aborted by user.")
                    self._set_status("Aborted")
                else:
                    error_msg = f"Processing failed: {exc}"
                    self._append_log(error_msg)
                    print(error_msg, file=sys.stderr)  # Also output to console
                    self._notify(lambda: self.messagebox.showerror("Error", error_msg))
                    self._set_status("Error")
            finally:
                self._notify(self._hide_stop_button)

        self._processing_thread = threading.Thread(target=worker, daemon=True)
        self._processing_thread.start()

        # Show Stop button when processing starts
        self.stop_button.grid()

    def _stop_processing(self) -> None:
        """Stop the currently running processing by terminating FFmpeg."""
        import signal

        self._stop_requested = True
        if self._ffmpeg_process and self._ffmpeg_process.poll() is None:
            self._append_log("Stopping FFmpeg process...")
            try:
                # Send SIGTERM to FFmpeg process
                if sys.platform == "win32":
                    # Windows doesn't have SIGTERM, use terminate()
                    self._ffmpeg_process.terminate()
                else:
                    # Unix-like systems can use SIGTERM
                    self._ffmpeg_process.send_signal(signal.SIGTERM)

                self._append_log("FFmpeg process stopped.")
            except Exception as e:
                self._append_log(f"Error stopping process: {e}")
        else:
            self._append_log("No active FFmpeg process to stop.")

        self._hide_stop_button()

    def _hide_stop_button(self) -> None:
        """Hide Stop button."""
        self.stop_button.grid_remove()
        # Show drop hint when stop button is hidden and no other buttons are visible
        if (
            not self.open_button.winfo_viewable()
            and hasattr(self, "drop_hint_button")
            and not self.drop_hint_button.winfo_viewable()
        ):
            self.drop_hint_button.grid()

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
            # Create status message with ratios if available
            status_msg = "Success"
            if self._last_time_ratio is not None and self._last_size_ratio is not None:
                status_msg = f"Time: {self._last_time_ratio:.0%}, Size: {self._last_size_ratio:.0%}"

            self._set_status("success", status_msg)
            self._set_progress(100)  # 100% on success
            self._video_duration_seconds = None  # Reset for next video
            self._encode_target_duration_seconds = None
            self._encode_total_frames = None
            self._encode_current_frame = None
        elif normalized.startswith("extracting audio"):
            self._set_status("processing", "Extracting audio...")
            self._set_progress(0)  # 0% on start
            self._video_duration_seconds = None  # Reset for new processing
            self._encode_target_duration_seconds = None
            self._encode_total_frames = None
            self._encode_current_frame = None
        elif normalized.startswith("starting processing") or normalized.startswith(
            "processing"
        ):
            self._set_status("processing", "Processing")
            self._set_progress(0)  # 0% on start
            self._video_duration_seconds = None  # Reset for new processing
            self._encode_target_duration_seconds = None
            self._encode_total_frames = None
            self._encode_current_frame = None

        frame_total_match = re.search(
            r"Final encode target frames(?: \(fallback\))?:\s*(\d+)", message
        )
        if frame_total_match:
            self._encode_total_frames = int(frame_total_match.group(1))
            return

        if "final encode target frames" in normalized and "unknown" in normalized:
            self._encode_total_frames = None
            return

        frame_match = re.search(r"frame=\s*(\d+)", message)
        if frame_match:
            try:
                current_frame = int(frame_match.group(1))
            except ValueError:
                current_frame = None

            if current_frame is not None:
                if self._encode_current_frame == current_frame:
                    return

                self._encode_current_frame = current_frame
                if self._encode_total_frames and self._encode_total_frames > 0:
                    percentage = min(
                        100,
                        int((current_frame / self._encode_total_frames) * 100),
                    )
                    self._set_progress(percentage)
                else:
                    self._set_status("processing", f"{current_frame} frames encoded")

        # Parse encode target duration reported by the pipeline
        encode_duration_match = re.search(
            r"Final encode target duration(?: \(fallback\))?:\s*([\d.]+)s",
            message,
        )
        if encode_duration_match:
            try:
                self._encode_target_duration_seconds = float(
                    encode_duration_match.group(1)
                )
            except ValueError:
                self._encode_target_duration_seconds = None

        if "final encode target duration" in normalized and "unknown" in normalized:
            self._encode_target_duration_seconds = None

        # Parse video duration from FFmpeg output
        duration_match = re.search(r"Duration:\s*(\d{2}):(\d{2}):(\d{2}\.\d+)", message)
        if duration_match:
            hours = int(duration_match.group(1))
            minutes = int(duration_match.group(2))
            seconds = float(duration_match.group(3))
            self._video_duration_seconds = hours * 3600 + minutes * 60 + seconds

        # Parse FFmpeg progress information (time and speed)
        time_match = re.search(r"time=(\d{2}):(\d{2}):(\d{2})\.\d+", message)
        speed_match = re.search(r"speed=\s*([\d.]+)x", message)

        if time_match and speed_match:
            hours = int(time_match.group(1))
            minutes = int(time_match.group(2))
            seconds = int(time_match.group(3))
            current_seconds = hours * 3600 + minutes * 60 + seconds
            time_str = self._format_progress_time(current_seconds)
            speed_str = speed_match.group(1)

            total_seconds = (
                self._encode_target_duration_seconds or self._video_duration_seconds
            )
            if total_seconds:
                total_str = self._format_progress_time(total_seconds)
                time_display = f"{time_str} / {total_str}"
            else:
                time_display = time_str

            status_msg = f"{time_display}, {speed_str}x"

            if (
                (
                    not self._encode_total_frames
                    or self._encode_total_frames <= 0
                    or self._encode_current_frame is None
                )
                and total_seconds
                and total_seconds > 0
            ):
                percentage = min(100, int((current_seconds / total_seconds) * 100))
                self._set_progress(percentage)

            self._set_status("processing", status_msg)

    def _apply_status_style(self, status: str) -> None:
        color = STATUS_COLORS.get(status.lower())
        if color:
            self.status_label.configure(fg=color)
        else:
            # For extracting audio or FFmpeg progress messages, use processing color
            # Also handle the new "Time: X%, Size: Y%" format as success
            status_lower = status.lower()
            if (
                "extracting audio" in status_lower
                or re.search(r"\d+:\d{2}(?: / \d+:\d{2})?.*\d+\.?\d*x", status)
                or ("time:" in status_lower and "size:" in status_lower)
            ):
                if "time:" in status_lower and "size:" in status_lower:
                    # This is our new success format with ratios
                    self.status_label.configure(fg=STATUS_COLORS["success"])
                else:
                    self.status_label.configure(fg=STATUS_COLORS["processing"])

    def _set_status(self, status: str, status_msg: str = "") -> None:
        def apply() -> None:
            self._status_state = status
            # Use status_msg if provided, otherwise use status
            display_text = status_msg if status_msg else status
            self.status_var.set(display_text)
            self._apply_status_style(
                status
            )  # Colors depend on status, not display text
            self._set_progress_bar_style(status)
            lowered = status.lower()
            is_processing = lowered == "processing" or "extracting audio" in lowered

            if is_processing:
                # Show stop button during processing
                if hasattr(self, "status_frame"):
                    self.status_frame.grid()
                self.stop_button.grid()
                self.drop_hint_button.grid_remove()

            if lowered == "success" or "time:" in lowered and "size:" in lowered:
                if self.simple_mode_var.get() and hasattr(self, "status_frame"):
                    self.status_frame.grid()
                    self.stop_button.grid_remove()
                self.drop_hint_button.grid_remove()
                self.open_button.grid()
                self.open_button.lift()  # Ensure open_button is above drop_hint_button
                # print("success status")
            else:
                self.open_button.grid_remove()
                # print("not success status")
                if (
                    self.simple_mode_var.get()
                    and not is_processing
                    and hasattr(self, "status_frame")
                ):
                    self.status_frame.grid_remove()
                    self.stop_button.grid_remove()
                    # Show drop hint when no other buttons are visible
                    if hasattr(self, "drop_hint_button"):
                        self.drop_hint_button.grid()

        self.root.after(0, apply)

    def _format_progress_time(self, total_seconds: float) -> str:
        """Format a duration in seconds as h:mm or m:ss for status display."""

        try:
            rounded_seconds = max(0, int(round(total_seconds)))
        except (TypeError, ValueError):
            return "0:00"

        hours, remainder = divmod(rounded_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        if hours > 0:
            return f"{hours}:{minutes:02d}"

        total_minutes = rounded_seconds // 60
        return f"{total_minutes}:{seconds:02d}"

    def _calculate_gradient_color(self, percentage: int, darken: float = 1.0) -> str:
        """Calculate color gradient from red (0%) to green (100%).

        Args:
            percentage: The position in the gradient (0-100)
            darken: Value between 0.0 (black) and 1.0 (original brightness)

        Returns:
            Hex color code string
        """
        # Clamp percentage between 0 and 100
        percentage = max(0, min(100, percentage))
        # Clamp darken between 0.0 and 1.0
        darken = max(0.0, min(1.0, darken))

        if percentage <= 50:
            # Red to Yellow (0% to 50%)
            # Red: (248, 113, 113) -> Yellow: (250, 204, 21)
            ratio = percentage / 50.0
            r = int((248 + (250 - 248) * ratio) * darken)
            g = int((113 + (204 - 113) * ratio) * darken)
            b = int((113 + (21 - 113) * ratio) * darken)
        else:
            # Yellow to Green (50% to 100%)
            # Yellow: (250, 204, 21) -> Green: (34, 197, 94)
            ratio = (percentage - 50) / 50.0
            r = int((250 + (34 - 250) * ratio) * darken)
            g = int((204 + (197 - 204) * ratio) * darken)
            b = int((21 + (94 - 21) * ratio) * darken)

        # Ensure values are within 0-255 range after darkening
        r = max(0, min(255, r))
        g = max(0, min(255, g))
        b = max(0, min(255, b))

        return f"#{r:02x}{g:02x}{b:02x}"

    def _set_progress(self, percentage: int) -> None:
        """Update the progress bar value and color (thread-safe)."""

        def updater() -> None:
            self.progress_var.set(percentage)
            # Update color based on percentage gradient
            color = self._calculate_gradient_color(percentage, 0.5)
            palette = (
                LIGHT_THEME if self._detect_system_theme() == "light" else DARK_THEME
            )
            if self.theme_var.get().lower() in {"light", "dark"}:
                palette = (
                    LIGHT_THEME
                    if self.theme_var.get().lower() == "light"
                    else DARK_THEME
                )

            self.style.configure(
                "Dynamic.Horizontal.TProgressbar",
                background=color,
                troughcolor=palette["surface"],
                borderwidth=0,
                thickness=20,
            )
            self.progress_bar.configure(style="Dynamic.Horizontal.TProgressbar")

            # Show stop button when progress < 100
            if percentage < 100:
                if hasattr(self, "status_frame"):
                    self.status_frame.grid()
                self.stop_button.grid()
                self.drop_hint_button.grid_remove()

        self.root.after(0, updater)

    def _set_progress_bar_style(self, status: str) -> None:
        """Update the progress bar color based on status."""

        def updater() -> None:
            # Map status to progress bar style
            status_lower = status.lower()
            if status_lower == "success" or (
                "time:" in status_lower and "size:" in status_lower
            ):
                style = "Success.Horizontal.TProgressbar"
            elif status_lower == "error":
                style = "Error.Horizontal.TProgressbar"
            elif status_lower == "aborted":
                style = "Aborted.Horizontal.TProgressbar"
            elif status_lower == "idle":
                style = "Idle.Horizontal.TProgressbar"
            else:
                # For processing states, use dynamic gradient (will be set by _set_progress)
                return

            self.progress_bar.configure(style=style)

        self.root.after(0, updater)

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

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--no-tray",
        action="store_true",
        help="Do not start the Talks Reducer server tray alongside the GUI.",
    )

    parsed_args, remaining = parser.parse_known_args(argv)
    no_tray = parsed_args.no_tray
    argv = remaining

    if argv:
        launch_gui = False
        if sys.platform == "win32" and not any(arg.startswith("-") for arg in argv):
            # Only attempt to launch the GUI automatically when the arguments
            # look like file or directory paths. This matches the behaviour of
            # file association launches on Windows while still allowing the CLI
            # to be used explicitly with option flags.
            if any(Path(arg).exists() for arg in argv if arg):
                launch_gui = True

        if launch_gui:
            try:
                app = TalksReducerGUI(argv, auto_run=True)
                if not no_tray:
                    _ensure_server_tray_running()
                app.run()
                return True
            except Exception:
                # Fall back to the CLI if the GUI cannot be started.
                pass

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
                print("Troubleshooting tips:")
                if sys.platform == "darwin":
                    print(
                        "  - On macOS, install Python from python.org or ensure "
                        "Homebrew's python-tk package is present."
                    )
                elif sys.platform.startswith("linux"):
                    print(
                        "  - On Linux, install the Tk bindings for Python (for example, "
                        "python3-tk)."
                    )
                else:
                    print("  - Ensure your Python installation includes Tk support.")
                print("  - You can always fall back to the CLI workflow below.")
                print()
                print("The CLI interface works perfectly and is recommended.")
            except UnicodeEncodeError:
                # Fallback for extreme encoding issues
                sys.stderr.write("GUI not available. Use CLI mode instead.\n")
            return False

    # Catch and report any errors during GUI initialization
    try:
        app = TalksReducerGUI()
        if not no_tray:
            _ensure_server_tray_running()
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
