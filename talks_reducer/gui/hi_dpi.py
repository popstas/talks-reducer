"""Enable High-DPI awareness for the Talks Reducer GUI on Windows."""

from __future__ import annotations

import sys

if sys.platform == "win32":
    import ctypes

    try:
        # Prefer Per-Monitor V2 on Windows 10 and later for best clarity.
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
