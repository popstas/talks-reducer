"""Tests for concatenating several inputs into a single glued media file."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any, Dict, List

import pytest

from talks_reducer import glue
from talks_reducer.pipeline import ProcessingAborted


class _RecordingRunner:
    """Collect the FFmpeg commands a concatenation attempts to run."""

    def __init__(self, failures: int = 0) -> None:
        self.commands: List[str] = []
        self.kwargs: List[Dict[str, Any]] = []
        self._failures = failures

    def __call__(self, command: str, **kwargs: Any) -> None:
        self.commands.append(command)
        self.kwargs.append(kwargs)
        if len(self.commands) <= self._failures:
            raise subprocess.CalledProcessError(1, shlex.split(command))


class _StubReporter:
    """Progress reporter capturing log lines and reporting a stop flag."""

    def __init__(self, stop: bool = False) -> None:
        self.messages: List[str] = []
        self.stop_requested = lambda: stop

    def log(self, message: str) -> None:
        self.messages.append(message)


def _make_inputs(tmp_path: Path, count: int = 2, suffix: str = ".mp4") -> List[Path]:
    paths = []
    for index in range(count):
        path = tmp_path / f"part{index + 1}{suffix}"
        path.write_bytes(b"data")
        paths.append(path)
    return paths


def test_build_concat_list_quotes_and_escapes_paths(tmp_path: Path) -> None:
    tricky = tmp_path / "it's a part.mp4"
    plain = tmp_path / "part2.mp4"

    listing = glue.build_concat_list([tricky, plain])

    assert listing.splitlines() == [
        f"file '{tmp_path}/it'\\''s a part.mp4'",
        f"file '{tmp_path}/part2.mp4'",
    ]


def test_concatenate_media_copies_streams_without_reencoding(tmp_path: Path) -> None:
    inputs = _make_inputs(tmp_path)
    destination = tmp_path / "glued.mp4"
    runner = _RecordingRunner()

    result = glue.concatenate_media(
        inputs,
        destination,
        ffmpeg_path="/usr/bin/ffmpeg",
        runner=runner,
    )

    assert result == destination
    assert len(runner.commands) == 1
    command = runner.commands[0]
    assert "-f concat" in command
    assert "-safe 0" in command
    assert "-c copy" in command
    assert str(destination) in command


def test_concatenate_media_removes_the_list_file(tmp_path: Path) -> None:
    inputs = _make_inputs(tmp_path)
    destination = tmp_path / "glued.mp4"

    glue.concatenate_media(
        inputs,
        destination,
        ffmpeg_path="/usr/bin/ffmpeg",
        runner=_RecordingRunner(),
    )

    assert list(tmp_path.glob("*.txt")) == []


def test_concatenate_media_reencodes_when_copying_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(glue, "_has_video_stream", lambda path: True)
    inputs = _make_inputs(tmp_path)
    destination = tmp_path / "glued.mp4"
    runner = _RecordingRunner(failures=1)
    reporter = _StubReporter()

    result = glue.concatenate_media(
        inputs,
        destination,
        ffmpeg_path="/usr/bin/ffmpeg",
        reporter=reporter,
        runner=runner,
    )

    assert result == destination
    assert len(runner.commands) == 2
    fallback = runner.commands[1]
    assert "concat=n=2:v=1:a=1" in fallback
    assert "libx264" in fallback
    assert any("re-encod" in message.lower() for message in reporter.messages)


def test_concatenate_media_reencodes_audio_only_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(glue, "_has_video_stream", lambda path: False)
    inputs = _make_inputs(tmp_path, suffix=".mp3")
    destination = tmp_path / "glued.mp3"
    runner = _RecordingRunner(failures=1)

    glue.concatenate_media(
        inputs,
        destination,
        ffmpeg_path="/usr/bin/ffmpeg",
        runner=runner,
    )

    fallback = runner.commands[1]
    assert "concat=n=2:v=0:a=1" in fallback
    assert "libx264" not in fallback


def test_concatenate_media_aborts_instead_of_retrying_after_stop(
    tmp_path: Path,
) -> None:
    inputs = _make_inputs(tmp_path)
    runner = _RecordingRunner(failures=1)
    reporter = _StubReporter(stop=True)

    with pytest.raises(ProcessingAborted):
        glue.concatenate_media(
            inputs,
            tmp_path / "glued.mp4",
            ffmpeg_path="/usr/bin/ffmpeg",
            reporter=reporter,
            runner=runner,
        )

    assert len(runner.commands) == 1


def test_concatenate_media_requires_two_inputs(tmp_path: Path) -> None:
    inputs = _make_inputs(tmp_path, count=1)

    with pytest.raises(ValueError):
        glue.concatenate_media(
            inputs, tmp_path / "glued.mp4", runner=_RecordingRunner()
        )


def test_prepare_glued_input_names_output_after_the_first_file(tmp_path: Path) -> None:
    inputs = _make_inputs(tmp_path)
    temp_folder = tmp_path / "temp"
    runner = _RecordingRunner()

    glued, temp_dir = glue.prepare_glued_input(
        inputs,
        temp_folder=temp_folder,
        ffmpeg_path="/usr/bin/ffmpeg",
        runner=runner,
    )

    assert glued.name == "part1.mp4"
    assert glued.parent == temp_dir
    assert temp_dir.parent == temp_folder
    assert temp_dir.is_dir()


def test_prepare_glued_input_logs_the_parts(tmp_path: Path) -> None:
    inputs = _make_inputs(tmp_path, count=3)
    reporter = _StubReporter()

    glue.prepare_glued_input(
        inputs,
        temp_folder=tmp_path / "temp",
        ffmpeg_path="/usr/bin/ffmpeg",
        reporter=reporter,
        runner=_RecordingRunner(),
    )

    assert any("3" in message for message in reporter.messages)


def _signature(width: int, height: int) -> Dict[str, Any]:
    return {
        "video": ("h264", width, height),
        "audio": ("aac", "48000", 2),
    }


def test_concatenate_media_skips_copying_mismatched_parts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Copying parts of different sizes yields a broken file, so re-encode."""

    inputs = _make_inputs(tmp_path)
    sizes = {inputs[0]: _signature(320, 240), inputs[1]: _signature(640, 480)}
    monkeypatch.setattr(glue, "_probe_streams", lambda path: sizes[Path(path)])
    runner = _RecordingRunner()
    reporter = _StubReporter()

    glue.concatenate_media(
        inputs,
        tmp_path / "glued.mp4",
        ffmpeg_path="/usr/bin/ffmpeg",
        reporter=reporter,
        runner=runner,
    )

    assert len(runner.commands) == 1
    command = runner.commands[0]
    assert "-c copy" not in command
    assert "scale=320:240" in command
    assert "concat=n=2:v=1:a=1" in command
    assert any("different stream parameters" in m for m in reporter.messages)


def test_concatenate_media_copies_matching_parts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Parts that agree on their parameters are copied without re-encoding."""

    inputs = _make_inputs(tmp_path)
    monkeypatch.setattr(glue, "_probe_streams", lambda path: _signature(320, 240))
    runner = _RecordingRunner()

    glue.concatenate_media(
        inputs,
        tmp_path / "glued.mp4",
        ffmpeg_path="/usr/bin/ffmpeg",
        runner=runner,
    )

    assert len(runner.commands) == 1
    assert "-c copy" in runner.commands[0]


def test_inputs_can_be_copied_allows_unprobeable_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed probe must not force every glue run through a re-encode."""

    monkeypatch.setattr(glue, "_probe_streams", lambda path: None)

    assert glue.inputs_can_be_copied(_make_inputs(tmp_path)) is True
