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
    local_speedup = (chunk[3] - chunk[2]) / (chunk[1] - chunk[0])
    offset = -chunk[0] * local_speedup + chunk[2]
    return "N*{}{:+}".format(local_speedup, offset)


__all__ = [
    "detect_loud_frames",
    "build_chunks",
    "get_tree_expression",
]
