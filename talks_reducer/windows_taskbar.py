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

    try:  # Optional dependency that only ships on Windows
        import pythoncom
        import pywintypes
    except ImportError:  # pragma: no cover - handled at runtime
        pythoncom = None  # type: ignore[assignment]
        pywintypes = None  # type: ignore[assignment]

    CLSID_TASKBARLIST = "{56FDF344-FD6D-11d0-958A-006097C9A090}"
    IID_ITASKBARLIST = "{56FDF342-FD6D-11d0-958A-006097C9A090}"
    IID_ITASKBARLIST3 = "{EA1AFB91-9E28-4B86-90E9-9E9F8A5A2B2A}"
    IID_ITASKBARLIST4 = "{C43DC798-95D1-4BEA-9030-BB99E2983A1A}"
    E_NOINTERFACE = 0x80004002
    REGDB_E_CLASSNOTREG = 0x80040154
    RPC_E_CHANGED_MODE = 0x80010106

    logger = logging.getLogger(__name__)

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

    class TaskbarProgress:
        """Wrapper around ``ITaskbarList3`` for reporting taskbar progress."""

        def __init__(self, hwnd: Optional[int] = None) -> None:
            if pythoncom is None or pywintypes is None:
                raise TaskbarUnavailableError(
                    "pywin32 is required for Windows taskbar progress updates."
                )

            self._closed = False
            self._iface = None
            self._should_uninit = False

            self._hwnd = hwnd or _default_hwnd()
            if not self._hwnd:
                raise TaskbarUnavailableError(
                    "Unable to locate a window handle for taskbar progress updates."
                )

            logger.debug("Initialising TaskbarProgress for HWND %s", self._hwnd)

            self._should_uninit = self._initialise_com_apartment()

            self._iface = self._create_taskbar_interface()

            try:
                self._iface.HrInit()
                logger.debug("ITaskbarList3.HrInit succeeded")
            except pywintypes.com_error as exc:
                self.close()
                raise TaskbarUnavailableError(
                    "ITaskbarList3.HrInit failed with HRESULT "
                    f"0x{exc.hresult & 0xFFFFFFFF:08X}."
                ) from exc

        def _initialise_com_apartment(self) -> bool:
            """Initialise COM for the current thread if needed."""

            try:
                initialise = pythoncom.CoInitializeEx
                apartment = getattr(
                    pythoncom,
                    "COINIT_APARTMENTTHREADED",
                    getattr(pythoncom, "COINIT_APARTMENT", 0),
                )
                logger.debug(
                    "Attempting CoInitializeEx with apartment flag 0x%X", apartment
                )
                initialise(apartment)
                logger.debug("CoInitializeEx succeeded (should_uninit=True)")
                return True
            except AttributeError:
                logger.debug(
                    "pywin32 lacks CoInitializeEx; falling back to CoInitialize"
                )
                pythoncom.CoInitialize()
                logger.debug("CoInitialize succeeded (should_uninit=True)")
                return True
            except pywintypes.com_error as exc:
                if exc.hresult == RPC_E_CHANGED_MODE:
                    logger.debug(
                        "COM already initialised in a different mode; continuing without uninitialise"
                    )
                    return False
                raise TaskbarUnavailableError(
                    "CoInitializeEx failed with HRESULT "
                    f"0x{exc.hresult & 0xFFFFFFFF:08X}."
                ) from exc

        def _make_iid(self, value: str):
            try:
                return pywintypes.IID(value)
            except AttributeError:  # pragma: no cover - very old pywin32
                return pythoncom.MakeIID(value)

        def _create_taskbar_interface(self):
            """Create an ``ITaskbarList3`` COM interface via pywin32."""

            context = getattr(
                pythoncom, "CLSCTX_ALL", getattr(pythoncom, "CLSCTX_INPROC_SERVER", 1)
            )

            last_error: pywintypes.com_error | None = None

            for label, iid in (
                ("ITaskbarList3", IID_ITASKBARLIST3),
                ("ITaskbarList4", IID_ITASKBARLIST4),
            ):
                try:
                    iface = pythoncom.CoCreateInstance(
                        self._make_iid(CLSID_TASKBARLIST),
                        None,
                        context,
                        self._make_iid(iid),
                    )
                    logger.debug("CoCreateInstance for %s succeeded via pywin32", label)
                    return iface
                except pywintypes.com_error as exc:
                    last_error = exc
                    if exc.hresult not in (E_NOINTERFACE, REGDB_E_CLASSNOTREG):
                        self._handle_creation_failure(
                            exc, f"CoCreateInstance for {label}"
                        )
                    logger.debug(
                        "Direct %s activation failed with HRESULT 0x%08X; attempting fallback",
                        label,
                        exc.hresult & 0xFFFFFFFF,
                    )

            try:
                base = pythoncom.CoCreateInstance(
                    self._make_iid(CLSID_TASKBARLIST),
                    None,
                    context,
                    self._make_iid(IID_ITASKBARLIST),
                )
            except pywintypes.com_error as exc:
                self._handle_creation_failure(exc, "CoCreateInstance for ITaskbarList")

            try:
                base.HrInit()
                logger.debug(
                    "ITaskbarList.HrInit succeeded for QueryInterface fallback"
                )
            except pywintypes.com_error as exc:
                self._handle_creation_failure(exc, "ITaskbarList.HrInit")

            for label, iid in (
                ("ITaskbarList3", IID_ITASKBARLIST3),
                ("ITaskbarList4", IID_ITASKBARLIST4),
            ):
                try:
                    iface = base.QueryInterface(self._make_iid(iid))
                    logger.debug("Obtained %s via QueryInterface fallback", label)
                    base = None
                    return iface
                except pywintypes.com_error as exc:
                    last_error = exc
                    if exc.hresult != E_NOINTERFACE:
                        self._handle_creation_failure(
                            exc, f"QueryInterface for {label}"
                        )
                    logger.debug(
                        "QueryInterface for %s returned E_NOINTERFACE; trying next candidate",
                        label,
                    )
            else:
                if last_error is not None:
                    self._handle_creation_failure(
                        last_error, "QueryInterface for taskbar interface"
                    )

        def _handle_creation_failure(self, exc, context: str) -> None:
            if self._should_uninit:
                pythoncom.CoUninitialize()
                self._should_uninit = False
            raise TaskbarUnavailableError(
                f"{context} failed with HRESULT 0x{exc.hresult & 0xFFFFFFFF:08X}."
            ) from exc

        def set_progress_value(self, completed: int, total: int) -> None:
            """Update the taskbar progress value."""

            if total <= 0:
                self.set_progress_state(TaskbarProgressState.INDETERMINATE)
                return

            completed = max(0, min(completed, total))

            try:
                self._iface.SetProgressValue(
                    int(self._hwnd), int(completed), int(total)
                )
            except pywintypes.com_error as exc:
                raise TaskbarUnavailableError(
                    "ITaskbarList3.SetProgressValue failed with HRESULT "
                    f"0x{exc.hresult & 0xFFFFFFFF:08X}."
                ) from exc

            logger.debug(
                "Updated taskbar progress: hwnd=%s completed=%s total=%s",
                self._hwnd,
                completed,
                total,
            )

        def set_progress_state(self, state: TaskbarProgressState) -> None:
            """Update the taskbar progress state."""

            try:
                self._iface.SetProgressState(int(self._hwnd), int(state))
            except pywintypes.com_error as exc:
                raise TaskbarUnavailableError(
                    "ITaskbarList3.SetProgressState failed with HRESULT "
                    f"0x{exc.hresult & 0xFFFFFFFF:08X}."
                ) from exc

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
            self._iface = None
            try:
                if self._should_uninit:
                    pythoncom.CoUninitialize()
                    logger.debug("CoUninitialize called during TaskbarProgress cleanup")
            finally:
                self._should_uninit = False

        def __del__(self) -> None:
            self.close()
