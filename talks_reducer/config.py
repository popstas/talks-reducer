"""Shared settings-file location, loading, and persistence helpers.

This module owns the ``settings.json`` path resolution and read/write
primitives so that non-GUI surfaces (``cli.py``, ``server.py``,
``dock_server.py``) can reach the shared configuration file without importing
from the ``gui`` package.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Mapping, Optional


def determine_config_path(
    platform: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    home: Optional[Path] = None,
) -> Path:
    """Return the path to the settings file for the current platform."""

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


def save_settings(config_path: Path, data: Mapping[str, object]) -> bool:
    """Write *data* to *config_path*, creating parent directories.

    Returns ``True`` when the file is written and ``False`` when an ``OSError``
    prevents persistence, so callers that must not act on a stale
    ``settings.json`` can detect the failure.
    """

    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with config_path.open("w", encoding="utf-8") as handle:
            json.dump(dict(data), handle, indent=2, sort_keys=True)
    except OSError:
        return False
    return True
