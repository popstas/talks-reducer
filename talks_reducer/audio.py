"""Audio processing helpers for the talks reducer pipeline."""

from __future__ import annotations

import math
import subprocess
import sys
from typing import List, Sequence, Tuple

import numpy as np
from audiotsm import phasevocoder
from audiotsm.io.array import ArrayReader, ArrayWriter

from .ffmpeg import get_ffprobe_path


def get_max_volume(samples: np.ndarray) -> float:
    """Return the maximum absolute volume in the provided sample array."""

    return float(max(-np.min(samples), np.max(samples)))


def is_valid_input_file(filename: str) -> bool:
    """Check whether ``ffprobe`` recognises the input file and finds an audio stream."""

    ffprobe_path = get_ffprobe_path()
    command = [
        ffprobe_path,
        "-i",
        filename,
        "-hide_banner",
        "-loglevel",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=codec_type",
    ]

    # Hide console window on Windows
    creationflags = 0
    if sys.platform == "win32":
        # CREATE_NO_WINDOW = 0x08000000
        creationflags = 0x08000000

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired:
        print("Timeout while checking the input file. Aborting. Command:")
        print(" ".join(command))
        return False

    if result.returncode != 0:
        return False

    stdout = result.stdout or ""
    return "codec_type=audio" in stdout


def process_audio_chunks(
    audio_data: np.ndarray,
    chunks: Sequence[Sequence[int]],
    samples_per_frame: float,
    speeds: Sequence[float],
    audio_fade_envelope_size: int,
    max_audio_volume: float,
    *,
    batch_size: int = 10,
) -> Tuple[np.ndarray, List[List[int]]]:
    """Return processed audio and updated chunk timings for the provided chunk list."""

    audio_buffers: List[np.ndarray] = []
    output_pointer = 0
    updated_chunks: List[List[int]] = [list(chunk) for chunk in chunks]
    normaliser = max(max_audio_volume, 1e-9)

    for batch_start in range(0, len(chunks), batch_size):
        batch_chunks = chunks[batch_start : batch_start + batch_size]
        batch_audio: List[np.ndarray] = []

        for chunk in batch_chunks:
            start = int(chunk[0] * samples_per_frame)
            end = int(chunk[1] * samples_per_frame)
            audio_chunk = audio_data[start:end]

            if audio_chunk.size == 0:
                channels = audio_data.shape[1] if audio_data.ndim > 1 else 1
                batch_audio.append(np.zeros((0, channels)))
                continue

            reader = ArrayReader(np.transpose(audio_chunk))
            writer = ArrayWriter(reader.channels)
            tsm = phasevocoder(reader.channels, speed=speeds[int(chunk[2])])
            tsm.run(reader, writer)
            altered_audio_data = np.transpose(writer.data)

            if altered_audio_data.shape[0] < audio_fade_envelope_size:
                altered_audio_data[:] = 0
            else:
                premask = np.arange(audio_fade_envelope_size) / audio_fade_envelope_size
                mask = np.repeat(
                    premask[:, np.newaxis], altered_audio_data.shape[1], axis=1
                )
                altered_audio_data[:audio_fade_envelope_size] *= mask
                altered_audio_data[-audio_fade_envelope_size:] *= 1 - mask

            batch_audio.append(altered_audio_data / normaliser)

        for index, chunk in enumerate(batch_chunks):
            altered_audio_data = batch_audio[index]
            audio_buffers.append(altered_audio_data)

            end_pointer = output_pointer + altered_audio_data.shape[0]
            start_output_frame = int(math.ceil(output_pointer / samples_per_frame))
            end_output_frame = int(math.ceil(end_pointer / samples_per_frame))

            updated_chunks[batch_start + index] = list(chunk[:2]) + [
                start_output_frame,
                end_output_frame,
            ]
            output_pointer = end_pointer

    if audio_buffers:
        output_audio_data = np.concatenate(audio_buffers)
    else:
        channels = audio_data.shape[1] if audio_data.ndim > 1 else 1
        output_audio_data = np.zeros((0, channels))

    return output_audio_data, updated_chunks
