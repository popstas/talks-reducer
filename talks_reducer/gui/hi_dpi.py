# hi_dpi.py
"""
Включает HiDPI на Windows как можно раньше:
- Пытается Per-Monitor-V2 (Win10+)
- Фоллбек: Per-Monitor (Win8.1+)
- Фоллбек: System DPI aware (Vista+)

Использование:
    import hi_dpi  # импорт до любых окон/виджетов Tk

Доп. хелперы:
    hi_dpi.get_window_dpi(widget) -> int | None
    hi_dpi.get_tk_scaling(root) -> float
"""
from __future__ import annotations

import sys
from typing import Optional

__all__ = ["enable_high_dpi", "get_window_dpi", "get_tk_scaling"]


def enable_high_dpi() -> str:
    """Включает DPI-осознанность процесса. Возвращает строку с режимом."""
    if sys.platform != "win32":
        return "non-windows"

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.SetLastError(0)

    # Попытка 1: Per-Monitor-V2 (Windows 10+)
    try:
        user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
        ok = user32.SetProcessDpiAwarenessContext(
            ctypes.c_void_p(-4)
        )  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        if ok:
            return "PerMonitorV2"
    except Exception:
        pass

    # Попытка 2: Per-Monitor (Windows 8.1+)
    try:
        shcore = ctypes.windll.shcore
        # PROCESS_PER_MONITOR_DPI_AWARE = 2
        hr = shcore.SetProcessDpiAwareness(ctypes.c_int(2))
        if hr == 0:  # S_OK
            return "PerMonitor"
    except Exception:
        pass

    # Попытка 3: System DPI aware (Vista+)
    try:
        user32.SetProcessDPIAware()
        return "System"
    except Exception:
        return "Unaware(failed)"


def get_window_dpi(widget) -> Optional[int]:
    """Возвращает фактический DPI окна (Win10+), иначе None."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        getdpi = ctypes.windll.user32.GetDpiForWindow
        getdpi.restype = ctypes.c_uint
        return int(getdpi(widget.winfo_id()))
    except Exception:
        return None


def get_tk_scaling(root) -> float:
    """Возвращает tk scaling (px per typographic point). На 125% ≈ 1.6667."""
    try:
        return float(root.tk.call("tk", "scaling"))
    except Exception:
        return 1.0


# Выполняем сразу при импорте
_enable_mode = enable_high_dpi()
