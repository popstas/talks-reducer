"""Audio processing helpers for the talks reducer pipeline."""

from __future__ import annotations

import logging
import math
import subprocess
import sys
from typing import Callable, List, Optional, Sequence, Tuple

import numpy as np
from audiotsm import phasevocoder
from audiotsm.io.array import ArrayReader, ArrayWriter

from . import audio_workers
from .ffmpeg import get_ffprobe_path

PARALLEL_MIN_OUTPUT_SAMPLES = 2_000_000
"""Below this much vocoder output the pool costs more to start than it saves."""

_LOGGER = logging.getLogger(__name__)


def get_max_volume(samples: np.ndarray) -> float:
    """Return the maximum absolute volume in the provided sample array."""

    return float(max(-np.min(samples), np.max(samples)))


def is_valid_video_file(filename: str) -> bool:
    """Check whether ``ffprobe`` recognises the input file and finds a video stream."""

    ffprobe_path = get_ffprobe_path()
    command = [
        ffprobe_path,
        "-i",
        filename,
        "-hide_banner",
        "-loglevel",
        "error",
        "-select_streams",
        "v",
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
    return "codec_type=video" in stdout


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


def has_audio_stream(filename: str) -> bool:
    """Check whether the input file contains an audio stream."""

    return is_valid_input_file(filename)


def render_chunk(
    audio_chunk: np.ndarray,
    speed: float,
    audio_fade_envelope_size: int,
    normaliser: float,
) -> np.ndarray:
    """Return one chunk resampled to ``speed``, faded at both ends and normalised.

    This runs both in the pipeline process and inside the worker processes of
    :mod:`talks_reducer.audio_workers`, so it must stay free of pipeline state.
    """

    if math.isclose(speed, 1.0, rel_tol=1e-9, abs_tol=1e-9):
        # A phase vocoder run at speed 1.0 reproduces its input, so the samples
        # are copied instead of paying for the STFT round-trip. The copy is
        # required because the fade envelope below writes in place and must not
        # reach the source array.
        altered_audio_data = audio_chunk.astype(np.float32, copy=True)
    else:
        reader = ArrayReader(np.transpose(audio_chunk))
        writer = ArrayWriter(reader.channels)
        tsm = phasevocoder(reader.channels, speed=speed)
        tsm.run(reader, writer)
        altered_audio_data = np.transpose(writer.data)

    if altered_audio_data.shape[0] < audio_fade_envelope_size:
        altered_audio_data[:] = 0
    else:
        premask = np.arange(audio_fade_envelope_size) / audio_fade_envelope_size
        mask = np.repeat(premask[:, np.newaxis], altered_audio_data.shape[1], axis=1)
        altered_audio_data[:audio_fade_envelope_size] *= mask
        altered_audio_data[-audio_fade_envelope_size:] *= 1 - mask

    return altered_audio_data / normaliser


def _collect_vocoder_jobs(
    chunks: Sequence[Sequence[int]],
    samples_per_frame: float,
    speeds: Sequence[float],
) -> Tuple[List[audio_workers.ChunkJob], int]:
    """Return the chunks needing time-scale modification and their workload.

    Chunks played at normal speed are excluded: copying their samples is cheaper
    than shipping them to a worker process and back. The workload is measured in
    samples the vocoder will *emit*, since its cost scales with the synthesis
    frames it writes — a chunk sped up ten times is a tenth of the work.
    """

    jobs: List[audio_workers.ChunkJob] = []
    estimated_output = 0

    for index, chunk in enumerate(chunks):
        start = int(chunk[0] * samples_per_frame)
        end = int(chunk[1] * samples_per_frame)
        if end <= start:
            continue
        speed = speeds[int(chunk[2])]
        if math.isclose(speed, 1.0, rel_tol=1e-9, abs_tol=1e-9):
            continue
        jobs.append((index, start, end, speed))
        estimated_output += int((end - start) / speed)

    return jobs, estimated_output


def process_audio_chunks(
    audio_data: np.ndarray,
    chunks: Sequence[Sequence[int]],
    samples_per_frame: float,
    speeds: Sequence[float],
    audio_fade_envelope_size: int,
    max_audio_volume: float,
    *,
    batch_size: int = 10,
    progress_callback: Optional[Callable[[int], None]] = None,
    check_stop: Optional[Callable[[], None]] = None,
) -> Tuple[np.ndarray, List[List[int]]]:
    """Return processed audio and updated chunk timings for the provided chunk list.

    When ``progress_callback`` is provided it is invoked once per processed
    chunk with a single unit, zero-length chunks included. Progress is counted
    in chunks rather than samples because the two chunk kinds no longer cost the
    same: a chunk played at normal speed is copied in microseconds while a
    resampled one runs the phase vocoder, so a sample-weighted bar would sprint
    through the copies and then crawl.

    When ``check_stop`` is provided it is invoked once per chunk before the
    blocking phase-vocoder pass; the callback is expected to raise when the user
    requested a stop, so cancellation is honored within a single chunk instead of
    only after the whole audio stage completes.
    """

    normaliser = max(max_audio_volume, 1e-9)

    jobs, estimated_output = _collect_vocoder_jobs(chunks, samples_per_frame, speeds)
    pool = None
    if estimated_output >= PARALLEL_MIN_OUTPUT_SAMPLES:
        pool = audio_workers.open_chunk_pool(
            audio_data,
            jobs,
            audio_fade_envelope_size=audio_fade_envelope_size,
            normaliser=normaliser,
        )

    try:
        return _render_chunk_list(
            audio_data,
            chunks,
            samples_per_frame,
            speeds,
            audio_fade_envelope_size,
            normaliser,
            batch_size=batch_size,
            progress_callback=progress_callback,
            check_stop=check_stop,
            pool=pool,
        )
    finally:
        if pool is not None:
            pool.close()


def _render_chunk_list(
    audio_data: np.ndarray,
    chunks: Sequence[Sequence[int]],
    samples_per_frame: float,
    speeds: Sequence[float],
    audio_fade_envelope_size: int,
    normaliser: float,
    *,
    batch_size: int,
    progress_callback: Optional[Callable[[int], None]],
    check_stop: Optional[Callable[[], None]],
    pool: Optional["audio_workers.ChunkRenderPool"],
) -> Tuple[np.ndarray, List[List[int]]]:
    """Render every chunk in order, taking finished work from ``pool`` when given."""

    audio_buffers: List[np.ndarray] = []
    output_pointer = 0
    updated_chunks: List[List[int]] = [list(chunk) for chunk in chunks]

    for batch_start in range(0, len(chunks), batch_size):
        batch_chunks = chunks[batch_start : batch_start + batch_size]
        batch_audio: List[np.ndarray] = []

        for position, chunk in enumerate(batch_chunks):
            index = batch_start + position
            if check_stop is not None:
                check_stop()
            start = int(chunk[0] * samples_per_frame)
            end = int(chunk[1] * samples_per_frame)
            audio_chunk = audio_data[start:end]

            if audio_chunk.size == 0:
                channels = audio_data.shape[1] if audio_data.ndim > 1 else 1
                batch_audio.append(np.zeros((0, channels)))
                if progress_callback is not None:
                    progress_callback(1)
                continue

            altered_audio_data = None
            if pool is not None and index in pool:
                try:
                    altered_audio_data = pool.result(index)
                except Exception:
                    # Workers can die on their own (a frozen build that cannot
                    # spawn, an out-of-memory kill). Rendering the rest of the
                    # chunks here is slower than the pool but still correct.
                    _LOGGER.debug(
                        "Audio worker pool failed; continuing in-process",
                        exc_info=True,
                    )
                    pool.close()
                    pool = None

            if altered_audio_data is None:
                altered_audio_data = render_chunk(
                    audio_chunk,
                    speeds[int(chunk[2])],
                    audio_fade_envelope_size,
                    normaliser,
                )

            batch_audio.append(altered_audio_data)

            if progress_callback is not None:
                progress_callback(1)

        for position, chunk in enumerate(batch_chunks):
            altered_audio_data = batch_audio[position]
            audio_buffers.append(altered_audio_data)

            end_pointer = output_pointer + altered_audio_data.shape[0]
            start_output_frame = int(math.ceil(output_pointer / samples_per_frame))
            end_output_frame = int(math.ceil(end_pointer / samples_per_frame))

            updated_chunks[batch_start + position] = list(chunk[:2]) + [
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
