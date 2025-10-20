"""Tests for the Windows taskbar helper."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

import talks_reducer

IID_ITASKBARLIST3 = "{EA1AFB91-9E28-4B86-90E9-9E9F8A5A2B2A}"


class FakeComError(Exception):
    """Minimal stand-in for :class:`pywintypes.com_error`."""

    def __init__(self, hresult: int) -> None:
        super().__init__(f"HRESULT 0x{hresult & 0xFFFFFFFF:08X}")
        # ``pywintypes.com_error`` exposes HRESULT values as signed integers.
        self.hresult = hresult if hresult < 0x80000000 else hresult - 0x100000000


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
    recorded: list[tuple[object, object]] = []
    fake_interface = FakeTaskbarList3()

    base_iface: FakeTaskbarList | None = None

    def co_create_instance(clsid, _outer, _ctx: int, iid):
        recorded.append((clsid, iid))
        if iid == "IID_ITaskbarList3":
            if direct_error is None:
                # Direct ITaskbarList3 activation succeeds.
                return fake_interface
            # Simulate failure so the fallback path runs.
            raise FakeComError(direct_error)
        if iid == "IID_ITaskbarList4":
            if direct_error is None:
                return fake_interface
            raise FakeComError(direct_error)
        if iid == "IID_ITaskbarList" and direct_error is not None:
            nonlocal base_iface
            base_iface = FakeTaskbarList(fake_interface)
            return base_iface
        raise AssertionError(f"Unexpected CoCreateInstance iid {iid}")

    fake_pythoncom = SimpleNamespace(
        CLSCTX_INPROC_SERVER=1,
        CLSCTX_LOCAL_SERVER=2,
        CLSCTX_REMOTE_SERVER=4,
        COINIT_APARTMENTTHREADED=2,
        CoInitialize=lambda: init_calls.append(("init", None)),
        CoInitializeEx=lambda flag: init_calls.append(("init_ex", flag)),
        CoUninitialize=lambda: init_calls.append(("uninit", None)),
        CLSIDFromString=lambda value: value,
        IIDFromString=lambda value: value,
        MakeIID=lambda value: value,
        CoCreateInstance=co_create_instance,
    )
    fake_pywintypes = SimpleNamespace(com_error=FakeComError, IID=lambda value: value)
    fake_shell = SimpleNamespace(
        CLSID_TaskbarList="CLSID_TaskbarList",
        IID_ITaskbarList="IID_ITaskbarList",
        IID_ITaskbarList3="IID_ITaskbarList3",
        IID_ITaskbarList4="IID_ITaskbarList4",
    )

    module_path = Path(talks_reducer.__file__).with_name("windows_taskbar.py")

    monkeypatch.setattr(sys, "platform", "win32", raising=False)
    monkeypatch.setitem(sys.modules, "pythoncom", fake_pythoncom)
    monkeypatch.setitem(sys.modules, "pywintypes", fake_pywintypes)
    win32com_module = ModuleType("win32com")
    shell_package = ModuleType("win32com.shell")
    shell_module = ModuleType("win32com.shell.shell")
    shell_module.CLSID_TaskbarList = fake_shell.CLSID_TaskbarList
    shell_module.IID_ITaskbarList = fake_shell.IID_ITaskbarList
    shell_module.IID_ITaskbarList3 = fake_shell.IID_ITaskbarList3
    shell_module.IID_ITaskbarList4 = fake_shell.IID_ITaskbarList4
    shell_package.shell = shell_module
    win32com_module.shell = shell_package

    monkeypatch.setitem(sys.modules, "win32com", win32com_module)
    monkeypatch.setitem(sys.modules, "win32com.shell", shell_package)
    monkeypatch.setitem(sys.modules, "win32com.shell.shell", shell_module)

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
    assert recorded[0][1] == "IID_ITaskbarList3"
    if direct_error is not None:
        # Expect fallback path to probe v4, then create ITaskbarList before querying for v3.
        assert recorded[1][1] == "IID_ITaskbarList4"
        assert recorded[2][1] == "IID_ITaskbarList"
        assert base_iface is not None and base_iface.hr_init_calls == 1
    assert fake_interface.init_calls == 1
    assert fake_interface.value_calls[-1] == (0x1234, 5, 10)
    assert fake_interface.state_calls[0] == (0x1234, module.TaskbarProgressState.NORMAL)


def test_taskbar_progress_uses_makeiid_when_shell_missing(monkeypatch):
    init_calls: list[tuple[str, int | None]] = []
    recorded_iids: list[object] = []
    made_iids: list[str] = []
    fake_interface = FakeTaskbarList3()

    def co_create_instance(clsid, _outer, _ctx: int, iid):
        recorded_iids.append(iid)
        if iid == "made:" + IID_ITASKBARLIST3:
            return fake_interface
        raise AssertionError(f"Unexpected IID {iid}")

    def make_iid(value: str) -> str:
        made_iids.append(value)
        return "made:" + value

    def iid_from_string(value: str) -> str:
        raise AssertionError("IIDFromString should not be used")

    fake_pythoncom = SimpleNamespace(
        CLSCTX_INPROC_SERVER=1,
        CLSCTX_LOCAL_SERVER=2,
        CLSCTX_REMOTE_SERVER=4,
        COINIT_APARTMENTTHREADED=2,
        CoInitialize=lambda: init_calls.append(("init", None)),
        CoInitializeEx=lambda flag: init_calls.append(("init_ex", flag)),
        CoUninitialize=lambda: init_calls.append(("uninit", None)),
        CLSIDFromString=lambda value: value,
        IIDFromString=iid_from_string,
        MakeIID=make_iid,
        CoCreateInstance=co_create_instance,
    )

    fake_pywintypes = SimpleNamespace(com_error=FakeComError, IID=lambda value: value)

    module_path = Path(talks_reducer.__file__).with_name("windows_taskbar.py")

    monkeypatch.setattr(sys, "platform", "win32", raising=False)
    monkeypatch.setitem(sys.modules, "pythoncom", fake_pythoncom)
    monkeypatch.setitem(sys.modules, "pywintypes", fake_pywintypes)

    win32com_module = ModuleType("win32com")
    shell_package = ModuleType("win32com.shell")
    shell_module = ModuleType("win32com.shell.shell")
    shell_package.shell = shell_module
    win32com_module.shell = shell_package
    monkeypatch.setitem(sys.modules, "win32com", win32com_module)
    monkeypatch.setitem(sys.modules, "win32com.shell", shell_package)
    monkeypatch.setitem(sys.modules, "win32com.shell.shell", shell_module)

    spec = importlib.util.spec_from_file_location(
        "talks_reducer.windows_taskbar_makeiid", module_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    taskbar = module.TaskbarProgress(hwnd=0x9999)
    taskbar.set_progress_value(1, 2)
    taskbar.close()

    assert made_iids == [IID_ITASKBARLIST3]
    assert recorded_iids == ["made:" + IID_ITASKBARLIST3]
