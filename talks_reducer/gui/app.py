"""Tkinter GUI application for the talks reducer pipeline."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Iterable,
    List,
    Optional,
    Sequence,
    Tuple,
)

if TYPE_CHECKING:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

try:
    from ..cli import gather_input_files
    from ..ffmpeg import FFmpegNotFoundError
    from ..models import ProcessingOptions
    from ..pipeline import ProcessingAborted, speed_up_video
    from ..progress import ProgressHandle
    from ..version_utils import resolve_version
    from . import discovery as discovery_helpers
    from . import layout as layout_helpers
    from .preferences import GUIPreferences, determine_config_path
    from .progress import _TkProgressReporter
    from .remote import (
        check_remote_server_for_gui,
        format_server_host,
        normalize_server_url,
        ping_server,
        process_files_via_server,
    )
    from .theme import (
        DARK_THEME,
        LIGHT_THEME,
        STATUS_COLORS,
        apply_theme,
        detect_system_theme,
        read_windows_theme_registry,
        run_defaults_command,
    )
except ImportError:  # pragma: no cover - handled at runtime
    if __package__ not in (None, ""):
        raise

    PACKAGE_ROOT = Path(__file__).resolve().parent.parent
    if str(PACKAGE_ROOT) not in sys.path:
        sys.path.insert(0, str(PACKAGE_ROOT))

    from talks_reducer.cli import gather_input_files
    from talks_reducer.ffmpeg import FFmpegNotFoundError
    from talks_reducer.gui import discovery as discovery_helpers
    from talks_reducer.gui import layout as layout_helpers
    from talks_reducer.gui.preferences import GUIPreferences, determine_config_path
    from talks_reducer.gui.progress import _TkProgressReporter
    from talks_reducer.gui.remote import (
        check_remote_server_for_gui,
        format_server_host,
        normalize_server_url,
        ping_server,
        process_files_via_server,
    )
    from talks_reducer.gui.theme import (
        DARK_THEME,
        LIGHT_THEME,
        STATUS_COLORS,
        apply_theme,
        detect_system_theme,
        read_windows_theme_registry,
        run_defaults_command,
    )
    from talks_reducer.models import ProcessingOptions
    from talks_reducer.pipeline import ProcessingAborted, speed_up_video
    from talks_reducer.progress import ProgressHandle
    from talks_reducer.version_utils import resolve_version

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ModuleNotFoundError:  # pragma: no cover - runtime dependency
    DND_FILES = None  # type: ignore[assignment]
    TkinterDnD = None  # type: ignore[assignment]


def _default_remote_destination(input_file: Path, *, small: bool) -> Path:
    """Return the default remote output path for *input_file*."""

    name = input_file.name
    dot_index = name.rfind(".")
    suffix = "_speedup_small" if small else "_speedup"

    if dot_index != -1:
        new_name = name[:dot_index] + suffix + name[dot_index:]
    else:
        new_name = name + suffix

    return input_file.with_name(new_name)


def _parse_ratios_from_summary(summary: str) -> Tuple[Optional[float], Optional[float]]:
    """Extract time and size ratios from a Markdown *summary* string."""

    time_ratio: Optional[float] = None
    size_ratio: Optional[float] = None

    for line in summary.splitlines():
        if "**Duration:**" in line:
            match = re.search(r"—\s*([0-9]+(?:\.[0-9]+)?)% of the original", line)
            if match:
                try:
                    time_ratio = float(match.group(1)) / 100
                except ValueError:
                    time_ratio = None
        elif "**Size:**" in line:
            match = re.search(r"\*\*Size:\*\*\s*([0-9]+(?:\.[0-9]+)?)%", line)
            if match:
                try:
                    size_ratio = float(match.group(1)) / 100
                except ValueError:
                    size_ratio = None

    return time_ratio, size_ratio


def _parse_source_duration_seconds(message: str) -> tuple[bool, Optional[float]]:
    """Return whether *message* includes source duration metadata."""

    metadata_match = re.search(
        r"source metadata: duration:\s*([\d.]+)s",
        message,
        re.IGNORECASE,
    )
    if not metadata_match:
        return False, None

    try:
        return True, float(metadata_match.group(1))
    except ValueError:
        return True, None


def _parse_encode_total_frames(message: str) -> tuple[bool, Optional[int]]:
    """Extract final encode frame totals from *message* when present."""

    frame_total_match = re.search(
        r"Final encode target frames(?: \(fallback\))?:\s*(\d+)", message
    )
    if not frame_total_match:
        return False, None

    try:
        return True, int(frame_total_match.group(1))
    except ValueError:
        return True, None


def _is_encode_total_frames_unknown(normalized_message: str) -> bool:
    """Return ``True`` if *normalized_message* marks encode frame totals unknown."""

    return (
        "final encode target frames" in normalized_message
        and "unknown" in normalized_message
    )


def _parse_current_frame(message: str) -> tuple[bool, Optional[int]]:
    """Extract the current encode frame from *message* when available."""

    frame_match = re.search(r"frame=\s*(\d+)", message)
    if not frame_match:
        return False, None

    try:
        return True, int(frame_match.group(1))
    except ValueError:
        return True, None


def _parse_encode_target_duration(message: str) -> tuple[bool, Optional[float]]:
    """Extract encode target duration from *message* if reported."""

    encode_duration_match = re.search(
        r"Final encode target duration(?: \(fallback\))?:\s*([\d.]+)s",
        message,
    )
    if not encode_duration_match:
        return False, None

    try:
        return True, float(encode_duration_match.group(1))
    except ValueError:
        return True, None


def _is_encode_target_duration_unknown(normalized_message: str) -> bool:
    """Return ``True`` if encode target duration is reported as unknown."""

    return (
        "final encode target duration" in normalized_message
        and "unknown" in normalized_message
    )


def _parse_video_duration_seconds(message: str) -> tuple[bool, Optional[float]]:
    """Parse the input video duration from *message* when FFmpeg prints it."""

    duration_match = re.search(r"Duration:\s*(\d{2}):(\d{2}):(\d{2}\.\d+)", message)
    if not duration_match:
        return False, None

    try:
        hours = int(duration_match.group(1))
        minutes = int(duration_match.group(2))
        seconds = float(duration_match.group(3))
    except ValueError:
        return True, None

    total_seconds = hours * 3600 + minutes * 60 + seconds
    return True, total_seconds


def _parse_ffmpeg_progress(message: str) -> tuple[bool, Optional[tuple[int, str]]]:
    """Parse FFmpeg progress information from *message* if available."""

    time_match = re.search(r"time=(\d{2}):(\d{2}):(\d{2})\.\d+", message)
    speed_match = re.search(r"speed=\s*([\d.]+)x", message)

    if not (time_match and speed_match):
        return False, None

    try:
        hours = int(time_match.group(1))
        minutes = int(time_match.group(2))
        seconds = int(time_match.group(3))
    except ValueError:
        return True, None

    current_seconds = hours * 3600 + minutes * 60 + seconds
    speed_str = speed_match.group(1)
    return True, (current_seconds, speed_str)


class TalksReducerGUI:
    """Tkinter application mirroring the CLI options with form controls."""

    PADDING = 10
    AUDIO_PROCESSING_RATIO = 0.02
    AUDIO_PROGRESS_STEPS = 20
    MIN_AUDIO_INTERVAL_MS = 10
    DEFAULT_AUDIO_INTERVAL_MS = 200

    def __init__(
        self,
        initial_inputs: Optional[Sequence[str]] = None,
        *,
        auto_run: bool = False,
    ) -> None:
        self._config_path = determine_config_path()
        self.preferences = GUIPreferences(self._config_path)

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

        # Set window title with version information
        app_version = resolve_version()
        if app_version and app_version != "unknown":
            self.root.title(f"Talks Reducer v{app_version}")
        else:
            self.root.title("Talks Reducer")

        self._apply_window_icon()

        self._full_size = (1000, 800)
        self._simple_size = (300, 270)
        # self.root.geometry(f"{self._full_size[0]}x{self._full_size[1]}")
        self.style = self.ttk.Style(self.root)

        self._processing_thread: Optional[threading.Thread] = None
        self._last_output: Optional[Path] = None
        self._last_time_ratio: Optional[float] = None
        self._last_size_ratio: Optional[float] = None
        self._last_progress_seconds: Optional[int] = None
        self._run_start_time: Optional[float] = None
        self._status_state = "Idle"
        self.status_var = tk.StringVar(value=self._status_state)
        self._status_animation_job: Optional[str] = None
        self._status_animation_phase = 0
        self._video_duration_seconds: Optional[float] = None
        self._encode_target_duration_seconds: Optional[float] = None
        self._encode_total_frames: Optional[int] = None
        self._encode_current_frame: Optional[int] = None
        self._source_duration_seconds: Optional[float] = None
        self._audio_progress_job: Optional[str] = None
        self._audio_progress_interval_ms: Optional[int] = None
        self._audio_progress_steps_completed = 0
        self.progress_var = tk.IntVar(value=0)
        self._ffmpeg_process: Optional[subprocess.Popen] = None
        self._stop_requested = False
        self._ping_worker_stop_requested = False
        self._current_remote_mode = False

        self.input_files: List[str] = []

        self._dnd_available = TkinterDnD is not None and DND_FILES is not None

        self.simple_mode_var = tk.BooleanVar(
            value=self.preferences.get("simple_mode", True)
        )
        self.run_after_drop_var = tk.BooleanVar(value=True)
        self.small_var = tk.BooleanVar(value=self.preferences.get("small_video", True))
        self.open_after_convert_var = tk.BooleanVar(
            value=self.preferences.get("open_after_convert", True)
        )
        stored_mode = str(self.preferences.get("processing_mode", "local"))
        if stored_mode not in {"local", "remote"}:
            stored_mode = "local"
        self.processing_mode_var = tk.StringVar(value=stored_mode)
        self.processing_mode_var.trace_add("write", self._on_processing_mode_change)
        self.theme_var = tk.StringVar(value=self.preferences.get("theme", "os"))
        self.theme_var.trace_add("write", self._on_theme_change)
        self.small_var.trace_add("write", self._on_small_video_change)
        self.open_after_convert_var.trace_add(
            "write", self._on_open_after_convert_change
        )
        self.server_url_var = tk.StringVar(
            value=str(self.preferences.get("server_url", ""))
        )
        self.server_url_var.trace_add("write", self._on_server_url_change)
        self._discovery_thread: Optional[threading.Thread] = None

        self._basic_defaults: dict[str, float] = {}
        self._basic_variables: dict[str, tk.DoubleVar] = {}
        self._slider_updaters: dict[str, Callable[[str], None]] = {}
        self._sliders: list[tk.Scale] = []

        self._build_layout()
        self._apply_simple_mode(initial=True)
        self._apply_status_style(self._status_state)
        self._refresh_theme()
        self.preferences.save()
        self._hide_stop_button()

        # Ping server on startup if in remote mode
        if (
            self.processing_mode_var.get() == "remote"
            and self.server_url_var.get().strip()
        ):
            server_url = self.server_url_var.get().strip()

            def ping_worker() -> None:
                try:
                    self._check_remote_server(
                        server_url,
                        success_status="Idle",
                        waiting_status="Error",
                        failure_status="Error",
                        stop_check=lambda: self._ping_worker_stop_requested,
                        switch_to_local_on_failure=True,
                    )
                except Exception as exc:  # pragma: no cover - defensive safeguard
                    host_label = self._format_server_host(server_url)
                    message = f"Error pinging server {host_label}: {exc}"
                    self._schedule_on_ui_thread(
                        lambda msg=message: self._append_log(msg)
                    )
                    self._schedule_on_ui_thread(
                        lambda msg=message: self._set_status("Idle", msg)
                    )

            threading.Thread(target=ping_worker, daemon=True).start()

        if not self._dnd_available:
            self._append_log(
                "Drag and drop requires the tkinterdnd2 package. Install it to enable the drop zone."
            )

        if initial_inputs:
            self._populate_initial_inputs(initial_inputs, auto_run=auto_run)

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
        self.stop_button.configure(text="Stop")
        self._run_start_time = time.monotonic()
        self._ping_worker_stop_requested = True
        open_after_convert = bool(self.open_after_convert_var.get())
        server_url = self.server_url_var.get().strip()
        remote_mode = self.processing_mode_var.get() == "remote"
        if remote_mode and not server_url:
            self.messagebox.showerror(
                "Missing server URL", "Remote mode requires a server URL."
            )
        remote_mode = remote_mode and bool(server_url)

        # Store remote_mode for use after thread starts
        self._current_remote_mode = remote_mode

        def worker() -> None:
            def set_process(proc: subprocess.Popen) -> None:
                self._ffmpeg_process = proc

            try:
                files = gather_input_files(self.input_files)
                if not files:
                    self._schedule_on_ui_thread(
                        lambda: self.messagebox.showwarning(
                            "No files", "No supported media files were found."
                        )
                    )
                    self._set_status("Idle")
                    return

                if self._current_remote_mode:
                    success = self._process_files_via_server(
                        files,
                        args,
                        server_url,
                        open_after_convert=open_after_convert,
                    )
                    if success:
                        self._schedule_on_ui_thread(self._hide_stop_button)
                        return
                    # If server processing failed, fall back to local processing
                    # The _process_files_via_server function already switched to local mode
                    # Update remote_mode variable to reflect the change
                    self._current_remote_mode = False

                reporter = _TkProgressReporter(
                    self._append_log,
                    process_callback=set_process,
                    stop_callback=lambda: self._stop_requested,
                )
                for index, file in enumerate(files, start=1):
                    self._append_log(f"Processing: {os.path.basename(file)}")
                    options = self._create_processing_options(Path(file), args)
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
                        self._schedule_on_ui_thread(
                            lambda path=result.output_file: self._open_in_file_manager(
                                path
                            )
                        )

                self._append_log("All jobs finished successfully.")
                self._schedule_on_ui_thread(
                    lambda: self.open_button.configure(state=self.tk.NORMAL)
                )
                self._schedule_on_ui_thread(self._clear_input_files)
            except FFmpegNotFoundError as exc:
                self._schedule_on_ui_thread(
                    lambda: self.messagebox.showerror("FFmpeg not found", str(exc))
                )
                self._set_status("Error")
            except ProcessingAborted:
                self._append_log("Processing aborted by user.")
                self._set_status("Aborted")
            except Exception as exc:  # pragma: no cover - GUI level safeguard
                # If stop was requested, don't show error (FFmpeg termination is expected)
                if self._stop_requested:
                    self._append_log("Processing aborted by user.")
                    self._set_status("Aborted")
                else:
                    error_msg = f"Processing failed: {exc}"
                    self._append_log(error_msg)
                    print(error_msg, file=sys.stderr)  # Also output to console
                    self._schedule_on_ui_thread(
                        lambda: self.messagebox.showerror("Error", error_msg)
                    )
                    self._set_status("Error")
            finally:
                self._run_start_time = None
                self._schedule_on_ui_thread(self._hide_stop_button)

        self._processing_thread = threading.Thread(target=worker, daemon=True)
        self._processing_thread.start()

        # Show Stop button when processing starts regardless of mode
        self.stop_button.grid()

    # ------------------------------------------------------------------ UI --
    def _apply_window_icon(self) -> None:
        layout_helpers.apply_window_icon(self)

    def _build_layout(self) -> None:
        layout_helpers.build_layout(self)

    def _update_basic_reset_state(self) -> None:
        layout_helpers.update_basic_reset_state(self)

    def _reset_basic_defaults(self) -> None:
        layout_helpers.reset_basic_defaults(self)

    def _update_processing_mode_state(self) -> None:
        has_url = bool(self.server_url_var.get().strip())
        if not has_url and self.processing_mode_var.get() == "remote":
            self.processing_mode_var.set("local")
            return

        if hasattr(self, "remote_mode_button"):
            state = self.tk.NORMAL if has_url else self.tk.DISABLED
            self.remote_mode_button.configure(state=state)

    def _normalize_server_url(self, server_url: str) -> str:
        return normalize_server_url(server_url)

    def _format_server_host(self, server_url: str) -> str:
        return format_server_host(server_url)

    def _check_remote_server(
        self,
        server_url: str,
        *,
        success_status: str,
        waiting_status: str,
        failure_status: str,
        success_message: Optional[str] = None,
        waiting_message_template: str = "Waiting server {host} (attempt {attempt}/{max_attempts})",
        failure_message: Optional[str] = None,
        stop_check: Optional[Callable[[], bool]] = None,
        on_stop: Optional[Callable[[], None]] = None,
        switch_to_local_on_failure: bool = False,
        alert_on_failure: bool = False,
        warning_title: str = "Server unavailable",
        warning_message: Optional[str] = None,
        max_attempts: int = 5,
        delay: float = 1.0,
    ) -> bool:
        return check_remote_server_for_gui(
            self,
            server_url,
            success_status=success_status,
            waiting_status=waiting_status,
            failure_status=failure_status,
            success_message=success_message,
            waiting_message_template=waiting_message_template,
            failure_message=failure_message,
            stop_check=stop_check,
            on_stop=on_stop,
            switch_to_local_on_failure=switch_to_local_on_failure,
            alert_on_failure=alert_on_failure,
            warning_title=warning_title,
            warning_message=warning_message,
            max_attempts=max_attempts,
            delay=delay,
        )

    def _ping_server(self, server_url: str, *, timeout: float = 5.0) -> bool:
        return ping_server(server_url, timeout=timeout)

    def _start_discovery(self) -> None:
        discovery_helpers.start_discovery(self)

    def _on_discovery_failed(self, exc: Exception) -> None:
        discovery_helpers.on_discovery_failed(self, exc)

    def _on_discovery_progress(self, current: int, total: int) -> None:
        discovery_helpers.on_discovery_progress(self, current, total)

    def _on_discovery_complete(self, urls: List[str]) -> None:
        discovery_helpers.on_discovery_complete(self, urls)

    def _show_discovery_results(self, urls: List[str]) -> None:
        discovery_helpers.show_discovery_results(self, urls)

    def _toggle_simple_mode(self) -> None:
        self.preferences.update("simple_mode", self.simple_mode_var.get())
        self._apply_simple_mode()

    def _apply_simple_mode(self, *, initial: bool = False) -> None:
        layout_helpers.apply_simple_mode(self, initial=initial)

    def _apply_window_size(self, *, simple: bool) -> None:
        layout_helpers.apply_window_size(self, simple=simple)

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
        self.preferences.update("theme", self.theme_var.get())
        self._refresh_theme()

    def _on_small_video_change(self, *_: object) -> None:
        self.preferences.update("small_video", bool(self.small_var.get()))

    def _on_open_after_convert_change(self, *_: object) -> None:
        self.preferences.update(
            "open_after_convert", bool(self.open_after_convert_var.get())
        )

    def _on_processing_mode_change(self, *_: object) -> None:
        value = self.processing_mode_var.get()
        if value not in {"local", "remote"}:
            self.processing_mode_var.set("local")
            return
        self.preferences.update("processing_mode", value)
        self._update_processing_mode_state()

        if self.processing_mode_var.get() == "remote":
            server_url = self.server_url_var.get().strip()
            if not server_url:
                return

            def ping_remote_mode() -> None:
                self._check_remote_server(
                    server_url,
                    success_status="Idle",
                    waiting_status="Error",
                    failure_status="Error",
                    failure_message="Server {host} is unreachable. Switching to local mode.",
                    switch_to_local_on_failure=True,
                    alert_on_failure=True,
                    warning_message="Server {host} is unreachable. Switching to local mode.",
                )

            threading.Thread(target=ping_remote_mode, daemon=True).start()

    def _on_server_url_change(self, *_: object) -> None:
        value = self.server_url_var.get().strip()
        self.preferences.update("server_url", value)
        self._update_processing_mode_state()

    def _resolve_theme_mode(self) -> str:
        preference = self.theme_var.get().lower()
        if preference not in {"light", "dark"}:
            return detect_system_theme(
                os.environ,
                sys.platform,
                read_windows_theme_registry,
                run_defaults_command,
            )
        return preference

    def _refresh_theme(self) -> None:
        mode = self._resolve_theme_mode()
        palette = LIGHT_THEME if mode == "light" else DARK_THEME
        apply_theme(
            self.style,
            palette,
            {
                "root": self.root,
                "drop_zone": getattr(self, "drop_zone", None),
                "log_text": getattr(self, "log_text", None),
                "status_label": getattr(self, "status_label", None),
                "sliders": getattr(self, "_sliders", []),
                "tk": self.tk,
                "apply_status_style": self._apply_status_style,
                "status_state": self._status_state,
            },
        )

    def _configure_drop_targets(self, widget) -> None:
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
                added = True
        if auto_run and added and self.run_after_drop_var.get():
            self._start_run()

    def _clear_input_files(self) -> None:
        """Clear all queued input files."""
        self.input_files.clear()

    def _on_drop(self, event: object) -> None:
        data = getattr(event, "data", "")
        if not data:
            return
        paths = self.root.tk.splitlist(data)
        cleaned = [path.strip("{}") for path in paths]
        # Clear existing files before adding dropped files
        self.input_files.clear()
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

    def _stop_processing(self) -> None:
        """Stop the currently running processing by terminating FFmpeg."""
        import signal

        self._stop_requested = True
        # Update button text to indicate stopping state
        self.stop_button.configure(text="Stopping...")
        if self._current_remote_mode:
            self._append_log("Cancelling remote job...")
        elif self._ffmpeg_process and self._ffmpeg_process.poll() is None:
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
        silent_threshold = float(self.silent_threshold_var.get())
        args["silent_threshold"] = round(silent_threshold, 2)

        sounded_speed = float(self.sounded_speed_var.get())
        args["sounded_speed"] = round(sounded_speed, 2)

        silent_speed = float(self.silent_speed_var.get())
        args["silent_speed"] = round(silent_speed, 2)
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

    def _process_files_via_server(
        self,
        files: List[str],
        args: dict[str, object],
        server_url: str,
        *,
        open_after_convert: bool,
    ) -> bool:
        """Send *files* to the configured server for processing."""

        return process_files_via_server(
            self,
            files,
            args,
            server_url,
            open_after_convert=open_after_convert,
            default_remote_destination=_default_remote_destination,
            parse_summary=_parse_ratios_from_summary,
        )

    def _parse_float(self, value: str, label: str) -> float:
        try:
            return float(value)
        except ValueError as exc:  # pragma: no cover - input validation
            raise ValueError(f"{label} must be a number.") from exc

    def _create_processing_options(
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

        metadata_found, source_duration = _parse_source_duration_seconds(message)
        if metadata_found:
            self._source_duration_seconds = source_duration

        if self._handle_status_transitions(normalized):
            return

        frame_total_found, frame_total = _parse_encode_total_frames(message)
        if frame_total_found:
            self._encode_total_frames = frame_total
            return

        if _is_encode_total_frames_unknown(normalized):
            self._encode_total_frames = None
            return

        frame_found, current_frame = _parse_current_frame(message)
        if frame_found:
            if current_frame is None:
                return

            if self._encode_current_frame == current_frame:
                return

            self._encode_current_frame = current_frame
            if self._encode_total_frames and self._encode_total_frames > 0:
                self._complete_audio_phase()
                frame_ratio = min(current_frame / self._encode_total_frames, 1.0)
                percentage = min(100, 5 + int(frame_ratio * 95))
                self._set_progress(percentage)
            else:
                self._complete_audio_phase()
                self._set_status("processing", f"{current_frame} frames encoded")

        duration_found, encode_duration = _parse_encode_target_duration(message)
        if duration_found:
            self._encode_target_duration_seconds = encode_duration

        if _is_encode_target_duration_unknown(normalized):
            self._encode_target_duration_seconds = None

        video_duration_found, video_duration = _parse_video_duration_seconds(message)
        if video_duration_found and video_duration is not None:
            self._video_duration_seconds = video_duration

        progress_found, progress_info = _parse_ffmpeg_progress(message)
        if progress_found and progress_info is not None:
            current_seconds, speed_str = progress_info
            time_str = self._format_progress_time(current_seconds)

            self._last_progress_seconds = current_seconds

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
                self._complete_audio_phase()
                time_ratio = min(current_seconds / total_seconds, 1.0)
                percentage = min(100, 5 + int(time_ratio * 95))
                self._set_progress(percentage)

            self._set_status("processing", status_msg)

    def _handle_status_transitions(self, normalized_message: str) -> bool:
        """Handle high-level status transitions for *normalized_message*."""

        if "all jobs finished successfully" in normalized_message:
            status_components: List[str] = []
            if self._run_start_time is not None:
                finish_time = time.monotonic()
                runtime_seconds = max(0.0, finish_time - self._run_start_time)
                duration_str = self._format_progress_time(runtime_seconds)
                status_components.append(f"{duration_str}")
            else:
                finished_seconds = next(
                    (
                        value
                        for value in (
                            self._last_progress_seconds,
                            self._encode_target_duration_seconds,
                            self._video_duration_seconds,
                        )
                        if value is not None
                    ),
                    None,
                )

                if finished_seconds is not None:
                    duration_str = self._format_progress_time(finished_seconds)
                    status_components.append(f"{duration_str}")
                else:
                    status_components.append("Finished")

            if self._last_time_ratio is not None and self._last_size_ratio is not None:
                status_components.append(
                    f"time: {self._last_time_ratio:.0%}, size: {self._last_size_ratio:.0%}"
                )

            status_msg = ", ".join(status_components)

            self._reset_audio_progress_state(clear_source=True)
            self._set_status("success", status_msg)
            self._set_progress(100)
            self._run_start_time = None
            self._video_duration_seconds = None
            self._encode_target_duration_seconds = None
            self._encode_total_frames = None
            self._encode_current_frame = None
            self._last_progress_seconds = None
            return True

        if normalized_message.startswith("extracting audio"):
            self._reset_audio_progress_state(clear_source=False)
            self._set_status("processing", "Extracting audio...")
            self._set_progress(0)
            self._video_duration_seconds = None
            self._encode_target_duration_seconds = None
            self._encode_total_frames = None
            self._encode_current_frame = None
            self._last_progress_seconds = None
            self._start_audio_progress()
            return False

        if normalized_message.startswith("uploading"):
            self._set_status("processing", "Uploading...")
            return False

        if normalized_message.startswith("starting processing"):
            self._reset_audio_progress_state(clear_source=True)
            self._set_status("processing", "Processing")
            self._set_progress(0)
            self._video_duration_seconds = None
            self._encode_target_duration_seconds = None
            self._encode_total_frames = None
            self._encode_current_frame = None
            self._last_progress_seconds = None
            return False

        if normalized_message.startswith("processing"):
            is_new_job = bool(re.match(r"processing \d+/\d+:", normalized_message))
            should_reset = self._status_state.lower() != "processing" or is_new_job
            if should_reset:
                self._set_progress(0)
                self._video_duration_seconds = None
                self._encode_target_duration_seconds = None
                self._encode_total_frames = None
                self._encode_current_frame = None
                self._last_progress_seconds = None
            if is_new_job:
                self._reset_audio_progress_state(clear_source=True)
            self._set_status("processing", "Processing")
            return False

        return False

    def _compute_audio_progress_interval(self) -> int:
        duration = self._source_duration_seconds or self._video_duration_seconds
        if duration and duration > 0:
            audio_seconds = max(duration * self.AUDIO_PROCESSING_RATIO, 0.0)
            interval_seconds = audio_seconds / self.AUDIO_PROGRESS_STEPS
            interval_ms = int(round(interval_seconds * 1000))
            return max(self.MIN_AUDIO_INTERVAL_MS, interval_ms)
        return self.DEFAULT_AUDIO_INTERVAL_MS

    def _start_audio_progress(self) -> None:
        interval_ms = self._compute_audio_progress_interval()

        def _start() -> None:
            if self._audio_progress_job is not None:
                self.root.after_cancel(self._audio_progress_job)
            self._audio_progress_steps_completed = 0
            self._audio_progress_interval_ms = interval_ms
            self._audio_progress_job = self.root.after(
                interval_ms, self._advance_audio_progress
            )

        self._schedule_on_ui_thread(_start)

    def _advance_audio_progress(self) -> None:
        self._audio_progress_job = None
        if self._audio_progress_steps_completed >= self.AUDIO_PROGRESS_STEPS:
            self._audio_progress_interval_ms = None
            return

        self._audio_progress_steps_completed += 1
        audio_percentage = (
            self._audio_progress_steps_completed / self.AUDIO_PROGRESS_STEPS * 100
        )
        percentage = (audio_percentage / 100) * 5
        self._set_progress(percentage)
        self._set_status("processing", "Audio processing: %d%%" % (audio_percentage))

        if self._audio_progress_steps_completed < self.AUDIO_PROGRESS_STEPS:
            interval_ms = (
                self._audio_progress_interval_ms or self.DEFAULT_AUDIO_INTERVAL_MS
            )
            self._audio_progress_job = self.root.after(
                interval_ms, self._advance_audio_progress
            )
        else:
            self._audio_progress_interval_ms = None

    def _cancel_audio_progress(self) -> None:
        if self._audio_progress_job is None:
            self._audio_progress_interval_ms = None
            return

        def _cancel() -> None:
            if self._audio_progress_job is not None:
                self.root.after_cancel(self._audio_progress_job)
                self._audio_progress_job = None
            self._audio_progress_interval_ms = None

        self._schedule_on_ui_thread(_cancel)

    def _reset_audio_progress_state(self, *, clear_source: bool) -> None:
        if clear_source:
            self._source_duration_seconds = None
        self._audio_progress_steps_completed = 0
        self._audio_progress_interval_ms = None
        if self._audio_progress_job is not None:
            self._cancel_audio_progress()

    def _complete_audio_phase(self) -> None:
        def _complete() -> None:
            if self._audio_progress_job is not None:
                self.root.after_cancel(self._audio_progress_job)
                self._audio_progress_job = None
            self._audio_progress_interval_ms = None
            if self._audio_progress_steps_completed < self.AUDIO_PROGRESS_STEPS:
                self._audio_progress_steps_completed = self.AUDIO_PROGRESS_STEPS
                current_value = self.progress_var.get()
                if current_value < self.AUDIO_PROGRESS_STEPS:
                    self._set_progress(self.AUDIO_PROGRESS_STEPS)

        self._schedule_on_ui_thread(_complete)

    def _get_status_style(self, status: str) -> str | None:
        """Return the foreground color for *status* if a match is known."""

        color = STATUS_COLORS.get(status.lower())
        if color:
            return color

        status_lower = status.lower()
        if "extracting audio" in status_lower:
            return STATUS_COLORS["processing"]

        if re.search(
            r"\d+:\d{2}(?::\d{2})?(?: / \d+:\d{2}(?::\d{2})?)?.*\d+\.?\d*x",
            status,
        ):
            return STATUS_COLORS["processing"]

        if "time:" in status_lower and "size:" in status_lower:
            # This is our new success format with ratios
            return STATUS_COLORS["success"]

        return None

    def _apply_status_style(self, status: str) -> None:
        color = self._get_status_style(status)
        if color:
            self.status_label.configure(fg=color)

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
            else:
                self._reset_audio_progress_state(clear_source=True)

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
                if self.simple_mode_var.get() and not is_processing:
                    self.stop_button.grid_remove()
                    # Show drop hint when no other buttons are visible
                    if hasattr(self, "drop_hint_button"):
                        self.drop_hint_button.grid()

        self.root.after(0, apply)

    def _format_progress_time(self, total_seconds: float) -> str:
        """Format a duration in seconds as h:mm:ss or m:ss for status display."""

        try:
            rounded_seconds = max(0, int(round(total_seconds)))
        except (TypeError, ValueError):
            return "0:00"

        hours, remainder = divmod(rounded_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"

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
                LIGHT_THEME if self._resolve_theme_mode() == "light" else DARK_THEME
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

    def _schedule_on_ui_thread(self, callback: Callable[[], None]) -> None:
        self.root.after(0, callback)

    def run(self) -> None:
        """Start the Tkinter event loop."""

        self.root.mainloop()


__all__ = [
    "TalksReducerGUI",
    "_default_remote_destination",
    "_parse_ratios_from_summary",
]
