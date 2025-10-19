"""Tests for the Windows taskbar helper."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import talks_reducer


class FakeComError(Exception):
    """Minimal stand-in for :class:`pywintypes.com_error`."""

    def __init__(self, hresult: int) -> None:
        super().__init__(f"HRESULT 0x{hresult & 0xFFFFFFFF:08X}")
        self.hresult = hresult


class FakeTaskbarList3:
    def __init__(self) -> None:
        self.init_calls = 0
        self.value_calls: list[tuple[int, int, int]] = []
        self.state_calls: list[tuple[int, int]] = []

    def HrInit(self) -> None:
        self.init_calls += 1

    def SetProgressValue(self, hwnd: int, completed: int, total: int) -> None:
        self.value_calls.append((hwnd, completed, total))

    def SetProgressState(self, hwnd: int, state: int) -> None:
        self.state_calls.append((hwnd, state))


class FakeTaskbarList:
    def __init__(self, target: FakeTaskbarList3) -> None:
        self._target = target
        self.hr_init_calls = 0

    def HrInit(self) -> None:
        self.hr_init_calls += 1

    def QueryInterface(self, iid: str) -> FakeTaskbarList3:
        return self._target


@pytest.mark.parametrize(
    "direct_error",
    [None, 0x80004002, 0x80040154],
)
def test_taskbar_progress_uses_pywin32(monkeypatch, direct_error):
    init_calls: list[tuple[str, int | None]] = []
    recorded: list[tuple[str, str]] = []
    fake_interface = FakeTaskbarList3()

    base_iface: FakeTaskbarList | None = None

    def co_create_instance(clsid: str, _outer, _ctx: int, iid: str):
        recorded.append((clsid, iid))
        if iid.endswith("2B2A}"):
            if direct_error is None:
                # Direct ITaskbarList3 activation succeeds.
                return fake_interface
            # Simulate failure so the fallback path runs.
            raise FakeComError(direct_error)
        if iid.endswith("3A1A}"):
            if direct_error is None:
                return fake_interface
            raise FakeComError(direct_error)
        if iid.endswith("A090}") and direct_error is not None:
            nonlocal base_iface
            base_iface = FakeTaskbarList(fake_interface)
            return base_iface
        raise AssertionError(f"Unexpected CoCreateInstance iid {iid}")

    fake_pythoncom = SimpleNamespace(
        CLSCTX_INPROC_SERVER=1,
        CLSCTX_ALL=7,
        COINIT_APARTMENTTHREADED=2,
        CoInitialize=lambda: init_calls.append(("init", None)),
        CoInitializeEx=lambda flag: init_calls.append(("init_ex", flag)),
        CoUninitialize=lambda: init_calls.append(("uninit", None)),
        MakeIID=lambda value: value,
        CoCreateInstance=co_create_instance,
    )
    fake_pywintypes = SimpleNamespace(com_error=FakeComError, IID=lambda value: value)

    module_path = Path(talks_reducer.__file__).with_name("windows_taskbar.py")

    monkeypatch.setattr(sys, "platform", "win32", raising=False)
    monkeypatch.setitem(sys.modules, "pythoncom", fake_pythoncom)
    monkeypatch.setitem(sys.modules, "pywintypes", fake_pywintypes)

    spec = importlib.util.spec_from_file_location(
        "talks_reducer.windows_taskbar_win32", module_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    taskbar = module.TaskbarProgress(hwnd=0x1234)
    taskbar.set_progress_value(5, 10)
    taskbar.set_progress_state(module.TaskbarProgressState.NORMAL)
    taskbar.clear()
    taskbar.close()

    assert init_calls == [("init_ex", 2), ("uninit", None)]
    assert recorded[0][1].endswith("2B2A}")
    if direct_error is not None:
        # Expect fallback path to probe v4, then create ITaskbarList before querying for v3.
        assert recorded[1][1].endswith("3A1A}")
        assert recorded[2][1].endswith("A090}")
        assert base_iface is not None and base_iface.hr_init_calls == 1
    assert fake_interface.init_calls == 1
    assert fake_interface.value_calls[-1] == (0x1234, 5, 10)
    assert fake_interface.state_calls[0] == (0x1234, module.TaskbarProgressState.NORMAL)
