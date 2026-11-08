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
        "video_codec": "hevc",
        "remove_ranges": ((1.0, 2.0),),
    }
    assert args["small"] is True
