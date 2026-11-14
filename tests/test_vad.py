"""Tests for the Silero VAD speech detection module."""

import sys

import numpy as np
import pytest

from talks_reducer import vad
from talks_reducer.vad import VadSettings


class FakeEngine:
    """Engine stub returning a preset probability array."""

    name = "fake"
    hop_samples = 512

    def __init__(self, probs=None):
        self._probs = probs

    def probabilities(self, audio, progress=None):
        count = vad.count_windows(len(audio), self.hop_samples)
        probs = (
            np.asarray(self._probs, dtype=np.float32)
            if self._probs is not None
            else np.zeros(count, dtype=np.float32)
        )
        if progress is not None:
            progress(len(probs))
        return probs


def test_to_mono_16k_int16_stereo_48k():
    data = np.full((48000, 2), 16384, np.int16)
    out = vad.to_mono_16k(data, 48000)
    assert out.dtype == np.float32
    assert len(out) == 16000
    assert np.allclose(out, 0.5, atol=1e-3)


def test_to_mono_16k_44100_float32():
    t = np.arange(44100) / 44100
    data = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    out = vad.to_mono_16k(data, 44100)
    assert out.dtype == np.float32
    assert len(out) in {15999, 16000, 16001}
    spectrum = np.abs(np.fft.rfft(out))
    freqs = np.fft.rfftfreq(len(out), 1 / 16000)
    assert abs(freqs[int(np.argmax(spectrum))] - 440) <= 5


def test_to_mono_16k_int32():
    data = np.array([np.iinfo(np.int32).min, np.iinfo(np.int32).max] * 8000, np.int32)
    out = vad.to_mono_16k(data, 16000)
    assert out.min() >= -1.0 and out.max() <= 1.0


def test_speech_intervals_hysteresis():
    probs = np.array([0.1] * 10 + [0.9] * 20 + [0.3] * 3 + [0.9] * 20 + [0.1] * 30)
    settings = VadSettings(padding_ms=0, min_silence_ms=300)
    intervals = vad.speech_intervals(probs, 0.032, settings, len(probs) * 0.032)
    assert len(intervals) == 1
    assert intervals[0][0] == pytest.approx(0.32, abs=0.01)


def test_speech_intervals_drops_short_speech():
    probs = np.array([0.1] * 10 + [0.9] * 3 + [0.1] * 30)
    settings = VadSettings(padding_ms=0)
    assert vad.speech_intervals(probs, 0.032, settings, len(probs) * 0.032) == []


def test_speech_intervals_padding_clamped():
    probs = np.array([0.9] * 30 + [0.1] * 30)
    total = len(probs) * 0.032
    intervals = vad.speech_intervals(probs, 0.032, VadSettings(padding_ms=150), total)
    assert intervals[0][0] == 0.0
    assert intervals[-1][1] <= total


def test_speech_intervals_splits_long_pause():
    probs = np.array([0.9] * 30 + [0.1] * 32 + [0.9] * 30 + [0.1] * 5)
    settings = VadSettings(padding_ms=0, min_silence_ms=300)
    intervals = vad.speech_intervals(probs, 0.032, settings, len(probs) * 0.032)
    assert len(intervals) == 2


def test_intervals_to_frame_mask():
    mask = vad.intervals_to_frame_mask([(1.0, 2.0)], 90, 30.0)
    assert mask.dtype == bool
    assert mask.shape == (90,)
    assert np.flatnonzero(mask).tolist() == list(range(30, 60))


def test_detect_voice_frames_shorter_than_window():
    audio = np.zeros(100, np.float32)
    result = vad.detect_voice_frames(
        audio, 48000, 30.0, 5, VadSettings(), engine=FakeEngine()
    )
    assert result.mask.shape == (5,)
    assert result.engine == "fake"


def test_detect_voice_frames_reports_progress():
    audio = np.zeros(48000 * 2, np.float32)
    seen = []
    vad.detect_voice_frames(
        audio, 48000, 30.0, 60, VadSettings(), engine=FakeEngine(), progress=seen.append
    )
    assert sum(seen) == vad.count_windows(32000, 512)


def test_load_engine_missing_package_raises_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "silero_vad_lite", None)
    with pytest.raises(vad.VadUnavailableError, match="pip install silero-vad-lite"):
        vad.load_engine()


def test_lite_engine_detects_silence():
    pytest.importorskip("silero_vad_lite")
    engine = vad.load_engine()
    seen = []
    probs = engine.probabilities(np.zeros(32000, np.float32), seen.append)
    assert engine.hop_samples == 512
    assert len(probs) == vad.count_windows(32000, 512)
    assert (probs < 0.5).all()
    assert sum(seen) == len(probs)


def test_to_mono_16k_int32_full_scale_normalizes():
    data = np.array([[np.iinfo(np.int32).min], [np.iinfo(np.int32).max], [0]], np.int32)
    out = vad.to_mono_16k(data, 16000)
    assert out.dtype == np.float32
    assert out.tolist() == pytest.approx([-1.0, 1.0, 0.0], abs=1e-6)


def test_to_mono_16k_uint8_normalizes():
    data = np.array([[0, 0], [128, 128], [255, 255], [0, 255]], np.uint8)
    out = vad.to_mono_16k(data, 16000)
    assert out.tolist() == pytest.approx([-1.0, 0.0, 127 / 128, -1 / 256], abs=1e-6)


def test_to_mono_16k_downmixes_int16_stereo_before_scaling():
    data = np.array([[32767, -32768], [16384, 16384], [-32768, -32768]], np.int16)
    out = vad.to_mono_16k(data, 16000)
    assert out.tolist() == pytest.approx([-0.5 / 32768, 0.5, -1.0], abs=1e-6)


@pytest.mark.parametrize("shape", [(6,), (6, 1)])
def test_to_mono_16k_leaves_float_input_untouched(shape):
    data = np.linspace(-2.0, 2.0, 6, dtype=np.float32).reshape(shape)
    original = data.copy()
    out = vad.to_mono_16k(data, 16000)
    assert np.array_equal(data, original)
    assert out.min() == -1.0 and out.max() == 1.0
    assert not np.shares_memory(out, data)


def test_to_mono_16k_peak_memory_stays_near_one_mono_copy():
    import tracemalloc

    seconds = 60
    data = np.random.default_rng(0).integers(
        -3000, 3000, size=(48000 * seconds, 2), dtype=np.int16
    )
    mono_float32_bytes = 48000 * seconds * 4
    tracemalloc.start()
    try:
        vad.to_mono_16k(data, 48000)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 2 * mono_float32_bytes


@pytest.mark.parametrize("threshold", [0.15, 0.1])
def test_speech_intervals_close_at_low_threshold(threshold):
    probs = np.array([0.9] * 20 + [0.0] * 20 + [0.9] * 20)
    settings = VadSettings(threshold=threshold, padding_ms=0, min_silence_ms=300)
    intervals = vad.speech_intervals(probs, 0.032, settings, len(probs) * 0.032)
    assert len(intervals) == 2
    assert intervals[0][1] == pytest.approx(0.64, abs=0.01)


def test_speech_intervals_dip_inside_hysteresis_never_splits():
    probs = np.array([0.9] * 20 + [0.4] * 30 + [0.9] * 20)
    settings = VadSettings(threshold=0.5, padding_ms=0, min_silence_ms=300)
    intervals = vad.speech_intervals(probs, 0.032, settings, len(probs) * 0.032)
    assert intervals == [(0.0, pytest.approx(len(probs) * 0.032))]


def _broken_module(name, **attributes):
    """Return a stand-in module whose attributes are the given callables."""

    import types

    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


def _raise(error):
    def factory(*args, **kwargs):
        raise error

    return factory


@pytest.mark.parametrize("error", [OSError("DLL load failed"), RuntimeError("boom")])
def test_lite_engine_native_failure_raises_unavailable(monkeypatch, error):
    monkeypatch.setitem(
        sys.modules,
        "silero_vad_lite",
        _broken_module("silero_vad_lite", SileroVAD=_raise(error)),
    )
    with pytest.raises(vad.VadUnavailableError) as info:
        vad.load_engine()
    assert "pip install silero-vad-lite" in str(info.value)
    assert str(error) in str(info.value)
