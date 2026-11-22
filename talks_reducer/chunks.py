"""Chunk creation utilities used by the talks reducer pipeline."""

from __future__ import annotations

from typing import List, Sequence, Tuple

import numpy as np

from .audio import get_max_volume


def detect_loud_frames(
    audio_data: np.ndarray,
    audio_frame_count: int,
    samples_per_frame: float,
    max_audio_volume: float,
    silent_threshold: float,
) -> np.ndarray:
    """Return a boolean array indicating which frames contain loud audio."""

    normaliser = max(max_audio_volume, 1e-9)
    has_loud_audio = np.zeros(audio_frame_count, dtype=bool)

    for frame_index in range(audio_frame_count):
        start = int(frame_index * samples_per_frame)
        end = min(int((frame_index + 1) * samples_per_frame), audio_data.shape[0])
        audio_chunk = audio_data[start:end]
        chunk_max_volume = float(get_max_volume(audio_chunk)) / normaliser
        if chunk_max_volume >= silent_threshold:
            has_loud_audio[frame_index] = True

    return has_loud_audio


def build_chunks(
    has_loud_audio: np.ndarray, frame_spreadage: int
) -> Tuple[List[List[int]], np.ndarray]:
    """Return chunks describing which frame ranges should be retained."""

    audio_frame_count = len(has_loud_audio)
    chunks: List[List[int]] = [[0, 0, 0]]
    should_include_frame = np.zeros(audio_frame_count, dtype=bool)

    for frame_index in range(audio_frame_count):
        start = int(max(0, frame_index - frame_spreadage))
        end = int(min(audio_frame_count, frame_index + 1 + frame_spreadage))
        should_include_frame[frame_index] = np.any(has_loud_audio[start:end])
        if (
            frame_index >= 1
            and should_include_frame[frame_index]
            != should_include_frame[frame_index - 1]
        ):
            chunks.append(
                [chunks[-1][1], frame_index, int(should_include_frame[frame_index - 1])]
            )

    chunks.append(
        [
            chunks[-1][1],
            audio_frame_count,
            int(should_include_frame[audio_frame_count - 1]),
        ]
    )
    return chunks[1:], should_include_frame


REMOVED_SPEED_INDEX = 2


def apply_remove_ranges(
    chunks: Sequence[Sequence[int]],
    ranges: Sequence[Tuple[float, float]],
    frame_rate: float,
) -> List[List[int]]:
    """Split *chunks* at the remove ranges and mark the pieces inside them.

    Chunks are ``[start_frame, end_frame, speed_index]`` in source frames.
    Each range in seconds becomes ``[round(start * fps), round(end * fps))``;
    pieces inside a range get :data:`REMOVED_SPEED_INDEX`, whose speed the
    pipeline sets to infinity so the piece produces no output. Adjacent removed
    pieces are merged and zero-length pieces are never emitted.
    """

    if not ranges or frame_rate <= 0:
        return [list(chunk) for chunk in chunks]

    frame_ranges = sorted(
        (max(0, int(round(start * frame_rate))), int(round(end * frame_rate)))
        for start, end in ranges
    )
    frame_ranges = [(a, b) for a, b in frame_ranges if b > a]

    pieces: List[List[int]] = []
    for chunk in chunks:
        start, end, speed = int(chunk[0]), int(chunk[1]), int(chunk[2])
        cursor = start
        for cut_start, cut_end in frame_ranges:
            if cut_end <= cursor or cut_start >= end:
                continue
            if cut_start > cursor:
                pieces.append([cursor, cut_start, speed])
            piece_end = min(cut_end, end)
            pieces.append([max(cut_start, cursor), piece_end, REMOVED_SPEED_INDEX])
            cursor = piece_end
        if cursor < end:
            pieces.append([cursor, end, speed])

    merged: List[List[int]] = []
    for piece in pieces:
        if (
            merged
            and piece[2] == REMOVED_SPEED_INDEX
            and merged[-1][2] == REMOVED_SPEED_INDEX
            and merged[-1][1] == piece[0]
        ):
            merged[-1][1] = piece[1]
        else:
            merged.append(piece)
    return merged


LONG_PAUSE_SPEED_INDEX = 3
LONG_PAUSE_SOUND_TOLERANCE_SECONDS = 2.0


def apply_long_pauses(
    chunks: Sequence[Sequence[int]], min_frames: int, tolerance_frames: int
) -> List[List[int]]:
    """Relabel silent stretches of at least *min_frames* as long pauses.

    *chunks* come from :func:`build_chunks` (``[start, end, speed_index]``,
    alternating silent ``0`` and sounded ``1``). A stretch starts and ends with
    a silent chunk and may contain sounded chunks no longer than
    *tolerance_frames*: during long script runs with the microphone off, a
    stray notification would otherwise split one long pause into several
    shorter ones. A qualifying stretch becomes a single chunk tagged
    :data:`LONG_PAUSE_SPEED_INDEX`, absorbed sounds included; everything else is
    copied unchanged.
    """

    result: List[List[int]] = []
    count = len(chunks)
    index = 0
    while index < count:
        chunk = chunks[index]
        if int(chunk[2]) != 0:
            result.append([int(value) for value in chunk])
            index += 1
            continue
        last = index
        while (
            last + 2 < count
            and int(chunks[last + 1][2]) == 1
            and int(chunks[last + 1][1]) - int(chunks[last + 1][0]) <= tolerance_frames
            and int(chunks[last + 2][2]) == 0
        ):
            last += 2
        start, end = int(chunk[0]), int(chunks[last][1])
        if end - start >= min_frames:
            result.append([start, end, LONG_PAUSE_SPEED_INDEX])
        else:
            result.extend(
                [int(value) for value in piece] for piece in chunks[index : last + 1]
            )
        index = last + 1
    return result


def get_tree_expression(chunks: Sequence[Sequence[int]]) -> str:
    """Return the FFmpeg expression needed to map chunk timing updates."""

    return "{}/TB/FR".format(_get_tree_expression_rec(chunks))


def _get_tree_expression_rec(chunks: Sequence[Sequence[int]]) -> str:
    if len(chunks) > 1:
        split_index = int(len(chunks) / 2)
        center = chunks[split_index]
        return "if(lt(N,{}),{},{})".format(
            center[0],
            _get_tree_expression_rec(chunks[:split_index]),
            _get_tree_expression_rec(chunks[split_index:]),
        )
    chunk = chunks[0]
    chunk_duration = chunk[1] - chunk[0]
    if chunk_duration == 0:
        # If chunk has zero duration, use identity transformation
        return "PTS"
    local_speedup = (chunk[3] - chunk[2]) / chunk_duration
    offset = -chunk[0] * local_speedup + chunk[2]
    return "N*{}{:+}".format(local_speedup, offset)


__all__ = [
    "LONG_PAUSE_SOUND_TOLERANCE_SECONDS",
    "LONG_PAUSE_SPEED_INDEX",
    "REMOVED_SPEED_INDEX",
    "apply_long_pauses",
    "apply_remove_ranges",
    "detect_loud_frames",
    "build_chunks",
    "get_tree_expression",
]
