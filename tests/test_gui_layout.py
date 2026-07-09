from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import talks_reducer.gui.layout as layout
from talks_reducer.presets import Preset

_TEST_PRESETS = [
    Preset(
        name="720p 10x speedup H.264",
        resolution="720p",
        silent_speed=10.0,
        sounded_speed=1.0,
        silent_threshold=0.01,
        video_codec="h264",
    ),
    Preset(
        name="480p 10x speedup H.265",
        resolution="480p",
        silent_speed=10.0,
        sounded_speed=1.0,
        silent_threshold=0.01,
        video_codec="hevc",
    ),
]


@pytest.fixture(autouse=True)
def _stub_preset_store(monkeypatch):
    """Keep ``build_layout`` from touching the real ``settings.json`` on disk.

    Individual tests override ``load_presets`` when they need a different list.
    """

    monkeypatch.setattr(
        layout.presets, "load_presets", lambda *a, **k: list(_TEST_PRESETS)
    )
    monkeypatch.setattr(layout.presets, "set_selected_preset", lambda *a, **k: True)
    monkeypatch.setattr(layout.presets, "get_selected_preset", lambda *a, **k: None)


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


def _make_layout_gui(**overrides) -> SimpleNamespace:
    """Build a fully-populated stub GUI namespace for ``build_layout`` tests."""

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
        RIGHT="right",
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
        _toggle_cut_panel=Mock(),
        _on_cut_slider_change=Mock(),
        _on_cut_entry_commit=Mock(),
        _update_cut_convert_button=Mock(),
        _start_run=Mock(),
        _update_processing_mode_state=Mock(),
        _stop_processing=Mock(),
        _open_last_output=Mock(),
        _check_for_updates=Mock(),
        _open_save_preset_dialog=Mock(),
        _update_selected_preset=Mock(),
        _delete_selected_preset=Mock(),
        _move_selected_preset_up=Mock(),
        _move_selected_preset_down=Mock(),
        small_var=BooleanVarStub(value=True),
        small_480_var=BooleanVarStub(value=False),
        optimize_var=BooleanVarStub(value=True),
        open_after_convert_var=BooleanVarStub(value=False),
        cut_enabled_var=BooleanVarStub(value=False),
        cut_start_var=DoubleVarStub(value=0.0),
        cut_end_var=DoubleVarStub(value=0.0),
        cut_start_text_var=StringVarStub(value="00:00:00.000"),
        cut_end_text_var=StringVarStub(value="00:00:00.000"),
        simple_mode_var=BooleanVarStub(value=False),
        simple_preset_var=StringVarStub(value=""),
        advanced_preset_var=StringVarStub(value=""),
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
        start_in_server_tray_var=BooleanVarStub(value=False),
        watch_enabled_var=BooleanVarStub(value=False),
        watch_directory_var=StringVarStub(value=""),
        global_ffmpeg_available=True,
    )
    for key, value in overrides.items():
        setattr(gui, key, value)
    return gui


@pytest.mark.parametrize(
    "url, expected",
    [
        (None, ""),
        ("", ""),
        ("   ", ""),
        ("http://192.168.1.5:9005/", "Server: http://192.168.1.5:9005"),
        ("http://192.168.1.5:9005", "Server: http://192.168.1.5:9005"),
    ],
)
def test_format_local_server_url(url, expected):
    assert layout.format_local_server_url(url) == expected


def test_format_activity_line_renders_clock_ip_action():
    import time

    timestamp = 1_700_000_000.0
    expected_clock = time.strftime("%H:%M:%S", time.localtime(timestamp))
    entry = {"timestamp": timestamp, "client_ip": "192.168.1.7", "action": "upload"}

    assert (
        layout.format_activity_line(entry) == f"{expected_clock}  192.168.1.7  upload"
    )


def test_format_activity_line_tolerates_missing_fields():
    line = layout.format_activity_line({})
    assert line == "--:--:--  unknown"


def test_build_layout_shows_activity_log_in_managed_mode(monkeypatch):
    monkeypatch.setattr(layout, "add_slider", Mock())
    monkeypatch.setattr(layout, "add_entry", Mock())
    monkeypatch.setattr(layout, "update_basic_reset_state", Mock())
    monkeypatch.setattr(layout, "default_temp_folder", lambda: Path("/tmp/mock"))

    gui = _make_layout_gui(server_managed=True, local_server_url="http://x:9005/")

    layout.build_layout(gui)

    assert isinstance(gui.activity_text, WidgetStub)
    assert gui.activity_frame.grid_calls
    assert not gui.activity_frame.grid_remove_calls


def test_build_layout_hides_activity_log_in_standalone_mode(monkeypatch):
    monkeypatch.setattr(layout, "add_slider", Mock())
    monkeypatch.setattr(layout, "add_entry", Mock())
    monkeypatch.setattr(layout, "update_basic_reset_state", Mock())
    monkeypatch.setattr(layout, "default_temp_folder", lambda: Path("/tmp/mock"))

    gui = _make_layout_gui(server_managed=False)

    layout.build_layout(gui)

    assert isinstance(gui.activity_text, WidgetStub)
    assert gui.activity_frame.grid_remove_calls


def test_build_layout_shows_local_server_url_in_managed_mode(monkeypatch):
    monkeypatch.setattr(layout, "add_slider", Mock())
    monkeypatch.setattr(layout, "add_entry", Mock())
    monkeypatch.setattr(layout, "update_basic_reset_state", Mock())
    monkeypatch.setattr(layout, "default_temp_folder", lambda: Path("/tmp/mock"))

    gui = _make_layout_gui(
        server_managed=True,
        local_server_url="http://192.168.1.5:9005/",
    )

    layout.build_layout(gui)

    label = gui.local_server_url_label
    assert isinstance(label, WidgetStub)
    assert label.kwargs["text"] == "Server: http://192.168.1.5:9005"
    # Visible in server mode: created with grid() and not removed.
    assert label.grid_calls
    assert not label.grid_remove_calls


def test_build_layout_hides_local_server_url_in_standalone_mode(monkeypatch):
    monkeypatch.setattr(layout, "add_slider", Mock())
    monkeypatch.setattr(layout, "add_entry", Mock())
    monkeypatch.setattr(layout, "update_basic_reset_state", Mock())
    monkeypatch.setattr(layout, "default_temp_folder", lambda: Path("/tmp/mock"))

    gui = _make_layout_gui(server_managed=False, local_server_url=None)

    layout.build_layout(gui)

    label = gui.local_server_url_label
    assert isinstance(label, WidgetStub)
    assert label.kwargs["text"] == ""
    # Hidden in standalone mode: grid_remove() called after creation.
    assert label.grid_remove_calls


def test_build_layout_creates_watch_widgets(monkeypatch):
    monkeypatch.setattr(layout, "add_slider", Mock())
    monkeypatch.setattr(layout, "add_entry", Mock())
    monkeypatch.setattr(layout, "update_basic_reset_state", Mock())
    monkeypatch.setattr(layout, "default_temp_folder", lambda: Path("/tmp/mock"))

    gui = _make_layout_gui()

    layout.build_layout(gui)

    assert hasattr(gui, "watch_button")
    assert hasattr(gui, "watch_check")
    assert hasattr(gui, "watch_directory_entry")
    assert hasattr(gui, "watch_browse_button")


def test_build_layout_adds_optimize_tooltip(monkeypatch):
    monkeypatch.setattr(layout, "add_slider", Mock())
    monkeypatch.setattr(layout, "add_entry", Mock())
    monkeypatch.setattr(layout, "update_basic_reset_state", Mock())
    monkeypatch.setattr(layout, "default_temp_folder", lambda: Path("/tmp/mock"))

    gui = _make_layout_gui()

    layout.build_layout(gui)

    bound_events = {event for event, _ in gui.optimize_check.bind_calls}
    assert "<Enter>" in bound_events
    assert "<Leave>" in bound_events


def test_build_layout_aligns_server_entry_and_discover_button(monkeypatch):
    monkeypatch.setattr(layout, "add_slider", Mock())
    monkeypatch.setattr(layout, "add_entry", Mock())
    monkeypatch.setattr(layout, "update_basic_reset_state", Mock())
    monkeypatch.setattr(layout, "default_temp_folder", lambda: Path("/tmp/mock"))

    gui = _make_layout_gui()

    layout.build_layout(gui)

    entry_grid = gui.server_entry.grid_calls[-1][1]
    button_grid = gui.server_discover_button.grid_calls[-1][1]

    # The entry and the Discover button share a row and must align vertically:
    # same top padding so their baselines match.
    assert entry_grid["row"] == button_grid["row"] == 5
    assert entry_grid["pady"] == button_grid["pady"] == (8, 0)
    assert button_grid["sticky"] == "ew"


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
        RIGHT="right",
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
        _toggle_cut_panel=Mock(),
        _on_cut_slider_change=Mock(),
        _on_cut_entry_commit=Mock(),
        _update_cut_convert_button=Mock(),
        _start_run=Mock(),
        _update_processing_mode_state=update_processing_mode_state,
        _stop_processing=stop_processing,
        _open_last_output=open_last_output,
        _check_for_updates=Mock(),
        _open_save_preset_dialog=Mock(),
        _update_selected_preset=Mock(),
        _delete_selected_preset=Mock(),
        _move_selected_preset_up=Mock(),
        _move_selected_preset_down=Mock(),
        small_var=BooleanVarStub(value=True),
        small_480_var=BooleanVarStub(value=False),
        optimize_var=BooleanVarStub(value=True),
        open_after_convert_var=BooleanVarStub(value=False),
        cut_enabled_var=BooleanVarStub(value=False),
        cut_start_var=DoubleVarStub(value=0.0),
        cut_end_var=DoubleVarStub(value=0.0),
        cut_start_text_var=StringVarStub(value="00:00:00.000"),
        cut_end_text_var=StringVarStub(value="00:00:00.000"),
        simple_mode_var=BooleanVarStub(value=False),
        simple_preset_var=StringVarStub(value=""),
        advanced_preset_var=StringVarStub(value=""),
        preferences=preferences,
        processing_mode_var=StringVarStub(value="local"),
        server_url_var=StringVarStub(value=""),
        theme_var=StringVarStub(value="os"),
        status_var=StringVarStub(value="Idle"),
        progress_var=DoubleVarStub(value=0.0),
        video_codec_var=StringVarStub(value="hevc"),
        add_codec_suffix_var=BooleanVarStub(value=False),
        use_global_ffmpeg_var=BooleanVarStub(value=False),
        start_in_server_tray_var=BooleanVarStub(value=False),
        watch_enabled_var=BooleanVarStub(value=False),
        watch_directory_var=StringVarStub(value=""),
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
    assert set(gui.video_codec_buttons) == {"h264", "hevc", "av1", "mp3"}
    for value, button in gui.video_codec_buttons.items():
        assert button.kwargs["variable"] is gui.video_codec_var
        assert button.kwargs["value"] == value
    assert gui.video_codec_var.get() == "hevc"
    assert hasattr(gui, "add_codec_suffix_check")
    assert gui.add_codec_suffix_check.kwargs["variable"] is gui.add_codec_suffix_var
    assert hasattr(gui, "use_global_ffmpeg_check")
    assert gui.use_global_ffmpeg_check.kwargs["variable"] is gui.use_global_ffmpeg_var
    assert gui.use_global_ffmpeg_check.kwargs["state"] == "normal"
    assert hasattr(gui, "start_in_server_tray_check")
    assert (
        gui.start_in_server_tray_check.kwargs["variable"]
        is gui.start_in_server_tray_var
    )


def test_build_layout_adds_macos_update_button_under_advanced(monkeypatch):
    monkeypatch.setattr(layout, "add_slider", Mock())
    monkeypatch.setattr(layout, "add_entry", Mock())
    monkeypatch.setattr(layout, "update_basic_reset_state", Mock())
    monkeypatch.setattr(layout, "default_temp_folder", lambda: Path("/tmp/mock"))
    monkeypatch.setattr(layout, "sys", SimpleNamespace(platform="darwin"))

    gui = _make_layout_gui()

    layout.build_layout(gui)

    assert isinstance(gui.check_updates_button, WidgetStub)
    assert gui.check_updates_button.kwargs["command"] is gui._check_for_updates
    assert isinstance(gui.update_status_label, WidgetStub)
    # Both widgets must live inside the Advanced panel, not the always-visible
    # button frame, so they appear under Advanced settings.
    assert gui.check_updates_button.args[0] is gui.advanced_frame
    assert gui.update_status_label.args[0] is gui.advanced_frame
    # Both must sit on row 9 (rows 0-8 are taken by existing Advanced controls:
    # the watch-directory line at row 0 pushes the rest down), so a future edit
    # that collides with another row is caught here. The status label sits in a
    # later column than the button so the two never overlap.
    assert gui.check_updates_button.grid_calls[0][1]["row"] == 9
    assert gui.update_status_label.grid_calls[0][1]["row"] == 9
    assert (
        gui.update_status_label.grid_calls[0][1]["column"]
        > gui.check_updates_button.grid_calls[0][1]["column"]
    )


def test_build_layout_omits_update_button_on_linux(monkeypatch):
    monkeypatch.setattr(layout, "add_slider", Mock())
    monkeypatch.setattr(layout, "add_entry", Mock())
    monkeypatch.setattr(layout, "update_basic_reset_state", Mock())
    monkeypatch.setattr(layout, "default_temp_folder", lambda: Path("/tmp/mock"))
    monkeypatch.setattr(layout, "sys", SimpleNamespace(platform="linux"))

    gui = _make_layout_gui()

    layout.build_layout(gui)

    assert not hasattr(gui, "check_updates_button")
    assert not hasattr(gui, "update_status_label")


def _build_layout_with_cut(monkeypatch, *, cut_enabled: bool):
    monkeypatch.setattr(layout, "add_slider", Mock())
    monkeypatch.setattr(layout, "add_entry", Mock())
    monkeypatch.setattr(layout, "update_basic_reset_state", Mock())
    monkeypatch.setattr(layout, "default_temp_folder", lambda: Path("/tmp/mock"))

    gui = _make_layout_gui(cut_enabled_var=BooleanVarStub(value=cut_enabled))
    layout.build_layout(gui)
    return gui


def test_build_cut_panel_constructs_widgets(monkeypatch):
    gui = _build_layout_with_cut(monkeypatch, cut_enabled=True)

    assert isinstance(gui.cut_check, WidgetStub)
    assert gui.cut_check.kwargs["variable"] is gui.cut_enabled_var
    assert gui.cut_check.kwargs["command"] is gui._toggle_cut_panel

    assert isinstance(gui.cut_panel, WidgetStub)
    assert isinstance(gui.cut_start_slider, WidgetStub)
    assert isinstance(gui.cut_end_slider, WidgetStub)
    assert gui.cut_start_slider.kwargs["variable"] is gui.cut_start_var
    assert gui.cut_end_slider.kwargs["variable"] is gui.cut_end_var
    # Manual-entry inputs replace the old read-only timecode labels.
    assert isinstance(gui.cut_start_entry, WidgetStub)
    assert isinstance(gui.cut_end_entry, WidgetStub)
    assert gui.cut_start_entry.kwargs["textvariable"] is gui.cut_start_text_var
    assert gui.cut_end_entry.kwargs["textvariable"] is gui.cut_end_text_var
    # The tall Convert button drives the Advanced cut workflow.
    assert isinstance(gui.cut_convert_button, WidgetStub)
    assert gui.cut_convert_button.kwargs["command"] is gui._start_run
    assert not hasattr(gui, "cut_thumbnail_label")

    # Visible because the checkbox is enabled: not hidden after creation.
    assert gui.cut_panel.grid_calls
    assert not gui.cut_panel.grid_remove_calls


def test_build_cut_panel_hidden_when_disabled(monkeypatch):
    gui = _build_layout_with_cut(monkeypatch, cut_enabled=False)

    assert isinstance(gui.cut_panel, WidgetStub)
    # Hidden because the checkbox is off: grid_remove() called after creation.
    assert gui.cut_panel.grid_remove_calls


def test_build_cut_panel_sliders_forward_to_handler(monkeypatch):
    gui = _build_layout_with_cut(monkeypatch, cut_enabled=True)

    gui.cut_start_slider.kwargs["command"]("0")
    gui.cut_end_slider.kwargs["command"]("0")

    assert gui._on_cut_slider_change.call_args_list[0].args == ("start",)
    assert gui._on_cut_slider_change.call_args_list[1].args == ("end",)


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
        RIGHT="right",
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
        _toggle_cut_panel=Mock(),
        _on_cut_slider_change=Mock(),
        _on_cut_entry_commit=Mock(),
        _update_cut_convert_button=Mock(),
        _start_run=Mock(),
        _update_processing_mode_state=Mock(),
        _stop_processing=Mock(),
        _open_last_output=Mock(),
        _check_for_updates=Mock(),
        _open_save_preset_dialog=Mock(),
        _update_selected_preset=Mock(),
        _delete_selected_preset=Mock(),
        _move_selected_preset_up=Mock(),
        _move_selected_preset_down=Mock(),
        small_var=BooleanVarStub(value=True),
        small_480_var=BooleanVarStub(value=False),
        optimize_var=BooleanVarStub(value=True),
        open_after_convert_var=BooleanVarStub(value=False),
        cut_enabled_var=BooleanVarStub(value=False),
        cut_start_var=DoubleVarStub(value=0.0),
        cut_end_var=DoubleVarStub(value=0.0),
        cut_start_text_var=StringVarStub(value="00:00:00.000"),
        cut_end_text_var=StringVarStub(value="00:00:00.000"),
        simple_mode_var=BooleanVarStub(value=False),
        simple_preset_var=StringVarStub(value=""),
        advanced_preset_var=StringVarStub(value=""),
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
        start_in_server_tray_var=BooleanVarStub(value=False),
        watch_enabled_var=BooleanVarStub(value=False),
        watch_directory_var=StringVarStub(value=""),
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
        tk=SimpleNamespace(LEFT="left", RIGHT="right"),
        simple_mode_var=SimpleNamespace(get=lambda: True),
        basic_options_frame=make_widget_mock(),
        advanced_preset_frame=make_widget_mock(),
        log_frame=make_widget_mock(),
        activity_frame=make_widget_mock(),
        server_managed=True,
        button_frame=make_widget_mock(),
        advanced_frame=make_widget_mock(),
        run_after_drop_var=SimpleNamespace(set=Mock()),
        advanced_visible=SimpleNamespace(get=lambda: False),
        _simple_presets=list(_TEST_PRESETS),
        small_check=make_widget_mock(),
        small_480_check=make_widget_mock(),
        open_output_check=make_widget_mock(),
        cut_check=make_widget_mock(),
        cut_panel=make_widget_mock(),
        cut_enabled_var=SimpleNamespace(get=lambda: True),
        drop_zone=Mock(),
    )

    layout.apply_simple_mode(gui, initial=True)

    gui.basic_options_frame.grid_remove.assert_called_once()
    # The Advanced-only preset management strip is hidden in Simple mode.
    gui.advanced_preset_frame.grid_remove.assert_called_once()
    gui.log_frame.grid_remove.assert_called_once()
    # The Connected clients panel is hidden in Simple mode even when managed.
    gui.activity_frame.grid_remove.assert_called_once()
    gui.activity_frame.grid.assert_not_called()
    gui.button_frame.grid_remove.assert_called_once()
    gui.advanced_frame.grid_remove.assert_called_once()
    gui.run_after_drop_var.set.assert_called_once_with(True)
    # With a preset available the manual resolution checkboxes are hidden so the
    # preset drives resolution.
    gui.small_check.pack_forget.assert_called_once()
    gui.small_480_check.pack_forget.assert_called_once()
    # Cut video is hidden in Simple mode regardless of the persisted flag.
    gui.cut_check.pack_forget.assert_called_once()
    gui.cut_panel.grid_remove.assert_called_once()
    apply_size.assert_called_once_with(gui, simple=True)
    gui.drop_zone.focus_set.assert_called_once()


def test_apply_simple_mode_simple_branch_keeps_checkboxes_without_presets(monkeypatch):
    """With no presets the resolution checkboxes stay visible in Simple mode."""

    apply_size = Mock()
    monkeypatch.setattr(layout, "apply_window_size", apply_size)

    gui = SimpleNamespace(
        tk=SimpleNamespace(LEFT="left", RIGHT="right"),
        simple_mode_var=SimpleNamespace(get=lambda: True),
        basic_options_frame=make_widget_mock(),
        advanced_preset_frame=make_widget_mock(),
        log_frame=make_widget_mock(),
        activity_frame=make_widget_mock(),
        server_managed=True,
        button_frame=make_widget_mock(),
        advanced_frame=make_widget_mock(),
        run_after_drop_var=SimpleNamespace(set=Mock()),
        advanced_visible=SimpleNamespace(get=lambda: False),
        _simple_presets=[],
        small_check=make_widget_mock(),
        small_480_check=make_widget_mock(),
        open_output_check=make_widget_mock(),
        cut_check=make_widget_mock(),
        cut_panel=make_widget_mock(),
        cut_enabled_var=SimpleNamespace(get=lambda: True),
        drop_zone=Mock(),
    )

    layout.apply_simple_mode(gui, initial=True)

    # The preset selector is hidden when empty, so the manual checkboxes remain
    # the only resolution control and must stay packed (not forgotten).
    gui.small_check.pack_forget.assert_not_called()
    gui.small_480_check.pack_forget.assert_not_called()
    gui.small_check.pack.assert_called_once_with(
        side="left", before=gui.open_output_check
    )
    gui.small_480_check.pack.assert_called_once_with(
        side="left", padx=(65, 0), before=gui.open_output_check
    )


def test_apply_simple_mode_full_branch(monkeypatch):
    apply_size = Mock()
    monkeypatch.setattr(layout, "apply_window_size", apply_size)

    gui = SimpleNamespace(
        simple_mode_var=SimpleNamespace(get=lambda: False),
        basic_options_frame=make_widget_mock(),
        advanced_preset_frame=make_widget_mock(),
        log_frame=make_widget_mock(),
        activity_frame=make_widget_mock(),
        server_managed=True,
        button_frame=make_widget_mock(),
        advanced_frame=make_widget_mock(),
        run_after_drop_var=SimpleNamespace(set=Mock()),
        advanced_visible=SimpleNamespace(get=lambda: True),
        small_check=make_widget_mock(),
        small_480_check=make_widget_mock(),
        open_output_check=make_widget_mock(),
        cut_check=make_widget_mock(),
        cut_panel=make_widget_mock(),
        cut_enabled_var=SimpleNamespace(get=lambda: True),
        tk=SimpleNamespace(LEFT="left", RIGHT="right"),
        drop_zone=Mock(),
    )

    layout.apply_simple_mode(gui)

    gui.basic_options_frame.grid.assert_called_once()
    # The full layout restores the Advanced preset management strip.
    gui.advanced_preset_frame.grid.assert_called_once()
    gui.log_frame.grid.assert_called_once()
    # A managed GUI restores the Connected clients panel in the full layout.
    gui.activity_frame.grid.assert_called_once()
    gui.activity_frame.grid_remove.assert_not_called()
    gui.button_frame.grid.assert_called_once()
    gui.advanced_frame.grid.assert_called_once()
    # Advanced restores the manual resolution checkboxes ahead of Open output.
    gui.small_check.pack.assert_called_once()
    gui.small_480_check.pack.assert_called_once()
    # Advanced restores the Cut video checkbox; the panel shows because cut is on.
    gui.cut_check.pack.assert_called_once()
    gui.cut_panel.grid.assert_called_once()
    apply_size.assert_called_once_with(gui, simple=False)
    gui.run_after_drop_var.set.assert_not_called()


def test_apply_simple_mode_full_branch_hides_activity_when_standalone(monkeypatch):
    apply_size = Mock()
    monkeypatch.setattr(layout, "apply_window_size", apply_size)

    gui = SimpleNamespace(
        simple_mode_var=SimpleNamespace(get=lambda: False),
        basic_options_frame=make_widget_mock(),
        log_frame=make_widget_mock(),
        activity_frame=make_widget_mock(),
        server_managed=False,
        button_frame=make_widget_mock(),
        advanced_frame=make_widget_mock(),
        run_after_drop_var=SimpleNamespace(set=Mock()),
        advanced_visible=SimpleNamespace(get=lambda: True),
        cut_check=make_widget_mock(),
        cut_panel=make_widget_mock(),
        cut_enabled_var=SimpleNamespace(get=lambda: False),
        tk=SimpleNamespace(LEFT="left", RIGHT="right"),
        drop_zone=Mock(),
    )

    layout.apply_simple_mode(gui)

    # A standalone GUI never shows the Connected clients panel.
    gui.activity_frame.grid.assert_not_called()
    gui.activity_frame.grid_remove.assert_called_once()


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


class TestParseWindowPosition:
    def test_parses_positive_offsets(self) -> None:
        assert layout.parse_window_position("1200x900+105+50") == (105, 50)

    def test_parses_negative_offsets(self) -> None:
        assert layout.parse_window_position("470x300+-5+-10") == (-5, -10)

    def test_returns_none_without_offsets(self) -> None:
        assert layout.parse_window_position("1200x900") is None

    def test_returns_none_for_garbage(self) -> None:
        assert layout.parse_window_position("not-a-geometry") is None


class TestClampWindowPosition:
    def test_keeps_fully_visible_position(self) -> None:
        assert layout.clamp_window_position((100, 80), (470, 300), (1920, 1080)) == (
            100,
            80,
        )

    def test_pulls_partially_offscreen_window_back(self) -> None:
        # Window overhangs the right/bottom edges but still overlaps the screen.
        assert layout.clamp_window_position((1900, 1050), (470, 300), (1920, 1080)) == (
            1920 - 470,
            1080 - 300,
        )

    def test_clamps_negative_position_to_origin(self) -> None:
        assert layout.clamp_window_position((-20, -15), (470, 300), (1920, 1080)) == (
            0,
            0,
        )

    def test_returns_none_when_fully_offscreen(self) -> None:
        # Saved on a monitor that is no longer connected.
        assert (
            layout.clamp_window_position((3000, 80), (470, 300), (1920, 1080)) is None
        )

    def test_returns_none_when_above_screen(self) -> None:
        assert (
            layout.clamp_window_position((100, -400), (470, 300), (1920, 1080)) is None
        )


def _make_preset_target_gui() -> SimpleNamespace:
    """Return a stub GUI exposing only the vars ``apply_preset_to_gui`` touches."""

    silent = DummyVar(5.0)
    sounded = DummyVar(1.0)
    threshold = DummyVar(0.01)
    return SimpleNamespace(
        small_var=BooleanVarStub(value=True),
        small_480_var=BooleanVarStub(value=False),
        video_codec_var=StringVarStub(value="h264"),
        silent_speed_var=silent,
        sounded_speed_var=sounded,
        silent_threshold_var=threshold,
        _slider_updaters={},
        _basic_variables={
            "silent_speed": silent,
            "sounded_speed": sounded,
            "silent_threshold": threshold,
        },
    )


def test_apply_preset_to_gui_sets_vars_for_480p():
    gui = _make_preset_target_gui()
    preset = Preset(
        name="480p 10x speedup H.265",
        resolution="480p",
        silent_speed=10.0,
        sounded_speed=1.0,
        silent_threshold=0.02,
        video_codec="hevc",
    )

    layout.apply_preset_to_gui(gui, preset)

    assert gui.small_var.get() is True
    assert gui.small_480_var.get() is True
    assert gui.silent_speed_var.get() == pytest.approx(10.0)
    assert gui.silent_threshold_var.get() == pytest.approx(0.02)
    assert gui.video_codec_var.get() == "hevc"


def test_apply_preset_to_gui_1080p_clears_small():
    gui = _make_preset_target_gui()
    preset = Preset(
        name="1080p no speedup H.264",
        resolution="1080p",
        silent_speed=1.0,
        sounded_speed=1.0,
        silent_threshold=0.01,
        video_codec="h264",
    )

    layout.apply_preset_to_gui(gui, preset)

    assert gui.small_var.get() is False
    assert gui.small_480_var.get() is False


def test_apply_preset_to_gui_prefers_slider_updaters():
    gui = _make_preset_target_gui()
    calls: list[tuple[str, str]] = []
    gui._slider_updaters = {
        "silent_speed": lambda value: calls.append(("silent_speed", value)),
    }
    preset = Preset(
        name="720p",
        resolution="720p",
        silent_speed=7.0,
        sounded_speed=1.0,
        silent_threshold=0.01,
        video_codec="h264",
    )

    layout.apply_preset_to_gui(gui, preset)

    # The slider updater is used when present so the label/preferences sync.
    assert ("silent_speed", "7.0") in calls
    assert gui.small_var.get() is True
    assert gui.small_480_var.get() is False


def test_build_layout_populates_preset_dropdown(monkeypatch):
    monkeypatch.setattr(layout, "add_slider", Mock())
    monkeypatch.setattr(layout, "add_entry", Mock())
    monkeypatch.setattr(layout, "update_basic_reset_state", Mock())
    monkeypatch.setattr(layout, "default_temp_folder", lambda: Path("/tmp/mock"))

    gui = _make_layout_gui()

    layout.build_layout(gui)

    assert isinstance(gui.simple_preset_combo, WidgetStub)
    assert gui.simple_preset_combo.kwargs["values"] == [
        preset.name for preset in _TEST_PRESETS
    ]
    # A non-empty list keeps the selector visible (no grid_remove after grid).
    assert gui.simple_preset_frame.grid_calls
    assert not gui.simple_preset_frame.grid_remove_calls


def test_build_layout_hides_preset_selector_when_empty(monkeypatch):
    monkeypatch.setattr(layout, "add_slider", Mock())
    monkeypatch.setattr(layout, "add_entry", Mock())
    monkeypatch.setattr(layout, "update_basic_reset_state", Mock())
    monkeypatch.setattr(layout, "default_temp_folder", lambda: Path("/tmp/mock"))
    monkeypatch.setattr(layout.presets, "load_presets", lambda *a, **k: [])

    gui = _make_layout_gui()

    layout.build_layout(gui)

    assert gui._simple_presets == []
    # No presets: the selector is hidden right after creation.
    assert gui.simple_preset_frame.grid_remove_calls


def test_apply_simple_preset_applies_and_persists(monkeypatch):
    persisted: list[str] = []
    monkeypatch.setattr(
        layout.presets,
        "set_selected_preset",
        lambda name, *a, **k: persisted.append(name) or True,
    )

    gui = _make_preset_target_gui()
    gui.simple_preset_var = StringVarStub(value="480p 10x speedup H.265")
    gui._simple_presets = list(_TEST_PRESETS)

    layout._apply_simple_preset(gui)

    assert gui.small_480_var.get() is True
    assert gui.video_codec_var.get() == "hevc"
    assert persisted == ["480p 10x speedup H.265"]


def test_apply_simple_preset_unknown_name_noops(monkeypatch):
    persisted: list[str] = []
    monkeypatch.setattr(
        layout.presets,
        "set_selected_preset",
        lambda name, *a, **k: persisted.append(name) or True,
    )

    gui = _make_preset_target_gui()
    gui.simple_preset_var = StringVarStub(value="does-not-exist")
    gui._simple_presets = list(_TEST_PRESETS)

    layout._apply_simple_preset(gui)

    # Unknown selection leaves the vars untouched and persists nothing.
    assert gui.small_480_var.get() is False
    assert gui.video_codec_var.get() == "h264"
    assert persisted == []


def _make_advanced_preset_gui() -> SimpleNamespace:
    """Return a stub GUI exposing the vars the Advanced strip helpers touch."""

    silent = DummyVar(10.0)
    sounded = DummyVar(1.0)
    threshold = DummyVar(0.01)
    return SimpleNamespace(
        small_var=BooleanVarStub(value=True),
        small_480_var=BooleanVarStub(value=False),
        video_codec_var=StringVarStub(value="h264"),
        silent_speed_var=silent,
        sounded_speed_var=sounded,
        silent_threshold_var=threshold,
        simple_mode_var=BooleanVarStub(value=False),
        simple_preset_var=StringVarStub(value=""),
        advanced_preset_var=StringVarStub(value=""),
        _slider_updaters={},
        _basic_variables={
            "silent_speed": silent,
            "sounded_speed": sounded,
            "silent_threshold": threshold,
        },
        _simple_presets=list(_TEST_PRESETS),
        messagebox=Mock(),
    )


def test_advanced_preset_values_maps_resolution_tri_state():
    gui = _make_advanced_preset_gui()

    gui.small_var.set(False)
    assert layout.advanced_preset_values(gui)["resolution"] == "1080p"

    gui.small_var.set(True)
    gui.small_480_var.set(False)
    assert layout.advanced_preset_values(gui)["resolution"] == "720p"

    gui.small_480_var.set(True)
    assert layout.advanced_preset_values(gui)["resolution"] == "480p"


def test_move_advanced_preset_persists_new_order(monkeypatch):
    saved: list = []
    monkeypatch.setattr(
        layout.presets,
        "save_presets",
        lambda presets_list, *a, **k: saved.append(list(presets_list)) or True,
    )
    monkeypatch.setattr(layout, "refresh_preset_dropdowns", lambda gui: None)

    gui = _make_advanced_preset_gui()
    gui.advanced_preset_var.set(_TEST_PRESETS[1].name)

    layout.move_advanced_preset(gui, -1)

    order = [preset.name for preset in saved[-1]]
    assert order == [_TEST_PRESETS[1].name, _TEST_PRESETS[0].name]
    assert gui.advanced_preset_var.get() == _TEST_PRESETS[1].name


def test_move_advanced_preset_noop_on_custom(monkeypatch):
    saved: list = []
    monkeypatch.setattr(
        layout.presets,
        "save_presets",
        lambda presets_list, *a, **k: saved.append(list(presets_list)) or True,
    )

    gui = _make_advanced_preset_gui()
    gui.advanced_preset_var.set(layout.presets.CUSTOM_LABEL)

    layout.move_advanced_preset(gui, 1)

    assert saved == []


def test_seed_initial_preset_defaults_to_first(monkeypatch):
    monkeypatch.setattr(layout.presets, "get_selected_preset", lambda *a, **k: None)
    persisted: list = []
    monkeypatch.setattr(
        layout.presets,
        "set_selected_preset",
        lambda name, *a, **k: persisted.append(name) or True,
    )

    gui = _make_advanced_preset_gui()
    gui.simple_preset_var.set("")

    layout.seed_initial_preset(gui)

    first = gui._simple_presets[0].name
    assert gui.simple_preset_var.get() == first
    assert persisted[-1] == first


def test_seed_initial_preset_restores_remembered(monkeypatch):
    remembered = _TEST_PRESETS[1].name
    monkeypatch.setattr(
        layout.presets, "get_selected_preset", lambda *a, **k: remembered
    )
    monkeypatch.setattr(layout.presets, "set_selected_preset", lambda *a, **k: True)

    gui = _make_advanced_preset_gui()
    layout.seed_initial_preset(gui)

    assert gui.simple_preset_var.get() == remembered


def test_seed_initial_preset_noop_without_presets(monkeypatch):
    monkeypatch.setattr(layout.presets, "get_selected_preset", lambda *a, **k: None)
    monkeypatch.setattr(layout.presets, "set_selected_preset", lambda *a, **k: True)

    gui = _make_advanced_preset_gui()
    gui._simple_presets = []
    gui.simple_preset_var.set("")

    layout.seed_initial_preset(gui)

    assert gui.simple_preset_var.get() == ""


def test_build_sparse_preset_copies_only_selected_fields():
    values = {
        "resolution": "480p",
        "silent_speed": 10.0,
        "sounded_speed": 1.0,
        "silent_threshold": 0.01,
        "video_codec": "hevc",
    }

    preset = layout.build_sparse_preset(
        "codec+speed", values, {"video_codec", "silent_speed"}
    )

    assert preset.name == "codec+speed"
    assert preset.video_codec == "hevc"
    assert preset.silent_speed == 10.0
    assert preset.resolution is None
    assert preset.sounded_speed is None
    assert preset.silent_threshold is None
    assert preset.present_fields() == {"video_codec", "silent_speed"}


def test_preset_from_gui_selection_captures_checked_subset():
    gui = _make_advanced_preset_gui()

    preset = layout.preset_from_gui_selection(gui, "just codec", {"video_codec"})

    assert preset.present_fields() == {"video_codec"}
    assert preset.video_codec == "h264"


def test_save_advanced_preset_persists_sparse_selection(monkeypatch):
    saved: list = []
    monkeypatch.setattr(
        layout.presets,
        "save_presets",
        lambda presets_list, *a, **k: saved.append(list(presets_list)) or True,
    )
    monkeypatch.setattr(layout.presets, "set_selected_preset", lambda *a, **k: True)
    monkeypatch.setattr(layout, "refresh_preset_dropdowns", lambda gui: None)

    gui = _make_advanced_preset_gui()
    layout.save_advanced_preset(gui, "Fast codec", {"video_codec", "silent_speed"})

    stored = saved[-1][-1]
    assert stored.name == "Fast codec"
    assert stored.present_fields() == {"video_codec", "silent_speed"}


def test_refresh_advanced_preset_selection_matches_preset():
    gui = _make_advanced_preset_gui()
    # The stub knobs match the first test preset (720p / 10x / h264).
    layout.refresh_advanced_preset_selection(gui)

    assert gui.advanced_preset_var.get() == "720p 10x speedup H.264"


def test_refresh_advanced_preset_selection_flips_to_custom():
    gui = _make_advanced_preset_gui()
    # Editing a knob so it no longer matches any preset flips to "Custom".
    gui.silent_speed_var.set(3.5)

    layout.refresh_advanced_preset_selection(gui)

    assert gui.advanced_preset_var.get() == layout.presets.CUSTOM_LABEL


def test_refresh_advanced_preset_selection_clears_stale_simple_selection(monkeypatch):
    """An Advanced edit to "Custom" must clear the Simple dropdown selection.

    Simple mode hides the manual knobs but processing reads the live vars, so a
    lingering preset name would show one preset while converting with different
    values. The persisted ``selected_preset`` is cleared too so a relaunch into
    Simple mode stays consistent.
    """

    persisted: list[str | None] = []
    monkeypatch.setattr(
        layout.presets,
        "set_selected_preset",
        lambda name, *a, **k: persisted.append(name) or True,
    )

    gui = _make_advanced_preset_gui()
    gui.simple_preset_var.set("720p 10x speedup H.264")
    gui.silent_speed_var.set(3.5)

    layout.refresh_advanced_preset_selection(gui)

    assert gui.advanced_preset_var.get() == layout.presets.CUSTOM_LABEL
    assert gui.simple_preset_var.get() == ""
    assert persisted == [None]


def test_refresh_advanced_preset_selection_syncs_simple_to_matched_preset(monkeypatch):
    """A knob edit that lands on a stored preset selects it in Simple mode too."""

    persisted: list[str | None] = []
    monkeypatch.setattr(
        layout.presets,
        "set_selected_preset",
        lambda name, *a, **k: persisted.append(name) or True,
    )

    gui = _make_advanced_preset_gui()
    # Stub knobs already match the first preset; the Simple selector starts empty.
    layout.refresh_advanced_preset_selection(gui)

    assert gui.simple_preset_var.get() == "720p 10x speedup H.264"
    assert persisted == ["720p 10x speedup H.264"]


def test_refresh_advanced_preset_selection_skips_redundant_persist(monkeypatch):
    """Repeated calls that keep the same match must not rewrite settings.json."""

    persisted: list[str | None] = []
    monkeypatch.setattr(
        layout.presets,
        "set_selected_preset",
        lambda name, *a, **k: persisted.append(name) or True,
    )

    gui = _make_advanced_preset_gui()
    gui.simple_preset_var.set("720p 10x speedup H.264")

    layout.refresh_advanced_preset_selection(gui)
    layout.refresh_advanced_preset_selection(gui)

    # Already in sync, so no write happens on either call.
    assert persisted == []


def test_refresh_advanced_preset_selection_skips_before_knobs_exist():
    """``add_slider`` builds sliders before every knob var exists.

    The first slider's build-time ``update()`` reaches this helper while
    ``sounded_speed_var``/``silent_threshold_var`` are still missing, so the
    reverse-match must no-op instead of raising ``AttributeError``.
    """

    gui = SimpleNamespace(
        advanced_preset_var=StringVarStub(value=""),
        small_var=BooleanVarStub(value=True),
        small_480_var=BooleanVarStub(value=False),
        video_codec_var=StringVarStub(value="h264"),
        silent_speed_var=DummyVar(10.0),
        _simple_presets=list(_TEST_PRESETS),
    )

    layout.refresh_advanced_preset_selection(gui)

    # No reverse-match ran, so the seeded value is left untouched.
    assert gui.advanced_preset_var.get() == ""


def test_apply_advanced_preset_applies_and_persists(monkeypatch):
    persisted: list[str] = []
    monkeypatch.setattr(
        layout.presets,
        "set_selected_preset",
        lambda name, *a, **k: persisted.append(name) or True,
    )

    gui = _make_advanced_preset_gui()
    gui.advanced_preset_var = StringVarStub(value="480p 10x speedup H.265")

    layout.apply_advanced_preset(gui)

    assert gui.small_480_var.get() is True
    assert gui.video_codec_var.get() == "hevc"
    assert persisted == ["480p 10x speedup H.265"]


def test_apply_advanced_preset_custom_noops(monkeypatch):
    persisted: list[str] = []
    monkeypatch.setattr(
        layout.presets,
        "set_selected_preset",
        lambda name, *a, **k: persisted.append(name) or True,
    )

    gui = _make_advanced_preset_gui()
    gui.advanced_preset_var = StringVarStub(value=layout.presets.CUSTOM_LABEL)

    layout.apply_advanced_preset(gui)

    assert persisted == []


def test_save_advanced_preset_persists_and_refreshes(monkeypatch):
    saved: list[list] = []
    monkeypatch.setattr(
        layout.presets,
        "save_presets",
        lambda presets, *a, **k: saved.append(presets) or True,
    )
    monkeypatch.setattr(layout.presets, "set_selected_preset", lambda *a, **k: True)
    # ``refresh_preset_dropdowns`` reloads the store: echo back what was saved.
    monkeypatch.setattr(
        layout.presets, "load_presets", lambda *a, **k: list(saved[-1]) if saved else []
    )

    gui = _make_advanced_preset_gui()
    gui.small_var.set(False)  # 1080p
    gui.video_codec_var.set("av1")

    layout.save_advanced_preset(gui, "My new preset")

    assert saved, "save_presets should be called"
    new = layout.presets.find_preset("My new preset", saved[-1])
    assert new is not None
    assert new.resolution == "1080p"
    assert new.video_codec == "av1"
    assert gui.advanced_preset_var.get() == "My new preset"


def test_save_advanced_preset_rejects_reserved_custom_name(monkeypatch):
    saved: list = []
    monkeypatch.setattr(
        layout.presets, "save_presets", lambda presets, *a, **k: saved.append(presets)
    )

    gui = _make_advanced_preset_gui()

    layout.save_advanced_preset(gui, layout.presets.CUSTOM_LABEL)

    # "Custom" is the dropdown sentinel; saving under it must be refused so the
    # preset never becomes unmanageable.
    assert gui.messagebox.showerror.called
    assert saved == []


def test_save_advanced_preset_reports_write_failure(monkeypatch):
    persisted: list = []
    monkeypatch.setattr(layout.presets, "save_presets", lambda *a, **k: False)
    monkeypatch.setattr(
        layout.presets,
        "set_selected_preset",
        lambda *a, **k: persisted.append(a) or True,
    )
    monkeypatch.setattr(
        layout.presets, "load_presets", lambda *a, **k: list(_TEST_PRESETS)
    )

    gui = _make_advanced_preset_gui()

    layout.save_advanced_preset(gui, "My new preset")

    # A failed write must surface an error and skip persisting the selection.
    assert gui.messagebox.showerror.called
    assert persisted == []


def test_update_advanced_preset_overwrites_selection(monkeypatch):
    saved: list[list] = []
    monkeypatch.setattr(
        layout.presets,
        "save_presets",
        lambda presets, *a, **k: saved.append(presets) or True,
    )
    monkeypatch.setattr(layout.presets, "set_selected_preset", lambda *a, **k: True)
    monkeypatch.setattr(
        layout.presets, "load_presets", lambda *a, **k: list(saved[-1]) if saved else []
    )

    gui = _make_advanced_preset_gui()
    gui.advanced_preset_var = StringVarStub(value="720p 10x speedup H.264")
    gui.video_codec_var.set("hevc")  # change a knob before updating

    layout.update_advanced_preset(gui)

    updated = layout.presets.find_preset("720p 10x speedup H.264", saved[-1])
    assert updated is not None
    assert updated.video_codec == "hevc"


def test_delete_advanced_preset_removes_selection(monkeypatch):
    saved: list[list] = []
    monkeypatch.setattr(
        layout.presets,
        "save_presets",
        lambda presets, *a, **k: saved.append(presets) or True,
    )
    monkeypatch.setattr(layout.presets, "set_selected_preset", lambda *a, **k: True)
    monkeypatch.setattr(
        layout.presets, "load_presets", lambda *a, **k: list(saved[-1]) if saved else []
    )

    gui = _make_advanced_preset_gui()
    gui.advanced_preset_var = StringVarStub(value="720p 10x speedup H.264")

    layout.delete_advanced_preset(gui)

    assert layout.presets.find_preset("720p 10x speedup H.264", saved[-1]) is None
    assert gui.advanced_preset_var.get() == layout.presets.CUSTOM_LABEL


def test_build_layout_creates_advanced_preset_strip(monkeypatch):
    monkeypatch.setattr(layout, "add_slider", Mock())
    monkeypatch.setattr(layout, "add_entry", Mock())
    monkeypatch.setattr(layout, "update_basic_reset_state", Mock())
    monkeypatch.setattr(layout, "default_temp_folder", lambda: Path("/tmp/mock"))

    gui = _make_layout_gui()

    layout.build_layout(gui)

    assert isinstance(gui.advanced_preset_combo, WidgetStub)
    assert gui.advanced_preset_combo.kwargs["values"] == [
        preset.name for preset in _TEST_PRESETS
    ]
    assert gui.advanced_preset_save_button.kwargs["command"] is (
        gui._open_save_preset_dialog
    )
    assert gui.advanced_preset_update_button.kwargs["command"] is (
        gui._update_selected_preset
    )
    assert gui.advanced_preset_delete_button.kwargs["command"] is (
        gui._delete_selected_preset
    )
    # The strip is created and gridded (visible in the full layout).
    assert gui.advanced_preset_frame.grid_calls
