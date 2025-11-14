"""High-level pipeline orchestration for Talks Reducer."""

from __future__ import annotations

import math
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict

import numpy as np
from scipy.io import wavfile

from talks_reducer.version_utils import resolve_version

from . import audio as audio_utils
from . import chunks as chunk_utils
from .ffmpeg import (
    build_extract_audio_command,
    build_video_commands,
    check_cuda_available,
    get_ffmpeg_path,
    run_timed_ffmpeg_command,
)
from .models import ProcessingOptions, ProcessingResult
from .progress import NullProgressReporter, ProgressReporter


class ProcessingAborted(RuntimeError):
    """Raised when processing is cancelled by the caller."""


@dataclass
class PipelineDependencies:
    """Bundle of external dependencies used by :func:`speed_up_video`."""

    get_ffmpeg_path: Callable[[bool], str] = get_ffmpeg_path
    check_cuda_available: Callable[[str], bool] = check_cuda_available
    build_extract_audio_command: Callable[..., str] = build_extract_audio_command
    build_video_commands: Callable[..., tuple[str, str | None, bool]] = (
        build_video_commands
    )
    run_timed_ffmpeg_command: Callable[..., None] = run_timed_ffmpeg_command
    create_path: Callable[[Path], None] | None = None
    delete_path: Callable[[Path], None] | None = None

    def __post_init__(self) -> None:
        if self.create_path is None:
            self.create_path = _create_path
        if self.delete_path is None:
            self.delete_path = _delete_path


def _invoke_get_ffmpeg_path(
    getter: Callable[..., str], prefer_global: bool
) -> tuple[str, str]:
    """Call a ``get_ffmpeg_path`` dependency while handling legacy signatures.

    Some callables still expect the ``prefer_global`` flag as a positional
    argument, while newer implementations accept only a keyword. This helper
    normalises the call and reports which style ultimately succeeded.
    """

    try:
        path = getter(prefer_global=prefer_global)
    except TypeError as exc:
        # Fallback to positional calls when the dependency rejects the keyword
        # argument. Re-raise unexpected ``TypeError`` instances so we do not hide
        # bugs raised from within the callable itself.
        if "unexpected keyword" not in str(exc):
            raise
        path = getter(prefer_global)
        return path, "positional"

    return path, "keyword"


def _stop_requested(reporter: ProgressReporter | None) -> bool:
    """Return ``True`` when *reporter* indicates that processing should stop."""

    if reporter is None:
        return False

    flag = getattr(reporter, "stop_requested", None)
    if callable(flag):
        try:
            flag = flag()
        except Exception:  # pragma: no cover - defensive
            flag = False
    return bool(flag)


def _raise_if_stopped(
    reporter: ProgressReporter | None,
    *,
    temp_path: Path | None = None,
    dependencies: PipelineDependencies | None = None,
) -> None:
    """Abort processing when the user has requested a stop."""

    if not _stop_requested(reporter):
        return

    if temp_path is not None and temp_path.exists():
        if dependencies is not None:
            dependencies.delete_path(temp_path)
        else:
            _delete_path(temp_path)
    raise ProcessingAborted("Processing aborted by user request.")


def speed_up_video(
    options: ProcessingOptions,
    reporter: ProgressReporter | None = None,
    dependencies: PipelineDependencies | None = None,
) -> ProcessingResult:
    """Speed up a video by shortening silent sections while keeping sounded sections intact."""

    reporter = reporter or NullProgressReporter()
    dependencies = dependencies or PipelineDependencies()

    input_path = Path(options.input_file)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    ffmpeg_path, ffmpeg_call_style = _invoke_get_ffmpeg_path(
        dependencies.get_ffmpeg_path,
        options.prefer_global_ffmpeg,
    )
    preference_label = (
        "global PATH" if options.prefer_global_ffmpeg else "bundled/static"
    )
    reporter.log(
        (
            "FFmpeg preference: {preference} (resolved via {style} call -> {path})"
        ).format(
            preference=preference_label,
            style=ffmpeg_call_style,
            path=ffmpeg_path,
        )
    )

    output_path = options.output_file or _input_to_output_filename(
        input_path,
        options.small,
        options.small_target_height,
        optimize=options.optimize,
        video_codec=options.video_codec,
        add_codec_suffix=options.add_codec_suffix,
        silent_speed=options.silent_speed,
        sounded_speed=options.sounded_speed,
    )
    output_path = Path(output_path)

    cuda_available = dependencies.check_cuda_available(ffmpeg_path)

    temp_path = Path(options.temp_folder)
    if temp_path.exists():
        dependencies.delete_path(temp_path)
    dependencies.create_path(temp_path)

    metadata = _extract_video_metadata(input_path, options.frame_rate)
    frame_rate = metadata["frame_rate"]
    original_duration = metadata["duration"]
    frame_count = metadata.get("frame_count", 0)
    original_width = metadata.get("width", 0)
    original_height = metadata.get("height", 0)

    app_version = resolve_version()
    if app_version and app_version != "unknown":
        reporter.log(f"talks-reducer v{app_version}")

    reporter.log(
        (
            "Source metadata: duration: {duration:.2f}s, frame rate: {fps:.3f} fps,"
            " frames: {frames}, resolution: {width}x{height}"
        ).format(
            duration=original_duration,
            fps=frame_rate,
            frames=frame_count if frame_count > 0 else "unknown",
            width=original_width if original_width > 0 else "unknown",
            height=original_height if original_height > 0 else "unknown",
        )
    )

    reporter.log("Processing on: {}".format("GPU (CUDA)" if cuda_available else "CPU"))
    if options.optimize:
        reporter.log("Optimized encoding enabled")
    else:
        reporter.log("Optimization disabled: using speed-focused encoder preset")
    if options.small:
        target_height = options.small_target_height or 720
        if target_height <= 0:
            target_height = 720
        reporter.log("Small mode scaling to %dp" % target_height)

    # Check if the video has an audio stream
    has_audio = audio_utils.has_audio_stream(os.fspath(input_path))
    if not has_audio:
        reporter.log("No audio stream found. Video will be re-encoded without speed modification.")

    hwaccel = (
        ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"] if cuda_available else []
    )
    process_callback = getattr(reporter, "process_callback", None)
    estimated_total_frames = frame_count
    if estimated_total_frames <= 0 and original_duration > 0 and frame_rate > 0:
        estimated_total_frames = int(math.ceil(original_duration * frame_rate))

    audio_new_path: Path | None = None
    filter_graph_path: Path | None = None
    updated_chunks: list[list[int]] = []
    max_audio_volume = 0.0

    if has_audio:
        # Process with audio-based speed modification
        audio_bitrate = "128k" if options.optimize else "160k"
        audio_wav = temp_path / "audio.wav"
        extraction_sample_rate = options.sample_rate

        extract_command = dependencies.build_extract_audio_command(
            os.fspath(input_path),
            os.fspath(audio_wav),
            extraction_sample_rate,
            audio_bitrate,
            hwaccel,
            ffmpeg_path=ffmpeg_path,
        )

        _raise_if_stopped(reporter, temp_path=temp_path, dependencies=dependencies)
        reporter.log("Extracting audio...")

        if estimated_total_frames > 0:
            reporter.log(f"Extract audio target frames: {estimated_total_frames}")
        else:
            reporter.log("Extract audio target frames: unknown")

        dependencies.run_timed_ffmpeg_command(
            extract_command,
            reporter=reporter,
            total=estimated_total_frames if estimated_total_frames > 0 else None,
            unit="frames",
            desc="Extracting audio:",
            process_callback=process_callback,
        )

        wav_sample_rate, audio_data = wavfile.read(os.fspath(audio_wav))
        audio_data = _ensure_two_dimensional(audio_data)
        audio_sample_count = audio_data.shape[0]
        max_audio_volume = audio_utils.get_max_volume(audio_data)

        reporter.log(f"Max Audio Volume: {max_audio_volume}")

        samples_per_frame = wav_sample_rate / frame_rate
        audio_frame_count = int(math.ceil(audio_sample_count / samples_per_frame))

        _raise_if_stopped(reporter, temp_path=temp_path, dependencies=dependencies)

        has_loud_audio = chunk_utils.detect_loud_frames(
            audio_data,
            audio_frame_count,
            samples_per_frame,
            max_audio_volume,
            options.silent_threshold,
        )

        chunks, _ = chunk_utils.build_chunks(has_loud_audio, options.frame_spreadage)

        reporter.log(f"Processing {len(chunks)} chunks...")

        _raise_if_stopped(reporter, temp_path=temp_path, dependencies=dependencies)

        new_speeds = [options.silent_speed, options.sounded_speed]
        output_audio_data, updated_chunks = audio_utils.process_audio_chunks(
            audio_data,
            chunks,
            samples_per_frame,
            new_speeds,
            options.audio_fade_envelope_size,
            max_audio_volume,
        )

        audio_new_path = temp_path / "audioNew.wav"
        # Use the sample rate that was actually used for processing
        output_sample_rate = extraction_sample_rate
        wavfile.write(
            os.fspath(audio_new_path),
            output_sample_rate,
            _prepare_output_audio(output_audio_data),
        )

        _raise_if_stopped(reporter, temp_path=temp_path, dependencies=dependencies)

        expression = chunk_utils.get_tree_expression(updated_chunks)
        filter_graph_path = temp_path / "filterGraph.txt"
        with open(filter_graph_path, "w", encoding="utf-8") as filter_graph_file:
            filter_parts = []
            if options.small:
                target_height = options.small_target_height or 720
                if target_height <= 0:
                    target_height = 720
                # Only scale down if the original height is greater than or equal to target
                if original_height > 0 and original_height >= target_height:
                    filter_parts.append(f"scale=-2:{target_height}")
                    reporter.log(
                        f"Scaling down from {int(original_height)}p to {target_height}p"
                    )
                else:
                    reporter.log(
                        f"Keeping original resolution {int(original_height)}p (smaller than target {target_height}p)"
                    )
            filter_parts.append(f"fps={frame_rate}")
            escaped_expression = expression.replace(",", "\\,")
            filter_parts.append(f"setpts={escaped_expression}")
            filter_graph_file.write(",".join(filter_parts))
    else:
        # No audio - just re-encode video without speed modification
        filter_parts = []
        if options.small:
            target_height = options.small_target_height or 720
            if target_height <= 0:
                target_height = 720
            # Only scale down if the original height is greater than or equal to target
            if original_height > 0 and original_height >= target_height:
                filter_parts.append(f"scale=-2:{target_height}")
                reporter.log(
                    f"Scaling down from {int(original_height)}p to {target_height}p"
                )
            else:
                reporter.log(
                    f"Keeping original resolution {int(original_height)}p (smaller than target {target_height}p)"
                )
        # Only create filter script if we have filters to apply
        if filter_parts:
            filter_graph_path = temp_path / "filterGraph.txt"
            with open(filter_graph_path, "w", encoding="utf-8") as filter_graph_file:
                filter_graph_file.write(",".join(filter_parts))
        else:
            filter_graph_path = None

    command_str, fallback_command_str, use_cuda_encoder = (
        dependencies.build_video_commands(
            os.fspath(input_path),
            os.fspath(audio_new_path) if audio_new_path else None,
            os.fspath(filter_graph_path) if filter_graph_path else None,
            os.fspath(output_path),
            ffmpeg_path=ffmpeg_path,
            cuda_available=cuda_available,
            optimize=options.optimize,
            small=options.small,
            frame_rate=frame_rate,
            keyframe_interval_seconds=options.keyframe_interval_seconds,
            video_codec=options.video_codec,
        )
    )
    reporter.log(
        (
            "Encoder plan: codec={codec} | CUDA available={cuda} | "
            "using CUDA encoder={using_cuda} | fallback prepared={has_fallback}"
        ).format(
            codec=options.video_codec,
            cuda=cuda_available,
            using_cuda=use_cuda_encoder,
            has_fallback=bool(fallback_command_str),
        )
    )

    output_dir = output_path.parent.resolve()
    if output_dir and not output_dir.exists():
        reporter.log(f"Creating output directory: {output_dir}")
        output_dir.mkdir(parents=True, exist_ok=True)

    reporter.log("\nExecuting FFmpeg command:")
    reporter.log(command_str)

    if has_audio and audio_new_path and not audio_new_path.exists():
        dependencies.delete_path(temp_path)
        raise FileNotFoundError("Audio intermediate file was not generated")

    if filter_graph_path and not filter_graph_path.exists():
        dependencies.delete_path(temp_path)
        raise FileNotFoundError("Filter graph file was not generated")

    _raise_if_stopped(reporter, temp_path=temp_path, dependencies=dependencies)

    try:
        if has_audio and updated_chunks:
            final_total_frames = updated_chunks[-1][3] if updated_chunks else 0
        else:
            # No audio - use original frame count
            final_total_frames = frame_count if frame_count > 0 else 0
            if final_total_frames <= 0 and original_duration > 0 and frame_rate > 0:
                final_total_frames = int(math.ceil(original_duration * frame_rate))

        if final_total_frames > 0:
            reporter.log(f"Final encode target frames: {final_total_frames}")
            if frame_rate > 0:
                final_duration_seconds = final_total_frames / frame_rate
                reporter.log(
                    (
                        "Final encode target duration: {duration:.2f}s at {fps:.3f} fps"
                    ).format(duration=final_duration_seconds, fps=frame_rate)
                )
            else:
                reporter.log(
                    "Final encode target duration: unknown (missing frame rate)"
                )
        else:
            reporter.log("Final encode target frames: unknown")

        total_frames_arg = final_total_frames if final_total_frames > 0 else None

        dependencies.run_timed_ffmpeg_command(
            command_str,
            reporter=reporter,
            total=total_frames_arg,
            unit="frames",
            desc="Generating final:",
            process_callback=process_callback,
        )
    except subprocess.CalledProcessError:
        if fallback_command_str:
            _raise_if_stopped(reporter, temp_path=temp_path, dependencies=dependencies)

            if use_cuda_encoder:
                reporter.log("CUDA encoding failed, retrying with CPU encoder...")
            else:
                reporter.log(
                    "Primary encoder failed, retrying with fallback settings..."
                )
            if final_total_frames > 0:
                reporter.log(
                    f"Final encode target frames (fallback): {final_total_frames}"
                )
            else:
                reporter.log("Final encode target frames (fallback): unknown")
            if final_total_frames > 0 and frame_rate > 0:
                reporter.log(
                    (
                        "Final encode target duration (fallback): {duration:.2f}s at {fps:.3f} fps"
                    ).format(
                        duration=final_total_frames / frame_rate,
                        fps=frame_rate,
                    )
                )
            dependencies.run_timed_ffmpeg_command(
                fallback_command_str,
                reporter=reporter,
                total=total_frames_arg,
                unit="frames",
                desc="Generating final (fallback):",
                process_callback=process_callback,
            )
        else:
            raise
    finally:
        dependencies.delete_path(temp_path)

    output_metadata = _extract_video_metadata(output_path, frame_rate)
    output_duration = output_metadata.get("duration", 0.0)
    time_ratio = output_duration / original_duration if original_duration > 0 else None

    input_size = input_path.stat().st_size if input_path.exists() else 0
    output_size = output_path.stat().st_size if output_path.exists() else 0
    size_ratio = (output_size / input_size) if input_size > 0 else None

    return ProcessingResult(
        input_file=input_path,
        output_file=output_path,
        frame_rate=frame_rate,
        original_duration=original_duration,
        output_duration=output_duration,
        chunk_count=len(updated_chunks) if updated_chunks else 0,
        used_cuda=use_cuda_encoder,
        max_audio_volume=max_audio_volume,
        time_ratio=time_ratio,
        size_ratio=size_ratio,
    )


_DEFAULT_SILENT_SPEED = ProcessingOptions.__dataclass_fields__[  # type: ignore[index]
    "silent_speed"
].default
_DEFAULT_SOUNDED_SPEED = ProcessingOptions.__dataclass_fields__[  # type: ignore[index]
    "sounded_speed"
].default


def _normalize_speed(value: float | None, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):  # pragma: no cover - defensive fallback
        return fallback


def _input_to_output_filename(
    filename: Path,
    small: bool = False,
    small_target_height: int | None = None,
    *,
    optimize: bool = True,
    video_codec: str | None = None,
    add_codec_suffix: bool = False,
    silent_speed: float | None = None,
    sounded_speed: float | None = None,
) -> Path:
    dot_index = filename.name.rfind(".")
    normalized_silent = _normalize_speed(silent_speed, _DEFAULT_SILENT_SPEED)
    normalized_sounded = _normalize_speed(sounded_speed, _DEFAULT_SOUNDED_SPEED)
    neutral_silent = math.isclose(normalized_silent, 1.0, rel_tol=1e-9, abs_tol=1e-9)
    neutral_sounded = math.isclose(normalized_sounded, 1.0, rel_tol=1e-9, abs_tol=1e-9)
    include_speed_marker = not (neutral_silent and neutral_sounded)

    normalized_codec = str(video_codec or "hevc").strip().lower()
    force_codec_suffix = not include_speed_marker and not small
    include_codec_suffix = (add_codec_suffix or force_codec_suffix) and normalized_codec

    suffix_tokens: list[str] = []

    if include_speed_marker:
        suffix_tokens.append("speedup")

    if small:
        suffix_tokens.append("small")

    if small_target_height == 480:
        suffix_tokens.append("480")

    if not optimize and not small:
        suffix_tokens.append("fast")

    if include_codec_suffix:
        suffix_tokens.append(normalized_codec)

    suffix = f"_{'_'.join(suffix_tokens)}" if suffix_tokens else ""
    new_name = (
        filename.name[:dot_index] + suffix + filename.name[dot_index:]
        if dot_index != -1
        else filename.name + suffix
    )
    return filename.with_name(new_name)


def _create_path(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # pragma: no cover - defensive logging
        raise AssertionError(
            "Creation of the directory failed. (The TEMP folder may already exist. Delete or rename it, and try again.)"
        ) from exc


def _delete_path(path: Path) -> None:
    import time
    from shutil import rmtree

    if not path.exists():
        return

    try:
        rmtree(path, ignore_errors=False)
        for i in range(5):
            if not path.exists():
                return
            time.sleep(0.01 * i)
    except OSError as exc:  # pragma: no cover - defensive logging
        print(f"Deletion of the directory {path} failed")
        print(exc)


def _extract_video_metadata(input_file: Path, frame_rate: float) -> Dict[str, float]:
    from .ffmpeg import get_ffprobe_path

    ffprobe_path = get_ffprobe_path()
    command = [
        ffprobe_path,
        "-i",
        os.fspath(input_file),
        "-hide_banner",
        "-loglevel",
        "error",
        "-select_streams",
        "v",
        "-show_entries",
        "format=duration:stream=avg_frame_rate,nb_frames,width,height",
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
        universal_newlines=True,
    )
    stdout, _ = process.communicate()

    match_frame_rate = re.search(r"frame_rate=(\d*)/(\d*)", str(stdout))
    if match_frame_rate is not None:
        frame_rate = float(match_frame_rate.group(1)) / float(match_frame_rate.group(2))

    match_duration = re.search(r"duration=([\d.]*)", str(stdout))
    original_duration = float(match_duration.group(1)) if match_duration else 0.0

    match_frames = re.search(r"nb_frames=(\d+)", str(stdout))
    frame_count = int(match_frames.group(1)) if match_frames else 0

    match_width = re.search(r"width=(\d+)", str(stdout))
    width = int(match_width.group(1)) if match_width else 0

    match_height = re.search(r"height=(\d+)", str(stdout))
    height = int(match_height.group(1)) if match_height else 0

    return {
        "frame_rate": frame_rate,
        "duration": original_duration,
        "frame_count": frame_count,
        "width": float(width),
        "height": float(height),
    }


def _ensure_two_dimensional(audio_data: np.ndarray) -> np.ndarray:
    if audio_data.ndim == 1:
        return audio_data[:, np.newaxis]
    return audio_data


def _prepare_output_audio(output_audio_data: np.ndarray) -> np.ndarray:
    if output_audio_data.ndim == 2 and output_audio_data.shape[1] == 1:
        return output_audio_data[:, 0]
    return output_audio_data
