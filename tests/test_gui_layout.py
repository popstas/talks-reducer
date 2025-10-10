from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import talks_reducer.gui.layout as layout


class DummyVar:
    def __init__(self, value: float):
        self._value = value
        self.set_calls: list[float] = []
        self.traces: list[tuple[str, object]] = []

    def get(self) -> float:
        return self._value

    def set(self, value: float) -> None:
        self._value = value
        self.set_calls.append(value)

    def trace_add(self, mode: str, callback):
        self.traces.append((mode, callback))


def make_widget_mock() -> Mock:
    widget = Mock()
    widget.grid = Mock()
    widget.grid_remove = Mock()
    widget.pack = Mock()
    widget.pack_forget = Mock()
    widget.configure = Mock()
    return widget


def test_add_entry_with_browse(monkeypatch):
    label_widget = Mock()
    entry_widget = Mock()
    button_widget = Mock()

    ttk = SimpleNamespace(
        Label=Mock(return_value=label_widget),
        Entry=Mock(return_value=entry_widget),
        Button=Mock(return_value=button_widget),
    )
    gui = SimpleNamespace(ttk=ttk, _browse_path=Mock())

    parent = Mock()
    variable = Mock()

    layout.add_entry(gui, parent, "Output", variable, row=3, browse=True)

    ttk.Label.assert_called_once_with(parent, text="Output")
    label_widget.grid.assert_called_once_with(row=3, column=0, sticky="w", pady=4)

    ttk.Entry.assert_called_once_with(parent, textvariable=variable)
    entry_widget.grid.assert_called_once_with(row=3, column=1, sticky="ew", pady=4)

    ttk.Button.assert_called_once()
    assert ttk.Button.call_args.kwargs["text"] == "Browse"
    command = ttk.Button.call_args.kwargs["command"]
    command()
    gui._browse_path.assert_called_once_with(variable, "Output")
    button_widget.grid.assert_called_once_with(row=3, column=2, padx=(8, 0))


def test_add_entry_without_browse():
    label_widget = Mock()
    entry_widget = Mock()

    ttk = SimpleNamespace(
        Label=Mock(return_value=label_widget),
        Entry=Mock(return_value=entry_widget),
        Button=Mock(),
    )
    gui = SimpleNamespace(ttk=ttk, _browse_path=Mock())

    layout.add_entry(gui, Mock(), "Temp", Mock(), row=1, browse=False)

    ttk.Button.assert_not_called()


def test_add_slider_quantizes_and_updates_preferences(monkeypatch):
    update_state = Mock()
    monkeypatch.setattr(layout, "update_basic_reset_state", update_state)

    main_label = Mock()
    value_label = Mock()
    slider_widget = Mock()

    ttk_label = Mock(side_effect=[main_label, value_label])
    ttk = SimpleNamespace(Label=ttk_label)
    tk = SimpleNamespace(
        Scale=Mock(return_value=slider_widget), HORIZONTAL="horizontal"
    )
    preferences = SimpleNamespace(update=Mock())

    gui = SimpleNamespace(
        ttk=ttk,
        tk=tk,
        preferences=preferences,
        _slider_updaters={},
        _basic_defaults={},
        _basic_variables={},
        _sliders=[],
    )

    variable = DummyVar(4.0)
    parent = Mock()

    layout.add_slider(
        gui,
        parent,
        "Silent speed",
        variable,
        row=0,
        setting_key="silent_speed",
        minimum=1.0,
        maximum=10.0,
        resolution=0.5,
        display_format="{:.1f}×",
        default_value=4.0,
    )

    ttk_label.assert_has_calls(
        [
            ((parent,), {"text": "Silent speed"}),
            ((parent,), {}),
        ]
    )
    main_label.grid.assert_called_once_with(row=0, column=0, sticky="w", pady=4)
    value_label.grid.assert_called_once_with(row=0, column=2, sticky="e", pady=4)

    slider_widget.grid.assert_called_once_with(
        row=0, column=1, sticky="ew", pady=4, padx=(0, 8)
    )
    assert gui._sliders == [slider_widget]
    assert gui._basic_defaults["silent_speed"] == 4.0
    assert gui._basic_variables["silent_speed"] is variable
    assert "silent_speed" in gui._slider_updaters
    assert variable.traces and variable.traces[0][0] == "write"

    value_label.configure.assert_called_with(text="4.0×")
    preferences.update.assert_called_with("silent_speed", 4.0)
    update_state.assert_called()

    preferences.update.reset_mock()
    layout_update = gui._slider_updaters["silent_speed"]
    layout_update("9.949")
    assert pytest.approx(variable.get(), rel=1e-9) == 10.0
    preferences.update.assert_called_with("silent_speed", 10.0)
    assert value_label.configure.call_args_list[-1].kwargs["text"] == "10.0×"


def test_update_basic_reset_state_toggles_visibility():
    variable = DummyVar(1.0)
    button = make_widget_mock()
    gui = SimpleNamespace(
        _basic_defaults={"speed": 1.0},
        _basic_variables={"speed": variable},
        _reset_button_visible=False,
        reset_basic_button=button,
        tk=SimpleNamespace(LEFT="left", NORMAL="normal", DISABLED="disabled"),
    )

    layout.update_basic_reset_state(gui)
    button.pack.assert_not_called()
    button.configure.assert_called_with(state="disabled")

    variable.set(2.0)
    layout.update_basic_reset_state(gui)
    button.pack.assert_called_once_with(side="left", padx=(8, 0))
    assert gui._reset_button_visible is True
    assert button.configure.call_args_list[-1].kwargs == {"state": "normal"}


def test_reset_basic_defaults_updates_variables(monkeypatch):
    update_state = Mock()
    monkeypatch.setattr(layout, "update_basic_reset_state", update_state)

    first = DummyVar(2.0)
    second = DummyVar(4.0)
    third = DummyVar(3.0)
    updater_calls: list[str] = []

    def updater(value: str) -> None:
        updater_calls.append(value)

    preferences = SimpleNamespace(update=Mock())
    gui = SimpleNamespace(
        _basic_defaults={"first": 1.5, "second": 3.0, "third": 3.0},
        _basic_variables={"first": first, "second": second, "third": third},
        _slider_updaters={"first": updater},
        preferences=preferences,
    )

    layout.reset_basic_defaults(gui)

    assert first.get() == pytest.approx(1.5)
    assert updater_calls == ["1.5"]

    preferences.update.assert_called_once_with("second", 3.0)
    assert second.get() == pytest.approx(3.0)
    assert third.get() == pytest.approx(3.0)
    update_state.assert_called_once()


def test_apply_window_icon_prefers_windows_ico(monkeypatch):
    icon_path = Path("C:/app.ico")
    monkeypatch.setattr(layout, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(layout, "find_icon_path", Mock(return_value=icon_path))

    gui = SimpleNamespace(
        root=Mock(),
        tk=SimpleNamespace(PhotoImage=Mock(), TclError=Exception),
    )

    layout.apply_window_icon(gui)
    gui.root.iconbitmap.assert_called_once_with(str(icon_path))
    gui.root.iconphoto.assert_not_called()


def test_apply_window_icon_uses_photoimage_for_png(monkeypatch):
    icon_path = Path("/tmp/app.png")
    monkeypatch.setattr(layout, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(layout, "find_icon_path", Mock(return_value=icon_path))

    photo_image = Mock()
    tk = SimpleNamespace(PhotoImage=Mock(return_value=photo_image), TclError=Exception)
    gui = SimpleNamespace(root=Mock(), tk=tk)

    layout.apply_window_icon(gui)

    tk.PhotoImage.assert_called_once_with(file=str(icon_path))
    gui.root.iconphoto.assert_called_once_with(False, photo_image)


def test_apply_window_icon_no_path_noop(monkeypatch):
    monkeypatch.setattr(layout, "find_icon_path", Mock(return_value=None))
    monkeypatch.setattr(layout, "sys", SimpleNamespace(platform="linux"))

    gui = SimpleNamespace(
        root=Mock(), tk=SimpleNamespace(PhotoImage=Mock(), TclError=Exception)
    )
    layout.apply_window_icon(gui)

    gui.root.iconphoto.assert_not_called()
    gui.root.iconbitmap.assert_not_called()


def test_apply_window_size_simple_sets_geometry():
    root = Mock()
    gui = SimpleNamespace(
        root=root,
        _simple_size=(320, 240),
        _full_size=(800, 600),
    )

    layout.apply_window_size(gui, simple=True)

    root.update_idletasks.assert_called_once()
    root.minsize.assert_called_once_with(320, 240)
    root.geometry.assert_called_once_with("320x240")


def test_apply_window_size_full_only_expands():
    root = Mock()
    root.winfo_width.return_value = 400
    root.winfo_height.return_value = 500
    gui = SimpleNamespace(
        root=root,
        _simple_size=(320, 240),
        _full_size=(800, 600),
    )

    layout.apply_window_size(gui, simple=False)

    root.update_idletasks.assert_called_once()
    root.minsize.assert_called_once_with(800, 600)
    root.geometry.assert_called_once_with("800x600")

    root.geometry.reset_mock()
    root.winfo_width.return_value = 900
    root.winfo_height.return_value = 700

    layout.apply_window_size(gui, simple=False)
    root.geometry.assert_not_called()


def test_apply_simple_mode_simple_branch(monkeypatch):
    apply_size = Mock()
    monkeypatch.setattr(layout, "apply_window_size", apply_size)

    gui = SimpleNamespace(
        simple_mode_var=SimpleNamespace(get=lambda: True),
        basic_options_frame=make_widget_mock(),
        log_frame=make_widget_mock(),
        advanced_button=make_widget_mock(),
        advanced_frame=make_widget_mock(),
        run_after_drop_var=SimpleNamespace(set=Mock()),
        advanced_visible=SimpleNamespace(get=lambda: False),
        drop_zone=Mock(),
    )

    layout.apply_simple_mode(gui, initial=True)

    gui.basic_options_frame.grid_remove.assert_called_once()
    gui.log_frame.grid_remove.assert_called_once()
    gui.advanced_button.grid_remove.assert_called_once()
    gui.advanced_frame.grid_remove.assert_called_once()
    gui.run_after_drop_var.set.assert_called_once_with(True)
    apply_size.assert_called_once_with(gui, simple=True)
    gui.drop_zone.focus_set.assert_called_once()


def test_apply_simple_mode_full_branch(monkeypatch):
    apply_size = Mock()
    monkeypatch.setattr(layout, "apply_window_size", apply_size)

    gui = SimpleNamespace(
        simple_mode_var=SimpleNamespace(get=lambda: False),
        basic_options_frame=make_widget_mock(),
        log_frame=make_widget_mock(),
        advanced_button=make_widget_mock(),
        advanced_frame=make_widget_mock(),
        run_after_drop_var=SimpleNamespace(set=Mock()),
        advanced_visible=SimpleNamespace(get=lambda: True),
        drop_zone=Mock(),
    )

    layout.apply_simple_mode(gui)

    gui.basic_options_frame.grid.assert_called_once()
    gui.log_frame.grid.assert_called_once()
    gui.advanced_button.grid.assert_called_once()
    gui.advanced_frame.grid.assert_called_once()
    apply_size.assert_called_once_with(gui, simple=False)
    gui.run_after_drop_var.set.assert_not_called()


def test_apply_simple_mode_full_branch_hides_advanced_when_not_visible(monkeypatch):
    apply_size = Mock()
    monkeypatch.setattr(layout, "apply_window_size", apply_size)

    gui = SimpleNamespace(
        simple_mode_var=SimpleNamespace(get=lambda: False),
        basic_options_frame=make_widget_mock(),
        log_frame=make_widget_mock(),
        advanced_button=make_widget_mock(),
        advanced_frame=make_widget_mock(),
        run_after_drop_var=SimpleNamespace(set=Mock()),
        advanced_visible=SimpleNamespace(get=lambda: False),
        drop_zone=Mock(),
    )

    layout.apply_simple_mode(gui)

    gui.advanced_frame.grid.assert_not_called()
    apply_size.assert_called_once_with(gui, simple=False)
