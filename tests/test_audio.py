"""Tests for the audio helper utilities."""

from __future__ import annotations

import subprocess
import types

import numpy as np
import pytest

from talks_reducer import audio


@pytest.fixture
def synthetic_audio_samples() -> dict[str, np.ndarray]:
    """Provide reusable mono and stereo test samples for audio processing."""

    return {
        "mono_positive": np.array([0.1, 0.6, 0.9], dtype=np.float32),
        "mono_negative": np.array([-0.25, -0.8, -0.5], dtype=np.float32),
        "stereo": np.array(
            [
                [0.0, 0.0],
                [1.0, -1.0],
                [2.0, -2.0],
                [3.0, -3.0],
                [4.0, -4.0],
                [5.0, -5.0],
            ],
            dtype=np.float32,
        ),
    }


@pytest.fixture
def prepared_chunks() -> list[list[int]]:
    """Return preconfigured chunks referencing sequential audio frames."""

    return [
        [0, 2, 0],
        [2, 3, 1],
        [3, 3, 0],
    ]


@pytest.fixture
def fake_phase_vocoder(monkeypatch):
    """Replace phase vocoder components with deterministic stand-ins for testing."""

    outputs: list[np.ndarray] = []

    class DummyArrayReader:
        def __init__(self, data: np.ndarray):
            self.data = np.asarray(data)
            self.channels = 1 if self.data.ndim == 1 else self.data.shape[0]

    class DummyArrayWriter:
        def __init__(self, channels: int):
            self.channels = channels
            self.data = np.zeros((channels, 0), dtype=np.float32)

    class DummyPhaseVocoder:
        def __init__(self, channels: int, speed: float):
            self.channels = channels
            self.speed = speed

        def run(self, reader: DummyArrayReader, writer: DummyArrayWriter) -> None:
            if not outputs:
                raise AssertionError(
                    "No prepared output available for phase vocoder run"
                )

            altered = outputs.pop(0)
            writer.data = np.asarray(altered, dtype=np.float32).T

    def configure_output_sequences(sequence: list[np.ndarray]) -> None:
        outputs[:] = [np.asarray(item, dtype=np.float32) for item in sequence]

    monkeypatch.setattr(audio, "ArrayReader", DummyArrayReader)
    monkeypatch.setattr(audio, "ArrayWriter", DummyArrayWriter)
    monkeypatch.setattr(
        audio,
        "phasevocoder",
        lambda channels, speed: DummyPhaseVocoder(channels, speed),
    )

    return configure_output_sequences


def _make_completed_process(stdout: str = "", stderr: str = "", returncode: int = 0):
    """Create a minimal object emulating :class:`subprocess.CompletedProcess`."""

    completed = types.SimpleNamespace()
    completed.stdout = stdout
    completed.stderr = stderr
    completed.returncode = returncode
    return completed


def test_process_audio_chunks_applies_envelope_and_updates_timings(
    synthetic_audio_samples, prepared_chunks, fake_phase_vocoder
):
    """Processed audio should handle fades, normalization, and timing updates."""

    stereo_audio = synthetic_audio_samples["stereo"]
    chunk_outputs = [
        np.array(
            [
                [1.0, 2.0],
                [3.0, 4.0],
                [5.0, 6.0],
                [7.0, 8.0],
            ],
            dtype=np.float32,
        ),
        np.array([[2.0, -2.0]], dtype=np.float32),
    ]

    fake_phase_vocoder(chunk_outputs)

    processed_audio, updated_chunks = audio.process_audio_chunks(
        stereo_audio,
        prepared_chunks,
        samples_per_frame=2.0,
        speeds=[1.0, 0.5],
        audio_fade_envelope_size=2,
        max_audio_volume=2.0,
    )

    expected_audio = np.array(
        [
            [0.0, 0.0],
            [0.75, 1.0],
            [2.5, 3.0],
            [1.75, 2.0],
            [0.0, 0.0],
        ],
        dtype=np.float32,
    )

    np.testing.assert_allclose(processed_audio, expected_audio)
    assert updated_chunks == [[0, 2, 0, 2], [2, 3, 2, 3], [3, 3, 3, 3]]


def test_get_max_volume_for_positive_samples(synthetic_audio_samples):
    """The maximum amplitude should match the highest positive sample value."""

    samples = synthetic_audio_samples["mono_positive"]
    assert audio.get_max_volume(samples) == pytest.approx(float(np.max(samples)))


def test_get_max_volume_for_negative_samples(synthetic_audio_samples):
    """The maximum amplitude should match the largest magnitude negative value."""

    samples = synthetic_audio_samples["mono_negative"]
    assert audio.get_max_volume(samples) == pytest.approx(
        float(np.abs(np.min(samples)))
    )


def test_is_valid_input_file_accepts_warnings(monkeypatch):
    """A warning written to stderr should not invalidate a valid audio file."""

    monkeypatch.setattr(audio, "get_ffprobe_path", lambda: "ffprobe")

    def fake_run(*args, **kwargs):
        return _make_completed_process(
            stdout="[STREAM]\ncodec_type=audio\n[/STREAM]\n",
            stderr="Configuration warning",
            returncode=0,
        )

    monkeypatch.setattr(audio.subprocess, "run", fake_run)

    assert audio.is_valid_input_file("example.mp4") is True


def test_is_valid_input_file_requires_audio_stream(monkeypatch):
    """Return ``False`` when ffprobe completes but finds no audio stream."""

    monkeypatch.setattr(audio, "get_ffprobe_path", lambda: "ffprobe")

    def fake_run(*args, **kwargs):
        return _make_completed_process(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(audio.subprocess, "run", fake_run)

    assert audio.is_valid_input_file("silent.mp4") is False


def test_is_valid_input_file_handles_timeout(monkeypatch):
    """Timeouts when invoking ffprobe should lead to a ``False`` result."""

    monkeypatch.setattr(audio, "get_ffprobe_path", lambda: "ffprobe")

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["ffprobe"], timeout=5)

    monkeypatch.setattr(audio.subprocess, "run", fake_run)

    assert audio.is_valid_input_file("delayed.mp4") is False


def test_is_valid_input_file_handles_nonzero_exit(monkeypatch):
    """A non-zero ffprobe exit status should result in ``False``."""

    monkeypatch.setattr(audio, "get_ffprobe_path", lambda: "ffprobe")

    def fake_run(*args, **kwargs):
        return _make_completed_process(stdout="", stderr="boom", returncode=1)

    monkeypatch.setattr(audio.subprocess, "run", fake_run)

    assert audio.is_valid_input_file("corrupt.mp4") is False


def test_is_valid_input_file_sets_creationflags_on_windows(monkeypatch):
    """Windows invocations should request hidden subprocess windows."""

    monkeypatch.setattr(audio, "get_ffprobe_path", lambda: "ffprobe")
    monkeypatch.setattr(audio.sys, "platform", "win32")

    captured_kwargs: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return _make_completed_process(
            stdout="[STREAM]\ncodec_type=audio\n[/STREAM]\n", returncode=0
        )

    monkeypatch.setattr(audio.subprocess, "run", fake_run)

    assert audio.is_valid_input_file("windows-input.mp4") is True
    assert captured_kwargs.get("creationflags") == 0x08000000


def test_process_audio_chunks_returns_empty_output_for_empty_inputs():
    """Empty inputs should produce an empty, correctly shaped audio array."""

    audio_data = np.zeros((0,), dtype=np.float32)

    processed, updated_chunks = audio.process_audio_chunks(
        audio_data,
        [],
        samples_per_frame=1.0,
        speeds=[],
        audio_fade_envelope_size=4,
        max_audio_volume=1.0,
    )

    assert processed.shape == (0, 1)
    assert processed.size == 0
    assert updated_chunks == []
