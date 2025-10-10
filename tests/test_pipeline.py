"""Tests for helper routines in :mod:`talks_reducer.pipeline`."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from talks_reducer import ffmpeg as ffmpeg_module
from talks_reducer import pipeline


@pytest.mark.parametrize(
    "filename, small, expected",
    [
        (Path("video.mp4"), False, Path("video_speedup.mp4")),
        (Path("video.mp4"), True, Path("video_speedup_small.mp4")),
        (Path("video"), False, Path("video_speedup")),
    ],
)
def test_input_to_output_filename(filename: Path, small: bool, expected: Path) -> None:
    """Appending the speedup suffix should respect the ``small`` flag and extension."""

    output = pipeline._input_to_output_filename(filename, small)
    assert output == expected


def test_extract_video_metadata_uses_ffprobe(monkeypatch) -> None:
    """Metadata should be parsed from ffprobe output for the demo asset."""

    demo_path = Path("docs/assets/demo.mp4").resolve()

    monkeypatch.setattr(ffmpeg_module, "_FFPROBE_PATH", None, raising=False)
    monkeypatch.setattr(ffmpeg_module, "get_ffprobe_path", lambda: "ffprobe")

    captured_commands: list[list[str]] = []

    class DummyProcess:
        def communicate(self) -> tuple[str, str]:
            return (
                "\n".join(
                    [
                        "[STREAM]",
                        "avg_frame_rate=25/1",
                        "nb_frames=125",
                        "[/STREAM]",
                        "[FORMAT]",
                        "duration=5.0",
                        "[/FORMAT]",
                    ]
                ),
                "",
            )

    def fake_popen(command, *args, **kwargs):
        captured_commands.append(list(command))
        assert os.fspath(demo_path) in command
        return DummyProcess()

    monkeypatch.setattr(pipeline.subprocess, "Popen", fake_popen)

    metadata = pipeline._extract_video_metadata(demo_path, frame_rate=30.0)

    assert captured_commands, "ffprobe should be invoked"
    assert metadata["frame_rate"] == pytest.approx(25.0)
    assert metadata["duration"] == pytest.approx(5.0)
    assert metadata["frame_count"] == 125
