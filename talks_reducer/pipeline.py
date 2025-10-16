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

    get_ffmpeg_path: Callable[[], str] = get_ffmpeg_path
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

    ffmpeg_path = dependencies.get_ffmpeg_path()

    output_path = options.output_file or _input_to_output_filename(
        input_path, options.small
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

    app_version = resolve_version()
    if app_version and app_version != "unknown":
        reporter.log(f"talks-reducer v{app_version}")

    reporter.log(
        (
            "Source metadata: duration: {duration:.2f}s, frame rate: {fps:.3f} fps,"
            " frames: {frames}"
        ).format(
            duration=original_duration,
            fps=frame_rate,
            frames=frame_count if frame_count > 0 else "unknown",
        )
    )

    reporter.log("Processing on: {}".format("GPU (CUDA)" if cuda_available else "CPU"))
    if options.small:
        reporter.log(
            "Small mode enabled: 720p video, 128k audio, optimized compression"
        )

    hwaccel = (
        ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"] if cuda_available else []
    )
    audio_bitrate = "128k" if options.small else "160k"
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
    process_callback = getattr(reporter, "process_callback", None)
    estimated_total_frames = frame_count
    if estimated_total_frames <= 0 and original_duration > 0 and frame_rate > 0:
        estimated_total_frames = int(math.ceil(original_duration * frame_rate))

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
            filter_parts.append("scale=-2:720")
        filter_parts.append(f"fps=fps={frame_rate}")
        escaped_expression = expression.replace(",", "\\,")
        filter_parts.append(f"setpts={escaped_expression}")
        filter_graph_file.write(",".join(filter_parts))

    command_str, fallback_command_str, use_cuda_encoder = (
        dependencies.build_video_commands(
            os.fspath(input_path),
            os.fspath(audio_new_path),
            os.fspath(filter_graph_path),
            os.fspath(output_path),
            ffmpeg_path=ffmpeg_path,
            cuda_available=cuda_available,
            small=options.small,
            frame_rate=frame_rate,
        )
    )

    output_dir = output_path.parent.resolve()
    if output_dir and not output_dir.exists():
        reporter.log(f"Creating output directory: {output_dir}")
        output_dir.mkdir(parents=True, exist_ok=True)

    reporter.log("\nExecuting FFmpeg command:")
    reporter.log(command_str)

    if not audio_new_path.exists():
        dependencies.delete_path(temp_path)
        raise FileNotFoundError("Audio intermediate file was not generated")

    if not filter_graph_path.exists():
        dependencies.delete_path(temp_path)
        raise FileNotFoundError("Filter graph file was not generated")

    _raise_if_stopped(reporter, temp_path=temp_path, dependencies=dependencies)

    try:
        final_total_frames = updated_chunks[-1][3] if updated_chunks else 0
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
        if fallback_command_str and use_cuda_encoder:
            _raise_if_stopped(reporter, temp_path=temp_path, dependencies=dependencies)

            reporter.log("CUDA encoding failed, retrying with CPU encoder...")
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
        chunk_count=len(chunks),
        used_cuda=use_cuda_encoder,
        max_audio_volume=max_audio_volume,
        time_ratio=time_ratio,
        size_ratio=size_ratio,
    )


def _input_to_output_filename(filename: Path, small: bool = False) -> Path:
    dot_index = filename.name.rfind(".")
    suffix_parts = []

    if small:
        suffix_parts.append("_small")

    if not suffix_parts:
        suffix_parts.append("")  # Default case

    suffix = "_speedup" + "".join(suffix_parts)
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
        "format=duration:stream=avg_frame_rate,nb_frames",
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

    return {
        "frame_rate": frame_rate,
        "duration": original_duration,
        "frame_count": frame_count,
    }


def _ensure_two_dimensional(audio_data: np.ndarray) -> np.ndarray:
    if audio_data.ndim == 1:
        return audio_data[:, np.newaxis]
    return audio_data


def _prepare_output_audio(output_audio_data: np.ndarray) -> np.ndarray:
    if output_audio_data.ndim == 2 and output_audio_data.shape[1] == 1:
        return output_audio_data[:, 0]
    return output_audio_data
