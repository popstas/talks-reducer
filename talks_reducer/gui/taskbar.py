"""Windows taskbar progress indicator for the desktop GUI.

The taskbar button can mirror the in-window progress bar through the
``ITaskbarList3`` COM interface. Only Windows exposes such an indicator, so on
every other platform :func:`create_taskbar_progress` returns an object whose
methods do nothing. The COM plumbing lives behind a small backend protocol so
the state machine in :class:`TaskbarProgress` stays testable without ``ctypes``.
"""

from __future__ import annotations

import ctypes
import sys
from contextlib import suppress
from typing import Any, Optional

__all__ = ["TaskbarProgress", "create_taskbar_progress"]

# ``ITaskbarList3::SetProgressState`` flags.
_TBPF_NOPROGRESS = 0x0
_TBPF_NORMAL = 0x2
_TBPF_ERROR = 0x4

# ``ITaskbarList3`` vtable slots, counting the three inherited ``IUnknown``
# entries: HrInit(3), AddTab, DeleteTab, ActivateTab, SetActiveAlt,
# MarkFullscreenWindow, SetProgressValue(9), SetProgressState(10).
_VTBL_HR_INIT = 3
_VTBL_SET_PROGRESS_VALUE = 9
_VTBL_SET_PROGRESS_STATE = 10

_CLSID_TASKBAR_LIST = "{56FDF344-FD6D-11D0-958A-006097C9A090}"
_IID_ITASKBAR_LIST3 = "{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}"

_CLSCTX_INPROC_SERVER = 0x1
_COINIT_APARTMENTTHREADED = 0x2
_S_OK = 0x00000000
_S_FALSE = 0x00000001
_RPC_E_CHANGED_MODE = 0x80010106


class _NullBackend:
    """Backend used when no taskbar indicator is available."""

    def set_value(self, percent: float) -> None:
        """Ignore the requested progress value."""

    def set_state(self, state: str) -> None:
        """Ignore the requested progress state."""


class TaskbarProgress:
    """Track the taskbar indicator state and forward it to a backend.

    Terminal states — :meth:`finish` and :meth:`set_error` — put the indicator on
    hold: later :meth:`set_value` calls are dropped so a stray progress callback
    cannot erase the result, and the indicator survives until the window regains
    focus (:meth:`on_focus`) or a new run calls :meth:`begin`.
    """

    def __init__(self, backend: Any) -> None:
        self._backend = backend
        self._held = False
        self._value = 0.0

    @property
    def held(self) -> bool:
        """Return whether a terminal state is waiting for the window's focus."""

        return self._held

    def begin(self) -> None:
        """Start a fresh run: release any hold and show an empty normal bar."""

        self._held = False
        self._value = 0.0
        self._backend.set_state("normal")
        self._backend.set_value(0.0)

    def set_value(self, percent: float) -> None:
        """Show *percent* (clamped to 0-100) unless a terminal state is held."""

        if self._held:
            return
        self._value = max(0.0, min(100.0, float(percent)))
        self._backend.set_value(self._value)

    def finish(self) -> None:
        """Hold a completed indicator at 100%."""

        self._held = True
        self._value = 100.0
        self._backend.set_state("normal")
        self._backend.set_value(100.0)

    def set_error(self) -> None:
        """Hold a red indicator at the current value."""

        self._held = True
        if self._value <= 0.0:
            # A red bar is only visible when it has some length; a run that fails
            # before reporting progress would otherwise look like no indicator.
            self._value = 100.0
            self._backend.set_value(100.0)
        self._backend.set_state("error")

    def clear(self) -> None:
        """Remove the indicator and release the hold."""

        self._held = False
        self._value = 0.0
        self._backend.set_state("none")

    def on_focus(self) -> None:
        """Clear a held indicator once the window regains focus."""

        if self._held:
            self.clear()


class _GUID(ctypes.Structure):
    """Binary layout of a Windows ``GUID`` for ``CoCreateInstance``."""

    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_string(cls, value: str) -> "_GUID":
        """Build a GUID from its ``{XXXXXXXX-XXXX-...}`` string form."""

        digits = value.strip("{}").replace("-", "")
        data4 = (ctypes.c_ubyte * 8)(
            *(int(digits[16 + index * 2 : 18 + index * 2], 16) for index in range(8))
        )
        return cls(
            int(digits[0:8], 16),
            int(digits[8:12], 16),
            int(digits[12:16], 16),
            data4,
        )


class _Win32Backend:
    """Drive ``ITaskbarList3`` on the thread that initialized COM."""

    def __init__(self, hwnd: int, taskbar_ptr: ctypes.c_void_p) -> None:
        self._hwnd = hwnd
        self._ptr = taskbar_ptr

    def _vtable_entry(self, index: int, *argtypes: Any) -> Any:
        """Return a callable bound to vtable slot *index* of the COM object."""

        vtable = ctypes.cast(
            self._ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
        )[0]
        prototype = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)
        return prototype(vtable[index])

    def set_value(self, percent: float) -> None:
        """Set the indicator to *percent* of a 0-100 range."""

        with suppress(Exception):
            self._vtable_entry(
                _VTBL_SET_PROGRESS_VALUE,
                ctypes.c_void_p,
                ctypes.c_ulonglong,
                ctypes.c_ulonglong,
            )(self._ptr, self._hwnd, int(round(percent)), 100)

    def set_state(self, state: str) -> None:
        """Switch the indicator between ``normal``, ``error``, and ``none``."""

        flags = {
            "normal": _TBPF_NORMAL,
            "error": _TBPF_ERROR,
            "none": _TBPF_NOPROGRESS,
        }.get(state, _TBPF_NOPROGRESS)
        with suppress(Exception):
            self._vtable_entry(_VTBL_SET_PROGRESS_STATE, ctypes.c_void_p, ctypes.c_int)(
                self._ptr, self._hwnd, flags
            )


def _resolve_hwnd(root: Any) -> Optional[int]:
    """Return the top-level window handle owning the taskbar button.

    Tk reports the handle of its own window; on Windows the taskbar button
    belongs to the wrapper frame above it. ``GetParent`` is declared explicitly
    because the default ``c_int`` return type would truncate a 64-bit handle.
    """

    handle = int(root.winfo_id())
    get_parent = ctypes.windll.user32.GetParent
    get_parent.argtypes = [ctypes.c_void_p]
    get_parent.restype = ctypes.c_void_p
    parent = get_parent(handle)
    return parent or handle


def _create_win32_backend(root: Any) -> Optional[_Win32Backend]:
    """Instantiate ``ITaskbarList3`` for *root*, or return ``None`` on failure."""

    ole32 = ctypes.windll.ole32
    result = ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
    # ``S_FALSE`` means COM was already initialized on this thread and
    # ``RPC_E_CHANGED_MODE`` that another apartment model won; both are usable.
    if result not in (_S_OK, _S_FALSE, ctypes.c_long(_RPC_E_CHANGED_MODE).value):
        return None

    taskbar_ptr = ctypes.c_void_p()
    hresult = ole32.CoCreateInstance(
        ctypes.byref(_GUID.from_string(_CLSID_TASKBAR_LIST)),
        None,
        _CLSCTX_INPROC_SERVER,
        ctypes.byref(_GUID.from_string(_IID_ITASKBAR_LIST3)),
        ctypes.byref(taskbar_ptr),
    )
    if hresult != _S_OK or not taskbar_ptr:
        return None

    hwnd = _resolve_hwnd(root)
    if not hwnd:
        return None

    backend = _Win32Backend(hwnd, taskbar_ptr)
    if backend._vtable_entry(_VTBL_HR_INIT)(taskbar_ptr) != _S_OK:
        return None
    return backend


def create_taskbar_progress(root: Any) -> TaskbarProgress:
    """Return a taskbar indicator for *root*, or a no-op outside Windows.

    Any failure to reach the COM interface — an unsupported platform, a stubbed
    Tk root, a taskbar-less session — degrades to the null backend rather than
    propagating, so callers never need to guard their calls.
    """

    backend: Any = _NullBackend()
    if sys.platform == "win32":
        with suppress(Exception):
            backend = _create_win32_backend(root) or backend
    return TaskbarProgress(backend)
