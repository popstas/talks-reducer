"""Tests for :mod:`talks_reducer.gui.watch`."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

from talks_reducer.gui.watch import (
    POLL_INTERVAL_MS,
    PROCESSED_MARKERS,
    VIDEO_EXTENSIONS,
    WatchController,
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


class _FakeButton:
    def __init__(self):
        self.visible = False
        self.kwargs: dict = {}

    def configure(self, **kwargs):
        self.kwargs.update(kwargs)

    def grid(self):
        self.visible = True

    def grid_remove(self):
        self.visible = False

    def winfo_viewable(self):
        return self.visible


def _make_watch_gui(tmp_path, *, enabled=True):
    started: list[bool] = []
    opened: list[Path] = []
    restored: list[bool] = []
    inputs = SimpleNamespace(
        cleared=[],
        extended=[],
        clear_input_files=lambda: inputs.cleared.append(True),
        extend_inputs=lambda paths, **kw: inputs.extended.append(list(paths)),
    )
    gui = SimpleNamespace(
        root=SimpleNamespace(after=lambda *_: "id", after_cancel=lambda *_: None),
        watch_enabled_var=SimpleNamespace(get=lambda: enabled),
        watch_directory_var=SimpleNamespace(get=lambda: str(tmp_path)),
        watch_button=_FakeButton(),
        stop_button=_FakeButton(),
        open_button=_FakeButton(),
        drop_hint_button=_FakeButton(),
        inputs=inputs,
        _start_run=lambda: started.append(True),
        _open_in_file_manager=lambda path: opened.append(path),
        _restore_default_action_button=lambda: restored.append(True),
        _is_run_active=lambda: False,
    )
    gui._started = started
    gui._opened = opened
    gui._restored = restored
    return gui


def test_refresh_button_shows_convert_for_raw_file(tmp_path):
    _touch(tmp_path / "raw.mp4", 1000)
    gui = _make_watch_gui(tmp_path)

    WatchController(gui).refresh_candidate()

    assert gui.watch_button.visible is True
    assert gui.watch_button.kwargs["text"] == "Convert raw.mp4"
    assert gui.open_button.visible is False


def test_refresh_button_shows_open_last_for_processed_file(tmp_path):
    _touch(tmp_path / "raw_speedup.mp4", 1000)
    gui = _make_watch_gui(tmp_path)

    WatchController(gui).refresh_candidate()

    assert gui.watch_button.kwargs["text"] == "Open last"


def test_refresh_button_hides_and_restores_when_no_candidate(tmp_path):
    gui = _make_watch_gui(tmp_path)  # empty dir

    WatchController(gui).refresh_candidate()

    assert gui.watch_button.visible is False
    assert gui._restored == [True]


def test_convert_latest_clears_inputs_and_runs(tmp_path):
    _touch(tmp_path / "raw.mp4", 1000)
    gui = _make_watch_gui(tmp_path)
    controller = WatchController(gui)
    controller.refresh_candidate()

    controller.convert_latest()

    assert gui.inputs.cleared == [True]
    assert gui.inputs.extended == [[str(tmp_path / "raw.mp4")]]
    assert gui._started == [True]


def test_open_latest_reveals_candidate(tmp_path):
    processed = _touch(tmp_path / "raw_speedup.mp4", 1000)
    gui = _make_watch_gui(tmp_path)
    controller = WatchController(gui)
    controller.refresh_candidate()

    controller.open_latest()

    assert gui._opened == [processed]


def test_refresh_button_yields_slot_to_active_run(tmp_path):
    _touch(tmp_path / "raw.mp4", 1000)
    gui = _make_watch_gui(tmp_path)
    gui.stop_button.grid()  # a run is active
    gui._is_run_active = lambda: True

    WatchController(gui).refresh_candidate()

    assert gui.watch_button.visible is False
