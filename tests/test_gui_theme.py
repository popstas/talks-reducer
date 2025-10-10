from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from talks_reducer.gui.theme import (
    LIGHT_THEME,
    STATUS_COLORS,
    apply_theme,
    detect_system_theme,
)


def test_detect_system_theme_windows(monkeypatch):
    reader = Mock(return_value=0)
    runner = Mock()
    result = detect_system_theme({}, "win32", reader, runner)
    assert result == "dark"
    reader.assert_called_once()


def test_detect_system_theme_windows_default_on_error():
    def raising_reader(*_args):
        raise OSError("boom")

    result = detect_system_theme({}, "win32", raising_reader, Mock())
    assert result == "light"


def test_detect_system_theme_macos(monkeypatch):
    runner = Mock(return_value=SimpleNamespace(returncode=0, stdout="dark"))
    result = detect_system_theme({}, "darwin", Mock(), runner)
    assert result == "dark"
    runner.assert_called_once()


def test_detect_system_theme_macos_light_when_command_fails():
    runner = Mock(side_effect=RuntimeError("failure"))
    result = detect_system_theme({}, "darwin", Mock(), runner)
    assert result == "light"


@pytest.mark.parametrize(
    "env,expected",
    [({"GTK_THEME": "Adwaita-dark"}, "dark"), ({}, "light")],
)
def test_detect_system_theme_linux(env, expected):
    result = detect_system_theme(env, "linux", Mock(), Mock())
    assert result == expected


def test_apply_theme_updates_widgets():
    style = Mock()
    root = Mock()
    drop_zone = Mock()
    log_text = Mock()
    status_label = Mock()
    slider = Mock()
    apply_status = Mock()

    result = apply_theme(
        style,
        LIGHT_THEME,
        {
            "root": root,
            "drop_zone": drop_zone,
            "log_text": log_text,
            "status_label": status_label,
            "sliders": [slider],
            "tk": SimpleNamespace(FLAT="flat"),
            "apply_status_style": apply_status,
            "status_state": "idle",
        },
    )

    assert result is LIGHT_THEME
    style.theme_use.assert_called_once_with("clam")
    root.configure.assert_called_once_with(bg=LIGHT_THEME["background"])
    drop_zone.configure.assert_called_once_with(
        bg=LIGHT_THEME["surface"], fg=LIGHT_THEME["foreground"], highlightthickness=0
    )
    slider.configure.assert_called_once_with(
        background=LIGHT_THEME["border"],
        troughcolor=LIGHT_THEME["surface"],
        activebackground=LIGHT_THEME["border"],
        sliderrelief="flat",
        bd=0,
    )
    log_text.configure.assert_called_once()
    status_label.configure.assert_called_once_with(bg=LIGHT_THEME["background"])
    apply_status.assert_called_once_with("idle")
    style.configure.assert_any_call(
        "Idle.Horizontal.TProgressbar",
        background=STATUS_COLORS["idle"],
        troughcolor=LIGHT_THEME["surface"],
        borderwidth=0,
        thickness=20,
    )
