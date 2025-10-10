"""Utilities for locating and persisting GUI preference settings."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Mapping, MutableMapping, Optional


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
