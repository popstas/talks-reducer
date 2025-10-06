"""High-level pipeline orchestration for Talks Reducer."""

from __future__ import annotations

import math
import os
import re
import subprocess
from pathlib import Path
from typing import Dict

import numpy as np
from scipy.io import wavfile

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


def _input_to_output_filename(filename: Path, small: bool = False) -> Path:
    dot_index = filename.name.rfind(".")
    suffix = "_speedup_small" if small else "_speedup"
    new_name = (
        filename.name[:dot_index] + suffix + filename.name[dot_index:]
        if dot_index != -1
        else filename.name + suffix
    )
    return filename.with_name(new_name)


def _create_path(path: Path) -> None:
    try:
        path.mkdir()
    except OSError as exc:  # pragma: no cover - defensive logging
        raise AssertionError(
            "Creation of the directory failed. (The TEMP folder may already exist. Delete or rename it, and try again.)"
        ) from exc


def _delete_path(path: Path) -> None:
    import time
    from shutil import rmtree

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
        "format=duration:stream=avg_frame_rate",
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

    return {"frame_rate": frame_rate, "duration": original_duration}


def _ensure_two_dimensional(audio_data: np.ndarray) -> np.ndarray:
    if audio_data.ndim == 1:
        return audio_data[:, np.newaxis]
    return audio_data


def _prepare_output_audio(output_audio_data: np.ndarray) -> np.ndarray:
    if output_audio_data.ndim == 2 and output_audio_data.shape[1] == 1:
        return output_audio_data[:, 0]
    return output_audio_data


def speed_up_video(
    options: ProcessingOptions, reporter: ProgressReporter | None = None
) -> ProcessingResult:
    """Speed up a video by shortening silent sections while keeping sounded sections intact."""

    reporter = reporter or NullProgressReporter()

    input_path = Path(options.input_file)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    ffmpeg_path = get_ffmpeg_path()

    output_path = options.output_file or _input_to_output_filename(
        input_path, options.small
    )
    output_path = Path(output_path)

    cuda_available = check_cuda_available(ffmpeg_path)

    temp_path = Path(options.temp_folder)
    if temp_path.exists():
        _delete_path(temp_path)
    _create_path(temp_path)

    metadata = _extract_video_metadata(input_path, options.frame_rate)
    frame_rate = metadata["frame_rate"]
    original_duration = metadata["duration"]

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

    extract_command = build_extract_audio_command(
        os.fspath(input_path),
        os.fspath(audio_wav),
        options.sample_rate,
        audio_bitrate,
        hwaccel,
        ffmpeg_path=ffmpeg_path,
    )

    reporter.log("Extracting audio...")
    process_callback = getattr(reporter, "process_callback", None)
    run_timed_ffmpeg_command(
        extract_command,
        reporter=reporter,
        total=int(original_duration * frame_rate),
        unit="frames",
        desc="Extracting audio:",
        process_callback=process_callback,
    )

    wav_sample_rate, audio_data = wavfile.read(os.fspath(audio_wav))
    audio_data = _ensure_two_dimensional(audio_data)
    audio_sample_count = audio_data.shape[0]
    max_audio_volume = audio_utils.get_max_volume(audio_data)

    reporter.log("\nProcessing Information:")
    reporter.log(f"- Max Audio Volume: {max_audio_volume}")

    samples_per_frame = wav_sample_rate / frame_rate
    audio_frame_count = int(math.ceil(audio_sample_count / samples_per_frame))

    has_loud_audio = chunk_utils.detect_loud_frames(
        audio_data,
        audio_frame_count,
        samples_per_frame,
        max_audio_volume,
        options.silent_threshold,
    )

    chunks, _ = chunk_utils.build_chunks(has_loud_audio, options.frame_spreadage)

    reporter.log(f"Generated {len(chunks)} chunks")

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
    wavfile.write(
        os.fspath(audio_new_path),
        options.sample_rate,
        _prepare_output_audio(output_audio_data),
    )

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

    command_str, fallback_command_str, use_cuda_encoder = build_video_commands(
        os.fspath(input_path),
        os.fspath(audio_new_path),
        os.fspath(filter_graph_path),
        os.fspath(output_path),
        ffmpeg_path=ffmpeg_path,
        cuda_available=cuda_available,
        small=options.small,
    )

    output_dir = output_path.parent.resolve()
    if output_dir and not output_dir.exists():
        reporter.log(f"Creating output directory: {output_dir}")
        output_dir.mkdir(parents=True, exist_ok=True)

    reporter.log("\nExecuting FFmpeg command:")
    reporter.log(command_str)

    if not audio_new_path.exists():
        _delete_path(temp_path)
        raise FileNotFoundError("Audio intermediate file was not generated")

    if not filter_graph_path.exists():
        _delete_path(temp_path)
        raise FileNotFoundError("Filter graph file was not generated")

    try:
        run_timed_ffmpeg_command(
            command_str,
            reporter=reporter,
            total=updated_chunks[-1][3],
            unit="frames",
            desc="Generating final:",
            process_callback=process_callback,
        )
    except subprocess.CalledProcessError as exc:
        if fallback_command_str and use_cuda_encoder:
            reporter.log("CUDA encoding failed, retrying with CPU encoder...")
            run_timed_ffmpeg_command(
                fallback_command_str,
                reporter=reporter,
                total=updated_chunks[-1][3],
                unit="frames",
                desc="Generating final (fallback):",
                process_callback=process_callback,
            )
        else:
            raise
    finally:
        _delete_path(temp_path)

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
