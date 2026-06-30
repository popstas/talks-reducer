"""Helpers for relaunching the Talks Reducer app in a different run mode.

These helpers build the argv used to start the app in either the plain desktop
GUI or the server-tray experience, and spawn that command detached from the
current process so the relaunching window can close cleanly.
"""

from __future__ import annotations

import subprocess
import sys
from typing import List, Optional, Sequence

# Mapping of mode name to the module executed via ``python -m`` for source and
# console runs (i.e. when the app is *not* a frozen PyInstaller bundle).
_MODE_MODULES = {
    "server-tray": "talks_reducer.server_tray",
    "gui": "talks_reducer.gui",
}

# Mode-specific arguments appended after the executable / module entry point.
_MODE_ARGS = {
    "server-tray": ["--with-gui"],
    "gui": [],
}


def _is_frozen() -> bool:
    """Return ``True`` when running from a frozen PyInstaller bundle."""

    return bool(getattr(sys, "frozen", False))


def build_app_command(
    mode: str,
    *,
    extra_args: Optional[Sequence[str]] = None,
) -> List[str]:
    """Return the argv used to start the app in ``mode``.

    ``mode`` must be ``"server-tray"`` (server + tray icon hosting a managed
    GUI) or ``"gui"`` (the plain desktop GUI). Frozen bundles invoke the bundle
    executable directly, while source/console runs use ``python -m`` with the
    matching module. Any ``extra_args`` are appended after the mode arguments.
    """

    if mode not in _MODE_MODULES:
        raise ValueError(f"Unknown app mode: {mode!r}")

    if _is_frozen():
        command: List[str] = [sys.executable]
        if mode == "server-tray":
            command.append("--server")
        command.extend(_MODE_ARGS[mode])
    else:
        command = [sys.executable, "-m", _MODE_MODULES[mode]]
        command.extend(_MODE_ARGS[mode])

    if extra_args:
        command.extend(extra_args)

    return command


def spawn_detached(command: Sequence[str]) -> "subprocess.Popen[bytes]":
    """Launch ``command`` decoupled from the parent process and return it.

    On POSIX the child starts a new session (``start_new_session=True``) so it
    survives the parent exiting. On Windows the ``DETACHED_PROCESS`` and
    ``CREATE_NEW_PROCESS_GROUP`` creation flags achieve the same isolation.
    """

    kwargs: dict[str, object] = {}
    if sys.platform == "win32":
        detached_process = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        new_group = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        kwargs["creationflags"] = detached_process | new_group
    else:
        kwargs["start_new_session"] = True

    return subprocess.Popen(list(command), **kwargs)
