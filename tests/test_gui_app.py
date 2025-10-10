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
