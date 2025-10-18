"""Windows taskbar progress helpers."""

from __future__ import annotations

import sys
from enum import IntEnum
from typing import Optional

__all__ = [
    "TaskbarProgress",
    "TaskbarProgressState",
    "TaskbarUnavailableError",
]


class TaskbarProgressState(IntEnum):
    """Progress states accepted by :meth:`ITaskbarList3.SetProgressState`."""

    NOPROGRESS = 0
    INDETERMINATE = 0x1
    NORMAL = 0x2
    ERROR = 0x4
    PAUSED = 0x8


class TaskbarUnavailableError(RuntimeError):
    """Raised when Windows taskbar progress APIs cannot be accessed."""


if sys.platform != "win32":  # pragma: no cover - platform-specific shim
    _WINDOWS_ONLY_MESSAGE = (
        "Windows taskbar progress reporting is only available on Windows."
    )

    class TaskbarProgress:
        """Placeholder implementation used on non-Windows platforms."""

        def __init__(
            self, *args, **kwargs
        ) -> None:  # noqa: D401 - standard error message
            raise TaskbarUnavailableError(_WINDOWS_ONLY_MESSAGE)

        def set_progress_value(self, completed: int, total: int) -> None:
            raise TaskbarUnavailableError(_WINDOWS_ONLY_MESSAGE)

        def set_progress_state(self, state: TaskbarProgressState) -> None:
            raise TaskbarUnavailableError(_WINDOWS_ONLY_MESSAGE)

        def clear(self) -> None:
            raise TaskbarUnavailableError(_WINDOWS_ONLY_MESSAGE)

        def close(self) -> None:
            raise TaskbarUnavailableError(_WINDOWS_ONLY_MESSAGE)

else:  # pragma: no cover - requires Windows runtime
    import ctypes
    import logging
    from ctypes import wintypes

    HRESULT = getattr(wintypes, "HRESULT", getattr(ctypes, "HRESULT", ctypes.c_long))

    COINIT_APARTMENTTHREADED = 0x2
    CLSCTX_INPROC_SERVER = 0x1
    RPC_E_CHANGED_MODE = 0x80010106

    logger = logging.getLogger(__name__)

    class GUID(ctypes.Structure):
        """ctypes representation of a Windows GUID."""

        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", wintypes.BYTE * 8),
        ]

    def _guid_from_string(value: str) -> GUID:
        """Convert a GUID string into a :class:`GUID` instance."""

        guid = GUID()
        ole32 = ctypes.OleDLL("ole32")
        ole32.CLSIDFromString.restype = HRESULT
        ole32.CLSIDFromString.argtypes = (wintypes.LPCOLESTR, ctypes.POINTER(GUID))
        hr = ole32.CLSIDFromString(ctypes.c_wchar_p(value), ctypes.byref(guid))
        if hr < 0:
            raise TaskbarUnavailableError(
                f"Unable to parse GUID '{value}' (HRESULT 0x{hr & 0xFFFFFFFF:08X})."
            )
        return guid

    CLSID_TaskbarList = _guid_from_string("{56FDF344-FD6D-11d0-958A-006097C9A090}")
    IID_ITaskbarList3 = _guid_from_string("{EA1AFB91-9E28-4B86-90E9-9E9F8A5A2B2A}")

    def _default_hwnd() -> Optional[int]:
        """Return the best-effort HWND for the current process."""

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32 = ctypes.WinDLL("user32", use_last_error=True)

        kernel32.GetConsoleWindow.restype = wintypes.HWND
        hwnd = kernel32.GetConsoleWindow()
        if hwnd:
            logger.debug("Resolved console window handle for taskbar updates: %s", hwnd)
            return hwnd

        user32.GetActiveWindow.restype = wintypes.HWND
        hwnd = user32.GetActiveWindow()
        if hwnd:
            logger.debug("Resolved active window handle for taskbar updates: %s", hwnd)
            return hwnd

        user32.GetForegroundWindow.restype = wintypes.HWND
        hwnd = user32.GetForegroundWindow()
        if hwnd:
            logger.debug(
                "Resolved foreground window handle for taskbar updates: %s", hwnd
            )
        else:
            logger.debug(
                "Unable to resolve any default window handle for taskbar updates"
            )
        return hwnd or None

    def _failed(hr: int) -> bool:
        """Return whether ``hr`` represents a failure HRESULT."""

        return hr < 0

    class TaskbarProgress:
        """Wrapper around ``ITaskbarList3`` for reporting taskbar progress."""

        def __init__(self, hwnd: Optional[int] = None) -> None:
            self._closed = False
            self._iface = None
            self._release = None
            self._should_uninit = False

            self._hwnd = hwnd or _default_hwnd()
            if not self._hwnd:
                raise TaskbarUnavailableError(
                    "Unable to locate a window handle for taskbar progress updates."
                )

            logger.debug("Initialising TaskbarProgress for HWND %s", self._hwnd)

            self._ole32 = ctypes.OleDLL("ole32")
            self._ole32.CoInitializeEx.restype = HRESULT
            self._ole32.CoInitializeEx.argtypes = (ctypes.c_void_p, wintypes.DWORD)
            self._ole32.CoUninitialize.argtypes = ()
            self._ole32.CoCreateInstance.restype = HRESULT
            self._ole32.CoCreateInstance.argtypes = (
                ctypes.POINTER(GUID),
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.POINTER(GUID),
                ctypes.POINTER(ctypes.c_void_p),
            )

            hr = self._ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
            self._should_uninit = hr in (0, 1)
            if hr not in (0, 1, RPC_E_CHANGED_MODE):
                raise TaskbarUnavailableError(
                    f"CoInitializeEx failed with HRESULT 0x{hr & 0xFFFFFFFF:08X}."
                )
            if hr == RPC_E_CHANGED_MODE:
                logger.debug(
                    "COM already initialised in a different mode; continuing with existing apartment"
                )
            else:
                logger.debug(
                    "CoInitializeEx succeeded with HRESULT 0x%08X (should_uninit=%s)",
                    hr & 0xFFFFFFFF,
                    self._should_uninit,
                )

            taskbar_ptr = ctypes.c_void_p()
            hr = self._ole32.CoCreateInstance(
                ctypes.byref(CLSID_TaskbarList),
                None,
                CLSCTX_INPROC_SERVER,
                ctypes.byref(IID_ITaskbarList3),
                ctypes.byref(taskbar_ptr),
            )
            if _failed(hr):
                if self._should_uninit:
                    self._ole32.CoUninitialize()
                raise TaskbarUnavailableError(
                    f"CoCreateInstance for ITaskbarList3 failed (HRESULT 0x{hr & 0xFFFFFFFF:08X})."
                )
            logger.debug(
                "CoCreateInstance for ITaskbarList3 succeeded: ptr=%s", taskbar_ptr
            )

            self._iface = taskbar_ptr
            self._vtable = ctypes.cast(
                self._iface, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
            ).contents

            self._release = self._get_method(2, ctypes.c_ulong)
            hr_init = self._get_method(3, HRESULT)
            hr = hr_init(self._iface)
            if _failed(hr):
                self.close()
                raise TaskbarUnavailableError(
                    f"ITaskbarList3.HrInit failed with HRESULT 0x{hr & 0xFFFFFFFF:08X}."
                )
            logger.debug("ITaskbarList3.HrInit succeeded")

            self._set_progress_value = self._get_method(
                9,
                HRESULT,
                wintypes.HWND,
                ctypes.c_ulonglong,
                ctypes.c_ulonglong,
            )
            self._set_progress_state = self._get_method(
                10,
                HRESULT,
                wintypes.HWND,
                ctypes.c_int,
            )
            self._closed = False

        def _get_method(self, index: int, restype, *argtypes):
            """Return a callable for the COM method located at ``index``."""

            method = self._vtable[index]
            prototype = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
            return prototype(method)

        def set_progress_value(self, completed: int, total: int) -> None:
            """Update the taskbar progress value."""

            if total <= 0:
                self.set_progress_state(TaskbarProgressState.INDETERMINATE)
                return

            completed = max(0, min(completed, total))
            hr = self._set_progress_value(self._iface, self._hwnd, completed, total)
            if _failed(hr):
                raise TaskbarUnavailableError(
                    f"ITaskbarList3.SetProgressValue failed with HRESULT 0x{hr & 0xFFFFFFFF:08X}."
                )
            logger.debug(
                "Updated taskbar progress: hwnd=%s completed=%s total=%s",
                self._hwnd,
                completed,
                total,
            )

        def set_progress_state(self, state: TaskbarProgressState) -> None:
            """Update the taskbar progress state."""

            hr = self._set_progress_state(self._iface, self._hwnd, int(state))
            if _failed(hr):
                raise TaskbarUnavailableError(
                    f"ITaskbarList3.SetProgressState failed with HRESULT 0x{hr & 0xFFFFFFFF:08X}."
                )
            logger.debug(
                "Updated taskbar progress state: hwnd=%s state=%s", self._hwnd, state
            )

        def clear(self) -> None:
            """Remove progress indicators from the taskbar button."""

            try:
                self.set_progress_state(TaskbarProgressState.NOPROGRESS)
            except TaskbarUnavailableError:
                logger.debug(
                    "Unable to clear taskbar progress state during cleanup; ignoring"
                )

        def close(self) -> None:
            """Release COM resources held by the helper."""

            if self._closed:
                return

            self._closed = True
            try:
                if getattr(self, "_iface", None) and getattr(self, "_release", None):
                    self._release(self._iface)
                    self._iface = None
                    logger.debug("Released taskbar COM interface")
            finally:
                if self._should_uninit:
                    self._ole32.CoUninitialize()
                    logger.debug("CoUninitialize called during TaskbarProgress cleanup")

        def __del__(self) -> None:
            self.close()
