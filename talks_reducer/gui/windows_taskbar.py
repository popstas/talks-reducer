"""Windows taskbar progress integration helpers for the Tkinter GUI."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Any, Optional, Sequence, Tuple
from uuid import UUID


class _GUID(ctypes.Structure):
    """Lightweight wrapper translating UUID strings to ``GUID`` structures."""

    _fields_: Sequence[tuple[str, object]] = (
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    )

    def __init__(self, value: str) -> None:
        super().__init__()
        parsed = UUID(value)
        self.Data1 = parsed.time_low
        self.Data2 = parsed.time_mid
        self.Data3 = parsed.time_hi_version
        data4 = parsed.bytes[8:]
        for index, component in enumerate(data4):
            self.Data4[index] = component


class _ITaskbarList(ctypes.Structure):
    """Minimal representation of the ``ITaskbarList`` COM interface."""

    _fields_: Sequence[tuple[str, object]] = (
        ("lpVtbl", ctypes.POINTER(ctypes.c_void_p)),
    )


class _ITaskbarList3(ctypes.Structure):
    """Minimal representation of the ``ITaskbarList3`` COM interface."""

    _fields_: Sequence[tuple[str, object]] = (
        ("lpVtbl", ctypes.POINTER(ctypes.c_void_p)),
    )


_PITaskbarList = ctypes.POINTER(_ITaskbarList)
_PITaskbarList3 = ctypes.POINTER(_ITaskbarList3)

_CLSID_TASKBAR_LIST = _GUID("56FDF344-FD6D-11d0-958A-006097C9A090")
_IID_ITASKBAR_LIST = _GUID("56FDF342-FD6D-11d0-958A-006097C9A090")
_IID_ITASKBAR_LIST3 = _GUID("EA1AFB91-9E28-4B86-90E9-9E9F7A5ACB12")

_CLSCTX_INPROC_SERVER = 0x1
_COINIT_APARTMENTTHREADED = 0x2
_S_OK = 0
_S_FALSE = 1
_RPC_E_CHANGED_MODE = 0x80010106


class TaskbarProgressController:
    """Expose a simple API for updating the Windows taskbar progress overlay.

    The controller wraps the ``ITaskbarList3`` COM interface when running on
    Windows. On other platforms the class safely degrades to a no-op so callers
    do not need to guard each update.
    """

    TBPF_NOPROGRESS = 0
    TBPF_INDETERMINATE = 0x1
    TBPF_NORMAL = 0x2
    TBPF_ERROR = 0x4
    TBPF_PAUSED = 0x8

    def __init__(self, hwnd: int) -> None:
        self._hwnd = wintypes.HWND(hwnd)
        self._taskbar: Optional[_PITaskbarList3] = None
        self._available = False
        self._current_state = self.TBPF_NOPROGRESS

        if not sys.platform.startswith("win"):
            return

        if not hwnd:
            return

        self._initialize()

    def is_available(self) -> bool:
        """Return ``True`` when the native taskbar integration succeeded."""

        return self._available

    def update_progress(self, percentage: int) -> None:
        """Display *percentage* completion on the taskbar button."""

        if not self._available:
            return

        clamped = max(0, min(percentage, 100))

        if clamped == 0 and percentage <= 0:
            self.clear()
            return

        if clamped >= 100:
            self._set_state(self.TBPF_NORMAL)
            self._set_progress_value(100, 100)
            self.clear()
            return

        self._set_state(self.TBPF_NORMAL)
        self._set_progress_value(clamped, 100)

    def update_status(self, status: str, message: str = "") -> None:
        """Map high-level GUI statuses to the taskbar progress state."""

        if not self._available:
            return

        lowered_status = status.lower()
        lowered_message = message.lower()

        if lowered_status == "processing" or "extracting audio" in lowered_message:
            self._set_state(self.TBPF_NORMAL)
        elif lowered_status == "error":
            self._set_state(self.TBPF_ERROR)
        elif lowered_status == "aborted":
            self._set_state(self.TBPF_PAUSED)
        else:
            self.clear()

    def clear(self) -> None:
        """Remove any taskbar progress overlay."""

        if not self._available or self._current_state == self.TBPF_NOPROGRESS:
            return

        self._set_state(self.TBPF_NOPROGRESS)

    # Internal helpers -------------------------------------------------

    def _initialize(self) -> None:
        """Create the COM taskbar instance if available on this platform."""

        ole32 = ctypes.oledll.ole32
        ole32.CoInitializeEx.restype = ctypes.HRESULT
        ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_ulong]

        try:
            init_result = ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
        except OSError as exc:  # pragma: no cover - requires Windows COM runtime
            if getattr(exc, "winerror", None) not in (None, _RPC_E_CHANGED_MODE):
                return
        else:
            if init_result not in (_S_OK, _S_FALSE, _RPC_E_CHANGED_MODE):
                return

        ole32.CoCreateInstance.restype = ctypes.HRESULT
        ole32.CoCreateInstance.argtypes = [
            ctypes.POINTER(_GUID),
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(_GUID),
            ctypes.POINTER(ctypes.c_void_p),
        ]

        instance = ctypes.c_void_p()
        result = ole32.CoCreateInstance(
            ctypes.byref(_CLSID_TASKBAR_LIST),
            None,
            _CLSCTX_INPROC_SERVER,
            ctypes.byref(_IID_ITASKBAR_LIST),
            ctypes.byref(instance),
        )
        if result != _S_OK or not instance.value:
            return

        pointer = ctypes.cast(instance.value, _PITaskbarList)
        if self._call_method(pointer, _PITaskbarList, 3, (), ()) != _S_OK:
            self._release(pointer, _PITaskbarList)
            return

        query_result, taskbar = self._query_interface(
            pointer, _PITaskbarList, _IID_ITASKBAR_LIST3, _PITaskbarList3
        )
        if query_result != _S_OK or taskbar is None:
            self._release(pointer, _PITaskbarList)
            return

        self._release(pointer, _PITaskbarList)

        self._taskbar = taskbar
        self._available = True

    def _set_state(self, flag: int) -> None:
        """Apply a new taskbar state if the COM bridge is active."""

        if not self._available or self._current_state == flag:
            return

        result = self._call_method(
            self._taskbar,
            _PITaskbarList3,
            10,
            (wintypes.HWND, ctypes.c_uint),
            (self._hwnd, ctypes.c_uint(flag)),
        )
        if result == _S_OK:
            self._current_state = flag

    def _set_progress_value(self, completed: int, total: int) -> None:
        """Send the current completion ratio to Windows."""

        if not self._available:
            return

        self._call_method(
            self._taskbar,
            _PITaskbarList3,
            9,
            (wintypes.HWND, ctypes.c_ulonglong, ctypes.c_ulonglong),
            (
                self._hwnd,
                ctypes.c_ulonglong(max(0, completed)),
                ctypes.c_ulonglong(max(1, total)),
            ),
        )

    def _call_method(
        self,
        pointer: Optional[ctypes.c_void_p],
        pointer_type: Any,
        index: int,
        arg_types: Sequence[object],
        args: Sequence[object],
    ) -> int:
        """Invoke a function from the COM vtable and return its ``HRESULT``."""

        if pointer is None:
            return _S_FALSE

        try:
            vtable = pointer.contents.lpVtbl
        except ValueError:
            return _S_FALSE

        try:
            entry = vtable[index]
        except IndexError:  # pragma: no cover - defensive programming
            return _S_FALSE

        address = ctypes.cast(entry, ctypes.c_void_p).value
        if address is None:
            return _S_FALSE

        prototype = ctypes.WINFUNCTYPE(ctypes.HRESULT, pointer_type, *arg_types)
        method = prototype(address)
        return method(pointer, *args)

    def _query_interface(
        self,
        pointer: Optional[ctypes.c_void_p],
        pointer_type: Any,
        interface_id: _GUID,
        result_type: Any,
    ) -> Tuple[int, Optional[Any]]:
        """Request a different COM interface from the current pointer."""

        if pointer is None:
            return _S_FALSE, None

        out_object = ctypes.c_void_p()
        result = self._call_method(
            pointer,
            pointer_type,
            0,
            (ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)),
            (ctypes.byref(interface_id), ctypes.byref(out_object)),
        )
        if result != _S_OK or not out_object.value:
            return result, None

        return result, ctypes.cast(out_object.value, result_type)

    def _release(
        self,
        pointer: Optional[ctypes.c_void_p],
        pointer_type: Any,
    ) -> None:
        """Decrease the reference count of a COM interface pointer."""

        if pointer is None:
            return

        self._call_method(pointer, pointer_type, 2, (), ())


__all__ = ["TaskbarProgressController"]
