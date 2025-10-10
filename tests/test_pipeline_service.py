"""Tests for the programmatic Talks Reducer pipeline API."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List

import numpy as np
import pytest

from talks_reducer.models import ProcessingOptions
from talks_reducer.pipeline import (
    PipelineDependencies,
    ProcessingAborted,
    ProcessingResult,
    speed_up_video,
)
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
    monkeypatch.setattr(
        "talks_reducer.pipeline._extract_video_metadata",
        lambda _input, _frame_rate: {"frame_rate": 30.0, "duration": 2.0},
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

    dependencies = PipelineDependencies(
        get_ffmpeg_path=lambda: "ffmpeg",
        check_cuda_available=lambda _path: False,
        build_extract_audio_command=lambda *args, **kwargs: "extract",
        build_video_commands=lambda *args, **kwargs: ("render", None, False),
        run_timed_ffmpeg_command=fake_run,
    )

    result = speed_up_video(options, reporter=reporter, dependencies=dependencies)

    assert isinstance(result, ProcessingResult)
    assert result.output_file == options.output_file
    assert result.chunk_count == 1
    assert result.time_ratio == 1.0
    assert result.size_ratio == 1.0
    assert reporter.messages  # progress logs should be collected


def test_speed_up_video_falls_back_to_cpu(monkeypatch, tmp_path):
    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"input")

    options = ProcessingOptions(
        input_file=input_path,
        temp_folder=tmp_path / "temp",
        output_file=tmp_path / "output.mp4",
    )

    reporter = DummyReporter()

    def fake_metadata(path, _frame_rate):
        if Path(path) == input_path:
            return {"frame_rate": 24.0, "duration": 4.0, "frame_count": 96}
        return {"frame_rate": 24.0, "duration": 2.0, "frame_count": 48}

    monkeypatch.setattr("talks_reducer.pipeline._extract_video_metadata", fake_metadata)

    def fake_read(_path):
        audio = np.zeros((48, 1), dtype=np.int16)
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
        lambda *args, **kwargs: (np.zeros((10, 1)), [[0, 10, 0, 48]]),
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

    commands: List[str] = []

    def fake_run(command, *args, **kwargs):
        commands.append(command)
        if command == "render":
            raise subprocess.CalledProcessError(1, command)
        if command == "render-cpu":
            options.output_file.write_bytes(b"fallback")
        return None

    dependencies = PipelineDependencies(
        get_ffmpeg_path=lambda: "ffmpeg",
        check_cuda_available=lambda _path: True,
        build_extract_audio_command=lambda *args, **kwargs: "extract",
        build_video_commands=lambda *args, **kwargs: ("render", "render-cpu", True),
        run_timed_ffmpeg_command=fake_run,
    )

    result = speed_up_video(options, reporter=reporter, dependencies=dependencies)

    assert commands == ["extract", "render", "render-cpu"]
    assert result.output_file.read_bytes() == b"fallback"
    assert any("CUDA encoding failed" in msg for msg in reporter.messages)


class ImmediateStopReporter(DummyReporter):
    def stop_requested(self) -> bool:
        return True


def test_speed_up_video_cleans_temp_on_abort(monkeypatch, tmp_path):
    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"input")

    temp_path = tmp_path / "temp"

    options = ProcessingOptions(
        input_file=input_path,
        temp_folder=temp_path,
        output_file=tmp_path / "output.mp4",
    )

    reporter = ImmediateStopReporter()

    monkeypatch.setattr(
        "talks_reducer.pipeline._extract_video_metadata",
        lambda _input, _frame_rate: {"frame_rate": 30.0, "duration": 2.0},
    )

    dependencies = PipelineDependencies(
        get_ffmpeg_path=lambda: "ffmpeg",
        check_cuda_available=lambda _path: False,
        build_extract_audio_command=lambda *args, **kwargs: "extract",
        build_video_commands=lambda *args, **kwargs: ("render", None, False),
        run_timed_ffmpeg_command=lambda *args, **kwargs: None,
    )

    with pytest.raises(ProcessingAborted):
        speed_up_video(options, reporter=reporter, dependencies=dependencies)

    assert not temp_path.exists()


def test_speed_up_video_computes_ratios(monkeypatch, tmp_path):
    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"i" * 1000)

    temp_path = tmp_path / "temp"

    options = ProcessingOptions(
        input_file=input_path,
        temp_folder=temp_path,
        output_file=tmp_path / "output.mp4",
    )

    reporter = DummyReporter()

    def fake_metadata(path, _frame_rate):
        if Path(path) == input_path:
            return {"frame_rate": 25.0, "duration": 5.0, "frame_count": 125}
        return {"frame_rate": 25.0, "duration": 2.0, "frame_count": 50}

    monkeypatch.setattr("talks_reducer.pipeline._extract_video_metadata", fake_metadata)

    def fake_read(_path):
        audio = np.zeros((50, 1), dtype=np.int16)
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
        lambda *args, **kwargs: (np.zeros((10, 1)), [[0, 10, 0, 50]]),
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
            options.output_file.write_bytes(b"o" * 400)
        return None

    dependencies = PipelineDependencies(
        get_ffmpeg_path=lambda: "ffmpeg",
        check_cuda_available=lambda _path: False,
        build_extract_audio_command=lambda *args, **kwargs: "extract",
        build_video_commands=lambda *args, **kwargs: ("render", None, False),
        run_timed_ffmpeg_command=fake_run,
    )

    result = speed_up_video(options, reporter=reporter, dependencies=dependencies)

    assert result.time_ratio == pytest.approx(0.4)
    assert result.size_ratio == pytest.approx(0.4)
