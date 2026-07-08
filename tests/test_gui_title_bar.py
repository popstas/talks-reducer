from __future__ import annotations

from types import SimpleNamespace

from talks_reducer.gui.theme import apply_windows_title_bar_theme


class FakeWindow:
    def __init__(self, window_id: int = 4242, *, raise_id: bool = False) -> None:
        self._id = window_id
        self._raise_id = raise_id

    def winfo_id(self) -> int:
        if self._raise_id:
            raise RuntimeError("no window id yet")
        return self._id


def test_no_op_on_non_windows():
    calls = []

    def setter(hwnd, dark):
        calls.append((hwnd, dark))
        return True

    result = apply_windows_title_bar_theme(
        FakeWindow(), dark=True, platform="linux", dwm_setter=setter
    )

    assert result is False
    assert calls == []


def test_applies_dark_on_windows():
    calls = []

    def setter(hwnd, dark):
        calls.append((hwnd, dark))
        return True

    result = apply_windows_title_bar_theme(
        FakeWindow(window_id=1234), dark=True, platform="win32", dwm_setter=setter
    )

    assert result is True
    assert calls == [(1234, True)]


def test_applies_light_on_windows():
    calls = []

    def setter(hwnd, dark):
        calls.append((hwnd, dark))
        return True

    apply_windows_title_bar_theme(
        FakeWindow(window_id=1234), dark=False, platform="win32", dwm_setter=setter
    )

    assert calls == [(1234, False)]


def test_returns_false_when_window_id_unavailable():
    def setter(hwnd, dark):
        raise AssertionError("setter should not be called without a window id")

    result = apply_windows_title_bar_theme(
        FakeWindow(raise_id=True), dark=True, platform="win32", dwm_setter=setter
    )

    assert result is False
