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

    def update(self, key: str, value: object) -> None:
        """Persist the provided *value* when it differs from the stored value."""

        if self._settings.get(key) == value:
            return
        self._settings[key] = value
        self.save()

    def save(self) -> None:
        """Write the current settings to disk, creating parent directories."""

        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            with self._config_path.open("w", encoding="utf-8") as handle:
                json.dump(self._settings, handle, indent=2, sort_keys=True)
        except OSError:
            pass


class PreferenceController:
    """Apply and persist GUI preference changes such as theme and modes."""

    def __init__(self, gui: "TalksReducerGUI") -> None:
        self.gui = gui

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

    def on_video_codec_change(self, *_: object) -> None:
        value = self.gui.video_codec_var.get().strip().lower()
        if value not in {"h264", "hevc", "av1"}:
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
