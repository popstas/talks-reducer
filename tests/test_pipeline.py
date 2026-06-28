"""Tests for helper routines in :mod:`talks_reducer.pipeline`."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from talks_reducer import audio as audio_module
from talks_reducer import ffmpeg as ffmpeg_module
from talks_reducer import pipeline
from talks_reducer.models import ProcessingOptions
from talks_reducer.progress import NullProgressReporter


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
            Path("video_speedup.mp4"),
        ),
        (
            Path("video"),
            True,
            480,
            True,
            "h264",
            None,
            None,
            Path("video_speedup_small_480_h264.mp4"),
        ),
        (
            Path("clip.mov"),
            False,
            None,
            True,
            "AV1",
            None,
            None,
            Path("clip_speedup_av1.mp4"),
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
        (
            Path("talk.mp4"),
            False,
            None,
            False,
            "mp3",
            None,
            None,
            Path("talk_speedup.mp3"),
        ),
        (
            Path("talk.mp4"),
            False,
            None,
            False,
            "mp3",
            1.0,
            1.0,
            Path("talk.mp3"),
        ),
        (
            Path("talk.mkv"),
            False,
            None,
            True,
            "MP3",
            None,
            None,
            Path("talk_speedup.mp3"),
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


@pytest.mark.parametrize("video_codec", ["h264", "hevc", "av1", None])
def test_input_to_output_filename_non_mp3_stays_mp4(video_codec) -> None:
    """Only the ``mp3`` codec switches the output extension to ``.mp3``."""

    output = pipeline._input_to_output_filename(
        Path("talk.mkv"),
        False,
        None,
        video_codec=video_codec,
    )

    assert output.suffix == ".mp4"


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


def test_resolve_trim_no_trim_returns_original() -> None:
    """With both bounds at zero the source duration/frame count pass through."""

    options = ProcessingOptions(input_file=Path("video.mp4"))
    reporter = NullProgressReporter()

    result = pipeline._resolve_trim(options, 10.0, 300, 30.0, reporter)

    assert result == (0.0, 0.0, 10.0, 300)


def test_resolve_trim_full_range_scales_effective_span() -> None:
    """A `[start, end]` range yields the trimmed duration and frame count."""

    options = ProcessingOptions(
        input_file=Path("video.mp4"),
        cut_start_seconds=2.0,
        cut_end_seconds=5.0,
    )
    reporter = NullProgressReporter()

    cut_start, cut_end, effective_duration, effective_frames = pipeline._resolve_trim(
        options, 10.0, 300, 30.0, reporter
    )

    assert cut_start == pytest.approx(2.0)
    assert cut_end == pytest.approx(5.0)
    assert effective_duration == pytest.approx(3.0)
    assert effective_frames == 90


def test_resolve_trim_start_only_keeps_until_eof() -> None:
    """A start-only trim keeps everything from the start to the end of file."""

    options = ProcessingOptions(
        input_file=Path("video.mp4"),
        cut_start_seconds=4.0,
    )
    reporter = NullProgressReporter()

    cut_start, cut_end, effective_duration, effective_frames = pipeline._resolve_trim(
        options, 10.0, 300, 30.0, reporter
    )

    assert cut_start == pytest.approx(4.0)
    assert cut_end == pytest.approx(0.0)
    assert effective_duration == pytest.approx(6.0)
    assert effective_frames == 180


def test_resolve_trim_caps_end_at_eof() -> None:
    """An end beyond the duration is capped at the end of the file."""

    options = ProcessingOptions(
        input_file=Path("video.mp4"),
        cut_start_seconds=2.0,
        cut_end_seconds=99.0,
    )
    reporter = NullProgressReporter()

    cut_start, cut_end, effective_duration, effective_frames = pipeline._resolve_trim(
        options, 10.0, 300, 30.0, reporter
    )

    assert cut_start == pytest.approx(2.0)
    assert cut_end == pytest.approx(10.0)
    assert effective_duration == pytest.approx(8.0)
    assert effective_frames == 240


def test_resolve_trim_ignores_empty_range() -> None:
    """A range that collapses to <= 0 length is ignored with a warning."""

    options = ProcessingOptions(
        input_file=Path("video.mp4"),
        cut_start_seconds=8.0,
        cut_end_seconds=3.0,
    )
    reporter = NullProgressReporter()

    result = pipeline._resolve_trim(options, 10.0, 300, 30.0, reporter)

    assert result == (0.0, 0.0, 10.0, 300)


def test_resolve_trim_ignores_start_beyond_duration() -> None:
    """A start at or beyond the duration disables the trim."""

    options = ProcessingOptions(
        input_file=Path("video.mp4"),
        cut_start_seconds=12.0,
    )
    reporter = NullProgressReporter()

    result = pipeline._resolve_trim(options, 10.0, 300, 30.0, reporter)

    assert result == (0.0, 0.0, 10.0, 300)


def test_resolve_trim_unknown_duration_uses_requested_range() -> None:
    """When the source duration is unknown the requested span drives the trim."""

    options = ProcessingOptions(
        input_file=Path("video.mp4"),
        cut_start_seconds=2.0,
        cut_end_seconds=5.0,
    )
    reporter = NullProgressReporter()

    cut_start, cut_end, effective_duration, effective_frames = pipeline._resolve_trim(
        options, 0.0, 0, 30.0, reporter
    )

    assert cut_start == pytest.approx(2.0)
    assert cut_end == pytest.approx(5.0)
    assert effective_duration == pytest.approx(3.0)
    assert effective_frames == 90


def test_resolve_trim_unknown_duration_ignores_empty_range() -> None:
    """An inverted range is ignored even when the source duration is unknown."""

    options = ProcessingOptions(
        input_file=Path("video.mp4"),
        cut_start_seconds=8.0,
        cut_end_seconds=3.0,
    )
    reporter = NullProgressReporter()

    result = pipeline._resolve_trim(options, 0.0, 0, 30.0, reporter)

    assert result == (0.0, 0.0, 0.0, 0)


def _run_no_audio_pipeline(tmp_path, monkeypatch, options_kwargs):
    """Drive ``speed_up_video`` through the no-audio branch with mocks.

    Returns ``(video_kwargs, encode_totals)`` captured from the stubbed
    dependencies so callers can assert on trim wiring and frame estimation.
    """

    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"fake")

    metadata = {
        "frame_rate": 30.0,
        "duration": 10.0,
        "frame_count": 300,
        "width": 1920.0,
        "height": 1080.0,
    }

    def fake_metadata(path, frame_rate):
        return dict(metadata)

    monkeypatch.setattr(pipeline, "_extract_video_metadata", fake_metadata)
    monkeypatch.setattr(audio_module, "has_audio_stream", lambda path: False)

    video_kwargs = {}

    def fake_build_video_commands(*args, **kwargs):
        video_kwargs.update(kwargs)
        return "video-command", None, False

    encode_totals = []

    def fake_run_timed(command, **kwargs):
        encode_totals.append(kwargs.get("total"))

    dependencies = pipeline.PipelineDependencies(
        get_ffmpeg_path=lambda prefer_global=False: "ffmpeg",
        check_cuda_available=lambda ffmpeg_path: False,
        build_video_commands=fake_build_video_commands,
        run_timed_ffmpeg_command=fake_run_timed,
    )

    options = ProcessingOptions(
        input_file=input_file,
        output_file=tmp_path / "output.mp4",
        temp_folder=tmp_path / "temp",
        **options_kwargs,
    )

    pipeline.speed_up_video(options, dependencies=dependencies)

    return video_kwargs, encode_totals


def test_speed_up_video_passes_trim_to_video_command(tmp_path, monkeypatch) -> None:
    """An active trim reaches the video builder and shrinks the frame estimate."""

    video_kwargs, encode_totals = _run_no_audio_pipeline(
        tmp_path,
        monkeypatch,
        {"cut_start_seconds": 2.0, "cut_end_seconds": 5.0},
    )

    assert video_kwargs["cut_start_seconds"] == pytest.approx(2.0)
    assert video_kwargs["cut_end_seconds"] == pytest.approx(5.0)
    # 3s effective span at 30 fps -> 90 frames.
    assert encode_totals == [90]


def test_speed_up_video_no_trim_uses_full_frame_count(tmp_path, monkeypatch) -> None:
    """Without trim the builder receives zeros and the full frame count is used."""

    video_kwargs, encode_totals = _run_no_audio_pipeline(tmp_path, monkeypatch, {})

    assert video_kwargs["cut_start_seconds"] == pytest.approx(0.0)
    assert video_kwargs["cut_end_seconds"] == pytest.approx(0.0)
    assert encode_totals == [300]


def test_speed_up_video_caps_trim_at_eof(tmp_path, monkeypatch) -> None:
    """An end beyond EOF is capped before reaching the video builder."""

    video_kwargs, encode_totals = _run_no_audio_pipeline(
        tmp_path,
        monkeypatch,
        {"cut_start_seconds": 2.0, "cut_end_seconds": 99.0},
    )

    assert video_kwargs["cut_end_seconds"] == pytest.approx(10.0)
    # 8s effective span at 30 fps -> 240 frames.
    assert encode_totals == [240]


def test_speed_up_video_mp3_uses_audio_only_command(tmp_path, monkeypatch) -> None:
    """With ``video_codec="mp3"`` the pipeline renders via the audio-only builder."""

    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"fake")

    metadata = {
        "frame_rate": 30.0,
        "duration": 10.0,
        "frame_count": 300,
        "width": 1920.0,
        "height": 1080.0,
    }

    monkeypatch.setattr(
        pipeline, "_extract_video_metadata", lambda path, frame_rate: dict(metadata)
    )
    monkeypatch.setattr(audio_module, "has_audio_stream", lambda path: True)

    audio_kwargs = {}
    audio_args = {}

    def fake_build_audio_only(input_arg, audio_arg, output_arg, **kwargs):
        audio_args["input"] = input_arg
        audio_args["audio"] = audio_arg
        audio_args["output"] = output_arg
        audio_kwargs.update(kwargs)
        return "audio-only-command"

    def fail_build_video_commands(*args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("build_video_commands should not be called for mp3")

    commands_run = []

    def fake_run_timed(command, **kwargs):
        commands_run.append(command)

    dependencies = pipeline.PipelineDependencies(
        get_ffmpeg_path=lambda prefer_global=False: "ffmpeg",
        check_cuda_available=lambda ffmpeg_path: False,
        build_video_commands=fail_build_video_commands,
        build_audio_only_command=fake_build_audio_only,
        run_timed_ffmpeg_command=fake_run_timed,
    )

    output_file = tmp_path / "output.mp3"
    options = ProcessingOptions(
        input_file=input_file,
        output_file=output_file,
        temp_folder=tmp_path / "temp",
        video_codec="mp3",
        silent_speed=1.0,
        sounded_speed=1.0,
    )

    result = pipeline.speed_up_video(options, dependencies=dependencies)

    assert commands_run == ["audio-only-command"]
    assert audio_args["output"] == os.fspath(output_file)
    assert str(audio_args["output"]).endswith(".mp3")
    assert result.output_file == output_file
    assert result.used_cuda is False


def test_speed_up_video_mp3_without_audio_raises(tmp_path, monkeypatch) -> None:
    """Requesting mp3 output on a file without audio raises a clear error."""

    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"fake")

    metadata = {
        "frame_rate": 30.0,
        "duration": 10.0,
        "frame_count": 300,
        "width": 1920.0,
        "height": 1080.0,
    }

    monkeypatch.setattr(
        pipeline, "_extract_video_metadata", lambda path, frame_rate: dict(metadata)
    )
    monkeypatch.setattr(audio_module, "has_audio_stream", lambda path: False)

    dependencies = pipeline.PipelineDependencies(
        get_ffmpeg_path=lambda prefer_global=False: "ffmpeg",
        check_cuda_available=lambda ffmpeg_path: False,
    )

    options = ProcessingOptions(
        input_file=input_file,
        output_file=tmp_path / "output.mp3",
        temp_folder=tmp_path / "temp",
        video_codec="mp3",
    )

    with pytest.raises(ValueError, match="mp3 output requires an audio stream"):
        pipeline.speed_up_video(options, dependencies=dependencies)


def test_create_path_builds_nested_directories(tmp_path) -> None:
    """The helper should create the requested directory tree if missing."""

    target = tmp_path / "nested" / "dir"

    assert not target.exists()

    pipeline._create_path(target)

    assert target.exists()
    assert target.is_dir()
