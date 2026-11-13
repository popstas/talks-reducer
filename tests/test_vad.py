"""Tests for the Silero VAD speech detection module."""

import re
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


def test_load_engine_unknown_raises_value_error():
    with pytest.raises(ValueError):
        vad.load_engine("nope")


def test_load_engine_missing_package_raises_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "silero_vad_lite", None)
    with pytest.raises(vad.VadUnavailableError, match="pip install silero-vad-lite"):
        vad.load_engine("lite")


def test_lite_engine_detects_silence():
    pytest.importorskip("silero_vad_lite")
    engine = vad.load_engine("lite")
    probs = engine.probabilities(np.zeros(32000, np.float32))
    assert len(probs) == vad.count_windows(32000, 512)
    assert (probs < 0.5).all()


@pytest.mark.parametrize(
    "name, module, hint",
    [
        ("torch", "silero_vad", "talks-reducer[vad-torch]"),
        ("ten", "ten_vad", "talks-reducer[vad-ten]"),
    ],
)
def test_load_engine_experimental_missing_raises_unavailable(
    monkeypatch, name, module, hint
):
    monkeypatch.setitem(sys.modules, module, None)
    with pytest.raises(vad.VadUnavailableError, match=re.escape(hint)):
        vad.load_engine(name)


@pytest.mark.parametrize(
    "name, module, hop",
    [("torch", "silero_vad", 512), ("ten", "ten_vad", 256)],
)
def test_experimental_engine_detects_silence(name, module, hop):
    pytest.importorskip(module)
    engine = vad.load_engine(name)
    seen = []
    probs = engine.probabilities(np.zeros(32000, np.float32), seen.append)
    assert engine.name == name
    assert engine.hop_samples == hop
    assert len(probs) == vad.count_windows(32000, hop)
    assert (probs < 0.5).all()
    assert sum(seen) == len(probs)


def test_engines_agree_on_speech_ratio():
    pytest.importorskip("silero_vad_lite")
    pytest.importorskip("silero_vad")
    rng = np.random.default_rng(0)
    t = np.arange(48000) / 16000.0
    voiced = sum(
        np.sin(2 * np.pi * f * t) / k for k, f in enumerate((120, 240, 360, 480), 1)
    )
    signal = np.concatenate([np.zeros(16000), 0.3 * voiced[:16000], np.zeros(16000)])
    signal = (signal + rng.normal(0, 0.001, signal.shape)).astype(np.float32)
    settings = VadSettings()
    found = {}
    for name in ("lite", "torch"):
        engine = vad.load_engine(name)
        probs = engine.probabilities(signal)
        found[name] = vad.speech_intervals(probs, 512 / 16000, settings, 3.0)
    assert len(found["lite"]) == len(found["torch"])
    for (a0, a1), (b0, b1) in zip(found["lite"], found["torch"]):
        assert abs(a0 - b0) <= 512 / 16000
        assert abs(a1 - b1) <= 512 / 16000
