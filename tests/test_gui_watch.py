"""Tests for :mod:`talks_reducer.gui.watch`."""

from __future__ import annotations

import os
from pathlib import Path

from talks_reducer.gui.watch import (
    POLL_INTERVAL_MS,
    PROCESSED_MARKERS,
    VIDEO_EXTENSIONS,
    is_processed,
    latest_video,
)


def _touch(path: Path, mtime: float) -> Path:
    path.write_bytes(b"data")
    os.utime(path, (mtime, mtime))
    return path


def test_latest_video_returns_newest_by_mtime(tmp_path):
    _touch(tmp_path / "old.mp4", 1000)
    newest = _touch(tmp_path / "new.mkv", 2000)
    _touch(tmp_path / "notes.txt", 3000)  # non-video ignored

    assert latest_video(tmp_path) == newest


def test_latest_video_breaks_ties_by_name(tmp_path):
    a = _touch(tmp_path / "a.mp4", 1000)
    b = _touch(tmp_path / "b.mp4", 1000)

    # Deterministic tie-break: greatest name wins.
    assert latest_video(tmp_path) == max(a, b, key=lambda p: p.name)


def test_latest_video_none_for_empty_dir(tmp_path):
    assert latest_video(tmp_path) is None


def test_latest_video_none_for_missing_dir(tmp_path):
    assert latest_video(tmp_path / "does-not-exist") is None


def test_is_processed_detects_markers():
    assert is_processed(Path("talk_speedup.mp4")) is True
    assert is_processed(Path("talk_small.mp4")) is True
    assert is_processed(Path("talk_SPEEDUP_small.mp4")) is True
    assert is_processed(Path("raw_recording.mp4")) is False


def test_constants_match_contract():
    assert VIDEO_EXTENSIONS == (".mp4", ".mkv", ".mov", ".avi", ".m4v")
    assert PROCESSED_MARKERS == ("_speedup", "_small")
    assert POLL_INTERVAL_MS == 2000
