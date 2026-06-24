"""Tkinter GUI application for the talks reducer pipeline."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from contextlib import suppress
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

from . import hi_dpi  # should be imported before tkinter

if TYPE_CHECKING:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

try:
    from ..cli import gather_input_files
    from ..ffmpeg import FFmpegNotFoundError, is_global_ffmpeg_available
    from ..models import ProcessingOptions
    from ..pipeline import ProcessingAborted, speed_up_video
    from ..progress import ProgressHandle
    from ..timecode import format_timecode, parse_timecode
    from ..version_utils import resolve_version
    from . import discovery as discovery_helpers
    from . import layout as layout_helpers
    from . import update_checker
    from .inputs import InputController
    from .preferences import GUIPreferences, PreferenceController, determine_config_path
    from .progress import _TkProgressReporter
    from .remote_io import RemoteController
    from .summaries import (
        SummaryManager,
        default_remote_destination,
        is_encode_target_duration_unknown,
        is_encode_total_frames_unknown,
        parse_current_frame,
        parse_encode_target_duration,
        parse_encode_total_frames,
        parse_ffmpeg_progress,
        parse_ratios_from_summary,
        parse_source_duration_seconds,
        parse_task_percent,
        parse_video_duration_seconds,
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
    from talks_reducer.ffmpeg import FFmpegNotFoundError, is_global_ffmpeg_available
    from talks_reducer.gui import discovery as discovery_helpers
    from talks_reducer.gui import layout as layout_helpers
    from talks_reducer.gui import update_checker
    from talks_reducer.gui.inputs import InputController
    from talks_reducer.gui.preferences import (
        GUIPreferences,
        PreferenceController,
        determine_config_path,
    )
    from talks_reducer.gui.progress import _TkProgressReporter
    from talks_reducer.gui.remote_io import RemoteController
    from talks_reducer.gui.summaries import (
        SummaryManager,
        default_remote_destination,
        is_encode_target_duration_unknown,
        is_encode_total_frames_unknown,
        parse_current_frame,
        parse_encode_target_duration,
        parse_encode_total_frames,
        parse_ffmpeg_progress,
        parse_ratios_from_summary,
        parse_source_duration_seconds,
        parse_task_percent,
        parse_video_duration_seconds,
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
    from talks_reducer.timecode import format_timecode, parse_timecode
    from talks_reducer.version_utils import resolve_version

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ModuleNotFoundError:  # pragma: no cover - runtime dependency
    DND_FILES = None  # type: ignore[assignment]
    TkinterDnD = None  # type: ignore[assignment]


def _format_seed_number(value: object) -> str:
    """Render a numeric CLI value for a ``StringVar`` without a trailing ``.0``.

    ``--frame_margin`` and ``--sample_rate`` parse as floats, so an integer such
    as ``48000`` arrives as ``48000.0``; format whole numbers without the decimal
    suffix to match the default control text.
    """

    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return str(int(number))
    return str(number)


class TalksReducerGUI:
    """Tkinter application mirroring the CLI options with form controls."""

    PADDING = 10
    AUDIO_PROCESSING_RATIO = 0.02
    AUDIO_PROGRESS_STEPS = 100
    AUDIO_PROGRESS_WEIGHT = 5.0
    MIN_AUDIO_INTERVAL_MS = 10
    DEFAULT_AUDIO_INTERVAL_MS = 200
    DOWNLOAD_WAIT_INTERVAL_MS = 5000
    DOWNLOAD_WAIT_STATUS = "Waiting for download…"
    ACTIVITY_POLL_INTERVAL_MS = 5000

    def __init__(
        self,
        initial_inputs: Optional[Sequence[str]] = None,
        *,
        auto_run: bool = False,
        cli_settings: Optional[dict] = None,
        server_managed: bool = False,
        local_server_url: Optional[str] = None,
    ) -> None:
        self.server_managed = bool(server_managed)
        self.local_server_url = local_server_url or None
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

        self._dnd_runtime_available = False
        if TkinterDnD is not None:
            try:
                self.root = TkinterDnD.Tk()  # type: ignore[call-arg]
                self._dnd_runtime_available = True
            except Exception as exc:  # pragma: no cover - depends on tkdnd build
                # A mismatched tkdnd library (e.g. a Tcl 9 build under Tcl 8.6)
                # would otherwise crash the whole GUI. Fall back to a plain Tk
                # window so the app still launches without drag-and-drop.
                print(f"[Talks Reducer] Drag and drop disabled: {exc}")
                self.root = tk.Tk()
        else:
            self.root = tk.Tk()

        # Set window title with version information
        app_version = resolve_version()
        if app_version and app_version != "unknown":
            self.root.title(f"Talks Reducer v{app_version}")
        else:
            self.root.title("Talks Reducer")

        self._apply_window_icon()

        self._full_size = (1200, 900)
        self._simple_size = (470, 300)
        # self.root.geometry(f"{self._full_size[0]}x{self._full_size[1]}")
        self.style = self.ttk.Style(self.root)

        self._processing_thread: Optional[threading.Thread] = None
        self._last_output: Optional[Path] = None
        self._last_time_ratio: Optional[float] = None
        self._last_size_ratio: Optional[float] = None
        self._last_output_duration: Optional[float] = None
        self._last_output_size: Optional[int] = None
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
        self._download_wait_job: Optional[str] = None
        self._download_wait_active: bool = False
        self._activity_poll_job: Optional[str] = None
        self._closing = False
        self.progress_var = tk.DoubleVar(value=0.0)
        self._progress_floor: float = 0.0
        self._ffmpeg_process: Optional[subprocess.Popen] = None
        self._stop_requested = False
        self._ping_worker_stop_requested = False
        self._current_remote_mode = False

        # Update checker state
        self._update_check_thread: Optional[threading.Thread] = None
        self._download_thread: Optional[threading.Thread] = None
        self._latest_version: Optional[str] = None
        self._installer_url: Optional[str] = None
        self._portable_url: Optional[str] = None
        self._update_link_labels: List[Any] = []

        self.input_files: List[str] = []

        self._dnd_available = self._dnd_runtime_available and DND_FILES is not None
        self.DND_FILES = DND_FILES

        self.inputs = InputController(self)
        self.remote_controller = RemoteController(self)
        self.summary_manager = SummaryManager(self)
        self.preference_controller = PreferenceController(self)

        self.simple_mode_var = tk.BooleanVar(
            value=self.preferences.get("simple_mode", True)
        )
        self.simple_preset_var = tk.StringVar(value="")
        self.simple_codec_var = tk.StringVar(value="")
        self.run_after_drop_var = tk.BooleanVar(value=True)
        self.small_var = tk.BooleanVar(value=self.preferences.get("small_video", True))
        self.small_480_var = tk.BooleanVar(
            value=self.preferences.get("small_video_480", False)
        )
        self.open_after_convert_var = tk.BooleanVar(
            value=self.preferences.get("open_after_convert", True)
        )
        self.cut_enabled_var = tk.BooleanVar(
            value=bool(self.preferences.get("cut_enabled", False))
        )
        self.cut_start_var = tk.DoubleVar(
            value=self.preferences.get_float("cut_start", 0.0)
        )
        self.cut_end_var = tk.DoubleVar(
            value=self.preferences.get_float("cut_end", 0.0)
        )
        # Editable text mirrors of the cut handles for manual timecode entry.
        self.cut_start_text_var = tk.StringVar(
            value=format_timecode(self.cut_start_var.get(), milliseconds=True)
        )
        self.cut_end_text_var = tk.StringVar(
            value=format_timecode(self.cut_end_var.get(), milliseconds=True)
        )
        stored_codec = str(self.preferences.get("video_codec", "h264")).lower()
        if stored_codec not in {"h264", "hevc", "av1"}:
            stored_codec = "h264"
            self.preferences.update("video_codec", stored_codec)
        prefer_global = bool(self.preferences.get("use_global_ffmpeg", False))
        self.global_ffmpeg_available = is_global_ffmpeg_available()
        if prefer_global and not self.global_ffmpeg_available:
            prefer_global = False
            self.preferences.update("use_global_ffmpeg", False)
        self.video_codec_var = tk.StringVar(value=stored_codec)
        self.add_codec_suffix_var = tk.BooleanVar(
            value=bool(self.preferences.get("add_codec_suffix", False))
        )
        self.optimize_var = tk.BooleanVar(
            value=bool(self.preferences.get("optimize", True))
        )
        self.use_global_ffmpeg_var = tk.BooleanVar(value=prefer_global)
        stored_mode = str(self.preferences.get("processing_mode", "local"))
        if stored_mode not in {"local", "remote"}:
            stored_mode = "local"
        self.processing_mode_var = tk.StringVar(value=stored_mode)
        self.processing_mode_var.trace_add("write", self._on_processing_mode_change)
        self.theme_var = tk.StringVar(value=self.preferences.get("theme", "os"))
        self.theme_var.trace_add("write", self._on_theme_change)
        self.small_var.trace_add("write", self._on_small_video_change)
        self.small_480_var.trace_add("write", self._on_small_480_change)
        self.open_after_convert_var.trace_add(
            "write", self._on_open_after_convert_change
        )
        self.cut_enabled_var.trace_add("write", self._on_cut_change)
        self.cut_start_var.trace_add("write", self._on_cut_change)
        self.cut_end_var.trace_add("write", self._on_cut_change)
        self.video_codec_var.trace_add("write", self._on_video_codec_change)
        self.add_codec_suffix_var.trace_add("write", self._on_add_codec_suffix_change)
        self.optimize_var.trace_add("write", self._on_optimize_change)
        self.use_global_ffmpeg_var.trace_add("write", self._on_use_global_ffmpeg_change)
        self.server_url_var = tk.StringVar(
            value=str(self.preferences.get("server_url", ""))
        )
        self.server_url_var.trace_add("write", self._on_server_url_change)
        self._discovery_thread: Optional[threading.Thread] = None

        self._basic_defaults: dict[str, float] = {}
        self._basic_variables: dict[str, tk.DoubleVar] = {}
        self._slider_updaters: dict[str, Callable[[str], None]] = {}
        self._sliders: list[tk.Scale] = []
        self._cut_duration: float = 0.0

        self._build_layout()
        self._sync_simple_preset()
        self.silent_speed_var.trace_add("write", self._sync_simple_preset)
        self.sounded_speed_var.trace_add("write", self._sync_simple_preset)
        self.silent_threshold_var.trace_add("write", self._sync_simple_preset)
        self._sync_simple_codec()
        self.video_codec_var.trace_add("write", self._sync_simple_codec)
        self._update_small_variant_state()
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

        if cli_settings:
            self._apply_cli_settings(cli_settings)

        if initial_inputs:
            self._populate_initial_inputs(initial_inputs, auto_run=auto_run)

        if self.server_managed:
            self.root.protocol("WM_DELETE_WINDOW", self._on_close)
            self._start_activity_log()

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
                    progress_callback=self._set_progress_monotonic,
                    stage_callback=self._apply_stage_transition,
                )
                for index, file in enumerate(files, start=1):
                    self._reset_progress_baseline()
                    self._append_log(f"Processing: {os.path.basename(file)}")
                    options = self._create_processing_options(Path(file), args)
                    result = speed_up_video(options, reporter=reporter)
                    self._last_output = result.output_file
                    self._last_time_ratio = result.time_ratio
                    self._last_size_ratio = result.size_ratio
                    self._last_output_duration = result.output_duration
                    self._last_output_size = (
                        result.output_file.stat().st_size
                        if result.output_file.exists()
                        else None
                    )

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

    def _apply_basic_preset(self, preset: str) -> None:
        layout_helpers.apply_basic_preset(self, preset)

    def _update_local_server_url_display(self, url: Optional[str] = None) -> None:
        """Show the LAN-reachable server URL label only in managed server mode.

        When *url* is provided (the LAN address reported by the server's
        ``/activity`` payload) it is shown in preference to the tray-provided
        loopback URL so the label advertises an address other machines can
        connect to. The loopback ``local_server_url`` is left untouched because
        it remains the reliable base for same-machine ``/activity`` polling.
        """

        display_url = url or self.local_server_url

        label = getattr(self, "local_server_url_label", None)
        if label is None:
            return

        if self.server_managed and display_url:
            label.configure(text=layout_helpers.format_local_server_url(display_url))
            label.grid()
        else:
            label.configure(text="")
            label.grid_remove()

    def _update_processing_mode_state(self) -> None:
        has_url = bool(self.server_url_var.get().strip())
        if not has_url and self.processing_mode_var.get() == "remote":
            self.processing_mode_var.set("local")
            return

        if hasattr(self, "remote_mode_button"):
            state = self.tk.NORMAL if has_url else self.tk.DISABLED
            self.remote_mode_button.configure(state=state)

    def _normalize_server_url(self, server_url: str) -> str:
        return self.remote_controller.normalize_server_url(server_url)

    def _format_server_host(self, server_url: str) -> str:
        return self.remote_controller.format_server_host(server_url)

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
        return self.remote_controller.check_remote_server(
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
        return self.remote_controller.ping_server(server_url, timeout=timeout)

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

    def _sync_simple_preset(self, *_: object) -> None:
        """Update the simple-mode speedup dropdown to reflect current speed vars."""
        key = layout_helpers.get_current_preset(self)
        if key == "custom":
            self.simple_preset_var.set("custom")
        else:
            self.simple_preset_var.set(layout_helpers.PRESET_LABELS[key])

    def _sync_simple_codec(self, *_: object) -> None:
        """Update the simple-mode codec dropdown to reflect the current video codec var."""
        key = self.video_codec_var.get()
        self.simple_codec_var.set(layout_helpers.CODEC_LABELS.get(key, key))

    def _toggle_simple_mode(self) -> None:
        self.preference_controller.toggle_simple_mode()

    def _apply_simple_mode(self, *, initial: bool = False) -> None:
        layout_helpers.apply_simple_mode(self, initial=initial)

    def _apply_window_size(self, *, simple: bool) -> None:
        self.preference_controller.apply_window_size(simple=simple)

    def _toggle_advanced(self, *, initial: bool = False) -> None:
        self.preference_controller.toggle_advanced(initial=initial)

    def _on_inputs_updated(self) -> None:
        """Refresh the Cut video range/preview when the input queue changes."""

        if not getattr(self, "cut_enabled_var", None):
            return
        if self.cut_enabled_var.get():
            self._update_cut_range_for_input()
            self._on_cut_slider_change("start")

    def _toggle_cut_panel(self) -> None:
        """Show or hide the Cut video panel based on ``cut_enabled_var``."""

        panel = getattr(self, "cut_panel", None)
        if panel is None:
            return
        if self.cut_enabled_var.get():
            panel.grid()
            self._update_cut_range_for_input()
            self._on_cut_slider_change("end")
        else:
            panel.grid_remove()
        self._update_cut_convert_button()

    def _on_cut_slider_change(self, which: str) -> None:
        """Clamp the start/end handles and mirror them into the text entries.

        ``start`` is never allowed past ``end`` (when an end is set) and ``end``
        never below ``start``; the entry fields mirror the handles as
        ``HH:MM:SS.mmm`` so the value can be edited by hand.
        """

        try:
            start = float(self.cut_start_var.get())
            end = float(self.cut_end_var.get())
        except (TypeError, ValueError):
            return

        if which == "start" and end > 0 and start > end:
            start = end
            self.cut_start_var.set(start)
        elif which == "end" and end > 0 and end < start:
            end = start
            self.cut_end_var.set(end)

        self._refresh_cut_entry_text("start")
        self._refresh_cut_entry_text("end")

    def _refresh_cut_entry_text(self, which: str) -> None:
        """Update a cut entry's text from its slider value unless it has focus."""

        if which == "start":
            text_var = getattr(self, "cut_start_text_var", None)
            entry = getattr(self, "cut_start_entry", None)
            value = float(self.cut_start_var.get())
        else:
            text_var = getattr(self, "cut_end_text_var", None)
            entry = getattr(self, "cut_end_entry", None)
            value = float(self.cut_end_var.get())
        if text_var is None:
            return
        # Avoid clobbering text the user is actively typing into the entry.
        if entry is not None:
            with suppress(Exception):
                if entry.focus_get() is entry:
                    return
        text_var.set(format_timecode(value, milliseconds=True))

    def _on_cut_entry_commit(self, which: str) -> None:
        """Parse a manually-typed timecode into the matching slider handle."""

        text_var = (
            self.cut_start_text_var if which == "start" else self.cut_end_text_var
        )
        raw = text_var.get().strip()
        try:
            seconds = parse_timecode(raw)
        except (ValueError, TypeError):
            # Reject malformed input by restoring the current handle value.
            self._refresh_cut_entry_text(which)
            return

        duration = getattr(self, "_cut_duration", 0.0)
        if duration > 0:
            seconds = min(seconds, duration)
        seconds = round(seconds, 3)

        if which == "start":
            self.cut_start_var.set(seconds)
        else:
            self.cut_end_var.set(seconds)
        self._on_cut_slider_change(which)

    def _update_cut_convert_button(self) -> None:
        """Show the **Convert** button only for the Advanced cut workflow.

        When Cut video is enabled and Simple mode is off the conversion must wait
        for an explicit click, so the button is revealed; otherwise it is hidden
        (Simple mode auto-converts and the Advanced Run button covers the rest).
        """

        button = getattr(self, "cut_convert_button", None)
        if button is None:
            return
        show = self.cut_enabled_var.get() and not self.simple_mode_var.get()
        if show:
            button.grid()
        else:
            button.grid_remove()

    def _update_cut_range_for_input(self) -> None:
        """Set the slider range from the duration of the first queued input."""

        if not self.input_files:
            return
        try:
            from ..ffmpeg import get_video_duration
        except Exception:  # pragma: no cover - defensive import guard
            return

        duration = 0.0
        try:
            duration = float(get_video_duration(self.input_files[0]))
        except Exception:
            duration = 0.0

        self._cut_duration = duration
        for slider in (
            getattr(self, "cut_start_slider", None),
            getattr(self, "cut_end_slider", None),
        ):
            if slider is not None:
                with suppress(Exception):
                    slider.configure(to=duration)

        # Clamp any stale handle values (e.g. persisted from a longer video)
        # into the new ``0..duration`` range so the forwarded trim cannot start
        # or end past EOF, which the pipeline would otherwise silently ignore.
        # A start handle at or past the new EOF is meaningless, so reset it to
        # the beginning rather than to ``duration``; otherwise both handles
        # could collapse onto EOF and produce an empty (``end <= start``) range
        # that ``_collect_arguments`` rejects on Run.
        if duration > 0:
            with suppress(TypeError, ValueError):
                if float(self.cut_end_var.get()) > duration:
                    self.cut_end_var.set(round(duration, 1))
            with suppress(TypeError, ValueError):
                if float(self.cut_start_var.get()) >= duration:
                    self.cut_start_var.set(0.0)

        # Default the end handle to the full duration the first time we learn it.
        if duration > 0 and float(self.cut_end_var.get()) <= 0:
            self.cut_end_var.set(round(duration, 1))

    def _check_for_updates(self) -> None:
        """Check for updates from GitHub releases."""
        if not sys.platform == "win32":
            return

        if not hasattr(self, "check_updates_button"):
            return

        # Disable button during check
        self.check_updates_button.configure(state=self.tk.DISABLED, text="Checking...")
        self._clear_update_status()
        self._set_update_status("Checking for updates...")

        def check_worker() -> None:
            try:
                latest_version, error = update_checker.fetch_latest_version()

                if error:
                    self._schedule_on_ui_thread(
                        lambda: self._on_update_check_complete(None, error)
                    )
                    return

                current_version = resolve_version()
                if current_version == "unknown":
                    self._schedule_on_ui_thread(
                        lambda: self._on_update_check_complete(
                            None, "Could not determine current version"
                        )
                    )
                    return

                # Compare versions
                is_newer = update_checker.compare_versions(
                    current_version, latest_version
                )

                if is_newer:
                    installer_url = update_checker.get_installer_url(latest_version)
                    portable_url = update_checker.get_portable_url(latest_version)
                    self._schedule_on_ui_thread(
                        lambda: self._on_update_check_complete(
                            latest_version, None, installer_url, portable_url
                        )
                    )
                else:
                    self._schedule_on_ui_thread(
                        lambda: self._on_update_check_complete(None, "up_to_date")
                    )

            except Exception as exc:
                self._schedule_on_ui_thread(
                    lambda: self._on_update_check_complete(None, f"Error: {str(exc)}")
                )

        self._update_check_thread = threading.Thread(target=check_worker, daemon=True)
        self._update_check_thread.start()

    def _on_update_check_complete(
        self,
        latest_version: Optional[str],
        error: Optional[str],
        installer_url: Optional[str] = None,
        portable_url: Optional[str] = None,
    ) -> None:
        """Handle update check completion."""
        if not hasattr(self, "check_updates_button"):
            return

        self.check_updates_button.configure(state=self.tk.NORMAL)

        if error:
            if error == "up_to_date":
                self._clear_update_status()
                self._set_update_status("You are using the latest version.")
                self.check_updates_button.configure(text="Check updates")
            else:
                self._clear_update_status()
                self._set_update_status(f"Update check failed: {error}")
                self.check_updates_button.configure(text="Check updates")
            return

        if latest_version:
            self._latest_version = latest_version
            self._installer_url = installer_url
            self._portable_url = portable_url

            # Change button to download
            self.check_updates_button.configure(
                text=f"Download {latest_version}",
                command=self._download_and_install_update,
            )

            # Show status and links
            self._clear_update_status()
            status_text = f"New version {latest_version} is available!"
            links = [
                ("Download portable", portable_url or ""),
                ("Releases page", update_checker.get_releases_page_url()),
            ]
            self._set_update_status_with_links(status_text, links)

    def _download_and_install_update(self) -> None:
        """Download and install the update."""
        if not self._installer_url or not self._latest_version:
            return

        if not hasattr(self, "check_updates_button"):
            return

        # Disable button during download
        self.check_updates_button.configure(state=self.tk.DISABLED)
        self._clear_update_status()
        self._set_update_status("Downloading installer...")

        def download_worker() -> None:
            def update_status_label(percent: int) -> None:
                if hasattr(self, "update_status_label"):
                    self._set_update_status(f"Downloading installer... {percent}%")

            try:

                def progress_callback(downloaded: int, total: int) -> None:
                    if total > 0:
                        percent = int((downloaded / total) * 100)
                        self._schedule_on_ui_thread(
                            lambda: self.check_updates_button.configure(
                                text=f"Downloading... {percent}%"
                            )
                        )
                        self._schedule_on_ui_thread(
                            lambda p=percent: update_status_label(p)
                        )

                file_path, error = update_checker.download_file(
                    self._installer_url, progress_callback
                )

                if error:
                    self._schedule_on_ui_thread(
                        lambda: self._on_download_complete(None, error)
                    )
                    return

                if file_path:
                    self._schedule_on_ui_thread(
                        lambda: self._on_download_complete(file_path, None)
                    )

            except Exception as exc:
                self._schedule_on_ui_thread(
                    lambda: self._on_download_complete(None, f"Error: {str(exc)}")
                )

        self._download_thread = threading.Thread(target=download_worker, daemon=True)
        self._download_thread.start()

    def _on_download_complete(
        self, file_path: Optional[Path], error: Optional[str]
    ) -> None:
        """Handle download completion."""
        if not hasattr(self, "check_updates_button"):
            return

        if error:
            self.check_updates_button.configure(state=self.tk.NORMAL)
            self._clear_update_status()
            self._set_update_status(f"Download failed: {error}")
            if self._latest_version:
                self.check_updates_button.configure(
                    text=f"Download {self._latest_version}",
                )
            return

        if file_path and file_path.exists():
            # Launch installer
            try:
                if sys.platform == "win32":
                    os.startfile(str(file_path))
                else:
                    subprocess.Popen([str(file_path)])

                self._clear_update_status()
                self._set_update_status(
                    "Installer launched. Please follow the installation wizard."
                )
                self.check_updates_button.configure(
                    state=self.tk.NORMAL,
                    text="Check updates",
                    command=self._check_for_updates,
                )
                # Reset state
                self._latest_version = None
                self._installer_url = None
                self._portable_url = None
            except Exception as exc:
                self._clear_update_status()
                self._set_update_status(f"Failed to launch installer: {str(exc)}")
                self.check_updates_button.configure(state=self.tk.NORMAL)

    def _clear_update_status(self) -> None:
        """Clear the update status label."""
        if hasattr(self, "update_status_label"):
            self.update_status_label.config(text="")
            # Remove any link labels if they exist
            if hasattr(self, "_update_link_labels"):
                for link_label in self._update_link_labels:
                    link_label.destroy()
                self._update_link_labels = []

    def _set_update_status(self, text: str) -> None:
        """Set text in the update status label."""
        if hasattr(self, "update_status_label"):
            self.update_status_label.config(text=text)

    def _set_update_status_with_links(
        self, text: str, links: list[tuple[str, str]]
    ) -> None:
        """Set text and add clickable links to the update status area."""
        if not hasattr(self, "update_status_label"):
            return

        # Clear previous link labels
        if hasattr(self, "_update_link_labels"):
            for link_label in self._update_link_labels:
                link_label.destroy()
            self._update_link_labels = []
        else:
            self._update_link_labels = []

        # Clear status label
        self.update_status_label.config(text=text)

        # Get accent color from current theme (same as Link.TButton)
        mode = self._resolve_theme_mode()
        palette = LIGHT_THEME if mode == "light" else DARK_THEME
        accent_color = palette["accent"]

        # Create link labels in the button_frame
        button_frame = self.update_status_label.master
        current_column = 3  # Start after status label (column 2)

        for i, (link_text, url) in enumerate(links):
            # Add separator if not first link
            if i > 0:
                separator = self.ttk.Label(button_frame, text=" | ")
                separator.grid(row=0, column=current_column, sticky="w", padx=(4, 0))
                current_column += 1
                self._update_link_labels.append(separator)

            # Create clickable link label with same style as Link.TButton
            link_label = self.ttk.Label(
                button_frame,
                text=link_text,
                foreground=accent_color,
                cursor="hand2",
                font=("TkDefaultFont", 8, "underline"),
            )
            link_label.grid(row=0, column=current_column, sticky="w", padx=(4, 0))

            # Bind click event
            def on_link_click(event: Any, link_url: str = url) -> None:
                if link_url:
                    webbrowser.open(link_url)

            link_label.bind("<Button-1>", on_link_click)
            self._update_link_labels.append(link_label)
            current_column += 1

    def _on_theme_change(self, *_: object) -> None:
        self.preference_controller.on_theme_change(*_)

    def _on_small_video_change(self, *_: object) -> None:
        self.preference_controller.on_small_video_change(*_)

    def _on_small_480_change(self, *_: object) -> None:
        self.preference_controller.on_small_480_change(*_)

    def _update_small_variant_state(self) -> None:
        self.preference_controller.update_small_variant_state()

    def _on_open_after_convert_change(self, *_: object) -> None:
        self.preference_controller.on_open_after_convert_change(*_)

    def _on_cut_change(self, *_: object) -> None:
        self.preference_controller.on_cut_change(*_)

    def _on_video_codec_change(self, *_: object) -> None:
        self.preference_controller.on_video_codec_change(*_)

    def _on_add_codec_suffix_change(self, *_: object) -> None:
        self.preference_controller.on_add_codec_suffix_change(*_)

    def _on_optimize_change(self, *_: object) -> None:
        self.preference_controller.on_optimize_change(*_)

    def _on_use_global_ffmpeg_change(self, *_: object) -> None:
        self.preference_controller.on_use_global_ffmpeg_change(*_)

    def _on_processing_mode_change(self, *_: object) -> None:
        self.preference_controller.on_processing_mode_change(*_)

    def _on_server_url_change(self, *_: object) -> None:
        self.preference_controller.on_server_url_change(*_)

    def _resolve_theme_mode(self) -> str:
        return self.preference_controller.resolve_theme_mode()

    def _refresh_theme(self) -> None:
        self.preference_controller.refresh_theme()

    def read_windows_theme_registry(self, key_path: str, value_name: str) -> int:
        """Read *value_name* from the registry key at *key_path*."""
        return read_windows_theme_registry(key_path, value_name)

    def run_defaults_command(
        self, args: Sequence[str]
    ) -> subprocess.CompletedProcess[str]:
        """Execute the macOS ``defaults`` command used to detect theme."""
        return run_defaults_command(args)

    def _configure_drop_targets(self, widget) -> None:
        self.inputs.configure_drop_targets(widget)

    def _apply_cli_settings(self, settings: dict) -> None:
        """Apply CLI-provided options to the matching GUI controls.

        Used by the file-association launch path so a shortcut such as
        ``talks-reducer.exe --small --silent-speed 5`` pre-seeds the GUI controls
        with the requested settings before processing the dropped file.
        """

        if not settings:
            return

        if "small" in settings:
            self.small_var.set(bool(settings["small"]))
        if "small_480" in settings:
            self.small_480_var.set(bool(settings["small_480"]))
        if "silent_speed" in settings:
            self.silent_speed_var.set(float(settings["silent_speed"]))
        if "sounded_speed" in settings:
            self.sounded_speed_var.set(float(settings["sounded_speed"]))
        if "silent_threshold" in settings:
            self.silent_threshold_var.set(float(settings["silent_threshold"]))
        if "frame_spreadage" in settings:
            self.frame_margin_var.set(_format_seed_number(settings["frame_spreadage"]))
        if "sample_rate" in settings:
            self.sample_rate_var.set(_format_seed_number(settings["sample_rate"]))
        if "keyframe_interval_seconds" in settings:
            self.keyframe_interval_var.set(float(settings["keyframe_interval_seconds"]))
        if "video_codec" in settings:
            codec_value = str(settings["video_codec"]).strip().lower()
            if codec_value in {"h264", "hevc", "av1"}:
                self.video_codec_var.set(codec_value)
        if "add_codec_suffix" in settings:
            self.add_codec_suffix_var.set(bool(settings["add_codec_suffix"]))
        if "prefer_global_ffmpeg" in settings:
            self.use_global_ffmpeg_var.set(bool(settings["prefer_global_ffmpeg"]))
        if "optimize" in settings:
            self.optimize_var.set(bool(settings["optimize"]))
        if "output_file" in settings:
            self.output_var.set(str(settings["output_file"]))
        if "temp_folder" in settings:
            self.temp_var.set(str(settings["temp_folder"]))
        if "server_url" in settings:
            self.server_url_var.set(str(settings["server_url"]))
            self.processing_mode_var.set("remote")

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
        return self.inputs.ask_for_input_files()

    def _add_files(self) -> None:
        self.inputs.add_files()

    def _add_directory(self) -> None:
        self.inputs.add_directory()

    def _extend_inputs(self, paths: Iterable[str], *, auto_run: bool = False) -> None:
        self.inputs.extend_inputs(paths, auto_run=auto_run)

    def _clear_input_files(self) -> None:
        """Clear all queued input files."""
        self.inputs.clear_input_files()

    def _on_drop(self, event: object) -> None:
        self.inputs.on_drop(event)

    def _on_drop_zone_click(self, event: object) -> str | None:
        return self.inputs.on_drop_zone_click(event)

    def _browse_path(
        self, variable, label: str
    ) -> None:  # type: (tk.StringVar, str) -> None
        self.inputs.browse_path(variable, label)

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

        codec_value = self.video_codec_var.get().strip().lower()
        if codec_value not in {"h264", "hevc", "av1"}:
            codec_value = "h264"
            self.video_codec_var.set(codec_value)
        args["video_codec"] = codec_value
        if self.add_codec_suffix_var.get():
            args["add_codec_suffix"] = True
        args["prefer_global_ffmpeg"] = bool(self.use_global_ffmpeg_var.get())

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
        if self.keyframe_interval_var.get():
            interval = float(self.keyframe_interval_var.get())
            if interval <= 0:
                raise ValueError("Keyframe interval must be positive.")
            clamped_interval = float(f"{interval:.6f}")
            args["keyframe_interval_seconds"] = clamped_interval
            self.preferences.update("keyframe_interval_seconds", clamped_interval)
        args["optimize"] = bool(self.optimize_var.get())
        if self.small_var.get():
            args["small"] = True
            if self.small_480_var.get():
                args["small_target_height"] = 480
        # Cut video is an Advanced-only feature; Simple mode never trims even if
        # the flag persisted from a previous Advanced session.
        if self.cut_enabled_var.get() and not self.simple_mode_var.get():
            cut_start = float(self.cut_start_var.get())
            cut_end = float(self.cut_end_var.get())
            if cut_end and cut_end <= cut_start:
                raise ValueError(
                    "Cut end must be greater than cut start (or 0 for end of video)."
                )
            args["cut_start_seconds"] = round(cut_start, 3)
            args["cut_end_seconds"] = round(cut_end, 3)
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

        return self.remote_controller.process_files_via_server(
            files,
            args,
            server_url,
            open_after_convert=open_after_convert,
            default_remote_destination=default_remote_destination,
            parse_summary=parse_ratios_from_summary,
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
        self.summary_manager.append_log(message)

    def _update_status_from_message(self, message: str) -> None:
        self.summary_manager.update_status_from_message(message)

    def _handle_status_transitions(self, normalized_message: str) -> bool:
        return self.summary_manager.handle_status_transitions(normalized_message)

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
        percentage = (audio_percentage / 100.0) * self.AUDIO_PROGRESS_WEIGHT
        # The synthetic timer only fills the 0-5% band. Route the bump through
        # the monotonic clamp so it can never drag the bar backwards once real
        # extraction or audio-processing progress has advanced past it. Reading
        # ``progress_var`` directly is unsafe: real progress raises
        # ``_progress_floor`` synchronously but applies the Tk variable through a
        # queued ``_set_progress`` callback, so this timer — already scheduled in
        # the event loop — could observe a stale, lower value (e.g. ``0``) and
        # queue a bump that lands after the real update, snapping the bar back.
        # Clamping against ``_progress_floor`` keeps the real progress instead.
        self._set_progress_monotonic(percentage)
        self._set_status("processing", f"Audio processing: {audio_percentage:.1f}%")

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
                # Route the floor bump through the monotonic clamp rather than a
                # stale ``progress_var`` read. ``_complete`` already runs inside a
                # ``root.after`` callback, so a plain ``_set_progress`` here would
                # schedule a *second* nested update that can land after a higher
                # final-encode value queued earlier in the same batch (callers
                # invoke ``_complete_audio_phase`` immediately before pushing a
                # frame/time percentage), snapping the bar backwards — e.g.
                # 35% -> 5%. Clamping against ``_progress_floor`` — the synchronous
                # source of truth raised by the structured progress channel — keeps
                # the audio-phase floor at ``AUDIO_PROGRESS_WEIGHT`` without ever
                # undercutting real progress.
                self._set_progress_monotonic(self.AUDIO_PROGRESS_WEIGHT)

        self._schedule_on_ui_thread(_complete)

    def _apply_stage_transition(self, desc: str) -> None:
        """Stop the synthetic audio timer when real stage progress arrives.

        The synthetic ``Audio processing:`` timer is only a fallback for when the
        pipeline cannot report real audio progress. Every structured progress
        channel — the local pipeline reporter, the remote streaming callback, and
        the log-parsed ``Task: NN%`` milestones — routes its stage label through
        this helper so the fallback timer never keeps overwriting the status with
        synthetic percentages after real progress has begun. Real
        ``Audio processing:`` progress cancels the timer, while ``Generating
        final`` progress completes the audio phase outright.
        """

        normalized = (desc or "").strip().lower()
        if normalized.startswith("generating final"):
            self._complete_audio_phase()
        elif normalized.startswith("audio processing"):
            self._cancel_audio_progress()

    def _begin_download_wait(self) -> None:
        """Show a refreshing "Waiting for download…" status before the download.

        After the remote pipeline finishes generating the final video the server
        spends several seconds finalizing the file before the download stream
        begins, emitting no progress events in between. Without a heartbeat the
        GUI would sit silently at the last processing status for that whole gap.
        Emit the waiting status immediately and re-emit it on a repeating timer
        until :meth:`_cancel_download_wait` stops it (on the first downloaded
        bytes, on error, or on a stop request).

        ``_download_wait_active`` is the synchronous source of truth for whether
        a wait is wanted. Both this method and :meth:`_cancel_download_wait` run
        on the background worker thread, while ``_start``/``_emit_download_wait``
        run later on the Tk thread. Setting the flag synchronously here (and
        clearing it synchronously in the cancel) means a cancellation that races
        ahead of the queued ``_start`` — e.g. the first ``"Downloading:"`` event
        or the post-``send_video`` cleanup arriving before Tk processes the
        start — invalidates the pending start instead of arming a stale timer.
        """

        self._download_wait_active = True

        def _start() -> None:
            if not self._download_wait_active:
                return
            if self._download_wait_job is not None:
                self.root.after_cancel(self._download_wait_job)
                self._download_wait_job = None
            self._emit_download_wait()

        self._schedule_on_ui_thread(_start)

    def _emit_download_wait(self) -> None:
        """Emit the waiting status and reschedule the next refresh."""

        if not self._download_wait_active:
            return
        self._download_wait_job = None
        self._set_status("processing", self.DOWNLOAD_WAIT_STATUS)
        self._download_wait_job = self.root.after(
            self.DOWNLOAD_WAIT_INTERVAL_MS, self._emit_download_wait
        )

    def _cancel_download_wait(self) -> None:
        """Stop the "Waiting for download…" heartbeat timer if it is running.

        Clear ``_download_wait_active`` synchronously so a start still queued on
        the Tk thread (but not yet run) is invalidated, then queue the timer
        teardown. Always queueing the teardown — even when ``_download_wait_job``
        is currently ``None`` — is what closes the race: the job handle may still
        be ``None`` simply because the queued ``_start`` has not run yet.
        """

        self._download_wait_active = False

        def _cancel() -> None:
            if self._download_wait_job is not None:
                self.root.after_cancel(self._download_wait_job)
                self._download_wait_job = None

        self._schedule_on_ui_thread(_cancel)

    def _start_activity_log(self) -> None:
        """Begin polling the managed server's ``/activity`` endpoint.

        The poll loop only runs when the GUI is started under a managed server
        (``--server-managed``) with a known local URL; in standalone mode this is
        a no-op so the normal GUI never touches the network.
        """

        if not (self.server_managed and self.local_server_url):
            return
        if self._activity_poll_job is not None:
            return
        self._poll_activity()

    def _poll_activity(self) -> None:
        """Fetch recent activity on a worker thread without blocking the UI."""

        self._activity_poll_job = None
        url = self.local_server_url
        if not (self.server_managed and url):
            return

        def worker() -> None:
            payload = self._fetch_activity(url)
            self._schedule_on_ui_thread(lambda: self._finish_activity_poll(payload))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_activity_poll(self, payload: Optional[dict]) -> None:
        """Render the fetched *payload* (if any) and schedule the next poll."""

        if payload is not None:
            server = payload.get("server")
            if isinstance(server, dict):
                server_url = server.get("url")
                if isinstance(server_url, str) and server_url:
                    self._update_local_server_url_display(server_url)
            self._render_activity(payload.get("entries", []))
        if self.server_managed and self.local_server_url:
            self._activity_poll_job = self.root.after(
                self.ACTIVITY_POLL_INTERVAL_MS, self._poll_activity
            )

    def _fetch_activity(self, url: str) -> Optional[dict]:
        """Return the ``/activity`` JSON payload from *url*, or ``None`` on failure.

        Network and parsing errors are swallowed so an unreachable server simply
        skips one render without crashing or spamming the log. The payload is the
        ``{"server": {...}, "entries": [...]}`` mapping; an absent or non-list
        ``entries`` is normalised to an empty list.
        """

        endpoint = url.rstrip("/") + "/activity"
        try:
            with urllib.request.urlopen(endpoint, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        if not isinstance(payload.get("entries"), list):
            payload["entries"] = []
        return payload

    def _render_activity(self, entries: list) -> None:
        """Render activity *entries* into the read-only activity panel."""

        widget = getattr(self, "activity_text", None)
        if widget is None:
            return

        lines = [layout_helpers.format_activity_line(entry) for entry in entries]
        text = "\n".join(lines)
        widget.configure(state=self.tk.NORMAL)
        widget.delete("1.0", self.tk.END)
        if text:
            widget.insert(self.tk.END, text + "\n")
        widget.see(self.tk.END)
        widget.configure(state=self.tk.DISABLED)

    def _stop_activity_log(self) -> None:
        """Cancel the activity poll timer if one is scheduled."""

        if self._activity_poll_job is None:
            return
        try:
            self.root.after_cancel(self._activity_poll_job)
        except Exception:  # pragma: no cover - defensive safeguard
            pass
        self._activity_poll_job = None

    def _on_close(self) -> None:
        """Cancel background timers before destroying the window."""

        self._closing = True
        self._stop_activity_log()
        self._cancel_download_wait()
        self.root.destroy()

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
        return SummaryManager.format_progress_time(total_seconds)

    def _calculate_gradient_color(self, percentage: float, darken: float = 1.0) -> str:
        """Calculate color gradient from red (0%) to green (100%).

        Args:
            percentage: The position in the gradient (0-100)
            darken: Value between 0.0 (black) and 1.0 (original brightness)

        Returns:
            Hex color code string
        """
        # Clamp percentage between 0 and 100
        percentage = max(0.0, min(100.0, float(percentage)))
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

    def _set_progress(self, percentage: float) -> None:
        """Update the progress bar value and color (thread-safe)."""

        def updater() -> None:
            value = max(0.0, min(100.0, float(percentage)))
            self.progress_var.set(value)
            # Update color based on percentage gradient
            color = self._calculate_gradient_color(value, 0.5)
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
            if value < 100.0:
                if hasattr(self, "status_frame"):
                    self.status_frame.grid()
                self.stop_button.grid()
                self.drop_hint_button.grid_remove()

        self.root.after(0, updater)

    def _set_progress_monotonic(self, percentage: float) -> None:
        """Update the progress bar without ever moving it backwards.

        Streamed pipeline progress is mapped into stable percentage bands, but a
        stage that restarts at zero — most notably the final encode falling back
        to the CPU encoder after a GPU failure — re-enters its band at the start
        and would otherwise drag the bar behind a value an earlier frame already
        reached. Clamping against a dedicated per-file floor keeps the bar
        monotonic within a single file while still allowing
        :meth:`_reset_progress_baseline` to re-base it for the next file in a
        batch. The floor is tracked synchronously rather than read back from the
        Tkinter variable so a background worker thread cannot observe a stale
        value mid-update.
        """

        value = min(100.0, max(self._progress_floor, float(percentage)))
        self._progress_floor = value
        self._set_progress(value)

    def _reset_progress_baseline(self) -> None:
        """Re-base the monotonic progress bar so the next file starts at zero.

        The monotonic clamp in :meth:`_set_progress_monotonic` must not carry the
        previous file's completed value into the next file of a batch, otherwise
        every file after the first would stay pinned at 100%. Resetting the floor
        and the visible bar lets each file report progress from the start of its
        own range.
        """

        self._progress_floor = 0.0
        self._set_progress(0.0)

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
        # A daemon worker (e.g. the activity poller blocked in ``urlopen``) can
        # return after the window is destroyed; calling ``after`` on a dead Tk
        # root would raise from the worker thread, so drop the callback instead.
        if self._closing:
            return
        with suppress(Exception):
            self.root.after(0, callback)

    def run(self) -> None:
        """Start the Tkinter event loop."""

        self.root.mainloop()


__all__ = [
    "TalksReducerGUI",
    "default_remote_destination",
    "parse_ratios_from_summary",
    "_default_remote_destination",
    "_parse_ratios_from_summary",
    "_parse_source_duration_seconds",
    "_parse_encode_total_frames",
    "_parse_current_frame",
    "_parse_encode_target_duration",
    "_parse_video_duration_seconds",
    "_parse_ffmpeg_progress",
    "_parse_task_percent",
    "_is_encode_total_frames_unknown",
    "_is_encode_target_duration_unknown",
]

# Backwards compatibility for legacy imports
_default_remote_destination = default_remote_destination
_parse_ratios_from_summary = parse_ratios_from_summary
_parse_source_duration_seconds = parse_source_duration_seconds
_parse_encode_total_frames = parse_encode_total_frames
_parse_current_frame = parse_current_frame
_parse_encode_target_duration = parse_encode_target_duration
_parse_video_duration_seconds = parse_video_duration_seconds
_parse_ffmpeg_progress = parse_ffmpeg_progress
_parse_task_percent = parse_task_percent
_is_encode_total_frames_unknown = is_encode_total_frames_unknown
_is_encode_target_duration_unknown = is_encode_target_duration_unknown
