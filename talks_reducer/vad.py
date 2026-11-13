"""Voice activity detection built on Silero VAD.

The module turns decoded audio into a per-video-frame boolean mask, the same
shape ``chunks.detect_loud_frames`` produces, so the rest of the pipeline can
use either source interchangeably.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable, Optional, Protocol, Sequence

import numpy as np

VAD_SAMPLE_RATE = 16000
MIN_SPEECH_MS = 250
ENGINE_NAMES = ("lite", "torch", "ten")

_LITE_HOP_SAMPLES = 512
_PROGRESS_BATCH = 1000
_RESAMPLE_BLOCK_SECONDS = 10
_HYSTERESIS_MARGIN = 0.15

_INSTALL_HINTS = {
    "lite": "pip install silero-vad-lite",
    "torch": "pip install talks-reducer[vad-torch]",
    "ten": "pip install talks-reducer[vad-ten]",
}


class VadUnavailableError(RuntimeError):
    """Raised when the requested VAD engine cannot be imported."""


@dataclass(frozen=True)
class VadSettings:
    """User-tunable VAD parameters."""

    engine: str = "lite"
    threshold: float = 0.5
    padding_ms: int = 150
    min_silence_ms: int = 300


class VadEngine(Protocol):
    """Backend that turns 16 kHz mono audio into speech probabilities."""

    name: str
    hop_samples: int

    def probabilities(
        self,
        audio: np.ndarray,
        progress: Optional[Callable[[int], None]] = None,
    ) -> np.ndarray:
        """Return one speech probability per ``hop_samples`` window."""


@dataclass(frozen=True)
class VadResult:
    """Outcome of :func:`detect_voice_frames`."""

    mask: np.ndarray
    intervals: list[tuple[float, float]]
    engine: str
    seconds: float
    speech_ratio: float


def count_windows(sample_count_16k: int, hop_samples: int) -> int:
    """Return how many VAD windows cover ``sample_count_16k`` samples (min 1)."""

    return max(1, math.ceil(sample_count_16k / hop_samples))


def _normalize_samples(audio_data: np.ndarray) -> np.ndarray:
    """Scale integer or float samples into float32 values within [-1, 1]."""

    kind = audio_data.dtype
    if kind == np.int16:
        data = audio_data.astype(np.float32) / 32768.0
    elif kind == np.int32:
        data = (audio_data.astype(np.float64) / 2147483648.0).astype(np.float32)
    elif kind == np.uint8:
        data = (audio_data.astype(np.float32) - 128.0) / 128.0
    else:
        data = audio_data.astype(np.float32)
    return np.clip(data, -1.0, 1.0)


def _resample_to_16k(mono: np.ndarray, sample_rate: int) -> np.ndarray:
    """Resample a mono signal to 16 kHz without building a full-length index."""

    if sample_rate == VAD_SAMPLE_RATE or len(mono) == 0:
        return mono
    if sample_rate % VAD_SAMPLE_RATE == 0:
        factor = sample_rate // VAD_SAMPLE_RATE
        usable = len(mono) // factor * factor
        return mono[:usable].reshape(-1, factor).mean(axis=1, dtype=np.float32)

    ratio = sample_rate / VAD_SAMPLE_RATE
    out_length = int(round(len(mono) * VAD_SAMPLE_RATE / sample_rate))
    out = np.empty(out_length, dtype=np.float32)
    block = VAD_SAMPLE_RATE * _RESAMPLE_BLOCK_SECONDS
    for start in range(0, out_length, block):
        stop = min(start + block, out_length)
        positions = np.arange(start, stop, dtype=np.float64) * ratio
        low = int(positions[0])
        high = min(len(mono), int(positions[-1]) + 2)
        out[start:stop] = np.interp(
            positions - low, np.arange(high - low), mono[low:high]
        )
    return out


def to_mono_16k(audio_data: np.ndarray, sample_rate: int) -> np.ndarray:
    """Convert decoded audio of any dtype and channel count to 16 kHz mono float32."""

    data = _normalize_samples(np.asarray(audio_data))
    if data.ndim > 1:
        data = data.mean(axis=1, dtype=np.float32)
    return _resample_to_16k(data, sample_rate).astype(np.float32, copy=False)


def speech_intervals(
    probs: np.ndarray,
    hop_seconds: float,
    settings: VadSettings,
    total_seconds: float,
) -> list[tuple[float, float]]:
    """Turn window probabilities into padded, merged speech intervals in seconds.

    Mirrors Silero's ``get_speech_timestamps`` post-processing: a window at or
    above ``threshold`` opens speech, and speech only closes after the
    probability stays below ``threshold - 0.15`` for ``min_silence_ms``.
    """

    threshold = settings.threshold
    negative = threshold - _HYSTERESIS_MARGIN
    min_silence = settings.min_silence_ms / 1000.0
    raw: list[tuple[float, float]] = []
    triggered = False
    start = 0.0
    temp_end: Optional[float] = None

    for index, prob in enumerate(probs):
        moment = index * hop_seconds
        if prob >= threshold:
            temp_end = None
            if not triggered:
                triggered, start = True, moment
        elif triggered and prob < negative:
            if temp_end is None:
                temp_end = moment
            if moment + hop_seconds - temp_end >= min_silence:
                raw.append((start, temp_end))
                triggered, temp_end = False, None
    if triggered:
        raw.append((start, total_seconds))

    padding = settings.padding_ms / 1000.0
    min_speech = MIN_SPEECH_MS / 1000.0
    merged: list[tuple[float, float]] = []
    for begin, end in raw:
        if end - begin < min_speech:
            continue
        begin = max(0.0, begin - padding)
        end = min(total_seconds, end + padding)
        if merged and begin <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((begin, end))
    return merged


def intervals_to_frame_mask(
    intervals: Sequence[tuple[float, float]],
    frame_count: int,
    frame_rate: float,
) -> np.ndarray:
    """Mark every video frame that overlaps a speech interval."""

    mask = np.zeros(frame_count, dtype=bool)
    for begin, end in intervals:
        first = max(0, int(math.floor(round(begin * frame_rate, 9))))
        last = min(frame_count, int(math.ceil(round(end * frame_rate, 9))))
        if last > first:
            mask[first:last] = True
    return mask


class LiteEngine:
    """Silero VAD through the dependency-light ``silero-vad-lite`` package."""

    name = "lite"
    hop_samples = _LITE_HOP_SAMPLES

    def __init__(self) -> None:
        try:
            from silero_vad_lite import SileroVAD
        except ImportError as exc:
            raise VadUnavailableError(
                "Speedup no voice needs the Silero VAD engine. Install it with: "
                f"{_INSTALL_HINTS['lite']}"
            ) from exc
        self._vad = SileroVAD(VAD_SAMPLE_RATE)

    def probabilities(
        self,
        audio: np.ndarray,
        progress: Optional[Callable[[int], None]] = None,
    ) -> np.ndarray:
        """Return one speech probability per 512-sample window."""

        hop = self.hop_samples
        total = count_windows(len(audio), hop)
        probs = np.zeros(total, dtype=np.float32)
        pending = 0
        for index in range(total):
            chunk = audio[index * hop : (index + 1) * hop]
            if len(chunk) < hop:
                chunk = np.pad(chunk, (0, hop - len(chunk)))
            probs[index] = self._vad.process(
                memoryview(np.ascontiguousarray(chunk, np.float32))
            )
            pending += 1
            if progress is not None and pending >= _PROGRESS_BATCH:
                progress(pending)
                pending = 0
        if progress is not None and pending:
            progress(pending)
        return probs


def load_engine(name: str) -> VadEngine:
    """Instantiate the VAD engine called ``name``.

    Raises ``ValueError`` for unknown names and :class:`VadUnavailableError`
    when the engine's package is missing.
    """

    if name == "lite":
        return LiteEngine()
    if name in ENGINE_NAMES:
        raise VadUnavailableError(
            f"The '{name}' VAD engine is not available. "
            f"Install it with: {_INSTALL_HINTS[name]}"
        )
    raise ValueError(
        f"Unknown VAD engine '{name}'. Choose one of: {', '.join(ENGINE_NAMES)}"
    )


def detect_voice_frames(
    audio_data: np.ndarray,
    sample_rate: int,
    frame_rate: float,
    frame_count: int,
    settings: VadSettings,
    *,
    engine: Optional[VadEngine] = None,
    progress: Optional[Callable[[int], None]] = None,
) -> VadResult:
    """Return a per-video-frame speech mask for ``audio_data``."""

    engine = engine if engine is not None else load_engine(settings.engine)
    audio = to_mono_16k(audio_data, sample_rate)
    total_seconds = len(audio) / VAD_SAMPLE_RATE
    started = time.perf_counter()
    probs = engine.probabilities(audio, progress)
    elapsed = time.perf_counter() - started
    hop_seconds = engine.hop_samples / VAD_SAMPLE_RATE
    intervals = speech_intervals(probs, hop_seconds, settings, total_seconds)
    mask = intervals_to_frame_mask(intervals, frame_count, frame_rate)
    ratio = float(mask.mean()) if frame_count else 0.0
    return VadResult(
        mask=mask,
        intervals=intervals,
        engine=engine.name,
        seconds=elapsed,
        speech_ratio=ratio,
    )
