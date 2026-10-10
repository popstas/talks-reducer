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
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Mapping, Optional

# Settings key under which ``ffmpeg.detect_hardware_backend`` caches its
# per-codec trial-encode results. Lives here so the GUI can protect it from
# wholesale rewrites without importing the FFmpeg module.
HARDWARE_BACKEND_KEY = "hardware_backend"


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


class SettingsReadError(Exception):
    """Raised when an existing settings file cannot be read or parsed.

    Distinguished from a genuinely absent file so callers that merge on-disk
    state into a wholesale rewrite can abort rather than treat an unreadable
    file as empty and clobber keys they do not own.
    """


def read_settings_strict(config_path: Path) -> dict[str, object]:
    """Load settings, distinguishing genuine absence from a read failure.

    Returns an empty dict when the file does not exist. Raises
    :class:`SettingsReadError` when the file exists but cannot be read or parsed
    (``OSError`` from a concurrent lock, ``json.JSONDecodeError`` from a
    partially written file, ``UnicodeDecodeError`` from a file that is not
    UTF-8), so a caller must not mistake a transient failure
    for real absence.
    """

    try:
        with config_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SettingsReadError(str(config_path)) from exc

    if isinstance(data, dict):
        return data
    return {}


def load_settings(config_path: Path) -> dict[str, object]:
    """Load settings from *config_path*, returning an empty dict on failure."""

    try:
        return read_settings_strict(config_path)
    except SettingsReadError:
        return {}


def save_settings(config_path: Path, data: Mapping[str, object]) -> bool:
    """Atomically write *data* to *config_path*, creating parent directories.

    The JSON is written to a temporary file in the target directory, flushed and
    fsynced, then moved onto *config_path* with :func:`os.replace`, so a reader
    or a crash mid-write sees either the previous file or the complete new one,
    never a truncated file that :func:`read_settings_strict` would reject.

    Returns ``True`` when the file is written and ``False`` when an ``OSError``
    prevents persistence (including the ``PermissionError`` Windows raises when
    another process holds the target open during the replace), so callers that
    must not act on a stale ``settings.json`` can detect the failure. The
    temporary file is removed whenever the replace does not happen. Data that
    cannot be serialized raises before anything touches the disk.
    """

    payload = json.dumps(dict(data), indent=2, sort_keys=True)
    temp_name: Optional[str] = None
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=config_path.parent,
            prefix=f".{config_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, config_path)
        temp_name = None
    except OSError:
        return False
    finally:
        if temp_name is not None:
            with suppress(OSError):
                os.unlink(temp_name)
    return True
