"""Tests for helper utilities in :mod:`talks_reducer.gui.app`."""

from __future__ import annotations

import math
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
        preferences=SimpleNamespace(update=lambda *args, **kwargs: None),
    )
    gui._parse_float = lambda value, _label: float(value)

    args = app.TalksReducerGUI._collect_arguments(gui)

    assert args["video_codec"] == "av1"
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
        preferences=SimpleNamespace(update=lambda *args, **kwargs: None),
    )
    gui._parse_float = lambda value, _label: float(value)

    args = app.TalksReducerGUI._collect_arguments(gui)

    assert args["add_codec_suffix"] is True
    assert args["prefer_global_ffmpeg"] is False


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
