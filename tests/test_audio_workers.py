"""Tests for the optional process-pool acceleration of the audio stage."""

from __future__ import annotations

from concurrent.futures.process import BrokenProcessPool

import numpy as np
import pytest

from talks_reducer import audio, audio_workers


@pytest.fixture
def tone_audio() -> np.ndarray:
    """Return a short stereo tone long enough to exercise the phase vocoder."""

    samples = np.arange(24000)
    wave = (np.sin(2 * np.pi * 220 * samples / 48000) * 8000).astype(np.int16)
    return np.stack([wave, wave], axis=1)


@pytest.fixture
def parallel_chunks() -> list[list[int]]:
    """Return four chunks that all need real time-scale modification."""

    return [[0, 4, 0], [4, 8, 0], [8, 12, 0], [12, 15, 0]]


def test_resolve_worker_count_honours_environment(monkeypatch):
    """An explicit worker count in the environment overrides the CPU default."""

    monkeypatch.setenv(audio_workers.ENV_WORKERS, "3")
    assert audio_workers.resolve_worker_count() == 3


def test_resolve_worker_count_ignores_invalid_environment(monkeypatch):
    """A non-numeric override falls back to the CPU-derived default."""

    monkeypatch.setenv(audio_workers.ENV_WORKERS, "many")
    assert audio_workers.resolve_worker_count() >= 1


def test_resolve_worker_count_stays_within_cpu_budget(monkeypatch):
    """The default leaves one core free and never exceeds the worker cap."""

    monkeypatch.delenv(audio_workers.ENV_WORKERS, raising=False)
    monkeypatch.setattr(audio_workers.os, "cpu_count", lambda: 4)
    assert audio_workers.resolve_worker_count() == 3


def test_job_estimate_scales_with_speed():
    """The workload estimate counts output samples, which shrink with speed."""

    chunks = [[0, 10, 0], [10, 20, 1]]

    jobs, estimate = audio._collect_vocoder_jobs(chunks, 100.0, [4.0, 2.0])

    assert [job[0] for job in jobs] == [0, 1]
    # 1000 source samples at speed 4 plus 1000 at speed 2 render 750 samples.
    assert estimate == 750


def test_job_estimate_skips_chunks_played_at_normal_speed():
    """Copied chunks are not work for the pool, so they leave the estimate alone."""

    chunks = [[0, 10, 0], [10, 20, 1]]

    jobs, estimate = audio._collect_vocoder_jobs(chunks, 100.0, [1.0, 2.0])

    assert [job[0] for job in jobs] == [1]
    assert estimate == 500


def test_parallel_rendering_matches_sequential_output(
    monkeypatch, tone_audio, parallel_chunks
):
    """Chunks rendered in worker processes match the sequential result."""

    kwargs = dict(
        samples_per_frame=1600.0,
        speeds=[1.5, 1.0],
        audio_fade_envelope_size=400,
        max_audio_volume=8000.0,
    )

    monkeypatch.setenv(audio_workers.ENV_WORKERS, "1")
    expected_audio, expected_chunks = audio.process_audio_chunks(
        tone_audio, parallel_chunks, **kwargs
    )

    monkeypatch.setenv(audio_workers.ENV_WORKERS, "2")
    monkeypatch.setattr(audio, "PARALLEL_MIN_OUTPUT_SAMPLES", 0)
    parallel_audio, updated_chunks = audio.process_audio_chunks(
        tone_audio, parallel_chunks, **kwargs
    )

    np.testing.assert_array_equal(parallel_audio, expected_audio)
    assert updated_chunks == expected_chunks


def test_parallel_rendering_reports_progress_in_chunk_order(
    monkeypatch, tone_audio, parallel_chunks
):
    """Worker results are consumed in order so progress stays monotonic."""

    monkeypatch.setenv(audio_workers.ENV_WORKERS, "2")
    monkeypatch.setattr(audio, "PARALLEL_MIN_OUTPUT_SAMPLES", 0)

    increments: list[int] = []
    audio.process_audio_chunks(
        tone_audio,
        parallel_chunks,
        samples_per_frame=1600.0,
        speeds=[1.5, 1.0],
        audio_fade_envelope_size=400,
        max_audio_volume=8000.0,
        progress_callback=increments.append,
    )

    assert increments == [6400, 6400, 6400, 4800]


def test_parallel_rendering_falls_back_when_pool_cannot_start(
    monkeypatch, tone_audio, parallel_chunks
):
    """A pool that fails to start leaves the sequential path in charge."""

    kwargs = dict(
        samples_per_frame=1600.0,
        speeds=[1.5, 1.0],
        audio_fade_envelope_size=400,
        max_audio_volume=8000.0,
    )

    monkeypatch.setenv(audio_workers.ENV_WORKERS, "1")
    expected_audio, _ = audio.process_audio_chunks(
        tone_audio, parallel_chunks, **kwargs
    )

    def explode(*args, **kwargs):
        raise OSError("no shared memory available")

    monkeypatch.setenv(audio_workers.ENV_WORKERS, "2")
    monkeypatch.setattr(audio, "PARALLEL_MIN_OUTPUT_SAMPLES", 0)
    monkeypatch.setattr(audio_workers, "ChunkRenderPool", explode)

    processed_audio, _ = audio.process_audio_chunks(
        tone_audio, parallel_chunks, **kwargs
    )

    np.testing.assert_array_equal(processed_audio, expected_audio)


def test_rendering_recovers_when_a_worker_dies(
    monkeypatch, tone_audio, parallel_chunks
):
    """A pool that breaks mid-run finishes the remaining chunks in-process."""

    kwargs = dict(
        samples_per_frame=1600.0,
        speeds=[1.5, 1.0],
        audio_fade_envelope_size=400,
        max_audio_volume=8000.0,
    )

    monkeypatch.setenv(audio_workers.ENV_WORKERS, "1")
    expected_audio, _ = audio.process_audio_chunks(
        tone_audio, parallel_chunks, **kwargs
    )

    class BrokenPool:
        """Stand-in for a pool whose workers died after the jobs were queued."""

        def __init__(self, *args, **kwargs):
            self.closed = False

        def __contains__(self, index: int) -> bool:
            return True

        def result(self, index: int):
            raise BrokenProcessPool("worker terminated abruptly")

        def close(self) -> None:
            self.closed = True

    monkeypatch.setenv(audio_workers.ENV_WORKERS, "2")
    monkeypatch.setattr(audio, "PARALLEL_MIN_OUTPUT_SAMPLES", 0)
    monkeypatch.setattr(audio_workers, "ChunkRenderPool", BrokenPool)

    processed_audio, _ = audio.process_audio_chunks(
        tone_audio, parallel_chunks, **kwargs
    )

    np.testing.assert_array_equal(processed_audio, expected_audio)


def test_parallel_rendering_honours_check_stop(
    monkeypatch, tone_audio, parallel_chunks
):
    """A raising ``check_stop`` aborts the run even while the pool is active."""

    monkeypatch.setenv(audio_workers.ENV_WORKERS, "2")
    monkeypatch.setattr(audio, "PARALLEL_MIN_OUTPUT_SAMPLES", 0)

    class _Stop(Exception):
        pass

    calls = {"count": 0}

    def check_stop() -> None:
        calls["count"] += 1
        if calls["count"] > 2:
            raise _Stop()

    with pytest.raises(_Stop):
        audio.process_audio_chunks(
            tone_audio,
            parallel_chunks,
            samples_per_frame=1600.0,
            speeds=[1.5, 1.0],
            audio_fade_envelope_size=400,
            max_audio_volume=8000.0,
            check_stop=check_stop,
        )


def test_small_workloads_stay_sequential(monkeypatch, tone_audio, parallel_chunks):
    """Below the sample threshold no worker pool is created at all."""

    monkeypatch.setenv(audio_workers.ENV_WORKERS, "4")

    def explode(*args, **kwargs):
        raise AssertionError("pool must not be created for a small workload")

    monkeypatch.setattr(audio_workers, "ChunkRenderPool", explode)

    audio.process_audio_chunks(
        tone_audio,
        parallel_chunks,
        samples_per_frame=1600.0,
        speeds=[1.5, 1.0],
        audio_fade_envelope_size=400,
        max_audio_volume=8000.0,
    )
