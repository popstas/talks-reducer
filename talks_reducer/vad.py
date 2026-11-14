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

_LITE_HOP_SAMPLES = 512
_PROGRESS_BATCH = 1000
_RESAMPLE_BLOCK_SECONDS = 10
_HYSTERESIS_MARGIN = 0.15
_MIN_NEGATIVE_THRESHOLD = 0.01

_INSTALL_HINT = "pip install silero-vad-lite"


class VadUnavailableError(RuntimeError):
    """Raised when the VAD engine cannot be imported or started."""


_LOAD_ERRORS = (ImportError, OSError, RuntimeError)


def _unavailable(message: str, exc: BaseException) -> VadUnavailableError:
    """Return a :class:`VadUnavailableError` carrying *message* and *exc*'s text.

    A missing package raises ``ImportError``, but a package whose native library
    cannot load (a missing DLL, a wrong architecture) raises ``OSError`` or a
    ``RuntimeError`` from the constructor; the original text is kept because
    the install hint alone cannot fix those.
    """

    return VadUnavailableError(f"{message} ({type(exc).__name__}: {exc})")


@dataclass(frozen=True)
class VadSettings:
    """User-tunable VAD parameters."""

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


_INTEGER_SCALES = {
    np.dtype(np.int16): (0.0, 32768.0),
    np.dtype(np.int32): (0.0, 2147483648.0),
    np.dtype(np.uint8): (128.0, 128.0),
}


def _mono_float32(audio_data: np.ndarray) -> np.ndarray:
    """Downmix to one float32 channel scaled into [-1, 1], in a single new array.

    The channels are averaged straight from the source dtype (NumPy casts in
    small buffers), so the only allocation the size of the input is the mono
    result; the integer offset, scale and clip then run in place on it. The
    caller's array is never modified, because the pipeline renders its output
    from it later.
    """

    if audio_data.ndim > 1:
        if audio_data.shape[1] == 1:
            mono = audio_data[:, 0].astype(np.float32)
        else:
            mono = audio_data.mean(axis=1, dtype=np.float32)
    else:
        mono = audio_data.astype(np.float32)
    offset, scale = _INTEGER_SCALES.get(audio_data.dtype, (0.0, 1.0))
    if offset:
        mono -= offset
    if scale != 1.0:
        mono /= scale
    np.clip(mono, -1.0, 1.0, out=mono)
    return mono


def _resample_to_16k(audio_data: np.ndarray, sample_rate: int) -> np.ndarray:
    """Downmix and resample ``audio_data`` to 16 kHz in 10-second output blocks.

    Each block's source span goes through :func:`_mono_float32` on its own, so
    no full-length float copy at the source rate is ever built: the only
    full-length array is the 16 kHz result. Integer ratios average each group
    of ``factor`` samples; other ratios interpolate linearly.
    """

    block = VAD_SAMPLE_RATE * _RESAMPLE_BLOCK_SECONDS
    if sample_rate % VAD_SAMPLE_RATE == 0:
        factor = sample_rate // VAD_SAMPLE_RATE
        out_length = len(audio_data) // factor
        out = np.empty(out_length, dtype=np.float32)
        for start in range(0, out_length, block):
            stop = min(start + block, out_length)
            mono = _mono_float32(audio_data[start * factor : stop * factor])
            out[start:stop] = mono.reshape(-1, factor).mean(axis=1, dtype=np.float32)
        return out

    ratio = sample_rate / VAD_SAMPLE_RATE
    out_length = int(round(len(audio_data) * VAD_SAMPLE_RATE / sample_rate))
    out = np.empty(out_length, dtype=np.float32)
    for start in range(0, out_length, block):
        stop = min(start + block, out_length)
        positions = np.arange(start, stop, dtype=np.float64) * ratio
        low = int(positions[0])
        high = min(len(audio_data), int(positions[-1]) + 2)
        mono = _mono_float32(audio_data[low:high])
        out[start:stop] = np.interp(positions - low, np.arange(high - low), mono)
    return out


def to_mono_16k(audio_data: np.ndarray, sample_rate: int) -> np.ndarray:
    """Convert decoded audio of any dtype and channel count to 16 kHz mono float32."""

    data = np.asarray(audio_data)
    if sample_rate == VAD_SAMPLE_RATE or len(data) == 0:
        return _mono_float32(data)
    return _resample_to_16k(data, sample_rate)


def speech_intervals(
    probs: np.ndarray,
    hop_seconds: float,
    settings: VadSettings,
    total_seconds: float,
) -> list[tuple[float, float]]:
    """Turn window probabilities into padded, merged speech intervals in seconds.

    Mirrors Silero's ``get_speech_timestamps`` post-processing: a window at or
    above ``threshold`` opens speech, and speech only closes after the
    probability stays below ``max(threshold - 0.15, 0.01)`` for
    ``min_silence_ms``. The 0.01 floor is Silero's: without it a threshold at or
    below 0.15 puts the close level at or below zero, which no probability can
    fall under, so speech would never end.
    """

    threshold = settings.threshold
    negative = max(threshold - _HYSTERESIS_MARGIN, _MIN_NEGATIVE_THRESHOLD)
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

            self._vad = SileroVAD(VAD_SAMPLE_RATE)
        except _LOAD_ERRORS as exc:
            raise _unavailable(
                "Speedup no voice needs the Silero VAD engine. Install it with: "
                f"{_INSTALL_HINT}",
                exc,
            ) from exc

    def probabilities(
        self,
        audio: np.ndarray,
        progress: Optional[Callable[[int], None]] = None,
    ) -> np.ndarray:
        """Return one speech probability per 512-sample window.

        The final window is zero-padded, and ``progress`` receives window counts
        in batches of ``_PROGRESS_BATCH`` plus the remainder.
        """

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


def load_engine() -> VadEngine:
    """Instantiate the Silero VAD engine.

    Raises :class:`VadUnavailableError` when ``silero-vad-lite`` is missing or
    its native library fails to start.
    """

    return LiteEngine()


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

    engine = engine if engine is not None else load_engine()
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
