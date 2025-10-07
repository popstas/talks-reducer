"""Utilities for voice activity detection using the Silero VAD model."""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Tuple

import numpy as np


@lru_cache(maxsize=1)
def _load_silero_model() -> Tuple[object, object]:
    """Load and cache the Silero VAD model and timestamp helper."""

    try:
        import torch
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "Silero VAD requires the 'torch' package to be installed."
        ) from exc

    try:
        model, utils = torch.hub.load(  # type: ignore[attr-defined]
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            verbose=False,
        )
    except Exception as exc:  # pragma: no cover - network or torch hub failure
        raise RuntimeError("Unable to load Silero VAD model") from exc

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
) -> np.ndarray:
    """Return a boolean array of frames containing speech using Silero VAD."""

    model, get_speech_timestamps = _load_silero_model()

    try:
        import torch
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "Silero VAD requires the 'torch' package to be installed."
        ) from exc

    prepared = _prepare_audio_for_vad(audio_data)
    tensor = torch.from_numpy(prepared)  # type: ignore[attr-defined]

    speech_segments = get_speech_timestamps(
        tensor, model, sampling_rate=int(sample_rate)
    )

    has_loud_audio = np.zeros(audio_frame_count, dtype=bool)

    for segment in speech_segments:
        start_sample = int(segment.get("start", 0))
        end_sample = int(segment.get("end", 0))

        if end_sample <= start_sample:
            continue

        start_frame = max(
            0, int(math.floor(start_sample / max(samples_per_frame, 1e-9)))
        )
        end_frame = min(
            audio_frame_count,
            int(math.ceil(end_sample / max(samples_per_frame, 1e-9))),
        )

        if end_frame > start_frame:
            has_loud_audio[start_frame:end_frame] = True

    return has_loud_audio


__all__ = ["detect_speech_frames"]
