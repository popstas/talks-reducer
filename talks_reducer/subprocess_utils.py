"""Spawn helpers that keep child processes from opening console windows.

A console program (``ffmpeg``, ``ffprobe``, ``powershell``) started from the
windowed Windows build gets a brand-new console window unless it is created
with ``CREATE_NO_WINDOW``. Every such spawn in the package passes
``**hidden_subprocess_kwargs()``; ``tests/test_no_console_windows.py`` fails
the build when one does not.
"""

from __future__ import annotations

import sys
from typing import Dict

CREATE_NO_WINDOW = 0x08000000
"""``subprocess.CREATE_NO_WINDOW``, spelled out because the attribute exists
only on Windows and the package is imported (and tested) everywhere."""


def hidden_subprocess_kwargs() -> Dict[str, int]:
    """Return ``subprocess`` keyword arguments that hide the child's console.

    On Windows this is ``{"creationflags": CREATE_NO_WINDOW}``; elsewhere it is
    empty, since ``creationflags`` is Windows-only. ``sys.platform`` is read on
    every call so tests can switch platforms with ``monkeypatch``.
    """

    if sys.platform == "win32":
        return {"creationflags": CREATE_NO_WINDOW}
    return {}
