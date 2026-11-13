"""Tests for the GUI glue around remove-range marks."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from talks_reducer import cut_marks
from talks_reducer.gui import cut_marks_ui


class Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def _gui(tmp_path: Path, files: list[str]):
    logs: list[str] = []
    gui = SimpleNamespace(
        input_files=files,
        remove_ranges=[],
        remove_ranges_text_var=Var(),
        _update_cut_convert_button=lambda: None,
        _append_log=logs.append,
    )
    return gui, logs


def test_current_input_video_needs_exactly_one_file(tmp_path: Path) -> None:
    video = tmp_path / "a.mp4"
    video.write_bytes(b"")

    assert cut_marks_ui.current_input_video(_gui(tmp_path, [str(video)])[0]) == video
    assert cut_marks_ui.current_input_video(_gui(tmp_path, [str(tmp_path)])[0]) is None
    assert cut_marks_ui.current_input_video(_gui(tmp_path, [str(video)] * 2)[0]) is None


def test_load_for_current_input_fills_field(tmp_path: Path) -> None:
    video = tmp_path / "a.mp4"
    video.write_bytes(b"")
    cut_marks.save_marks(video, [(80, 105)])
    gui, _ = _gui(tmp_path, [str(video)])

    cut_marks_ui.load_for_current_input(gui)

    assert gui.remove_ranges == [(80.0, 105.0)]
    assert gui.remove_ranges_text_var.get() == "00:01:20-00:01:45"


def test_commit_text_saves_sidecar(tmp_path: Path) -> None:
    video = tmp_path / "a.mp4"
    video.write_bytes(b"")
    gui, _ = _gui(tmp_path, [str(video)])
    gui.remove_ranges_text_var.set("5-7, 1-2")

    cut_marks_ui.commit_text(gui)

    assert gui.remove_ranges == [(1.0, 2.0), (5.0, 7.0)]
    assert gui.remove_ranges_text_var.get() == "00:00:01-00:00:02, 00:00:05-00:00:07"
    assert cut_marks.load_marks(video) == [(1.0, 2.0), (5.0, 7.0)]


def test_commit_text_rejects_bad_input_and_reverts(tmp_path: Path) -> None:
    video = tmp_path / "a.mp4"
    video.write_bytes(b"")
    gui, logs = _gui(tmp_path, [str(video)])
    cut_marks_ui.set_ranges(gui, [(1.0, 2.0)])
    gui.remove_ranges_text_var.set("garbage")

    cut_marks_ui.commit_text(gui)

    assert gui.remove_ranges == [(1.0, 2.0)]
    assert gui.remove_ranges_text_var.get() == "00:00:01-00:00:02"
    assert any("Invalid remove ranges" in line for line in logs)


def test_remove_only_overrides_keep_codec_and_drop_scaling() -> None:
    args = {
        "silent_speed": 10.0,
        "sounded_speed": 1.5,
        "small": True,
        "small_target_height": 720,
        "max_frame_rate": 30.0,
        "video_codec": "hevc",
        "remove_ranges": ((1.0, 2.0),),
    }

    result = cut_marks_ui.remove_only_overrides(args)

    assert result == {
        "silent_speed": 1.0,
        "sounded_speed": 1.0,
        "vad": False,
        "video_codec": "hevc",
        "remove_ranges": ((1.0, 2.0),),
    }
    assert args["small"] is True


def test_commit_text_unchanged_keeps_sidecar(tmp_path: Path) -> None:
    video = tmp_path / "a.mp4"
    video.write_bytes(b"")
    cut_marks.save_marks(video, [(1, 2)])
    gui, _ = _gui(tmp_path, [str(video)])
    gui.remove_ranges_text_var.set("")

    cut_marks_ui.commit_text(gui)

    assert cut_marks.sidecar_path(video).exists()


def test_commit_text_change_still_saves(tmp_path: Path) -> None:
    video = tmp_path / "a.mp4"
    video.write_bytes(b"")
    cut_marks.save_marks(video, [(1, 2)])
    gui, _ = _gui(tmp_path, [str(video)])
    cut_marks_ui.load_for_current_input(gui)
    gui.remove_ranges_text_var.set("")

    cut_marks_ui.commit_text(gui)

    assert not cut_marks.sidecar_path(video).exists()


def test_commit_text_logs_and_keeps_ranges_when_save_fails(
    tmp_path: Path, monkeypatch
) -> None:
    video = tmp_path / "a.mp4"
    video.write_bytes(b"")
    gui, logs = _gui(tmp_path, [str(video)])
    gui.remove_ranges_text_var.set("5-7")

    def boom(*_args, **_kwargs):
        raise OSError("read-only")

    monkeypatch.setattr(cut_marks, "save_marks", boom)

    cut_marks_ui.commit_text(gui)

    assert gui.remove_ranges == [(5.0, 7.0)]
    assert any("Could not save cut marks" in line for line in logs)


def test_apply_player_result_saves_and_shows_ranges(tmp_path: Path) -> None:
    video = tmp_path / "a.mp4"
    video.write_bytes(b"")
    gui, _ = _gui(tmp_path, [str(video)])

    cut_marks_ui.apply_player_result(gui, video, [(3.0, 4.0)])

    assert cut_marks.load_marks(video) == [(3.0, 4.0)]
    assert gui.remove_ranges == [(3.0, 4.0)]


def test_apply_player_result_keeps_sidecar_when_result_unreadable(
    tmp_path: Path,
) -> None:
    video = tmp_path / "a.mp4"
    video.write_bytes(b"")
    cut_marks.save_marks(video, [(1, 2)])
    gui, logs = _gui(tmp_path, [str(video)])
    cut_marks_ui.load_for_current_input(gui)

    cut_marks_ui.apply_player_result(gui, video, None)

    assert cut_marks.load_marks(video) == [(1.0, 2.0)]
    assert gui.remove_ranges == [(1.0, 2.0)]
    assert any("unreadable" in line.lower() for line in logs)


def test_apply_player_result_empty_list_clears_sidecar(tmp_path: Path) -> None:
    video = tmp_path / "a.mp4"
    video.write_bytes(b"")
    cut_marks.save_marks(video, [(1, 2)])
    gui, _ = _gui(tmp_path, [str(video)])

    cut_marks_ui.apply_player_result(gui, video, [])

    assert not cut_marks.sidecar_path(video).exists()
    assert gui.remove_ranges == []


def test_apply_player_result_logs_save_failure_but_updates_field(
    tmp_path: Path, monkeypatch
) -> None:
    video = tmp_path / "a.mp4"
    video.write_bytes(b"")
    gui, logs = _gui(tmp_path, [str(video)])

    def boom(*_args, **_kwargs):
        raise OSError("locked")

    monkeypatch.setattr(cut_marks, "save_marks", boom)

    cut_marks_ui.apply_player_result(gui, video, [(3.0, 4.0)])

    assert gui.remove_ranges == [(3.0, 4.0)]
    assert any("Could not save cut marks" in line for line in logs)


def test_remove_only_overrides_turn_voice_detection_off() -> None:
    """A remove-only pass must not run VAD: speeds are 1, so it would only cost."""

    args = {
        "silent_speed": 10.0,
        "sounded_speed": 1.0,
        "vad": True,
        "vad_threshold": 0.4,
        "vad_padding_ms": 200,
        "vad_min_silence_ms": 500,
        "remove_ranges": ((1.0, 2.0),),
    }

    result = cut_marks_ui.remove_only_overrides(args)

    assert result == {
        "silent_speed": 1.0,
        "sounded_speed": 1.0,
        "vad": False,
        "remove_ranges": ((1.0, 2.0),),
    }
    assert args["vad"] is True
