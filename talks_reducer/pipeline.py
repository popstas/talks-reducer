"""High-level pipeline orchestration for Talks Reducer."""

from __future__ import annotations

import math
import os
import re
import subprocess
from typing import Dict, Optional

import numpy as np
from scipy.io import wavfile

from . import audio as audio_utils
from . import chunks as chunk_utils
from .ffmpeg import (
    FFMPEG_PATH,
    build_extract_audio_command,
    build_video_commands,
    check_cuda_available,
    run_timed_ffmpeg_command,
)


def _input_to_output_filename(filename: str, small: bool = False) -> str:
    dot_index = filename.rfind(".")
    suffix = "_speedup_small" if small else "_speedup"
    return filename[:dot_index] + suffix + filename[dot_index:]


def _create_path(path: str) -> None:
    try:
        os.mkdir(path)
    except OSError as exc:  # pragma: no cover - defensive logging
        raise AssertionError(
            "Creation of the directory failed. (The TEMP folder may already exist. Delete or rename it, and try again.)"
        ) from exc


def _delete_path(path: str) -> None:
    import time
    from shutil import rmtree

    try:
        rmtree(path, ignore_errors=False)
        for i in range(5):
            if not os.path.exists(path):
                return
            time.sleep(0.01 * i)
    except OSError as exc:  # pragma: no cover - defensive logging
        print(f"Deletion of the directory {path} failed")
        print(exc)


def _extract_video_metadata(input_file: str, frame_rate: float) -> Dict[str, float]:
    command = (
        'ffprobe -i "{}" -hide_banner -loglevel error -select_streams v'
        " -show_entries format=duration:stream=avg_frame_rate".format(input_file)
    )
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
    input_file: str,
    output_file: Optional[str] = None,
    frame_rate: float = 30,
    sample_rate: int = 44100,
    silent_threshold: float = 0.03,
    silent_speed: float = 4.0,
    sounded_speed: float = 1.0,
    frame_spreadage: int = 2,
    audio_fade_envelope_size: int = 400,
    temp_folder: str = "TEMP",
    small: bool = False,
) -> None:
    """Speed up a video by shortening silent sections while keeping sounded sections intact."""

    if output_file is None:
        output_file = _input_to_output_filename(input_file, small)

    cuda_available = check_cuda_available()

    if os.path.exists(temp_folder):
        _delete_path(temp_folder)
    _create_path(temp_folder)

    metadata = _extract_video_metadata(input_file, frame_rate)
    frame_rate = metadata["frame_rate"]
    original_duration = metadata["duration"]

    hwaccel = (
        ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"] if cuda_available else []
    )
    audio_bitrate = "128k" if small else "160k"
    audio_wav = os.path.join(temp_folder, "audio.wav")

    extract_command = build_extract_audio_command(
        input_file,
        audio_wav,
        sample_rate,
        audio_bitrate,
        hwaccel,
    )

    run_timed_ffmpeg_command(
        extract_command,
        total=int(original_duration * frame_rate),
        unit="frames",
        desc="Extracting audio:",
    )

    wav_sample_rate, audio_data = wavfile.read(audio_wav)
    audio_data = _ensure_two_dimensional(audio_data)
    audio_sample_count = audio_data.shape[0]
    max_audio_volume = audio_utils.get_max_volume(audio_data)

    print("\nProcessing Information:")
    print(f"- Max Audio Volume: {max_audio_volume}")
    print(f"- Processing on: {'GPU (CUDA)' if cuda_available else 'CPU'}")
    if small:
        print("- Small mode: 720p video, 128k audio, optimized compression")

    samples_per_frame = wav_sample_rate / frame_rate
    audio_frame_count = int(math.ceil(audio_sample_count / samples_per_frame))

    has_loud_audio = chunk_utils.detect_loud_frames(
        audio_data,
        audio_frame_count,
        samples_per_frame,
        max_audio_volume,
        silent_threshold,
    )

    chunks, _ = chunk_utils.build_chunks(has_loud_audio, frame_spreadage)

    print(f"Generated {len(chunks)} chunks:")
    for index, chunk in enumerate(chunks[:5]):
        print(f"  Chunk {index}: {chunk}")
    if len(chunks) > 5:
        print(f"  ... and {len(chunks) - 5} more chunks")

    new_speeds = [silent_speed, sounded_speed]
    output_audio_data, updated_chunks = audio_utils.process_audio_chunks(
        audio_data,
        chunks,
        samples_per_frame,
        new_speeds,
        audio_fade_envelope_size,
        max_audio_volume,
    )

    audio_new_path = os.path.join(temp_folder, "audioNew.wav")
    wavfile.write(audio_new_path, sample_rate, _prepare_output_audio(output_audio_data))

    expression = chunk_utils.get_tree_expression(updated_chunks)
    filter_graph_path = os.path.join(temp_folder, "filterGraph.txt")
    with open(filter_graph_path, "w", encoding="utf-8") as filter_graph_file:
        filter_parts = []
        if small:
            filter_parts.append("scale=-2:720")
        filter_parts.append(f"fps=fps={frame_rate}")
        filter_parts.append(f'setpts={expression.replace(",", "\\,")}')
        filter_graph_file.write(",".join(filter_parts))

    command_str, fallback_command_str, use_cuda_encoder = build_video_commands(
        input_file,
        audio_new_path,
        filter_graph_path,
        output_file,
        ffmpeg_path=FFMPEG_PATH,
        cuda_available=cuda_available,
        small=small,
    )

    output_dir = os.path.dirname(os.path.abspath(output_file))
    if output_dir and not os.path.exists(output_dir):
        print(f"Creating output directory: {output_dir}")
        os.makedirs(output_dir, exist_ok=True)

    print("\nExecuting FFmpeg command:")
    print(command_str)

    if not os.path.exists(audio_new_path):
        print("ERROR: Audio file not found!")
        _delete_path(temp_folder)
        return

    if not os.path.exists(filter_graph_path):
        print("ERROR: Filter file not found!")
        _delete_path(temp_folder)
        return

    try:
        run_timed_ffmpeg_command(
            command_str,
            total=updated_chunks[-1][3],
            unit="frames",
            desc="Generating final:",
        )
    except subprocess.CalledProcessError as exc:
        if fallback_command_str and use_cuda_encoder:
            print("CUDA encoding failed, retrying with CPU encoder...")
            run_timed_ffmpeg_command(
                fallback_command_str,
                total=updated_chunks[-1][3],
                unit="frames",
                desc="Generating final (fallback):",
            )
        else:
            print(f"\nError running FFmpeg command: {exc}")
            print(
                "Please check if all input files exist and FFmpeg has proper permissions."
            )
            raise
    finally:
        _delete_path(temp_folder)
