"""Tests for the GUI log conversion header and summary formatters."""

from __future__ import annotations

from pathlib import Path

import pytest

from talks_reducer.gui import summaries
from talks_reducer.gui.summaries import (
    format_conversion_header,
    format_conversion_params,
    format_conversion_summary,
    format_file_size,
    measure_media,
)


def test_header_lists_effective_settings() -> None:
    args = {
        "small": True,
        "small_target_height": 480,
        "video_codec": "hevc",
        "max_frame_rate": 30.0,
        "silent_speed": 10.0,
        "sounded_speed": 1.0,
        "silent_threshold": 0.01,
        "vad": False,
    }

    assert format_conversion_header("VID.mp4", args) == (
        "### Processing VID.mp4: 480p, h.265, 30 fps, silent ×10, sounded ×1, "
        "threshold 0.01"
    )


def test_header_vad_replaces_threshold_and_orig_defaults() -> None:
    args = {
        "video_codec": "h264",
        "silent_speed": 5.0,
        "sounded_speed": 1.3,
        "silent_threshold": 0.05,
        "vad": True,
    }

    assert format_conversion_params(args) == (
        "orig, h.264, orig fps, silent ×5, sounded ×1.3, no voice"
    )


def test_header_lists_long_pauses_after_threshold() -> None:
    args = {
        "video_codec": "h264",
        "silent_speed": 10.0,
        "sounded_speed": 1.0,
        "silent_threshold": 0.01,
        "long_pause_speed": 20.0,
        "long_pause_seconds": 60.0,
    }

    assert format_conversion_params(args) == (
        "orig, h.264, orig fps, silent ×10, sounded ×1, threshold 0.01, "
        "long pauses ×20 >60s"
    )


def test_header_mp3_omits_video_fields() -> None:
    args = {
        "small": True,
        "small_target_height": 720,
        "video_codec": "mp3",
        "max_frame_rate": 30.0,
        "silent_speed": 10.0,
        "sounded_speed": 1.0,
        "silent_threshold": 0.01,
    }

    assert format_conversion_params(args) == (
        "mp3, silent ×10, sounded ×1, threshold 0.01"
    )


def test_header_cut_and_remove() -> None:
    args = {
        "video_codec": "h264",
        "cut_start_seconds": 65.0,
        "cut_end_seconds": 0.0,
        "remove_ranges": ((1.0, 2.0), (3.0, 4.0)),
    }

    assert format_conversion_params(args).endswith("cut 00:01:05–end, remove 2 ranges")


def test_header_single_remove_range_is_singular() -> None:
    args = {"video_codec": "h264", "remove_ranges": ((1.0, 2.0),)}

    assert format_conversion_params(args).endswith("remove 1 range")


def test_header_minimal_args_lists_only_codec() -> None:
    assert format_conversion_header("a.mp4", {"video_codec": "mp3"}) == (
        "### Processing a.mp4: mp3"
    )
    assert format_conversion_params({"video_codec": "mp3"}) == "mp3"


def test_summary_matches_spec_example() -> None:
    lines = format_conversion_summary(
        Path("C:/v/out.mp4"),
        elapsed_seconds=682,
        time_ratio=0.9931,
        output_duration=733,
        size_ratio=0.0157,
        output_size=int(1.5 * 1024 * 1024),
    )

    assert lines[0].startswith("Completed: ")
    assert lines[0].endswith("out.mp4")
    assert lines[1] == (
        "Duration: 00:11:22, Time: 99.31% (00:12:13), Size: 1.57% (1.5 MB)"
    )


def test_summary_degrades_when_ratios_unknown() -> None:
    lines = format_conversion_summary(
        Path("out.mp4"),
        elapsed_seconds=5,
        time_ratio=None,
        output_duration=None,
        size_ratio=None,
        output_size=None,
    )

    assert lines[1] == "Duration: 00:00:05"


def test_summary_is_one_line_when_nothing_is_known() -> None:
    lines = format_conversion_summary(
        Path("out.mp4"),
        elapsed_seconds=None,
        time_ratio=None,
        output_duration=None,
        size_ratio=None,
        output_size=None,
    )

    assert len(lines) == 1


def test_format_file_size_default_keeps_status_bar_shape() -> None:
    assert format_file_size(1536) == "1.5KB"
    assert format_file_size(1536, sep=" ") == "1.5 KB"


def test_measure_media_missing_file_does_not_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_args: object) -> float:
        pytest.fail("probed a missing file")

    monkeypatch.setattr(summaries, "get_video_duration", fail)

    assert measure_media(tmp_path / "absent.mp4") == (None, None)


def test_measure_media_reads_size_and_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"x" * 100)
    monkeypatch.setattr(summaries, "get_video_duration", lambda *_: 12.5)

    assert measure_media(media) == (12.5, 100)


def test_measure_media_zero_duration_is_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"x")
    monkeypatch.setattr(summaries, "get_video_duration", lambda *_: 0.0)

    assert measure_media(media) == (None, 1)


def test_measure_media_probe_error_degrades_to_unknown_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A blocked or undecodable ffprobe must not fail a finished download."""

    media = tmp_path / "clip.mp4"
    media.write_bytes(b"x" * 4)

    def blocked(*_args: object) -> float:
        raise PermissionError("ffprobe.exe locked")

    monkeypatch.setattr(summaries, "get_video_duration", blocked)

    assert measure_media(media) == (None, 4)
