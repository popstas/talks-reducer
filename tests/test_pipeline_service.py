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
        lambda _input, _frame_rate: {"frame_rate": 30.0, "duration": 2.0, "width": 1920.0, "height": 1080.0},
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

    ffmpeg_calls: List[bool] = []

    def positional_get_ffmpeg_path(flag: bool) -> str:
        ffmpeg_calls.append(flag)
        return "ffmpeg"

    dependencies = PipelineDependencies(
        get_ffmpeg_path=positional_get_ffmpeg_path,
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
    assert ffmpeg_calls == [options.prefer_global_ffmpeg]


def test_speed_up_video_falls_back_to_cpu(monkeypatch, tmp_path):
    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"input")

    options = ProcessingOptions(
        input_file=input_path,
        temp_folder=tmp_path / "temp",
        output_file=tmp_path / "output.mp4",
        prefer_global_ffmpeg=True,
    )

    reporter = DummyReporter()

    def fake_metadata(path, _frame_rate):
        if Path(path) == input_path:
            return {"frame_rate": 24.0, "duration": 4.0, "frame_count": 96, "width": 1920.0, "height": 1080.0}
        return {"frame_rate": 24.0, "duration": 2.0, "frame_count": 48, "width": 1920.0, "height": 1080.0}

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

    ffmpeg_calls: List[bool] = []

    def positional_get_ffmpeg_path(flag: bool) -> str:
        ffmpeg_calls.append(flag)
        return "ffmpeg"

    dependencies = PipelineDependencies(
        get_ffmpeg_path=positional_get_ffmpeg_path,
        check_cuda_available=lambda _path: True,
        build_extract_audio_command=lambda *args, **kwargs: "extract",
        build_video_commands=lambda *args, **kwargs: ("render", "render-cpu", True),
        run_timed_ffmpeg_command=fake_run,
    )

    result = speed_up_video(options, reporter=reporter, dependencies=dependencies)

    assert commands == ["extract", "render", "render-cpu"]
    assert result.output_file.read_bytes() == b"fallback"
    assert any("CUDA encoding failed" in msg for msg in reporter.messages)
    assert ffmpeg_calls == [options.prefer_global_ffmpeg]


def test_speed_up_video_falls_back_without_cuda(monkeypatch, tmp_path):
    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"input")

    options = ProcessingOptions(
        input_file=input_path,
        temp_folder=tmp_path / "temp-copy",
        output_file=tmp_path / "output.mp4",
        optimize=False,
    )

    reporter = DummyReporter()

    monkeypatch.setattr(
        "talks_reducer.pipeline._extract_video_metadata",
        lambda *_args, **_kwargs: {
            "frame_rate": 30.0,
            "duration": 5.0,
            "frame_count": 150,
        },
    )
    monkeypatch.setattr(
        "talks_reducer.pipeline.wavfile.read",
        lambda _path: (48000, np.zeros((60, 1), dtype=np.int16)),
    )
    monkeypatch.setattr(
        "talks_reducer.pipeline.wavfile.write",
        lambda path, sample_rate, data: Path(path).write_bytes(b"audio"),
    )
    monkeypatch.setattr(
        "talks_reducer.pipeline.audio_utils.get_max_volume", lambda _data: 1.0
    )
    monkeypatch.setattr(
        "talks_reducer.pipeline.audio_utils.process_audio_chunks",
        lambda *args, **kwargs: (np.zeros((5, 1)), [[0, 5, 0, 25]]),
    )
    monkeypatch.setattr(
        "talks_reducer.pipeline.chunk_utils.detect_loud_frames",
        lambda *args, **kwargs: np.array([True] * 5),
    )
    monkeypatch.setattr(
        "talks_reducer.pipeline.chunk_utils.build_chunks",
        lambda *_args, **_kwargs: ([[0, 5, 0]], np.array([True] * 5)),
    )
    monkeypatch.setattr(
        "talks_reducer.pipeline.chunk_utils.get_tree_expression",
        lambda _chunks: "X",
    )

    commands: List[str] = []

    def fake_run(command, *args, **kwargs):
        commands.append(command)
        if command == "render-fast":
            raise subprocess.CalledProcessError(1, command)
        if command == "render-cpu":
            options.output_file.write_bytes(b"fallback")
        return None

    dependencies = PipelineDependencies(
        get_ffmpeg_path=lambda flag: "ffmpeg",
        check_cuda_available=lambda _path: False,
        build_extract_audio_command=lambda *args, **kwargs: "extract",
        build_video_commands=lambda *args, **kwargs: (
            "render-fast",
            "render-cpu",
            False,
        ),
        run_timed_ffmpeg_command=fake_run,
    )

    result = speed_up_video(options, reporter=reporter, dependencies=dependencies)

    assert commands == ["extract", "render-fast", "render-cpu"]
    assert result.output_file.read_bytes() == b"fallback"
    assert any("Primary encoder failed" in msg for msg in reporter.messages)


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
        lambda _input, _frame_rate: {"frame_rate": 30.0, "duration": 2.0, "width": 1920.0, "height": 1080.0},
    )

    ffmpeg_calls: List[bool] = []

    def positional_get_ffmpeg_path(flag: bool) -> str:
        ffmpeg_calls.append(flag)
        return "ffmpeg"

    dependencies = PipelineDependencies(
        get_ffmpeg_path=positional_get_ffmpeg_path,
        check_cuda_available=lambda _path: False,
        build_extract_audio_command=lambda *args, **kwargs: "extract",
        build_video_commands=lambda *args, **kwargs: ("render", None, False),
        run_timed_ffmpeg_command=lambda *args, **kwargs: None,
    )

    with pytest.raises(ProcessingAborted):
        speed_up_video(options, reporter=reporter, dependencies=dependencies)

    assert not temp_path.exists()
    assert ffmpeg_calls == [options.prefer_global_ffmpeg]


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
            return {"frame_rate": 25.0, "duration": 5.0, "frame_count": 125, "width": 1920.0, "height": 1080.0}
        return {"frame_rate": 25.0, "duration": 2.0, "frame_count": 50, "width": 1920.0, "height": 1080.0}

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
        get_ffmpeg_path=lambda prefer=False: "ffmpeg",
        check_cuda_available=lambda _path: False,
        build_extract_audio_command=lambda *args, **kwargs: "extract",
        build_video_commands=lambda *args, **kwargs: ("render", None, False),
        run_timed_ffmpeg_command=fake_run,
    )

    result = speed_up_video(options, reporter=reporter, dependencies=dependencies)

    assert result.time_ratio == pytest.approx(0.4)
    assert result.size_ratio == pytest.approx(0.4)


def test_small_mode_preserves_lower_resolution(monkeypatch, tmp_path):
    """When original video height is less than target, it should not be scaled up."""

    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"fake")

    options = ProcessingOptions(
        input_file=input_path,
        temp_folder=tmp_path / "temp",
        output_file=tmp_path / "output.mp4",
        small=True,
        small_target_height=720,
    )

    reporter = DummyReporter()

    # Original video is 480p, which is less than target 720p
    def fake_metadata(path, _frame_rate):
        if Path(path) == input_path:
            return {"frame_rate": 30.0, "duration": 2.0, "frame_count": 60, "width": 854.0, "height": 480.0}
        return {"frame_rate": 30.0, "duration": 2.0, "frame_count": 60, "width": 854.0, "height": 480.0}

    monkeypatch.setattr("talks_reducer.pipeline._extract_video_metadata", fake_metadata)

    def fake_read(_path):
        audio = np.zeros((60, 1), dtype=np.int16)
        return 48000, audio

    monkeypatch.setattr("talks_reducer.pipeline.wavfile.read", fake_read)

    def fake_write(path, sample_rate, data):
        Path(path).write_bytes(b"audio")

    monkeypatch.setattr("talks_reducer.pipeline.wavfile.write", fake_write)

    monkeypatch.setattr(
        "talks_reducer.pipeline.audio_utils.get_max_volume", lambda _data: 1.0
    )
    monkeypatch.setattr(
        "talks_reducer.pipeline.audio_utils.process_audio_chunks",
        lambda *args, **kwargs: (np.zeros((10, 1)), [[0, 10, 0, 60]]),
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
        if command != "extract":
            options.output_file.write_bytes(b"fake")
        return None

    dependencies = PipelineDependencies(
        get_ffmpeg_path=lambda prefer=False: "ffmpeg",
        check_cuda_available=lambda _path: False,
        build_extract_audio_command=lambda *args, **kwargs: "extract",
        build_video_commands=lambda input_file, audio_file, filter_script, output_file, **kwargs: (
            f"ffmpeg -i {input_file} -i {audio_file} -filter_script:v {filter_script} {output_file}",
            None,
            False,
        ),
        run_timed_ffmpeg_command=fake_run,
        delete_path=lambda _path: None,  # Don't delete temp folder so we can inspect it
    )

    speed_up_video(options, reporter=reporter, dependencies=dependencies)

    # Should keep original 480p resolution, not scale to 720p
    assert any("Keeping original resolution" in msg for msg in reporter.messages)
    assert not any("Scaling down from" in msg for msg in reporter.messages)
    
    # Read the actual filter graph file that was created
    filter_graph_path = tmp_path / "temp" / "filterGraph.txt"
    assert filter_graph_path.exists()
    filter_graph = filter_graph_path.read_text()
    # Filter graph should NOT contain scale filter since we keep original resolution
    assert "scale=" not in filter_graph


def test_small_mode_scales_down_when_larger(monkeypatch, tmp_path):
    """When original video height is greater than target, it should scale down."""

    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"fake")

    options = ProcessingOptions(
        input_file=input_path,
        temp_folder=tmp_path / "temp",
        output_file=tmp_path / "output.mp4",
        small=True,
        small_target_height=480,
    )

    reporter = DummyReporter()

    # Original video is 720p, target is 480p
    def fake_metadata(path, _frame_rate):
        if Path(path) == input_path:
            return {"frame_rate": 30.0, "duration": 2.0, "frame_count": 60, "width": 1280.0, "height": 720.0}
        return {"frame_rate": 30.0, "duration": 2.0, "frame_count": 60, "width": 1280.0, "height": 720.0}

    monkeypatch.setattr("talks_reducer.pipeline._extract_video_metadata", fake_metadata)

    def fake_read(_path):
        audio = np.zeros((60, 1), dtype=np.int16)
        return 48000, audio

    monkeypatch.setattr("talks_reducer.pipeline.wavfile.read", fake_read)

    def fake_write(path, sample_rate, data):
        Path(path).write_bytes(b"audio")

    monkeypatch.setattr("talks_reducer.pipeline.wavfile.write", fake_write)

    monkeypatch.setattr(
        "talks_reducer.pipeline.audio_utils.get_max_volume", lambda _data: 1.0
    )
    monkeypatch.setattr(
        "talks_reducer.pipeline.audio_utils.process_audio_chunks",
        lambda *args, **kwargs: (np.zeros((10, 1)), [[0, 10, 0, 60]]),
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
        if command != "extract":
            options.output_file.write_bytes(b"fake")
        return None

    dependencies = PipelineDependencies(
        get_ffmpeg_path=lambda prefer=False: "ffmpeg",
        check_cuda_available=lambda _path: False,
        build_extract_audio_command=lambda *args, **kwargs: "extract",
        build_video_commands=lambda input_file, audio_file, filter_script, output_file, **kwargs: (
            f"ffmpeg -i {input_file} -i {audio_file} -filter_script:v {filter_script} {output_file}",
            None,
            False,
        ),
        run_timed_ffmpeg_command=fake_run,
        delete_path=lambda _path: None,  # Don't delete temp folder so we can inspect it
    )

    speed_up_video(options, reporter=reporter, dependencies=dependencies)

    # Should scale down from 720p to 480p
    assert any("Scaling down from 720p to 480p" in msg for msg in reporter.messages)
    
    # Read the actual filter graph file that was created
    filter_graph_path = tmp_path / "temp" / "filterGraph.txt"
    assert filter_graph_path.exists()
    filter_graph = filter_graph_path.read_text()
    # Filter graph SHOULD contain scale filter
    assert "scale=-2:480" in filter_graph
