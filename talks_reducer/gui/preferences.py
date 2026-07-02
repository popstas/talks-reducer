"""Preference loading, persistence, and GUI appearance helpers."""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Mapping, MutableMapping, Optional

from . import layout as layout_helpers
from .theme import DARK_THEME, LIGHT_THEME, apply_theme, detect_system_theme

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from .app import TalksReducerGUI


def determine_config_path(
    platform: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    home: Optional[Path] = None,
) -> Path:
    """Return the path to the GUI settings file for the current platform."""

    platform_name = platform if platform is not None else sys.platform
    env_mapping = env if env is not None else os.environ
    home_path = Path(home) if home is not None else Path.home()

    if platform_name == "win32":
        appdata = env_mapping.get("APPDATA")
        if appdata:
            base = Path(appdata)
        else:
            base = home_path / "AppData" / "Roaming"
    elif platform_name == "darwin":
        base = home_path / "Library" / "Application Support"
    else:
        xdg_config = env_mapping.get("XDG_CONFIG_HOME")
        base = Path(xdg_config) if xdg_config else home_path / ".config"

    return base / "talks-reducer" / "settings.json"


def load_settings(config_path: Path) -> dict[str, object]:
    """Load settings from *config_path*, returning an empty dict on failure."""

    try:
        with config_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        return {}

    if isinstance(data, dict):
        return data
    return {}


class GUIPreferences:
    """In-memory representation of GUI preferences backed by JSON storage."""

    def __init__(
        self,
        config_path: Path,
        settings: Optional[MutableMapping[str, object]] = None,
    ) -> None:
        self._config_path = config_path
        if settings is None:
            self._settings: MutableMapping[str, object] = load_settings(config_path)
        else:
            self._settings = settings

    @property
    def data(self) -> MutableMapping[str, object]:
        """Return the underlying mutable mapping of settings."""

        return self._settings

    def get(self, key: str, default: object) -> object:
        """Return the setting *key*, storing *default* when missing."""

        value = self._settings.get(key, default)
        if key not in self._settings:
            self._settings[key] = value
        return value

    def get_float(self, key: str, default: float) -> float:
        """Return *key* as a float, normalising persisted string values."""

        raw_value = self.get(key, default)
        try:
            number = float(raw_value)
        except (TypeError, ValueError):
            number = float(default)

        if self._settings.get(key) != number:
            self._settings[key] = number
            self.save()

        return number

    def update(self, key: str, value: object) -> bool:
        """Persist the provided *value* when it differs from the stored value.

        Returns ``True`` when the stored value matches *value* on disk (either
        already present or freshly written) and ``False`` when the write fails.
        On a failed write the in-memory value is rolled back so it stays
        consistent with what is actually on disk.
        """

        if self._settings.get(key) == value:
            return True
        missing = object()
        previous = self._settings.get(key, missing)
        self._settings[key] = value
        if self.save():
            return True
        if previous is missing:
            self._settings.pop(key, None)
        else:
            self._settings[key] = previous
        return False

    def save(self) -> bool:
        """Write the current settings to disk, creating parent directories.

        Returns ``True`` when the file is written and ``False`` when an
        ``OSError`` prevents persistence, so callers that must not act on a
        stale ``settings.json`` can detect the failure.
        """

        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            with self._config_path.open("w", encoding="utf-8") as handle:
                json.dump(self._settings, handle, indent=2, sort_keys=True)
        except OSError:
            return False
        return True


class PreferenceController:
    """Apply and persist GUI preference changes such as theme and modes."""

    def __init__(self, gui: "TalksReducerGUI") -> None:
        self.gui = gui
        self._restoring_server_tray = False

    def on_theme_change(self, *_: object) -> None:
        self.gui.preferences.update("theme", self.gui.theme_var.get())
        self.refresh_theme()

    def on_small_video_change(self, *_: object) -> None:
        self.gui.preferences.update("small_video", bool(self.gui.small_var.get()))
        self.update_small_variant_state()

    def on_small_480_change(self, *_: object) -> None:
        self.gui.preferences.update(
            "small_video_480", bool(self.gui.small_480_var.get())
        )

    def update_small_variant_state(self) -> None:
        if not hasattr(self.gui, "small_480_check"):
            return
        state = self.gui.tk.NORMAL if self.gui.small_var.get() else self.gui.tk.DISABLED
        self.gui.small_480_check.configure(state=state)

    def on_open_after_convert_change(self, *_: object) -> None:
        self.gui.preferences.update(
            "open_after_convert", bool(self.gui.open_after_convert_var.get())
        )

    def on_cut_change(self, *_: object) -> None:
        """Persist the Cut video enable flag and start/end keep-range values."""

        self.gui.preferences.update("cut_enabled", bool(self.gui.cut_enabled_var.get()))
        try:
            cut_start = float(self.gui.cut_start_var.get())
        except (TypeError, ValueError):
            cut_start = 0.0
        try:
            cut_end = float(self.gui.cut_end_var.get())
        except (TypeError, ValueError):
            cut_end = 0.0
        self.gui.preferences.update("cut_start", cut_start)
        self.gui.preferences.update("cut_end", cut_end)

    def on_watch_change(self, *_: object) -> None:
        """Persist the watch-directory settings and toggle the poller."""

        enabled = bool(self.gui.watch_enabled_var.get())
        self.gui.preferences.update("watch_enabled", enabled)
        self.gui.preferences.update(
            "watch_directory", str(self.gui.watch_directory_var.get())
        )
        watch = getattr(self.gui, "watch", None)
        if watch is None:
            return
        if enabled:
            watch.start()
        else:
            watch.stop()
            watch.refresh_candidate()

    def on_video_codec_change(self, *_: object) -> None:
        value = self.gui.video_codec_var.get().strip().lower()
        if value not in {"h264", "hevc", "av1", "mp3"}:
            value = "h264"
            self.gui.video_codec_var.set(value)
        self.gui.preferences.update("video_codec", value)

    def on_add_codec_suffix_change(self, *_: object) -> None:
        self.gui.preferences.update(
            "add_codec_suffix", bool(self.gui.add_codec_suffix_var.get())
        )

    def on_optimize_change(self, *_: object) -> None:
        self.gui.preferences.update("optimize", bool(self.gui.optimize_var.get()))

    def on_use_global_ffmpeg_change(self, *_: object) -> None:
        self.gui.preferences.update(
            "use_global_ffmpeg", bool(self.gui.use_global_ffmpeg_var.get())
        )

    def on_start_in_server_tray_change(self, *_: object) -> None:
        """Dispatch the switch action and persist the server-tray toggle.

        Seeding ``start_in_server_tray_var`` never fires this callback because
        the variable is created before its ``trace_add`` is installed.

        Both directions persist *before* the switch spawns the replacement
        process; otherwise that freshly spawned process could cold-start and
        read a stale value from ``settings.json`` before this write lands. When
        disabling, a stale ``True`` would boot the new plain GUI straight back
        into server-tray mode (a relaunch loop). When enabling, a stale
        ``False`` would seed the managed GUI child's checkbox unchecked while it
        actually runs under tray mode, forcing the user to toggle twice to
        disable. On the enable path the write is reverted if the relaunch spawn
        fails, so a failed relaunch still leaves the stored value effectively
        off.

        ``preferences.update`` swallows ``OSError`` and reports failure rather
        than raising, so if the write to ``settings.json`` cannot land the
        relaunch is aborted entirely: spawning a process that would cold-start
        from a stale file is worse than not switching. The checkbox is restored
        to the persisted value so it never advertises a switch that did not
        happen.
        """

        if self._restoring_server_tray:
            # Re-entrant callback fired by ``_restore_server_tray_var`` setting
            # the variable back to its persisted value. Skip it so the restore
            # never dispatches a relaunch the failed write was meant to abort.
            return

        value = bool(self.gui.start_in_server_tray_var.get())
        if not self.gui.preferences.update("start_in_server_tray", value):
            self._restore_server_tray_var()
            return
        if value:
            try:
                self.gui._apply_server_tray_toggle(value)
            except Exception:
                self.gui.preferences.update("start_in_server_tray", False)
                raise
        else:
            self.gui._apply_server_tray_toggle(value)

    def _restore_server_tray_var(self) -> None:
        """Reset the toggle variable to the value persisted on disk.

        Used when a persistence failure aborts the switch so the checkbox
        reflects the stored state instead of the attempted change. In real Tk
        ``set`` fires the ``write`` trace, which would re-enter
        ``on_start_in_server_tray_change`` and could dispatch the very relaunch
        the failed write was meant to abort (e.g. a standalone GUI with a
        persisted ``True`` whose disable write fails would restore ``True`` and
        spawn server-tray). The ``_restoring_server_tray`` guard makes that
        re-entrant callback a no-op.
        """

        stored = bool(self.gui.preferences.get("start_in_server_tray", False))
        self._restoring_server_tray = True
        try:
            self.gui.start_in_server_tray_var.set(stored)
        finally:
            self._restoring_server_tray = False

    def on_processing_mode_change(self, *_: object) -> None:
        value = self.gui.processing_mode_var.get()
        if value not in {"local", "remote"}:
            self.gui.processing_mode_var.set("local")
            return
        self.gui.preferences.update("processing_mode", value)
        self.gui._update_processing_mode_state()

        if self.gui.processing_mode_var.get() == "remote":
            server_url = self.gui.server_url_var.get().strip()
            if not server_url:
                return

            def ping_remote_mode() -> None:
                self.gui._check_remote_server(
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

    def on_server_url_change(self, *_: object) -> None:
        value = self.gui.server_url_var.get().strip()
        self.gui.preferences.update("server_url", value)
        self.gui._update_processing_mode_state()

    def resolve_theme_mode(self) -> str:
        preference = self.gui.theme_var.get().lower()
        if preference not in {"light", "dark"}:
            return detect_system_theme(
                os.environ,
                sys.platform,
                self.gui.read_windows_theme_registry,
                self.gui.run_defaults_command,
            )
        return preference

    def refresh_theme(self) -> None:
        mode = self.resolve_theme_mode()
        palette = LIGHT_THEME if mode == "light" else DARK_THEME
        apply_theme(
            self.gui.style,
            palette,
            {
                "root": self.gui.root,
                "drop_zone": getattr(self.gui, "drop_zone", None),
                "log_text": getattr(self.gui, "log_text", None),
                "activity_text": getattr(self.gui, "activity_text", None),
                "status_label": getattr(self.gui, "status_label", None),
                "sliders": getattr(self.gui, "_sliders", []),
                "tk": self.gui.tk,
                "apply_status_style": self.gui._apply_status_style,
                "status_state": self.gui._status_state,
            },
        )

    def toggle_simple_mode(self) -> None:
        self.gui.preferences.update("simple_mode", self.gui.simple_mode_var.get())
        self.gui._apply_simple_mode()

    def apply_window_size(self, *, simple: bool) -> None:
        layout_helpers.apply_window_size(self.gui, simple=simple)

    def toggle_advanced(self, *, initial: bool = False) -> None:
        if not initial:
            self.gui.advanced_visible.set(not self.gui.advanced_visible.get())
        visible = self.gui.advanced_visible.get()
        if visible:
            self.gui.advanced_frame.grid()
            self.gui.advanced_button.configure(text="Hide advanced")
        else:
            self.gui.advanced_frame.grid_remove()
            self.gui.advanced_button.configure(text="Advanced")
