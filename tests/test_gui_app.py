"""Tests for helper utilities in :mod:`talks_reducer.gui.app`."""

from __future__ import annotations

from talks_reducer.gui import app


def test_default_remote_destination_with_suffix(tmp_path):
    input_path = tmp_path / "video.mp4"
    input_path.write_text("data")

    result = app._default_remote_destination(input_path, small=False)

    assert result.name == "video_speedup.mp4"


def test_default_remote_destination_without_suffix(tmp_path):
    input_path = tmp_path / "archive"
    input_path.write_text("data")

    result = app._default_remote_destination(input_path, small=True)

    assert result.name == "archive_speedup_small"


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
