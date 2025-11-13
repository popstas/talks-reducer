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


class VarStub:
    def __init__(self, *, value):
        self._value = value
        self.trace_calls: list[tuple[str, object]] = []

    def get(self):
        return self._value

    def set(self, value):
        self._value = value

    def trace_add(self, mode: str, callback):
        self.trace_calls.append((mode, callback))


class StringVarStub(VarStub):
    def __init__(self, value: str = ""):
        super().__init__(value=str(value))

    def set(self, value):
        super().set(str(value))


class DoubleVarStub(VarStub):
    def __init__(self, value: float = 0.0):
        super().__init__(value=float(value))

    def set(self, value):
        super().set(float(value))


class BooleanVarStub(VarStub):
    def __init__(self, value: bool = False):
        super().__init__(value=bool(value))

    def set(self, value):
        super().set(bool(value))


class WidgetStub:
    def __init__(self, widget_type: str, *, args: tuple, kwargs: dict):
        self.widget_type = widget_type
        self.args = args
        self.kwargs = kwargs
        self.grid_calls: list[tuple[tuple, dict]] = []
        self.grid_remove_calls: list[None] = []
        self.pack_calls: list[tuple[tuple, dict]] = []
        self.pack_forget_calls: list[None] = []
        self.configure_calls: list[tuple[tuple, dict]] = []
        self.bind_calls: list[tuple[str, object]] = []
        self.columnconfigure_calls: list[tuple[int, dict]] = []
        self.rowconfigure_calls: list[tuple[int, dict]] = []
        self.yview_calls: list[tuple[tuple, dict]] = []
        self.set_calls: list[tuple[tuple, dict]] = []
        self.focused = False

    def grid(self, *args, **kwargs):
        self.grid_calls.append((args, kwargs))
        return self

    def grid_remove(self):
        self.grid_remove_calls.append(None)

    def pack(self, *args, **kwargs):
        self.pack_calls.append((args, kwargs))
        return self

    def pack_forget(self):
        self.pack_forget_calls.append(None)

    def configure(self, *args, **kwargs):
        self.configure_calls.append((args, kwargs))

    def bind(self, sequence, callback):
        self.bind_calls.append((sequence, callback))

    def columnconfigure(self, index: int, **kwargs):
        self.columnconfigure_calls.append((index, kwargs))

    def rowconfigure(self, index: int, **kwargs):
        self.rowconfigure_calls.append((index, kwargs))

    def focus_set(self):
        self.focused = True

    def yview(self, *args, **kwargs):
        self.yview_calls.append((args, kwargs))

    def set(self, *args, **kwargs):
        self.set_calls.append((args, kwargs))


class WidgetFactory:
    def __init__(self, widget_type: str):
        self.widget_type = widget_type
        self.created: list[WidgetStub] = []

    def __call__(self, *args, **kwargs):
        widget = WidgetStub(self.widget_type, args=args, kwargs=kwargs)
        self.created.append(widget)
        return widget


class RootStub:
    def __init__(self):
        self.columnconfigure_calls: list[tuple[int, dict]] = []
        self.rowconfigure_calls: list[tuple[int, dict]] = []
        self.update_idletasks_calls = 0
        self.minsize_calls: list[tuple[int, int]] = []
        self.geometry_calls: list[str] = []

    def columnconfigure(self, index: int, **kwargs):
        self.columnconfigure_calls.append((index, kwargs))

    def rowconfigure(self, index: int, **kwargs):
        self.rowconfigure_calls.append((index, kwargs))

    def update_idletasks(self):
        self.update_idletasks_calls += 1

    def minsize(self, width: int, height: int):
        self.minsize_calls.append((width, height))

    def geometry(self, spec: str):
        self.geometry_calls.append(spec)

    def winfo_width(self) -> int:
        return 0

    def winfo_height(self) -> int:
        return 0


def make_widget_mock() -> Mock:
    widget = Mock()
    widget.grid = Mock()
    widget.grid_remove = Mock()
    widget.pack = Mock()
    widget.pack_forget = Mock()
    widget.configure = Mock()
    return widget


def test_build_layout_initializes_widgets(monkeypatch):
    add_slider_mock = Mock()
    add_entry_mock = Mock()
    update_reset_mock = Mock()
    monkeypatch.setattr(layout, "add_slider", add_slider_mock)
    monkeypatch.setattr(layout, "add_entry", add_entry_mock)
    monkeypatch.setattr(layout, "update_basic_reset_state", update_reset_mock)

    temp_path = Path("/tmp/mock-temp")
    monkeypatch.setattr(layout, "default_temp_folder", lambda: temp_path)

    ttk = SimpleNamespace(
        Frame=WidgetFactory("Frame"),
        Checkbutton=WidgetFactory("Checkbutton"),
        Label=WidgetFactory("Label"),
        Button=WidgetFactory("Button"),
        Labelframe=WidgetFactory("Labelframe"),
        Entry=WidgetFactory("Entry"),
        Radiobutton=WidgetFactory("Radiobutton"),
        Progressbar=WidgetFactory("Progressbar"),
        Scrollbar=WidgetFactory("Scrollbar"),
        Combobox=WidgetFactory("Combobox"),
    )
    tk = SimpleNamespace(
        Label=WidgetFactory("Label"),
        Text=WidgetFactory("Text"),
        StringVar=StringVarStub,
        DoubleVar=DoubleVarStub,
        BooleanVar=BooleanVarStub,
        Scale=WidgetFactory("Scale"),
        FLAT="flat",
        LEFT="left",
        NORMAL="normal",
        DISABLED="disabled",
        HORIZONTAL="horizontal",
        VERTICAL="vertical",
    )

    preferences = SimpleNamespace(
        get_float=lambda key, default: default,
        get=lambda key, default: default,
        update=Mock(),
    )

    configure_drop_targets = Mock()
    on_drop_zone_click = Mock()
    toggle_simple_mode = Mock()
    reset_basic_defaults = Mock()
    start_discovery = Mock()
    refresh_theme = Mock()
    toggle_advanced = Mock()
    update_processing_mode_state = Mock()
    stop_processing = Mock()
    open_last_output = Mock()

    gui = SimpleNamespace(
        root=RootStub(),
        ttk=ttk,
        tk=tk,
        PADDING=8,
        _configure_drop_targets=configure_drop_targets,
        _on_drop_zone_click=on_drop_zone_click,
        _toggle_simple_mode=toggle_simple_mode,
        _reset_basic_defaults=reset_basic_defaults,
        _apply_basic_preset=Mock(),
        _start_discovery=start_discovery,
        _refresh_theme=refresh_theme,
        _toggle_advanced=toggle_advanced,
        _update_processing_mode_state=update_processing_mode_state,
        _stop_processing=stop_processing,
        _open_last_output=open_last_output,
        small_var=BooleanVarStub(value=True),
        small_480_var=BooleanVarStub(value=False),
        optimize_var=BooleanVarStub(value=True),
        open_after_convert_var=BooleanVarStub(value=False),
        simple_mode_var=BooleanVarStub(value=False),
        preferences=preferences,
        processing_mode_var=StringVarStub(value="local"),
        server_url_var=StringVarStub(value=""),
        theme_var=StringVarStub(value="os"),
        status_var=StringVarStub(value="Idle"),
        progress_var=DoubleVarStub(value=0.0),
        video_codec_var=StringVarStub(value="hevc"),
        add_codec_suffix_var=BooleanVarStub(value=False),
        use_global_ffmpeg_var=BooleanVarStub(value=False),
        global_ffmpeg_available=True,
    )

    layout.build_layout(gui)

    assert isinstance(gui.drop_zone, WidgetStub)
    assert any(
        kwargs == {"cursor": "hand2", "takefocus": 1}
        for _, kwargs in gui.drop_zone.configure_calls
    )
    assert {event for event, _ in gui.drop_zone.bind_calls} == {
        "<Button-1>",
        "<Return>",
        "<space>",
    }
    assert all(
        callback is on_drop_zone_click for _, callback in gui.drop_zone.bind_calls
    )
    configure_drop_targets.assert_any_call(gui.drop_zone)

    assert isinstance(gui.advanced_button, WidgetStub)
    assert gui.advanced_button.kwargs["command"] is toggle_advanced
    toggle_advanced.assert_any_call(initial=True)
    assert gui.advanced_visible.get() is False

    assert isinstance(gui.temp_var, StringVarStub)
    assert gui.temp_var.get() == str(temp_path)
    update_processing_mode_state.assert_called_once_with()
    update_reset_mock.assert_called_once_with(gui)

    configure_drop_targets.assert_any_call(gui.drop_hint_button)
    assert gui.drop_hint_button.grid_remove_calls

    assert hasattr(gui, "video_codec_buttons")
    assert set(gui.video_codec_buttons) == {"h264", "hevc", "av1"}
    for value, button in gui.video_codec_buttons.items():
        assert button.kwargs["variable"] is gui.video_codec_var
        assert button.kwargs["value"] == value
    assert gui.video_codec_var.get() == "hevc"
    assert hasattr(gui, "add_codec_suffix_check")
    assert gui.add_codec_suffix_check.kwargs["variable"] is gui.add_codec_suffix_var
    assert hasattr(gui, "use_global_ffmpeg_check")
    assert gui.use_global_ffmpeg_check.kwargs["variable"] is gui.use_global_ffmpeg_var
    assert gui.use_global_ffmpeg_check.kwargs["state"] == "normal"


def test_build_layout_disables_global_ffmpeg_when_unavailable(monkeypatch):
    monkeypatch.setattr(layout, "add_slider", Mock())
    monkeypatch.setattr(layout, "add_entry", Mock())
    monkeypatch.setattr(layout, "update_basic_reset_state", Mock())
    monkeypatch.setattr(layout, "default_temp_folder", lambda: Path("/tmp/mock"))

    ttk = SimpleNamespace(
        Frame=WidgetFactory("Frame"),
        Checkbutton=WidgetFactory("Checkbutton"),
        Label=WidgetFactory("Label"),
        Button=WidgetFactory("Button"),
        Labelframe=WidgetFactory("Labelframe"),
        Entry=WidgetFactory("Entry"),
        Radiobutton=WidgetFactory("Radiobutton"),
        Progressbar=WidgetFactory("Progressbar"),
        Scrollbar=WidgetFactory("Scrollbar"),
        Combobox=WidgetFactory("Combobox"),
    )
    tk = SimpleNamespace(
        Label=WidgetFactory("Label"),
        Text=WidgetFactory("Text"),
        StringVar=StringVarStub,
        DoubleVar=DoubleVarStub,
        BooleanVar=BooleanVarStub,
        Scale=WidgetFactory("Scale"),
        FLAT="flat",
        LEFT="left",
        NORMAL="normal",
        DISABLED="disabled",
        HORIZONTAL="horizontal",
        VERTICAL="vertical",
    )

    gui = SimpleNamespace(
        root=RootStub(),
        ttk=ttk,
        tk=tk,
        PADDING=8,
        _configure_drop_targets=Mock(),
        _on_drop_zone_click=Mock(),
        _toggle_simple_mode=Mock(),
        _reset_basic_defaults=Mock(),
        _apply_basic_preset=Mock(),
        _start_discovery=Mock(),
        _refresh_theme=Mock(),
        _toggle_advanced=Mock(),
        _update_processing_mode_state=Mock(),
        _stop_processing=Mock(),
        _open_last_output=Mock(),
        small_var=BooleanVarStub(value=True),
        small_480_var=BooleanVarStub(value=False),
        optimize_var=BooleanVarStub(value=True),
        open_after_convert_var=BooleanVarStub(value=False),
        simple_mode_var=BooleanVarStub(value=False),
        preferences=SimpleNamespace(
            get_float=lambda key, default: default,
            get=lambda key, default: default,
            update=Mock(),
        ),
        processing_mode_var=StringVarStub(value="local"),
        server_url_var=StringVarStub(value=""),
        theme_var=StringVarStub(value="os"),
        status_var=StringVarStub(value="Idle"),
        progress_var=DoubleVarStub(value=0.0),
        video_codec_var=StringVarStub(value="hevc"),
        add_codec_suffix_var=BooleanVarStub(value=False),
        use_global_ffmpeg_var=BooleanVarStub(value=True),
        global_ffmpeg_available=False,
    )

    layout.build_layout(gui)

    assert gui.use_global_ffmpeg_var.get() is False
    assert gui.use_global_ffmpeg_check.kwargs["state"] == "disabled"


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

    variable = DummyVar(5.0)
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
        default_value=5.0,
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
    assert gui._basic_defaults["silent_speed"] == 5.0
    assert gui._basic_variables["silent_speed"] is variable
    assert "silent_speed" in gui._slider_updaters
    assert variable.traces and variable.traces[0][0] == "write"

    value_label.configure.assert_called_with(text="5.0×")
    preferences.update.assert_called_with("silent_speed", 5.0)
    update_state.assert_called()

    preferences.update.reset_mock()
    layout_update = gui._slider_updaters["silent_speed"]
    layout_update("9.949")
    assert pytest.approx(variable.get(), rel=1e-9) == 10.0
    preferences.update.assert_called_with("silent_speed", 10.0)
    assert value_label.configure.call_args_list[-1].kwargs["text"] == "10.0×"


def test_update_basic_reset_state_updates_state_and_highlight():
    silent_var = DummyVar(5.0)
    sounded_var = DummyVar(1.0)
    threshold_var = DummyVar(0.01)
    defaults_button = make_widget_mock()
    compress_button = make_widget_mock()
    silence_button = make_widget_mock()
    gui = SimpleNamespace(
        _basic_defaults={
            "silent_speed": 5.0,
            "sounded_speed": 1.0,
            "silent_threshold": 0.01,
        },
        _basic_variables={
            "silent_speed": silent_var,
            "sounded_speed": sounded_var,
            "silent_threshold": threshold_var,
        },
        reset_basic_button=defaults_button,
        basic_preset_buttons={
            "compress_only": compress_button,
            "defaults": defaults_button,
            "silence_x10": silence_button,
        },
        tk=SimpleNamespace(NORMAL="normal", DISABLED="disabled"),
    )

    layout.update_basic_reset_state(gui)

    assert any(
        call.kwargs == {"state": "disabled"}
        for call in defaults_button.configure.call_args_list
    )
    assert any(
        call.kwargs == {"style": "SelectedLink.TButton"}
        for call in defaults_button.configure.call_args_list
    )
    assert any(
        call.kwargs == {"style": "Link.TButton"}
        for call in compress_button.configure.call_args_list
    )
    assert gui._active_basic_preset == "defaults"

    defaults_button.configure.reset_mock()
    compress_button.configure.reset_mock()
    silence_button.configure.reset_mock()

    silent_var.set(2.0)
    layout.update_basic_reset_state(gui)

    assert defaults_button.configure.call_args_list[0].kwargs == {"state": "normal"}
    assert all(
        call.kwargs == {"style": "Link.TButton"}
        for call in defaults_button.configure.call_args_list[1:]
    )
    assert any(
        call.kwargs == {"style": "Link.TButton"}
        for call in compress_button.configure.call_args_list
    )
    assert any(
        call.kwargs == {"style": "Link.TButton"}
        for call in silence_button.configure.call_args_list
    )
    assert gui._active_basic_preset is None


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


def test_apply_basic_preset_updates_values(monkeypatch):
    update_state = Mock()
    monkeypatch.setattr(layout, "update_basic_reset_state", update_state)

    silent_var = DummyVar(2.5)
    sounded_var = DummyVar(0.8)
    threshold_var = DummyVar(0.2)

    def silent_updater(value: str) -> None:
        silent_var.set(float(value))

    def sounded_updater(value: str) -> None:
        sounded_var.set(float(value))

    preferences = SimpleNamespace(update=Mock())
    gui = SimpleNamespace(
        _basic_variables={
            "silent_speed": silent_var,
            "sounded_speed": sounded_var,
            "silent_threshold": threshold_var,
        },
        _slider_updaters={
            "silent_speed": silent_updater,
            "sounded_speed": sounded_updater,
        },
        preferences=preferences,
    )

    layout.apply_basic_preset(gui, "silence_x10")
    assert silent_var.get() == pytest.approx(10.0)
    assert sounded_var.get() == pytest.approx(1.0)
    preferences.update.assert_called_with("silent_threshold", 0.01)

    layout.apply_basic_preset(gui, "compress_only")
    assert silent_var.get() == pytest.approx(1.0)
    assert sounded_var.get() == pytest.approx(1.0)
    update_state.assert_called()


def test_update_basic_preset_highlight_selects_active_button():
    silent_var = DummyVar(10.0)
    sounded_var = DummyVar(1.0)
    threshold_var = DummyVar(0.01)

    compress_button = make_widget_mock()
    defaults_button = make_widget_mock()
    silence_button = make_widget_mock()

    gui = SimpleNamespace(
        _basic_variables={
            "silent_speed": silent_var,
            "sounded_speed": sounded_var,
            "silent_threshold": threshold_var,
        },
        basic_preset_buttons={
            "compress_only": compress_button,
            "defaults": defaults_button,
            "silence_x10": silence_button,
        },
    )

    layout.update_basic_preset_highlight(gui)

    assert gui._active_basic_preset == "silence_x10"
    assert any(
        call.kwargs == {"style": "SelectedLink.TButton"}
        for call in silence_button.configure.call_args_list
    )
    assert all(
        call.kwargs == {"style": "Link.TButton"}
        for call in compress_button.configure.call_args_list
    )
    assert all(
        call.kwargs == {"style": "Link.TButton"}
        for call in defaults_button.configure.call_args_list
    )


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
