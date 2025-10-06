"""Tests for the programmatic Talks Reducer pipeline API."""

from __future__ import annotations

from pathlib import Path
from typing import List

import numpy as np

from talks_reducer.models import ProcessingOptions
from talks_reducer.pipeline import ProcessingResult, speed_up_video
from talks_reducer.progress import NullProgressReporter


class DummyReporter(NullProgressReporter):
    """Collects log messages for assertions without printing them."""

    def __init__(self) -> None:
        self.messages: List[str] = []

    def log(self, message: str) -> None:
        self.messages.append(message)


def test_speed_up_video_returns_result(monkeypatch, tmp_path):
    """The pipeline should run end-to-end without invoking the CLI."""

    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"fake")

    temp_path = tmp_path / "temp"

    options = ProcessingOptions(
        input_file=input_path,
        temp_folder=temp_path,
        output_file=tmp_path / "output.mp4",
    )

    reporter = DummyReporter()

    # Stub heavy external dependencies.
    monkeypatch.setattr("talks_reducer.pipeline.get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(
        "talks_reducer.pipeline.check_cuda_available", lambda _path: False
    )
    monkeypatch.setattr(
        "talks_reducer.pipeline._extract_video_metadata",
        lambda _input, _frame_rate: {"frame_rate": 30.0, "duration": 2.0},
    )
    monkeypatch.setattr(
        "talks_reducer.pipeline.build_extract_audio_command",
        lambda *args, **kwargs: "extract",
    )
    monkeypatch.setattr(
        "talks_reducer.pipeline.build_video_commands",
        lambda *args, **kwargs: ("render", None, False),
    )

    def fake_read(_path):
        audio = np.zeros((30, 1), dtype=np.int16)
        return 48000, audio

    monkeypatch.setattr("talks_reducer.pipeline.wavfile.read", fake_read)

    def fake_write(path, sample_rate, data):
        Path(path).write_bytes(b"audio")
        assert sample_rate == options.sample_rate
        assert data.ndim >= 1

    monkeypatch.setattr("talks_reducer.pipeline.wavfile.write", fake_write)

    monkeypatch.setattr(
        "talks_reducer.pipeline.audio_utils.get_max_volume", lambda _data: 1.0
    )
    monkeypatch.setattr(
        "talks_reducer.pipeline.audio_utils.process_audio_chunks",
        lambda *args, **kwargs: (np.zeros((10, 1)), [[0, 10, 0, 10]]),
    )
    monkeypatch.setattr(
        "talks_reducer.pipeline.chunk_utils.detect_loud_frames",
        lambda *args, **kwargs: np.array([True] * 10),
    )
    monkeypatch.setattr(
        "talks_reducer.pipeline.chunk_utils.build_chunks",
        lambda *_args, **_kwargs: ([[0, 10, 0]], np.array([True] * 10)),
    )
    monkeypatch.setattr(
        "talks_reducer.pipeline.chunk_utils.get_tree_expression", lambda _chunks: "X"
    )

    def fake_run(command, *args, **kwargs):
        if command == "render":
            options.output_file.write_bytes(b"fake")
        return None

    monkeypatch.setattr("talks_reducer.pipeline.run_timed_ffmpeg_command", fake_run)

    result = speed_up_video(options, reporter=reporter)

    assert isinstance(result, ProcessingResult)
    assert result.output_file == options.output_file
    assert result.chunk_count == 1
    assert result.time_ratio == 1.0
    assert result.size_ratio == 1.0
    assert reporter.messages  # progress logs should be collected
