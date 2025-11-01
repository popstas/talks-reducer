"""Tests for helper routines in :mod:`talks_reducer.pipeline`."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from talks_reducer import ffmpeg as ffmpeg_module
from talks_reducer import pipeline


@pytest.mark.parametrize(
    "filename, small, small_target_height, add_codec_suffix, video_codec, silent_speed, sounded_speed, expected",
    [
        (
            Path("video.mp4"),
            False,
            None,
            False,
            "hevc",
            None,
            None,
            Path("video_speedup.mp4"),
        ),
        (
            Path("video.mp4"),
            True,
            None,
            False,
            "hevc",
            None,
            None,
            Path("video_speedup_small.mp4"),
        ),
        (
            Path("video.mp4"),
            True,
            720,
            False,
            "hevc",
            None,
            None,
            Path("video_speedup_small.mp4"),
        ),
        (
            Path("video.mp4"),
            True,
            480,
            False,
            "hevc",
            None,
            None,
            Path("video_speedup_small_480.mp4"),
        ),
        (
            Path("video"),
            False,
            None,
            False,
            "hevc",
            None,
            None,
            Path("video_speedup"),
        ),
        (
            Path("video"),
            True,
            480,
            True,
            "h264",
            None,
            None,
            Path("video_speedup_small_480_h264"),
        ),
        (
            Path("clip.mov"),
            False,
            None,
            True,
            "AV1",
            None,
            None,
            Path("clip_speedup_av1.mov"),
        ),
        (
            Path("plain.mp4"),
            False,
            None,
            False,
            "hevc",
            1.0,
            1.0,
            Path("plain_hevc.mp4"),
        ),
        (
            Path("plain.mp4"),
            True,
            None,
            False,
            "hevc",
            1.0,
            1.0,
            Path("plain_small.mp4"),
        ),
        (
            Path("plain.mp4"),
            True,
            480,
            False,
            "hevc",
            1.0,
            1.0,
            Path("plain_small_480.mp4"),
        ),
        (
            Path("plain.mp4"),
            False,
            None,
            True,
            "H264",
            1.0,
            1.0,
            Path("plain_h264.mp4"),
        ),
    ],
)
def test_input_to_output_filename(
    filename: Path,
    small: bool,
    small_target_height: int | None,
    add_codec_suffix: bool,
    video_codec: str,
    silent_speed: float | None,
    sounded_speed: float | None,
    expected: Path,
) -> None:
    """Appending the speedup suffix should respect the ``small`` flag and extension."""

    output = pipeline._input_to_output_filename(
        filename,
        small,
        small_target_height,
        video_codec=video_codec,
        add_codec_suffix=add_codec_suffix,
        silent_speed=silent_speed,
        sounded_speed=sounded_speed,
    )
    assert output == expected


def test_input_to_output_filename_adds_fast_suffix() -> None:
    """Disabling optimization on large runs appends the fast suffix."""

    output = pipeline._input_to_output_filename(
        Path("video.mp4"),
        False,
        None,
        optimize=False,
        video_codec="hevc",
        add_codec_suffix=False,
    )

    assert output == Path("video_speedup_fast.mp4")


def test_input_to_output_filename_orders_fast_before_codec() -> None:
    """The fast suffix should precede the optional codec suffix."""

    output = pipeline._input_to_output_filename(
        Path("clip.mp4"),
        False,
        None,
        optimize=False,
        video_codec="h264",
        add_codec_suffix=True,
    )

    assert output == Path("clip_speedup_fast_h264.mp4")


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
                        "width=1920",
                        "height=1080",
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
    assert metadata["width"] == pytest.approx(1920.0)
    assert metadata["height"] == pytest.approx(1080.0)


def test_stop_requested_handles_callable_and_bool() -> None:
    """The stop helper should respect both callable and boolean flags."""

    assert pipeline._stop_requested(None) is False

    class ReporterWithMethod:
        def __init__(self) -> None:
            self.calls = 0

        def stop_requested(self) -> bool:
            self.calls += 1
            return True

    reporter_callable = ReporterWithMethod()
    assert pipeline._stop_requested(reporter_callable) is True
    assert reporter_callable.calls == 1

    reporter_true = SimpleNamespace(stop_requested=True)
    reporter_false = SimpleNamespace(stop_requested=False)

    assert pipeline._stop_requested(reporter_true) is True
    assert pipeline._stop_requested(reporter_false) is False


def test_raise_if_stopped_cleans_temp_and_raises(tmp_path) -> None:
    """Stopping should delete intermediates and raise ``ProcessingAborted``."""

    temp_path = tmp_path / "intermediates"
    temp_path.mkdir()

    deleted: list[Path] = []

    def record_delete(path: Path) -> None:
        deleted.append(path)

    class Reporter:
        def stop_requested(self) -> bool:
            return True

    dependencies = SimpleNamespace(delete_path=record_delete)

    with pytest.raises(pipeline.ProcessingAborted):
        pipeline._raise_if_stopped(
            Reporter(), temp_path=temp_path, dependencies=dependencies
        )

    assert deleted == [temp_path]


def test_ensure_two_dimensional_expands_mono_audio() -> None:
    """One-dimensional audio arrays should gain an explicit channel axis."""

    mono_audio = np.array([0.1, -0.2, 0.3], dtype=np.float32)

    result = pipeline._ensure_two_dimensional(mono_audio)

    assert result.shape == (3, 1)
    np.testing.assert_allclose(result[:, 0], mono_audio)


def test_prepare_output_audio_squeezes_single_channel() -> None:
    """Two-dimensional mono audio should be flattened for writing."""

    mono_audio = np.array([[0.5], [-0.5], [1.0]], dtype=np.float32)

    result = pipeline._prepare_output_audio(mono_audio)

    assert result.ndim == 1
    np.testing.assert_allclose(result, mono_audio[:, 0])


def test_create_path_builds_nested_directories(tmp_path) -> None:
    """The helper should create the requested directory tree if missing."""

    target = tmp_path / "nested" / "dir"

    assert not target.exists()

    pipeline._create_path(target)

    assert target.exists()
    assert target.is_dir()
