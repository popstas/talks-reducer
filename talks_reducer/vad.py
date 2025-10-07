"""Utilities for voice activity detection using the Silero VAD model."""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Tuple

import numpy as np

from .audio import get_max_volume


@lru_cache(maxsize=1)
def _load_silero_model() -> Tuple[object, object]:
    """Load and cache the Silero VAD model and timestamp helper."""

    import torch

    try:
        model, utils = torch.hub.load(  # type: ignore[attr-defined]
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            verbose=False,
        )
    except Exception as exc:  # pragma: no cover - network or torch hub failure
        import sys
        error_msg = (
            f"Unable to load Silero VAD model: \n{exc}. "
        )
        print(error_msg, file=sys.stderr)  # Also output to console
        raise RuntimeError(error_msg) from exc

    try:
        (get_speech_timestamps, *_rest) = utils
    except Exception as exc:  # pragma: no cover - defensive programming
        raise RuntimeError("Silero VAD helper functions were not returned") from exc

    return model, get_speech_timestamps


def _prepare_audio_for_vad(audio_data: np.ndarray) -> np.ndarray:
    """Return a mono float32 waveform scaled for Silero VAD."""

    if audio_data.ndim == 2:
        mono = audio_data.mean(axis=1)
    else:
        mono = audio_data

    if np.issubdtype(mono.dtype, np.integer):
        info = np.iinfo(mono.dtype)
        scale = float(max(abs(info.min), info.max)) or 1.0
        mono = mono.astype(np.float32) / scale
    else:
        mono = mono.astype(np.float32)

    if mono.size == 0:
        return np.zeros((0,), dtype=np.float32)

    return mono


def detect_speech_frames(
    audio_data: np.ndarray,
    sample_rate: int,
    audio_frame_count: int,
    samples_per_frame: float,
    silent_threshold: float = 0.03,
    max_audio_volume: float = 1.0,
) -> np.ndarray:
    """Return a boolean array of frames containing speech using Silero VAD with volume filtering."""

    model, get_speech_timestamps = _load_silero_model()

    import torch

    prepared = _prepare_audio_for_vad(audio_data)
    tensor = torch.from_numpy(prepared)  # type: ignore[attr-defined]

    speech_segments = get_speech_timestamps(
        tensor, model, sampling_rate=int(sample_rate)
    )

    has_loud_audio = np.zeros(audio_frame_count, dtype=bool)

    # Apply volume threshold filtering to VAD results
    normaliser = max(max_audio_volume, 1e-9)

    for segment in speech_segments:
        start_sample = int(segment.get("start", 0))
        end_sample = int(segment.get("end", 0))

        if end_sample <= start_sample:
            continue

        # Check volume for this speech segment
        start_frame = max(
            0, int(math.floor(start_sample / max(samples_per_frame, 1e-9)))
        )
        end_frame = min(
            audio_frame_count,
            int(math.ceil(end_sample / max(samples_per_frame, 1e-9))),
        )

        # Check if any frame in this segment has sufficient volume
        segment_has_loud_audio = False
        for frame_index in range(start_frame, end_frame):
            frame_start = int(frame_index * samples_per_frame)
            frame_end = min(int((frame_index + 1) * samples_per_frame), audio_data.shape[0])
            audio_chunk = audio_data[frame_start:frame_end]
            chunk_max_volume = float(get_max_volume(audio_chunk)) / normaliser
            if chunk_max_volume >= silent_threshold:
                segment_has_loud_audio = True
                break

        if segment_has_loud_audio:
            # Mark all frames in this segment as loud
            has_loud_audio[start_frame:end_frame] = True

    return has_loud_audio


__all__ = ["detect_speech_frames"]
