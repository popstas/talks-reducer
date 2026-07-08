"""Tests for the Windows taskbar progress indicator."""

from __future__ import annotations

import sys

import pytest

from talks_reducer.gui import taskbar


class RecordingBackend:
    """Collect the calls a :class:`TaskbarProgress` forwards to its backend."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def set_value(self, percent: float) -> None:
        self.calls.append(("value", percent))

    def set_state(self, state: str) -> None:
        self.calls.append(("state", state))


@pytest.fixture()
def backend() -> RecordingBackend:
    return RecordingBackend()


@pytest.fixture()
def progress(backend: RecordingBackend) -> taskbar.TaskbarProgress:
    return taskbar.TaskbarProgress(backend)


def test_begin_shows_an_empty_normal_bar(progress, backend):
    progress.begin()

    assert backend.calls == [("state", "normal"), ("value", 0.0)]
    assert not progress.held


def test_set_value_clamps_to_the_zero_to_hundred_range(progress, backend):
    progress.set_value(-5)
    progress.set_value(42.5)
    progress.set_value(140)

    assert backend.calls == [("value", 0.0), ("value", 42.5), ("value", 100.0)]


def test_finish_holds_the_bar_at_full(progress, backend):
    progress.set_value(30)
    backend.calls.clear()

    progress.finish()

    assert backend.calls == [("state", "normal"), ("value", 100.0)]
    assert progress.held


def test_held_state_ignores_stray_progress_updates(progress, backend):
    progress.finish()
    backend.calls.clear()

    progress.set_value(0)
    progress.set_value(55)

    assert backend.calls == []


def test_set_error_keeps_the_current_value(progress, backend):
    progress.set_value(60)
    backend.calls.clear()

    progress.set_error()

    assert backend.calls == [("state", "error")]
    assert progress.held


def test_set_error_without_progress_fills_the_bar(progress, backend):
    progress.set_error()

    assert backend.calls == [("value", 100.0), ("state", "error")]


def test_clear_removes_the_indicator_and_the_hold(progress, backend):
    progress.finish()
    backend.calls.clear()

    progress.clear()

    assert backend.calls == [("state", "none")]
    assert not progress.held


def test_on_focus_clears_only_while_held(progress, backend):
    progress.set_value(20)
    backend.calls.clear()

    progress.on_focus()
    assert backend.calls == []

    progress.finish()
    backend.calls.clear()
    progress.on_focus()

    assert backend.calls == [("state", "none")]
    assert not progress.held


def test_begin_releases_a_previous_hold(progress, backend):
    progress.finish()
    backend.calls.clear()

    progress.begin()
    progress.set_value(10)

    assert backend.calls == [("state", "normal"), ("value", 0.0), ("value", 10.0)]


def test_create_taskbar_progress_is_a_no_op_off_windows(monkeypatch):
    monkeypatch.setattr(taskbar.sys, "platform", "linux")

    progress = taskbar.create_taskbar_progress(root=object())

    assert isinstance(progress._backend, taskbar._NullBackend)
    progress.begin()
    progress.set_value(50)
    progress.finish()
    progress.clear()


def test_create_taskbar_progress_falls_back_when_com_fails(monkeypatch):
    monkeypatch.setattr(taskbar.sys, "platform", "win32")

    def explode(_root: object) -> object:
        raise OSError("no COM here")

    monkeypatch.setattr(taskbar, "_create_win32_backend", explode)

    progress = taskbar.create_taskbar_progress(root=object())

    assert isinstance(progress._backend, taskbar._NullBackend)


def test_create_taskbar_progress_uses_the_win32_backend(monkeypatch):
    monkeypatch.setattr(taskbar.sys, "platform", "win32")
    sentinel = RecordingBackend()
    monkeypatch.setattr(taskbar, "_create_win32_backend", lambda _root: sentinel)

    progress = taskbar.create_taskbar_progress(root=object())

    assert progress._backend is sentinel


def test_guid_parses_the_taskbar_class_identifier():
    guid = taskbar._GUID.from_string(taskbar._CLSID_TASKBAR_LIST)

    assert guid.Data1 == 0x56FDF344
    assert guid.Data2 == 0xFD6D
    assert guid.Data3 == 0x11D0
    assert list(guid.Data4) == [0x95, 0x8A, 0x00, 0x60, 0x97, 0xC9, 0xA0, 0x90]


@pytest.mark.skipif(sys.platform == "win32", reason="ctypes.windll exists on Windows")
def test_module_imports_without_windows_com_symbols():
    assert not hasattr(taskbar.ctypes, "windll")
