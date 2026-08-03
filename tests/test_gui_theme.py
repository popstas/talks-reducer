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


def _configured_styles(style: Mock) -> dict[str, dict]:
    """Map style name to kwargs for every ``style.configure(name, **kwargs)`` call."""

    return {
        call.args[0]: call.kwargs
        for call in style.configure.call_args_list
        if call.args
    }


def _mapped_styles(style: Mock) -> dict[str, dict]:
    """Map style name to kwargs for every ``style.map(name, **kwargs)`` call."""

    return {call.args[0]: call.kwargs for call in style.map.call_args_list if call.args}


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
    activity_text = Mock()
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
            "activity_text": activity_text,
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
    # The Connected clients panel is themed identically to the log area.
    activity_text.configure.assert_called_once_with(
        bg=LIGHT_THEME["surface"],
        fg=LIGHT_THEME["foreground"],
        insertbackground=LIGHT_THEME["foreground"],
        highlightbackground=LIGHT_THEME["border"],
        highlightcolor=LIGHT_THEME["border"],
    )
    status_label.configure.assert_called_once_with(bg=LIGHT_THEME["background"])
    apply_status.assert_called_once_with("idle")
    style.configure.assert_any_call(
        "Idle.Horizontal.TProgressbar",
        background=STATUS_COLORS["idle"],
        troughcolor=LIGHT_THEME["surface"],
        borderwidth=0,
        thickness=20,
    )


def test_segment_styles_are_configured():
    style = Mock()
    apply_theme(
        style,
        LIGHT_THEME,
        {
            "root": Mock(),
            "drop_zone": Mock(),
            "log_text": Mock(),
            "activity_text": Mock(),
            "status_label": Mock(),
            "sliders": [Mock()],
            "tk": SimpleNamespace(FLAT="flat"),
            "apply_status_style": Mock(),
            "status_state": "idle",
        },
    )

    configured = _configured_styles(style)
    assert "Segment.TButton" in configured
    assert "SelectedSegment.TButton" in configured
    assert (
        configured["SelectedSegment.TButton"]["background"]
        != configured["Segment.TButton"]["background"]
    )

    # A disabled Segment.TButton (e.g. the Remote mode button before a server
    # URL is set) must not look identical to an enabled one: the ``disabled``
    # foreground has to differ from the normal (enabled) foreground, or the
    # button silently does nothing with no visual cue that it is unavailable.
    mapped = _mapped_styles(style)
    assert "Segment.TButton" in mapped
    disabled_foreground = dict(mapped["Segment.TButton"]["foreground"])["disabled"]
    assert disabled_foreground != configured["Segment.TButton"]["foreground"]
