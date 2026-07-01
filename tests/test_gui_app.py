"""Tests for helper utilities in :mod:`talks_reducer.gui.app`."""

from __future__ import annotations

import json
import math
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from talks_reducer.gui import app, summaries
from talks_reducer.gui.theme import STATUS_COLORS


def test_default_remote_destination_with_suffix(tmp_path):
    input_path = tmp_path / "video.mp4"
    input_path.write_text("data")

    result = app._default_remote_destination(input_path, small=False)

    assert result.name == "video_speedup.mp4"


def test_default_remote_destination_without_suffix(tmp_path):
    input_path = tmp_path / "archive"
    input_path.write_text("data")

    result = app._default_remote_destination(input_path, small=True)

    assert result.name == "archive_speedup_small.mp4"


def test_default_remote_destination_with_small_480(tmp_path):
    input_path = tmp_path / "clip.mov"
    input_path.write_text("data")

    result = app._default_remote_destination(input_path, small=True, small_480=True)

    assert result.name == "clip_speedup_small_480.mp4"


def test_default_remote_destination_with_codec_suffix(tmp_path):
    input_path = tmp_path / "sample.mp4"
    input_path.write_text("data")

    result = app._default_remote_destination(
        input_path, small=False, add_codec_suffix=True, video_codec="H264"
    )

    assert result.name == "sample_speedup_h264.mp4"


def test_default_remote_destination_without_speedup(tmp_path):
    input_path = tmp_path / "plain.mp4"
    input_path.write_text("data")

    result = app._default_remote_destination(
        input_path,
        small=False,
        silent_speed=1.0,
        sounded_speed=1.0,
        video_codec="av1",
    )

    assert result.name == "plain_av1.mp4"


def test_default_remote_destination_small_without_speedup(tmp_path):
    input_path = tmp_path / "mini.mp4"
    input_path.write_text("data")

    result = app._default_remote_destination(
        input_path,
        small=True,
        silent_speed=1.0,
        sounded_speed=1.0,
    )

    assert result.name == "mini_small.mp4"


def test_parse_ratios_from_summary_extracts_values():
    summary = "**Duration:** — 42.5% of the original\n" "**Size:** 17.25%\n"

    time_ratio, size_ratio = app._parse_ratios_from_summary(summary)

    assert time_ratio == 0.425
    assert size_ratio == 0.1725


def test_parse_ratios_from_summary_handles_invalid_numbers():
    summary = "**Duration:** — not-a-number% of the original\n" "**Size:** 10 percent\n"

    time_ratio, size_ratio = app._parse_ratios_from_summary(summary)

    assert time_ratio is None
    assert size_ratio is None


def test_parse_source_duration_seconds_extracts_value():
    message = "Source metadata: duration: 12.5s"

    found, duration = app._parse_source_duration_seconds(message)

    assert found is True
    assert duration == 12.5


def test_parse_source_duration_seconds_handles_invalid_value():
    message = "source metadata: duration: 1.2.3s"

    found, duration = app._parse_source_duration_seconds(message)

    assert found is True
    assert duration is None


@pytest.mark.parametrize(
    "message",
    [
        "Final encode target frames: 4800",
        "Final encode target frames (fallback): 98765",
    ],
)
def test_parse_encode_total_frames_extracts_values(message):
    found, frames = app._parse_encode_total_frames(message)

    assert found is True
    assert frames == int(message.rsplit(":", 1)[-1].strip())


def test_parse_encode_total_frames_handles_invalid_number():
    message = "Final encode target frames: not-a-number"

    found, frames = app._parse_encode_total_frames(message)

    assert found is False
    assert frames is None


def test_parse_encode_total_frames_missing_returns_false():
    found, frames = app._parse_encode_total_frames("No frame info here")

    assert found is False
    assert frames is None


@pytest.mark.parametrize(
    "message, expected",
    [
        ("frame=   42", 42),
        ("frame=1000 fps=30", 1000),
    ],
)
def test_parse_current_frame_extracts_integer(message, expected):
    found, frame = app._parse_current_frame(message)

    assert found is True
    assert frame == expected


def test_parse_current_frame_handles_invalid_number():
    found, frame = app._parse_current_frame("frame=notanint")

    assert found is False
    assert frame is None


def test_parse_current_frame_missing_returns_false():
    found, frame = app._parse_current_frame("no frame information")

    assert found is False
    assert frame is None


@pytest.mark.parametrize(
    "message, expected",
    [
        ("Final encode target duration: 12.5s", 12.5),
        ("Final encode target duration (fallback): 30s", 30.0),
    ],
)
def test_parse_encode_target_duration_extracts_seconds(message, expected):
    found, duration = app._parse_encode_target_duration(message)

    assert found is True
    assert duration == expected


def test_parse_encode_target_duration_handles_invalid_value():
    found, duration = app._parse_encode_target_duration(
        "Final encode target duration: 5.5.5s"
    )

    assert found is True
    assert duration is None


def test_parse_encode_target_duration_missing_returns_false():
    found, duration = app._parse_encode_target_duration("no duration info")

    assert found is False
    assert duration is None


def test_collect_arguments_includes_video_codec():
    class DummyVar:
        def __init__(self, value: str) -> None:
            self._value = value
            self.set_calls: list[str] = []

        def get(self) -> str:
            return self._value

        def set(self, value: str) -> None:
            self._value = value
            self.set_calls.append(value)

    gui = SimpleNamespace(
        output_var=SimpleNamespace(get=lambda: ""),
        temp_var=SimpleNamespace(get=lambda: ""),
        silent_threshold_var=SimpleNamespace(get=lambda: 0.01),
        sounded_speed_var=SimpleNamespace(get=lambda: 1.0),
        silent_speed_var=SimpleNamespace(get=lambda: 4.0),
        frame_margin_var=SimpleNamespace(get=lambda: "2"),
        sample_rate_var=SimpleNamespace(get=lambda: "48000"),
        keyframe_interval_var=SimpleNamespace(get=lambda: 30.0),
        small_var=SimpleNamespace(get=lambda: False),
        small_480_var=SimpleNamespace(get=lambda: False),
        video_codec_var=DummyVar("AV1"),
        add_codec_suffix_var=SimpleNamespace(get=lambda: False),
        use_global_ffmpeg_var=SimpleNamespace(get=lambda: True),
        optimize_var=SimpleNamespace(get=lambda: True),
        cut_enabled_var=SimpleNamespace(get=lambda: False),
        cut_start_var=SimpleNamespace(get=lambda: 0.0),
        cut_end_var=SimpleNamespace(get=lambda: 0.0),
        preferences=SimpleNamespace(update=lambda *args, **kwargs: None),
    )
    gui._parse_float = lambda value, _label: float(value)

    args = app.TalksReducerGUI._collect_arguments(gui)

    assert args["video_codec"] == "av1"
    assert gui.video_codec_var.set_calls == []


def test_collect_arguments_accepts_mp3_codec():
    class DummyVar:
        def __init__(self, value: str) -> None:
            self._value = value
            self.set_calls: list[str] = []

        def get(self) -> str:
            return self._value

        def set(self, value: str) -> None:
            self._value = value
            self.set_calls.append(value)

    gui = SimpleNamespace(
        output_var=SimpleNamespace(get=lambda: ""),
        temp_var=SimpleNamespace(get=lambda: ""),
        silent_threshold_var=SimpleNamespace(get=lambda: 0.01),
        sounded_speed_var=SimpleNamespace(get=lambda: 1.0),
        silent_speed_var=SimpleNamespace(get=lambda: 4.0),
        frame_margin_var=SimpleNamespace(get=lambda: "2"),
        sample_rate_var=SimpleNamespace(get=lambda: "48000"),
        keyframe_interval_var=SimpleNamespace(get=lambda: 30.0),
        small_var=SimpleNamespace(get=lambda: False),
        small_480_var=SimpleNamespace(get=lambda: False),
        video_codec_var=DummyVar("mp3"),
        add_codec_suffix_var=SimpleNamespace(get=lambda: False),
        use_global_ffmpeg_var=SimpleNamespace(get=lambda: True),
        optimize_var=SimpleNamespace(get=lambda: True),
        cut_enabled_var=SimpleNamespace(get=lambda: False),
        cut_start_var=SimpleNamespace(get=lambda: 0.0),
        cut_end_var=SimpleNamespace(get=lambda: 0.0),
        preferences=SimpleNamespace(update=lambda *args, **kwargs: None),
    )
    gui._parse_float = lambda value, _label: float(value)

    args = app.TalksReducerGUI._collect_arguments(gui)

    assert args["video_codec"] == "mp3"
    assert gui.video_codec_var.set_calls == []


def test_collect_arguments_includes_add_codec_suffix():
    gui = SimpleNamespace(
        output_var=SimpleNamespace(get=lambda: ""),
        temp_var=SimpleNamespace(get=lambda: ""),
        silent_threshold_var=SimpleNamespace(get=lambda: 0.01),
        sounded_speed_var=SimpleNamespace(get=lambda: 1.0),
        silent_speed_var=SimpleNamespace(get=lambda: 4.0),
        frame_margin_var=SimpleNamespace(get=lambda: "2"),
        sample_rate_var=SimpleNamespace(get=lambda: "48000"),
        keyframe_interval_var=SimpleNamespace(get=lambda: 30.0),
        small_var=SimpleNamespace(get=lambda: False),
        small_480_var=SimpleNamespace(get=lambda: False),
        video_codec_var=SimpleNamespace(get=lambda: "hevc", set=lambda value: None),
        add_codec_suffix_var=SimpleNamespace(get=lambda: True),
        use_global_ffmpeg_var=SimpleNamespace(get=lambda: False),
        optimize_var=SimpleNamespace(get=lambda: True),
        cut_enabled_var=SimpleNamespace(get=lambda: False),
        cut_start_var=SimpleNamespace(get=lambda: 0.0),
        cut_end_var=SimpleNamespace(get=lambda: 0.0),
        preferences=SimpleNamespace(update=lambda *args, **kwargs: None),
    )
    gui._parse_float = lambda value, _label: float(value)

    args = app.TalksReducerGUI._collect_arguments(gui)

    assert args["add_codec_suffix"] is True
    assert args["prefer_global_ffmpeg"] is False


def _make_collect_gui(**overrides) -> SimpleNamespace:
    defaults = dict(
        output_var=SimpleNamespace(get=lambda: ""),
        temp_var=SimpleNamespace(get=lambda: ""),
        silent_threshold_var=SimpleNamespace(get=lambda: 0.01),
        sounded_speed_var=SimpleNamespace(get=lambda: 1.0),
        silent_speed_var=SimpleNamespace(get=lambda: 4.0),
        frame_margin_var=SimpleNamespace(get=lambda: "2"),
        sample_rate_var=SimpleNamespace(get=lambda: "48000"),
        keyframe_interval_var=SimpleNamespace(get=lambda: 30.0),
        small_var=SimpleNamespace(get=lambda: False),
        small_480_var=SimpleNamespace(get=lambda: False),
        video_codec_var=SimpleNamespace(get=lambda: "h264", set=lambda value: None),
        add_codec_suffix_var=SimpleNamespace(get=lambda: False),
        use_global_ffmpeg_var=SimpleNamespace(get=lambda: False),
        optimize_var=SimpleNamespace(get=lambda: True),
        cut_enabled_var=SimpleNamespace(get=lambda: False),
        cut_start_var=SimpleNamespace(get=lambda: 0.0),
        cut_end_var=SimpleNamespace(get=lambda: 0.0),
        simple_mode_var=SimpleNamespace(get=lambda: False),
        preferences=SimpleNamespace(update=lambda *args, **kwargs: None),
    )
    defaults.update(overrides)
    gui = SimpleNamespace(**defaults)
    gui._parse_float = lambda value, _label: float(value)
    return gui


def test_collect_arguments_includes_cut_range_when_enabled():
    gui = _make_collect_gui(
        cut_enabled_var=SimpleNamespace(get=lambda: True),
        cut_start_var=SimpleNamespace(get=lambda: 10.0),
        cut_end_var=SimpleNamespace(get=lambda: 60.0),
    )

    args = app.TalksReducerGUI._collect_arguments(gui)

    assert args["cut_start_seconds"] == 10.0
    assert args["cut_end_seconds"] == 60.0


def test_collect_arguments_ignores_cut_in_simple_mode():
    # Cut is Advanced-only: a persisted enabled flag must not trim in Simple mode.
    gui = _make_collect_gui(
        cut_enabled_var=SimpleNamespace(get=lambda: True),
        cut_start_var=SimpleNamespace(get=lambda: 10.0),
        cut_end_var=SimpleNamespace(get=lambda: 60.0),
        simple_mode_var=SimpleNamespace(get=lambda: True),
    )

    args = app.TalksReducerGUI._collect_arguments(gui)

    assert "cut_start_seconds" not in args
    assert "cut_end_seconds" not in args


def test_collect_arguments_omits_cut_range_when_disabled():
    gui = _make_collect_gui(
        cut_enabled_var=SimpleNamespace(get=lambda: False),
        cut_start_var=SimpleNamespace(get=lambda: 10.0),
        cut_end_var=SimpleNamespace(get=lambda: 60.0),
    )

    args = app.TalksReducerGUI._collect_arguments(gui)

    assert "cut_start_seconds" not in args
    assert "cut_end_seconds" not in args


def test_collect_arguments_allows_cut_end_zero_for_eof():
    gui = _make_collect_gui(
        cut_enabled_var=SimpleNamespace(get=lambda: True),
        cut_start_var=SimpleNamespace(get=lambda: 5.0),
        cut_end_var=SimpleNamespace(get=lambda: 0.0),
    )

    args = app.TalksReducerGUI._collect_arguments(gui)

    assert args["cut_start_seconds"] == 5.0
    assert args["cut_end_seconds"] == 0.0


def test_collect_arguments_rejects_invalid_cut_range():
    gui = _make_collect_gui(
        cut_enabled_var=SimpleNamespace(get=lambda: True),
        cut_start_var=SimpleNamespace(get=lambda: 60.0),
        cut_end_var=SimpleNamespace(get=lambda: 10.0),
    )

    with pytest.raises(ValueError):
        app.TalksReducerGUI._collect_arguments(gui)


class _RecordingLabel:
    def __init__(self) -> None:
        self.configure_calls: list = []

    def configure(self, **kwargs) -> None:
        self.configure_calls.append(kwargs)


class _RecordingSlider:
    def __init__(self) -> None:
        self.configure_calls: list = []

    def configure(self, **kwargs) -> None:
        self.configure_calls.append(kwargs)

    def grid(self) -> None:
        pass

    def grid_remove(self) -> None:
        pass


def _make_cut_slider_gui(start: float, end: float) -> SimpleNamespace:
    gui = SimpleNamespace(
        cut_start_var=_RecordingVar(start),
        cut_end_var=_RecordingVar(end),
        cut_start_text_var=_RecordingVar(""),
        cut_end_text_var=_RecordingVar(""),
    )
    gui._refresh_cut_entry_text = (
        lambda which: app.TalksReducerGUI._refresh_cut_entry_text(gui, which)
    )
    gui._on_cut_slider_change = lambda which: app.TalksReducerGUI._on_cut_slider_change(
        gui, which
    )
    return gui


def test_on_cut_slider_change_clamps_start_to_end():
    gui = _make_cut_slider_gui(70.0, 60.0)

    app.TalksReducerGUI._on_cut_slider_change(gui, "start")

    assert gui.cut_start_var.get() == 60.0
    # The entry mirrors the clamped handle with millisecond precision.
    assert gui.cut_start_text_var.get() == "00:01:00.000"


def test_on_cut_slider_change_clamps_end_to_start():
    gui = _make_cut_slider_gui(30.0, 10.0)

    app.TalksReducerGUI._on_cut_slider_change(gui, "end")

    assert gui.cut_end_var.get() == 30.0


def test_on_cut_entry_commit_parses_milliseconds():
    gui = _make_cut_slider_gui(0.0, 0.0)
    gui._cut_duration = 600.0
    gui.cut_start_text_var.set("00:01:02.500")

    app.TalksReducerGUI._on_cut_entry_commit(gui, "start")

    assert gui.cut_start_var.get() == pytest.approx(62.5)


def test_on_cut_entry_commit_rejects_invalid_input():
    gui = _make_cut_slider_gui(12.0, 0.0)
    gui._cut_duration = 600.0
    gui.cut_start_text_var.set("not-a-time")

    app.TalksReducerGUI._on_cut_entry_commit(gui, "start")

    # Malformed input is rejected and the entry restored to the handle value.
    assert gui.cut_start_var.get() == 12.0
    assert gui.cut_start_text_var.get() == "00:00:12.000"


def test_update_cut_range_sets_slider_to_duration(monkeypatch):
    import talks_reducer.ffmpeg as ffmpeg_module

    monkeypatch.setattr(ffmpeg_module, "get_video_duration", lambda path: 120.0)

    start_slider = _RecordingSlider()
    end_slider = _RecordingSlider()
    gui = SimpleNamespace(
        input_files=["video.mp4"],
        cut_start_slider=start_slider,
        cut_end_slider=end_slider,
        cut_start_var=_RecordingVar(0.0),
        cut_end_var=_RecordingVar(0.0),
        _cut_duration=0.0,
    )

    app.TalksReducerGUI._update_cut_range_for_input(gui)

    assert gui._cut_duration == 120.0
    assert start_slider.configure_calls[-1]["to"] == 120.0
    assert end_slider.configure_calls[-1]["to"] == 120.0
    # End handle defaults to the discovered duration on first learn.
    assert gui.cut_end_var.get() == 120.0


def test_update_cut_range_clamps_stale_values_to_shorter_duration(monkeypatch):
    import talks_reducer.ffmpeg as ffmpeg_module

    monkeypatch.setattr(ffmpeg_module, "get_video_duration", lambda path: 60.0)

    gui = SimpleNamespace(
        input_files=["short.mp4"],
        cut_start_slider=_RecordingSlider(),
        cut_end_slider=_RecordingSlider(),
        # Stale values persisted from a longer video, both past the new EOF.
        cut_start_var=_RecordingVar(120.0),
        cut_end_var=_RecordingVar(300.0),
        _cut_duration=0.0,
    )

    app.TalksReducerGUI._update_cut_range_for_input(gui)

    assert gui._cut_duration == 60.0
    # The end handle is clamped to the new EOF, while a start handle past the
    # new EOF resets to the beginning so the range stays valid (non-empty)
    # instead of collapsing both handles onto EOF.
    assert gui.cut_start_var.get() == 0.0
    assert gui.cut_end_var.get() == 60.0

    # The clamped range must survive ``_collect_arguments`` without tripping the
    # ``cut_end <= cut_start`` guard, otherwise Run would fail for shorter videos.
    collect_gui = _make_collect_gui(
        cut_enabled_var=SimpleNamespace(get=lambda: True),
        cut_start_var=SimpleNamespace(get=gui.cut_start_var.get),
        cut_end_var=SimpleNamespace(get=gui.cut_end_var.get),
    )

    args = app.TalksReducerGUI._collect_arguments(collect_gui)

    assert args["cut_start_seconds"] == 0.0
    assert args["cut_end_seconds"] == 60.0


def test_update_cut_range_no_input_is_noop():
    gui = SimpleNamespace(input_files=[], _cut_duration=0.0)

    app.TalksReducerGUI._update_cut_range_for_input(gui)

    assert gui._cut_duration == 0.0


def test_update_cut_convert_button_shows_in_advanced_cut():
    button = _RecordingSlider()
    shown: list = []
    button.grid = lambda: shown.append(True)
    button.grid_remove = lambda: shown.append(False)
    gui = SimpleNamespace(
        cut_convert_button=button,
        cut_enabled_var=SimpleNamespace(get=lambda: True),
        simple_mode_var=SimpleNamespace(get=lambda: False),
    )

    app.TalksReducerGUI._update_cut_convert_button(gui)

    assert shown[-1] is True


def test_update_cut_convert_button_hidden_in_simple_mode():
    button = _RecordingSlider()
    shown: list = []
    button.grid = lambda: shown.append(True)
    button.grid_remove = lambda: shown.append(False)
    gui = SimpleNamespace(
        cut_convert_button=button,
        cut_enabled_var=SimpleNamespace(get=lambda: True),
        simple_mode_var=SimpleNamespace(get=lambda: True),
    )

    app.TalksReducerGUI._update_cut_convert_button(gui)

    assert shown[-1] is False


def test_on_inputs_updated_refreshes_cut_range_when_enabled():
    calls: list = []
    gui = SimpleNamespace(
        cut_enabled_var=SimpleNamespace(get=lambda: True),
        _update_cut_range_for_input=lambda: calls.append("range"),
        _on_cut_slider_change=lambda which: calls.append(which),
    )

    app.TalksReducerGUI._on_inputs_updated(gui)

    assert calls == ["range", "start"]


def test_on_inputs_updated_noop_when_cut_disabled():
    calls: list = []
    gui = SimpleNamespace(
        cut_enabled_var=SimpleNamespace(get=lambda: False),
        _update_cut_range_for_input=lambda: calls.append("range"),
        _on_cut_slider_change=lambda which: calls.append(which),
    )

    app.TalksReducerGUI._on_inputs_updated(gui)

    assert calls == []


class _RecordingVar:
    def __init__(self, value=None) -> None:
        self._value = value
        self.set_calls: list = []

    def get(self):
        return self._value

    def set(self, value) -> None:
        self._value = value
        self.set_calls.append(value)


def _make_settings_gui() -> SimpleNamespace:
    silent_speed_var = _RecordingVar(4.0)
    sounded_speed_var = _RecordingVar(1.0)
    silent_threshold_var = _RecordingVar(0.01)
    slider_calls: dict[str, list] = {}

    def _make_updater(key: str):
        slider_calls[key] = []
        return lambda value: slider_calls[key].append(value)

    gui = SimpleNamespace(
        small_var=_RecordingVar(False),
        small_480_var=_RecordingVar(False),
        silent_speed_var=silent_speed_var,
        sounded_speed_var=sounded_speed_var,
        silent_threshold_var=silent_threshold_var,
        frame_margin_var=_RecordingVar("2"),
        sample_rate_var=_RecordingVar("48000"),
        keyframe_interval_var=_RecordingVar(30.0),
        video_codec_var=_RecordingVar("h264"),
        add_codec_suffix_var=_RecordingVar(False),
        use_global_ffmpeg_var=_RecordingVar(False),
        optimize_var=_RecordingVar(True),
        output_var=_RecordingVar(""),
        temp_var=_RecordingVar(""),
        server_url_var=_RecordingVar(""),
        processing_mode_var=_RecordingVar("local"),
        _slider_updaters={
            "silent_speed": _make_updater("silent_speed"),
            "sounded_speed": _make_updater("sounded_speed"),
            "silent_threshold": _make_updater("silent_threshold"),
        },
        _basic_variables={
            "silent_speed": silent_speed_var,
            "sounded_speed": sounded_speed_var,
            "silent_threshold": silent_threshold_var,
        },
    )
    gui.slider_calls = slider_calls
    gui._refresh_slider_label = lambda key: app.TalksReducerGUI._refresh_slider_label(
        gui, key
    )
    return gui


def test_apply_cli_settings_updates_controls():
    gui = _make_settings_gui()

    app.TalksReducerGUI._apply_cli_settings(
        gui,
        {
            "small": True,
            "silent_speed": 5.0,
            "video_codec": "av1",
            "optimize": False,
        },
    )

    assert gui.small_var.get() is True
    assert gui.silent_speed_var.get() == 5.0
    assert gui.video_codec_var.get() == "av1"
    assert gui.optimize_var.get() is False
    # Untouched controls keep their existing values.
    assert gui.sounded_speed_var.set_calls == []


def test_apply_cli_settings_refreshes_seeded_slider_labels():
    gui = _make_settings_gui()

    app.TalksReducerGUI._apply_cli_settings(
        gui,
        {
            "silent_speed": 10.0,
            "sounded_speed": 1.5,
            "silent_threshold": 0.05,
        },
    )

    assert gui.silent_speed_var.get() == 10.0
    assert gui.slider_calls["silent_speed"] == ["10.0"]
    assert gui.slider_calls["sounded_speed"] == ["1.5"]
    assert gui.slider_calls["silent_threshold"] == ["0.05"]


def test_apply_cli_settings_skips_slider_refresh_when_value_absent():
    gui = _make_settings_gui()

    app.TalksReducerGUI._apply_cli_settings(gui, {"small": True})

    assert gui.slider_calls["silent_speed"] == []
    assert gui.slider_calls["sounded_speed"] == []
    assert gui.slider_calls["silent_threshold"] == []


def test_apply_cli_settings_server_url_switches_to_remote():
    gui = _make_settings_gui()

    app.TalksReducerGUI._apply_cli_settings(
        gui, {"server_url": "http://localhost:9005"}
    )

    assert gui.server_url_var.get() == "http://localhost:9005"
    assert gui.processing_mode_var.get() == "remote"


def test_apply_cli_settings_ignores_invalid_codec():
    gui = _make_settings_gui()

    app.TalksReducerGUI._apply_cli_settings(gui, {"video_codec": "bogus"})

    assert gui.video_codec_var.get() == "h264"
    assert gui.video_codec_var.set_calls == []


def test_parse_video_duration_seconds_extracts_total_seconds():
    message = "Duration: 00:05:10.50"

    found, total_seconds = app._parse_video_duration_seconds(message)

    assert found is True
    assert total_seconds == 310.5


def test_parse_ffmpeg_progress_returns_seconds_and_speed():
    message = "frame=   42 time=00:00:10.00 bitrate=1000.0kbits/s speed=1.25x"

    found, progress = app._parse_ffmpeg_progress(message)

    assert found is True
    assert progress == (10, "1.25")


def test_is_encode_total_frames_unknown_detects_indicator():
    normalized = "final encode target frames unknown"

    assert app._is_encode_total_frames_unknown(normalized) is True


def test_is_encode_target_duration_unknown_detects_indicator():
    normalized = "status: final encode target duration unknown"

    assert app._is_encode_target_duration_unknown(normalized) is True


@pytest.mark.parametrize(
    ("message", "expected_label", "expected_percent"),
    [
        ("Generating final: 30%", "Generating final:", 30.0),
        ("Generating final (fallback): 30%", "Generating final (fallback):", 30.0),
        ("Audio processing: 45%", "Audio processing:", 45.0),
        ("Uploading: 50%", "Uploading:", 50.0),
        ("Extracting audio: 12.5%", "Extracting audio:", 12.5),
    ],
)
def test_parse_task_percent_extracts_values(message, expected_label, expected_percent):
    found, result = app._parse_task_percent(message)

    assert found is True
    assert result == (expected_label, expected_percent)


def test_parse_task_percent_matches_tqdm_style_bar():
    message = "Generating final:  30%|███       | 100/330 [00:05<00:11]"

    found, result = app._parse_task_percent(message)

    assert found is True
    assert result == ("Generating final:", 30.0)


def test_parse_task_percent_missing_returns_false():
    found, result = app._parse_task_percent("source metadata: duration: 12.5s")

    assert found is False
    assert result is None


def test_parse_task_percent_ignores_summary_size_line():
    found, result = app._parse_task_percent("**Size:** 17.25%")

    assert found is False
    assert result is None


def _make_summary_gui(progress_value: float = 0.0) -> SimpleNamespace:
    """Build a stub GUI that records progress-related calls for SummaryManager."""

    gui = SimpleNamespace()
    gui._source_duration_seconds = None
    gui._encode_total_frames = None
    gui._encode_current_frame = None
    gui._encode_target_duration_seconds = None
    gui._video_duration_seconds = None
    gui._last_progress_seconds = None
    gui._status_state = "processing"
    gui.AUDIO_PROGRESS_WEIGHT = 5.0
    gui._progress_floor = 0.0
    gui.progress_var = SimpleNamespace(get=lambda: progress_value)
    gui._set_progress = MagicMock()
    gui._set_status = MagicMock()
    gui._complete_audio_phase = MagicMock()
    gui._cancel_audio_progress = MagicMock()
    gui._start_audio_progress = MagicMock()
    gui._reset_audio_progress_state = MagicMock()
    gui._reset_progress_baseline = MagicMock()

    def _set_progress_monotonic(percentage: float) -> None:
        """Mirror the production monotonic clamp so the floor is written."""

        value = min(100.0, max(gui._progress_floor, float(percentage)))
        gui._progress_floor = value
        gui._set_progress(value)

    gui._set_progress_monotonic = _set_progress_monotonic
    return gui


def test_apply_stage_transition_routes_structured_stages():
    """The shared helper cancels the timer on audio and completes it on final."""

    gui = SimpleNamespace(
        _complete_audio_phase=MagicMock(),
        _cancel_audio_progress=MagicMock(),
    )

    app.TalksReducerGUI._apply_stage_transition(gui, "Audio processing:")
    gui._cancel_audio_progress.assert_called_once()
    gui._complete_audio_phase.assert_not_called()

    app.TalksReducerGUI._apply_stage_transition(gui, "Generating final (fallback):")
    gui._complete_audio_phase.assert_called_once()

    # Unknown stages (e.g. uploading/extracting) leave the timer untouched.
    app.TalksReducerGUI._apply_stage_transition(gui, "Uploading:")
    gui._cancel_audio_progress.assert_called_once()
    gui._complete_audio_phase.assert_called_once()


def test_summary_manager_generating_final_percent_advances_progress():
    gui = _make_summary_gui(progress_value=10.0)
    manager = summaries.SummaryManager(gui)

    manager.update_status_from_message("Generating final: 30%")

    gui._complete_audio_phase.assert_called_once()
    gui._set_progress.assert_called_once()
    assert gui._set_progress.call_args[0][0] == pytest.approx(54.5)


def test_summary_manager_audio_processing_percent_cancels_synthetic_timer():
    gui = _make_summary_gui(progress_value=0.0)
    manager = summaries.SummaryManager(gui)

    manager.update_status_from_message("Audio processing: 45%")

    gui._cancel_audio_progress.assert_called_once()
    gui._complete_audio_phase.assert_not_called()
    gui._set_progress.assert_called_once()
    assert gui._set_progress.call_args[0][0] == pytest.approx(26.75)


def test_summary_manager_task_percent_never_moves_backwards():
    # Every channel that advances the bar raises ``_progress_floor`` through the
    # monotonic clamp, so the floor — not the asynchronously-applied
    # ``progress_var`` — is the source of truth for the bar position.
    gui = _make_summary_gui(progress_value=0.0)
    gui._progress_floor = 70.0
    manager = summaries.SummaryManager(gui)

    manager.update_status_from_message("Generating final: 30%")

    assert gui._set_progress.call_args[0][0] == pytest.approx(70.0)


def test_summary_manager_task_percent_raises_floor_on_log_only_path():
    """A log-only final milestone must raise the floor so the audio-phase
    completion callback cannot snap the bar back down.

    On the log-only fallback path no structured channel raises
    ``_progress_floor``. ``_handle_task_percent`` queues ``_complete_audio_phase``
    (which later applies ``AUDIO_PROGRESS_WEIGHT`` through the monotonic clamp)
    before applying the mapped milestone. Unless the milestone writes the floor,
    that trailing callback would clamp against the old floor and regress the bar
    from 54.5% back to 5%.
    """

    gui = _make_summary_gui(progress_value=5.0)
    gui._progress_floor = 5.0

    manager = summaries.SummaryManager(gui)
    manager.update_status_from_message("Generating final: 30%")

    # The floor is raised to the mapped milestone, so a subsequent monotonic
    # update at AUDIO_PROGRESS_WEIGHT cannot move the bar backwards.
    assert gui._progress_floor == pytest.approx(54.5)
    gui._set_progress_monotonic(gui.AUDIO_PROGRESS_WEIGHT)
    assert gui._set_progress.call_args[0][0] == pytest.approx(54.5)


def test_summary_manager_task_percent_clamps_against_progress_floor():
    """The coarse log milestone must not undercut the exact structured update.

    Locally, ``progress.advance`` raises ``_progress_floor`` synchronously to the
    exact frame percentage before the rounded ``Generating final: NN%`` log line
    is parsed, but the structured ``_set_progress`` is applied asynchronously, so
    ``progress_var`` can still read a stale, lower value. The parser must clamp
    against the floor so the bar does not regress behind the queued update.
    """

    gui = _make_summary_gui(progress_value=10.0)
    # Structured channel already advanced to the exact 47% final-encode value.
    gui._progress_floor = 65.55

    manager = summaries.SummaryManager(gui)

    # The rounded "40%" milestone maps to 61.0, which is below the floor.
    manager.update_status_from_message("Generating final: 40%")

    assert gui._set_progress.call_args[0][0] == pytest.approx(65.55)


def test_summary_manager_starting_processing_resets_progress_floor():
    """A new run must clear the floor so a prior local batch cannot pin it."""

    gui = _make_summary_gui(progress_value=100.0)
    manager = summaries.SummaryManager(gui)

    manager.update_status_from_message("Starting processing…")

    gui._reset_progress_baseline.assert_called_once()


def test_summary_manager_extracting_audio_preserves_upload_progress():
    """Remote upload progress must not be reset when extraction begins.

    In remote mode the streamed ``Uploading:`` band advances the bar to ~5%
    before the server logs ``Extracting audio...``. The upload band is applied
    through the monotonic clamp, so it has raised ``_progress_floor`` to 5%. That
    log line must keep the bar where it is rather than dragging it back to zero
    ahead of the ``Extracting audio: NN%`` milestones.
    """

    gui = _make_summary_gui(progress_value=0.0)
    gui._progress_floor = 5.0
    manager = summaries.SummaryManager(gui)

    manager.update_status_from_message("Extracting audio...")

    gui._set_progress.assert_called_once()
    assert gui._set_progress.call_args[0][0] == pytest.approx(5.0)
    gui._start_audio_progress.assert_called_once()


def test_summary_manager_extracting_audio_starts_at_zero_locally():
    """Local runs have no upload band, so extraction still starts at zero."""

    gui = _make_summary_gui(progress_value=0.0)
    manager = summaries.SummaryManager(gui)

    manager.update_status_from_message("Extracting audio...")

    gui._set_progress.assert_called_once()
    assert gui._set_progress.call_args[0][0] == pytest.approx(0.0)


def test_summary_manager_new_job_resets_progress_floor():
    """A ``Processing N/M:`` line for a new file must clear the monotonic floor.

    Zeroing only the visible bar would leave ``_progress_floor`` at the previous
    file's completed value, so the next file's lower-mapped progress would be
    clamped back up. The branch must re-base the floor like the run-start reset.
    """

    gui = _make_summary_gui(progress_value=100.0)
    gui._progress_floor = 100.0
    gui._status_state = "processing"
    manager = summaries.SummaryManager(gui)

    manager.update_status_from_message("Processing 2/3: clip.mp4")

    gui._reset_progress_baseline.assert_called_once()


def test_summary_manager_final_encode_target_completes_audio_phase():
    gui = _make_summary_gui()
    manager = summaries.SummaryManager(gui)

    manager.update_status_from_message("Final encode target frames: 4800")

    gui._complete_audio_phase.assert_called_once()
    assert gui._encode_total_frames == 4800


@pytest.mark.parametrize(
    ("percentage", "expected"),
    [
        (-10, "#f87171"),
        (0, "#f87171"),
        (50, "#facc15"),
        (100, "#22c55e"),
        (150, "#22c55e"),
    ],
)
def test_calculate_gradient_color_clamps_percentage(percentage, expected):
    gui = object.__new__(app.TalksReducerGUI)

    assert app.TalksReducerGUI._calculate_gradient_color(gui, percentage) == expected


def test_calculate_gradient_color_applies_darken_factor():
    gui = object.__new__(app.TalksReducerGUI)

    color = app.TalksReducerGUI._calculate_gradient_color(gui, 25, darken=0.5)

    # 25% sits midway in the red-to-yellow gradient and should be half the brightness.
    assert color == "#7c4f21"


@pytest.mark.parametrize(
    ("total_seconds", "expected"),
    [
        (59.4, "0:59"),
        (61, "1:01"),
        (3661.2, "1:01:01"),
        (-5, "0:00"),
    ],
)
def test_format_progress_time_formats_values(total_seconds, expected):
    gui = object.__new__(app.TalksReducerGUI)

    assert app.TalksReducerGUI._format_progress_time(gui, total_seconds) == expected


def test_format_progress_time_handles_invalid_input():
    gui = object.__new__(app.TalksReducerGUI)

    assert app.TalksReducerGUI._format_progress_time(gui, math.nan) == "0:00"


class _DummyLabel:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def configure(self, **kwargs: str) -> None:
        self.calls.append(kwargs)


def _make_gui_with_dummy_label() -> app.TalksReducerGUI:
    gui = object.__new__(app.TalksReducerGUI)
    gui.status_label = _DummyLabel()
    return gui


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("success", STATUS_COLORS["success"]),
        ("ERROR", STATUS_COLORS["error"]),
        ("Extracting audio", STATUS_COLORS["processing"]),
        (
            "Time: 50%, Size: 25%",
            STATUS_COLORS["success"],
        ),
    ],
)
def test_apply_status_style_sets_expected_color(status, expected):
    gui = _make_gui_with_dummy_label()

    app.TalksReducerGUI._apply_status_style(gui, status)

    assert gui.status_label.calls[-1]["fg"] == expected


def test_apply_status_style_ignores_unknown_status():
    gui = _make_gui_with_dummy_label()

    app.TalksReducerGUI._apply_status_style(gui, "something else entirely")

    assert gui.status_label.calls == []


def test_advance_audio_progress_does_not_move_bar_backwards():
    """The synthetic 0-5% timer must not drag the bar back once real progress
    from the extraction or audio-processing reporter has advanced past it."""

    gui = object.__new__(app.TalksReducerGUI)
    gui.AUDIO_PROGRESS_STEPS = app.TalksReducerGUI.AUDIO_PROGRESS_STEPS
    gui.AUDIO_PROGRESS_WEIGHT = app.TalksReducerGUI.AUDIO_PROGRESS_WEIGHT
    gui.DEFAULT_AUDIO_INTERVAL_MS = app.TalksReducerGUI.DEFAULT_AUDIO_INTERVAL_MS
    gui._audio_progress_job = None
    gui._audio_progress_steps_completed = 0
    gui._audio_progress_interval_ms = 100
    # Real audio-processing progress has already raised ``_progress_floor`` to
    # 25%, but its queued ``_set_progress`` update has not applied yet, so the
    # Tk variable still reads a stale ``0``. The timer must clamp against the
    # synchronous floor, not the stale variable.
    gui._progress_floor = 25.0
    gui.progress_var = SimpleNamespace(get=lambda: 0.0)
    gui._set_progress = MagicMock()
    gui._set_status = MagicMock()
    gui.root = SimpleNamespace(after=lambda *_args, **_kwargs: "job")

    app.TalksReducerGUI._advance_audio_progress(gui)

    gui._set_progress.assert_called_once()
    assert gui._set_progress.call_args[0][0] == pytest.approx(25.0)
    assert gui._progress_floor == pytest.approx(25.0)


def test_set_progress_monotonic_does_not_move_bar_backwards():
    """A stage restarting at its band start (e.g. the CPU encoder fallback)
    must not drag the bar behind a value an earlier frame already reached."""

    gui = object.__new__(app.TalksReducerGUI)
    gui._progress_floor = 70.0
    gui._set_progress = MagicMock()

    app.TalksReducerGUI._set_progress_monotonic(gui, 35.0)

    gui._set_progress.assert_called_once()
    assert gui._set_progress.call_args[0][0] == pytest.approx(70.0)
    assert gui._progress_floor == pytest.approx(70.0)


def test_set_progress_monotonic_forwards_higher_value():
    gui = object.__new__(app.TalksReducerGUI)
    gui._progress_floor = 35.0
    gui._set_progress = MagicMock()

    app.TalksReducerGUI._set_progress_monotonic(gui, 80.0)

    gui._set_progress.assert_called_once()
    assert gui._set_progress.call_args[0][0] == pytest.approx(80.0)
    assert gui._progress_floor == pytest.approx(80.0)


def test_complete_audio_phase_does_not_regress_below_floor():
    """Completing the audio phase must not snap the bar back to 5%.

    Callers invoke ``_complete_audio_phase`` immediately before queuing a higher
    final-encode percentage. Because both schedule through ``root.after(0, ...)``
    in FIFO order, the nested floor bump applies *after* that higher value, so a
    plain ``_set_progress(AUDIO_PROGRESS_WEIGHT)`` would drag the bar backwards.
    Clamping against ``_progress_floor`` keeps the real progress instead.
    """

    gui = object.__new__(app.TalksReducerGUI)
    gui.AUDIO_PROGRESS_STEPS = app.TalksReducerGUI.AUDIO_PROGRESS_STEPS
    gui.AUDIO_PROGRESS_WEIGHT = app.TalksReducerGUI.AUDIO_PROGRESS_WEIGHT
    gui._audio_progress_job = None
    gui._audio_progress_steps_completed = 0
    gui._audio_progress_interval_ms = None
    # The structured progress channel already advanced the floor to the top of
    # the audio band before the encode milestone triggered completion.
    gui._progress_floor = 35.0
    gui.progress_var = SimpleNamespace(get=lambda: 0.0)
    gui._set_progress = MagicMock()
    gui.root = SimpleNamespace(after_cancel=lambda *_: None)
    gui._schedule_on_ui_thread = lambda callback: callback()

    app.TalksReducerGUI._complete_audio_phase(gui)

    gui._set_progress.assert_called_once()
    assert gui._set_progress.call_args[0][0] == pytest.approx(35.0)
    assert gui._progress_floor == pytest.approx(35.0)
    assert (
        gui._audio_progress_steps_completed == app.TalksReducerGUI.AUDIO_PROGRESS_STEPS
    )


def test_complete_audio_phase_raises_low_bar_to_audio_weight():
    """With no real progress yet, completion still lifts the bar to 5%."""

    gui = object.__new__(app.TalksReducerGUI)
    gui.AUDIO_PROGRESS_STEPS = app.TalksReducerGUI.AUDIO_PROGRESS_STEPS
    gui.AUDIO_PROGRESS_WEIGHT = app.TalksReducerGUI.AUDIO_PROGRESS_WEIGHT
    gui._audio_progress_job = None
    gui._audio_progress_steps_completed = 0
    gui._audio_progress_interval_ms = None
    gui._progress_floor = 0.0
    gui.progress_var = SimpleNamespace(get=lambda: 0.0)
    gui._set_progress = MagicMock()
    gui.root = SimpleNamespace(after_cancel=lambda *_: None)
    gui._schedule_on_ui_thread = lambda callback: callback()

    app.TalksReducerGUI._complete_audio_phase(gui)

    gui._set_progress.assert_called_once()
    assert gui._set_progress.call_args[0][0] == pytest.approx(
        app.TalksReducerGUI.AUDIO_PROGRESS_WEIGHT
    )
    assert gui._progress_floor == pytest.approx(
        app.TalksReducerGUI.AUDIO_PROGRESS_WEIGHT
    )


def test_reset_progress_baseline_clears_floor_for_next_file():
    """Each file in a batch must start from zero so a completed file cannot pin
    the monotonic clamp at the previous file's final value."""

    gui = object.__new__(app.TalksReducerGUI)
    gui._progress_floor = 100.0
    gui._set_progress = MagicMock()

    app.TalksReducerGUI._reset_progress_baseline(gui)

    assert gui._progress_floor == pytest.approx(0.0)
    gui._set_progress.assert_called_once_with(0.0)

    # After re-basing, a lower mapped value from the next file is honored.
    app.TalksReducerGUI._set_progress_monotonic(gui, 12.0)
    assert gui._set_progress.call_args[0][0] == pytest.approx(12.0)


def _make_download_wait_gui() -> app.TalksReducerGUI:
    gui = object.__new__(app.TalksReducerGUI)
    gui.DOWNLOAD_WAIT_INTERVAL_MS = app.TalksReducerGUI.DOWNLOAD_WAIT_INTERVAL_MS
    gui.DOWNLOAD_WAIT_STATUS = app.TalksReducerGUI.DOWNLOAD_WAIT_STATUS
    gui._download_wait_job = None
    gui._download_wait_active = True
    gui._set_status = MagicMock()
    gui._schedule_on_ui_thread = lambda callback: callback()
    gui.root = SimpleNamespace(
        after=MagicMock(return_value="job"),
        after_cancel=MagicMock(),
    )
    return gui


def test_begin_download_wait_emits_status_and_schedules_refresh():
    """Starting the wait emits the status immediately and arms the 5s refresh."""

    gui = _make_download_wait_gui()

    app.TalksReducerGUI._begin_download_wait(gui)

    gui._set_status.assert_called_once_with(
        "processing", app.TalksReducerGUI.DOWNLOAD_WAIT_STATUS
    )
    gui.root.after.assert_called_once_with(
        app.TalksReducerGUI.DOWNLOAD_WAIT_INTERVAL_MS, gui._emit_download_wait
    )
    assert gui._download_wait_job == "job"


def test_emit_download_wait_reschedules_itself():
    """Each refresh re-emits the waiting status and arms the next refresh."""

    gui = _make_download_wait_gui()

    app.TalksReducerGUI._emit_download_wait(gui)
    app.TalksReducerGUI._emit_download_wait(gui)

    assert gui._set_status.call_count == 2
    assert gui.root.after.call_count == 2
    assert gui._download_wait_job == "job"


def test_begin_download_wait_cancels_existing_timer_before_restart():
    """Re-arming cancels any previously scheduled refresh first."""

    gui = _make_download_wait_gui()
    gui._download_wait_job = "old-job"

    app.TalksReducerGUI._begin_download_wait(gui)

    gui.root.after_cancel.assert_called_once_with("old-job")
    assert gui._download_wait_job == "job"


def test_cancel_download_wait_cancels_active_timer():
    """Cancelling stops the timer and clears the stored job handle."""

    gui = _make_download_wait_gui()
    gui._download_wait_job = "job"

    app.TalksReducerGUI._cancel_download_wait(gui)

    gui.root.after_cancel.assert_called_once_with("job")
    assert gui._download_wait_job is None


def test_cancel_download_wait_is_noop_when_idle():
    """Cancelling with no active timer must not touch the scheduler."""

    gui = _make_download_wait_gui()
    gui._download_wait_job = None

    app.TalksReducerGUI._cancel_download_wait(gui)

    gui.root.after_cancel.assert_not_called()
    assert gui._download_wait_job is None


def test_cancel_before_queued_start_runs_does_not_arm_stale_timer():
    """A cancel racing ahead of the queued start must invalidate it.

    Both ``_begin_download_wait`` and ``_cancel_download_wait`` run on the worker
    thread and only *queue* their UI work. If the cancel (first download bytes or
    post-``send_video`` cleanup) lands before Tk runs the queued start, the start
    must not emit the waiting status or arm a heartbeat afterwards.
    """

    gui = _make_download_wait_gui()
    gui._download_wait_active = False
    gui._download_wait_job = None

    queued: list = []
    gui._schedule_on_ui_thread = queued.append

    # Worker thread: begin queues a start, then a cancel arrives before Tk runs.
    app.TalksReducerGUI._begin_download_wait(gui)
    app.TalksReducerGUI._cancel_download_wait(gui)

    # Now flush the queued UI callbacks in order.
    for callback in queued:
        callback()

    gui._set_status.assert_not_called()
    gui.root.after.assert_not_called()
    assert gui._download_wait_job is None
    assert gui._download_wait_active is False


class _LabelStub:
    def __init__(self) -> None:
        self.configure_calls: list[dict] = []
        self.grid_calls = 0
        self.grid_remove_calls = 0

    def configure(self, **kwargs) -> None:
        self.configure_calls.append(kwargs)

    def grid(self) -> None:
        self.grid_calls += 1

    def grid_remove(self) -> None:
        self.grid_remove_calls += 1


def test_update_local_server_url_display_shows_url_in_server_mode():
    """In managed server mode the label is populated and shown."""

    label = _LabelStub()
    gui = SimpleNamespace(
        local_server_url_label=label,
        server_managed=True,
        local_server_url="http://192.168.1.5:9005/",
    )

    app.TalksReducerGUI._update_local_server_url_display(gui)

    assert label.configure_calls[-1] == {"text": "Server: http://192.168.1.5:9005"}
    assert label.grid_calls == 1
    assert label.grid_remove_calls == 0


def test_update_local_server_url_display_hidden_in_standalone_mode():
    """Without server context the label is blanked and removed."""

    label = _LabelStub()
    gui = SimpleNamespace(
        local_server_url_label=label,
        server_managed=False,
        local_server_url=None,
    )

    app.TalksReducerGUI._update_local_server_url_display(gui)

    assert label.configure_calls[-1] == {"text": ""}
    assert label.grid_remove_calls == 1
    assert label.grid_calls == 0


def test_update_local_server_url_display_noop_without_label():
    """The helper tolerates the label widget being absent."""

    gui = SimpleNamespace(
        local_server_url_label=None,
        server_managed=True,
        local_server_url="http://192.168.1.5:9005",
    )

    # Should not raise.
    app.TalksReducerGUI._update_local_server_url_display(gui)


class _ActivityTextStub:
    def __init__(self) -> None:
        self.configure_calls: list[dict] = []
        self.deleted: list[tuple] = []
        self.inserted: list[tuple] = []
        self.see_calls = 0

    def configure(self, **kwargs) -> None:
        self.configure_calls.append(kwargs)

    def delete(self, *args) -> None:
        self.deleted.append(args)

    def insert(self, *args) -> None:
        self.inserted.append(args)

    def see(self, *args) -> None:
        self.see_calls += 1


def _make_activity_gui(server_managed: bool = True, url: str = "http://1.2.3.4:9005"):
    gui = object.__new__(app.TalksReducerGUI)
    gui.ACTIVITY_POLL_INTERVAL_MS = app.TalksReducerGUI.ACTIVITY_POLL_INTERVAL_MS
    gui.server_managed = server_managed
    gui.local_server_url = url
    gui._activity_poll_job = None
    gui.tk = SimpleNamespace(NORMAL="normal", DISABLED="disabled", END="end")
    gui._schedule_on_ui_thread = lambda callback: callback()
    gui.root = SimpleNamespace(
        after=MagicMock(return_value="job"),
        after_cancel=MagicMock(),
    )
    gui.activity_text = _ActivityTextStub()
    return gui


class _FakeResponse:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def read(self) -> bytes:
        return self._data


def test_render_activity_writes_formatted_lines():
    """Sample entries are rendered as HH:MM:SS  <ip>  <action> lines."""

    gui = _make_activity_gui()
    timestamp = 1_700_000_000.0
    clock = time.strftime("%H:%M:%S", time.localtime(timestamp))
    entries = [
        {"timestamp": timestamp, "client_ip": "10.0.0.2", "action": "upload"},
        {"timestamp": timestamp, "client_ip": "10.0.0.3", "action": "download"},
    ]

    app.TalksReducerGUI._render_activity(gui, entries)

    inserted_text = gui.activity_text.inserted[-1][1]
    assert inserted_text == (
        f"{clock}  10.0.0.2  upload\n{clock}  10.0.0.3  download\n"
    )
    # The widget is toggled writable then back to read-only.
    assert {"state": "normal"} in gui.activity_text.configure_calls
    assert gui.activity_text.configure_calls[-1] == {"state": "disabled"}
    assert gui.activity_text.deleted == [("1.0", "end")]


def test_render_activity_clears_when_empty():
    gui = _make_activity_gui()

    app.TalksReducerGUI._render_activity(gui, [])

    assert gui.activity_text.deleted == [("1.0", "end")]
    assert gui.activity_text.inserted == []


def test_render_activity_noop_without_widget():
    gui = _make_activity_gui()
    gui.activity_text = None

    # Should not raise.
    app.TalksReducerGUI._render_activity(gui, [{"action": "upload"}])


def test_fetch_activity_returns_entries(monkeypatch):
    gui = _make_activity_gui()
    payload = {
        "server": {"identity": "host", "url": "http://1.2.3.4:9005"},
        "entries": [{"timestamp": 1.0, "client_ip": "9.9.9.9", "action": "upload"}],
    }

    def fake_urlopen(endpoint, timeout=None):
        assert endpoint == "http://1.2.3.4:9005/activity"
        return _FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(app.urllib.request, "urlopen", fake_urlopen)

    result = app.TalksReducerGUI._fetch_activity(gui, gui.local_server_url)

    assert result == payload


def test_fetch_activity_normalizes_non_list_entries(monkeypatch):
    gui = _make_activity_gui()
    payload = {"server": {"url": "http://1.2.3.4:9005"}, "entries": "oops"}

    monkeypatch.setattr(
        app.urllib.request,
        "urlopen",
        lambda endpoint, timeout=None: _FakeResponse(json.dumps(payload).encode()),
    )

    result = app.TalksReducerGUI._fetch_activity(gui, gui.local_server_url)

    assert result == {"server": {"url": "http://1.2.3.4:9005"}, "entries": []}


def test_fetch_activity_tolerates_unreachable_server(monkeypatch):
    gui = _make_activity_gui()

    def boom(endpoint, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr(app.urllib.request, "urlopen", boom)

    assert app.TalksReducerGUI._fetch_activity(gui, gui.local_server_url) is None


def test_fetch_activity_handles_malformed_payload(monkeypatch):
    gui = _make_activity_gui()

    monkeypatch.setattr(
        app.urllib.request,
        "urlopen",
        lambda endpoint, timeout=None: _FakeResponse(b"[]"),
    )

    assert app.TalksReducerGUI._fetch_activity(gui, gui.local_server_url) is None


def test_finish_activity_poll_renders_and_reschedules():
    gui = _make_activity_gui()
    rendered: list = []
    gui._render_activity = lambda entries: rendered.append(entries)
    shown: list = []
    gui._update_local_server_url_display = lambda url: shown.append(url)

    entries = [{"timestamp": 1.0, "client_ip": "1.1.1.1", "action": "upload"}]
    payload = {"server": {"url": "http://192.168.1.9:9005/"}, "entries": entries}
    app.TalksReducerGUI._finish_activity_poll(gui, payload)

    assert rendered == [entries]
    assert shown == ["http://192.168.1.9:9005/"]
    gui.root.after.assert_called_once_with(
        app.TalksReducerGUI.ACTIVITY_POLL_INTERVAL_MS, gui._poll_activity
    )
    assert gui._activity_poll_job == "job"


def test_finish_activity_poll_renders_without_server_url():
    gui = _make_activity_gui()
    rendered: list = []
    gui._render_activity = lambda entries: rendered.append(entries)
    gui._update_local_server_url_display = MagicMock()

    payload = {"entries": []}
    app.TalksReducerGUI._finish_activity_poll(gui, payload)

    assert rendered == [[]]
    gui._update_local_server_url_display.assert_not_called()


def test_finish_activity_poll_skips_render_on_error_but_reschedules():
    gui = _make_activity_gui()
    rendered: list = []
    gui._render_activity = lambda entries: rendered.append(entries)

    app.TalksReducerGUI._finish_activity_poll(gui, None)

    assert rendered == []
    gui.root.after.assert_called_once()
    assert gui._activity_poll_job == "job"


def test_finish_activity_poll_stops_when_not_server_managed():
    gui = _make_activity_gui(server_managed=False)
    gui._render_activity = MagicMock()

    app.TalksReducerGUI._finish_activity_poll(gui, None)

    gui.root.after.assert_not_called()
    assert gui._activity_poll_job is None


def test_start_activity_log_noop_in_standalone_mode():
    gui = _make_activity_gui(server_managed=False)
    gui._poll_activity = MagicMock()

    app.TalksReducerGUI._start_activity_log(gui)

    gui._poll_activity.assert_not_called()


def test_start_activity_log_starts_poll_in_server_mode():
    gui = _make_activity_gui()
    gui._poll_activity = MagicMock()

    app.TalksReducerGUI._start_activity_log(gui)

    gui._poll_activity.assert_called_once_with()


def test_start_activity_log_does_not_restart_active_poll():
    gui = _make_activity_gui()
    gui._activity_poll_job = "running"
    gui._poll_activity = MagicMock()

    app.TalksReducerGUI._start_activity_log(gui)

    gui._poll_activity.assert_not_called()


def test_poll_activity_runs_worker_and_finishes(monkeypatch):
    gui = _make_activity_gui()
    gui._fetch_activity = MagicMock(return_value=["entry"])
    finished: list = []
    gui._finish_activity_poll = lambda entries: finished.append(entries)

    class _ImmediateThread:
        def __init__(self, target, daemon=None):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(app.threading, "Thread", _ImmediateThread)

    app.TalksReducerGUI._poll_activity(gui)

    gui._fetch_activity.assert_called_once_with(gui.local_server_url)
    assert finished == [["entry"]]


def test_stop_activity_log_cancels_timer():
    gui = _make_activity_gui()
    gui._activity_poll_job = "job"

    app.TalksReducerGUI._stop_activity_log(gui)

    gui.root.after_cancel.assert_called_once_with("job")
    assert gui._activity_poll_job is None


def test_stop_activity_log_noop_when_idle():
    gui = _make_activity_gui()
    gui._activity_poll_job = None

    app.TalksReducerGUI._stop_activity_log(gui)

    gui.root.after_cancel.assert_not_called()


def test_on_close_cancels_timers_and_destroys():
    gui = _make_activity_gui()
    gui._stop_activity_log = MagicMock()
    gui._cancel_download_wait = MagicMock()
    gui.root = SimpleNamespace(destroy=MagicMock())

    app.TalksReducerGUI._on_close(gui)

    gui._stop_activity_log.assert_called_once_with()
    gui._cancel_download_wait.assert_called_once_with()
    gui.root.destroy.assert_called_once_with()


def _make_server_tray_gui(**overrides):
    """Build a minimal stand-in GUI for ``_apply_server_tray_toggle`` tests."""

    gui = SimpleNamespace(
        server_managed=False,
        _close_for_relaunch=MagicMock(),
        _stop_parent_tray=MagicMock(),
    )
    for key, value in overrides.items():
        setattr(gui, key, value)
    return gui


def test_apply_server_tray_toggle_enable_spawns_and_closes(monkeypatch):
    gui = _make_server_tray_gui(server_managed=False)
    built: list[str] = []
    spawned: list[list[str]] = []
    monkeypatch.setattr(
        app.relaunch,
        "build_app_command",
        lambda mode, **kwargs: built.append(mode) or [mode],
    )
    monkeypatch.setattr(
        app.relaunch, "spawn_detached", lambda command: spawned.append(command)
    )

    app.TalksReducerGUI._apply_server_tray_toggle(gui, True)

    assert built == ["server-tray"]
    assert spawned == [["server-tray"]]
    gui._close_for_relaunch.assert_called_once_with()
    gui._stop_parent_tray.assert_not_called()


def test_apply_server_tray_toggle_enable_noop_when_managed(monkeypatch):
    gui = _make_server_tray_gui(server_managed=True)
    spawned: list[list[str]] = []
    monkeypatch.setattr(
        app.relaunch, "build_app_command", lambda mode, **kwargs: [mode]
    )
    monkeypatch.setattr(
        app.relaunch, "spawn_detached", lambda command: spawned.append(command)
    )

    app.TalksReducerGUI._apply_server_tray_toggle(gui, True)

    assert spawned == []
    gui._close_for_relaunch.assert_not_called()


def test_apply_server_tray_toggle_disable_spawns_gui_and_stops_parent(monkeypatch):
    gui = _make_server_tray_gui(server_managed=True)
    built: list[str] = []
    spawned: list[list[str]] = []
    monkeypatch.setattr(
        app.relaunch,
        "build_app_command",
        lambda mode, **kwargs: built.append(mode) or [mode],
    )
    monkeypatch.setattr(
        app.relaunch, "spawn_detached", lambda command: spawned.append(command)
    )

    app.TalksReducerGUI._apply_server_tray_toggle(gui, False)

    assert built == ["gui"]
    assert spawned == [["gui"]]
    gui._stop_parent_tray.assert_called_once_with()
    gui._close_for_relaunch.assert_called_once_with()


def test_apply_server_tray_toggle_disable_noop_when_not_managed(monkeypatch):
    gui = _make_server_tray_gui(server_managed=False)
    spawned: list[list[str]] = []
    monkeypatch.setattr(
        app.relaunch, "build_app_command", lambda mode, **kwargs: [mode]
    )
    monkeypatch.setattr(
        app.relaunch, "spawn_detached", lambda command: spawned.append(command)
    )

    app.TalksReducerGUI._apply_server_tray_toggle(gui, False)

    assert spawned == []
    gui._close_for_relaunch.assert_not_called()
    gui._stop_parent_tray.assert_not_called()


def test_close_for_relaunch_destroys_window():
    gui = SimpleNamespace(
        _closing=False,
        _stop_activity_log=MagicMock(),
        _cancel_download_wait=MagicMock(),
        root=SimpleNamespace(destroy=MagicMock()),
    )

    app.TalksReducerGUI._close_for_relaunch(gui)

    assert gui._closing is True
    gui._stop_activity_log.assert_called_once_with()
    gui._cancel_download_wait.assert_called_once_with()
    gui.root.destroy.assert_called_once_with()


def test_stop_parent_tray_posix_sends_sigterm(monkeypatch):
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(app.sys, "platform", "linux")
    monkeypatch.setattr(app.os, "getppid", lambda: 4321)
    monkeypatch.setattr(app.os, "kill", lambda pid, sig: killed.append((pid, sig)))

    gui = SimpleNamespace()
    app.TalksReducerGUI._stop_parent_tray(gui)

    assert killed == [(4321, app.signal.SIGTERM)]


def test_stop_parent_tray_windows_uses_taskkill(monkeypatch):
    spawned: list[list[str]] = []
    monkeypatch.setattr(app.sys, "platform", "win32")
    monkeypatch.setattr(app.os, "getppid", lambda: 99)
    monkeypatch.setattr(
        app.relaunch, "spawn_detached", lambda command: spawned.append(command)
    )

    gui = SimpleNamespace()
    app.TalksReducerGUI._stop_parent_tray(gui)

    assert spawned == [["taskkill", "/PID", "99", "/T", "/F"]]


def test_stop_parent_tray_suppresses_errors(monkeypatch):
    monkeypatch.setattr(app.sys, "platform", "linux")
    monkeypatch.setattr(app.os, "getppid", lambda: 1)

    def boom(pid, sig):
        raise OSError("nope")

    monkeypatch.setattr(app.os, "kill", boom)

    gui = SimpleNamespace()
    # Should not raise despite os.kill failing.
    app.TalksReducerGUI._stop_parent_tray(gui)


class _UpdateButtonStub:
    """Records ``configure`` calls so update-flow wiring can be asserted."""

    def __init__(self) -> None:
        self.configure_calls: list[dict] = []

    def configure(self, **kwargs) -> None:
        self.configure_calls.append(kwargs)


def _make_update_complete_gui() -> tuple[SimpleNamespace, _UpdateButtonStub, dict]:
    button = _UpdateButtonStub()
    captured: dict = {}
    gui = SimpleNamespace(
        check_updates_button=button,
        tk=SimpleNamespace(NORMAL="normal", DISABLED="disabled"),
        _check_for_updates=object(),
        _download_and_install_update=object(),
        _clear_update_status=lambda: None,
        _set_update_status=lambda text: captured.update(status=text),
        _set_update_status_with_links=lambda text, links: captured.update(
            text=text, links=links
        ),
    )
    return gui, button, captured


def test_on_update_check_complete_macos_keeps_check_button(monkeypatch):
    """On macOS the button stays a plain "Check updates" and never wires the
    installer download path (the unsigned-installer flow the feature avoids)."""

    from talks_reducer.gui import update_checker

    monkeypatch.setattr(update_checker.sys, "platform", "darwin")
    gui, button, captured = _make_update_complete_gui()

    app.TalksReducerGUI._on_update_check_complete(gui, "9.9.9", None)

    last = button.configure_calls[-1]
    assert last["command"] is gui._check_for_updates
    assert last["command"] is not gui._download_and_install_update
    assert last["text"] == "Check updates"
    assert "brew upgrade --cask talks-reducer" in captured["text"]


def test_on_update_check_complete_windows_wires_download(monkeypatch):
    """On Windows the button becomes the installer-download action."""

    from talks_reducer.gui import update_checker

    monkeypatch.setattr(update_checker.sys, "platform", "win32")
    gui, button, captured = _make_update_complete_gui()

    app.TalksReducerGUI._on_update_check_complete(gui, "9.9.9", None)

    last = button.configure_calls[-1]
    assert last["command"] is gui._download_and_install_update
    assert last["text"] == "Download 9.9.9"
    assert captured["text"] == "New version 9.9.9 is available!"


class _LinkLabelStub:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        self.grid_calls: list[dict] = []
        self.bind_calls: list[tuple] = []
        self.destroyed = False

    def grid(self, **kwargs) -> None:
        self.grid_calls.append(kwargs)

    def bind(self, sequence, callback) -> None:
        self.bind_calls.append((sequence, callback))

    def destroy(self) -> None:
        self.destroyed = True


class _LinkLabelFactory:
    def __init__(self) -> None:
        self.created: list[_LinkLabelStub] = []

    def __call__(self, *args, **kwargs) -> _LinkLabelStub:
        widget = _LinkLabelStub(*args, **kwargs)
        self.created.append(widget)
        return widget


class _StatusLabelStub:
    def __init__(self, grid_info: dict) -> None:
        self._grid_info = grid_info
        self.master = object()
        self.config_calls: list[dict] = []

    def grid_info(self) -> dict:
        return self._grid_info

    def config(self, **kwargs) -> None:
        self.config_calls.append(kwargs)


def test_set_update_status_with_links_places_links_on_status_row():
    """Links must follow the status label's actual grid placement so the macOS
    label at row 8 of the Advanced panel keeps its links beside it instead of
    stranding them at the hardcoded row 0 (top of the panel)."""

    factory = _LinkLabelFactory()
    status_label = _StatusLabelStub({"row": 8, "column": 1, "columnspan": 2})
    gui = SimpleNamespace(
        update_status_label=status_label,
        ttk=SimpleNamespace(Label=factory),
        _resolve_theme_mode=lambda: "light",
    )

    app.TalksReducerGUI._set_update_status_with_links(
        gui,
        "New version 9.9.9 is available!",
        [("Releases page", "https://example.com/releases")],
    )

    assert factory.created, "a clickable link label should be created"
    link = factory.created[-1]
    # Row matches the label (8), and the column starts right after the label's
    # span (column 1 + columnspan 2 == 3), not the old hardcoded row 0/column 3.
    assert link.grid_calls[0]["row"] == 8
    assert link.grid_calls[0]["column"] == 3
    assert link.args[0] is status_label.master
