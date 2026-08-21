"""Optional process-pool acceleration for the phase-vocoder audio stage.

The phase vocoder is pure Python plus small NumPy operations, so it holds the
GIL for most of its runtime: threads make it slower rather than faster. Worker
*processes* do help, and the chunks are independent, so this module renders them
in a :class:`~concurrent.futures.ProcessPoolExecutor`.

The source audio is published once through :mod:`multiprocessing.shared_memory`
instead of being pickled per task, since a one hour recording is several hundred
megabytes and every chunk would otherwise carry its slice through the pipe.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import Future, ProcessPoolExecutor
from contextlib import suppress
from multiprocessing import get_context
from multiprocessing.shared_memory import SharedMemory
from typing import Dict, Optional, Sequence, Tuple

import numpy as np

ENV_WORKERS = "TALKS_REDUCER_AUDIO_WORKERS"
"""Environment variable overriding the automatic worker count."""

MAX_WORKERS = 8
"""Upper bound on worker processes, past which the pipe becomes the bottleneck."""

ChunkJob = Tuple[int, int, int, float]
"""A chunk to render: its index plus the sample range and speed to render it at."""

_LOGGER = logging.getLogger(__name__)


def resolve_worker_count() -> int:
    """Return how many worker processes the audio stage may use.

    ``TALKS_REDUCER_AUDIO_WORKERS`` overrides the automatic choice; a value of
    ``1`` disables the pool. Otherwise one core is left free for the main thread
    and the count is capped at :data:`MAX_WORKERS`.
    """

    override = os.environ.get(ENV_WORKERS, "").strip()
    if override:
        try:
            requested = int(override)
        except ValueError:
            _LOGGER.debug("Ignoring invalid %s value %r", ENV_WORKERS, override)
        else:
            return max(1, requested)

    cpu_count = os.cpu_count() or 1
    return max(1, min(cpu_count - 1, MAX_WORKERS))


def _render_shared_chunk(
    shm_name: str,
    shape: Tuple[int, ...],
    dtype_name: str,
    start: int,
    end: int,
    speed: float,
    audio_fade_envelope_size: int,
    normaliser: float,
) -> np.ndarray:
    """Render one chunk inside a worker process from the shared audio buffer."""

    from talks_reducer.audio import render_chunk

    shared = SharedMemory(name=shm_name)
    try:
        audio_data = np.ndarray(shape, dtype=np.dtype(dtype_name), buffer=shared.buf)
        return render_chunk(
            audio_data[start:end], speed, audio_fade_envelope_size, normaliser
        )
    finally:
        shared.close()


class ChunkRenderPool:
    """Render phase-vocoder chunks in worker processes, in submission order."""

    def __init__(
        self,
        audio_data: np.ndarray,
        jobs: Sequence[ChunkJob],
        *,
        audio_fade_envelope_size: int,
        normaliser: float,
        workers: int,
    ) -> None:
        self._shared = SharedMemory(create=True, size=max(int(audio_data.nbytes), 1))
        buffer = np.ndarray(
            audio_data.shape, dtype=audio_data.dtype, buffer=self._shared.buf
        )
        np.copyto(buffer, audio_data)

        # ``spawn`` rather than ``fork``: the GUI and tray run Tk and pystray on
        # the main thread, and forking a process that owns them is unsafe.
        self._executor = ProcessPoolExecutor(
            max_workers=workers, mp_context=get_context("spawn")
        )
        self._futures: Dict[int, "Future[np.ndarray]"] = {}
        try:
            for index, start, end, speed in jobs:
                self._futures[index] = self._executor.submit(
                    _render_shared_chunk,
                    self._shared.name,
                    audio_data.shape,
                    audio_data.dtype.name,
                    start,
                    end,
                    speed,
                    audio_fade_envelope_size,
                    normaliser,
                )
        except BaseException:
            self.close()
            raise

    def __contains__(self, index: int) -> bool:
        return index in self._futures

    def result(self, index: int) -> np.ndarray:
        """Return the rendered chunk, waiting for its worker to finish."""

        return self._futures[index].result()

    def close(self) -> None:
        """Stop the workers and release the shared audio buffer."""

        with suppress(Exception):
            self._executor.shutdown(wait=True, cancel_futures=True)
        # Unlink only after the workers exited, so no worker maps a freed block.
        with suppress(Exception):
            self._shared.close()
        with suppress(Exception):
            self._shared.unlink()

    def __enter__(self) -> "ChunkRenderPool":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def open_chunk_pool(
    audio_data: np.ndarray,
    jobs: Sequence[ChunkJob],
    *,
    audio_fade_envelope_size: int,
    normaliser: float,
) -> Optional[ChunkRenderPool]:
    """Return a running :class:`ChunkRenderPool`, or ``None`` to stay sequential.

    Any failure to start the pool — a sandbox without shared memory, a frozen
    build that cannot spawn, an exhausted process table — is logged and reported
    as ``None`` so the caller falls back to rendering chunks in-process.
    """

    workers = resolve_worker_count()
    if workers < 2 or len(jobs) < 2:
        return None

    try:
        return ChunkRenderPool(
            audio_data,
            jobs,
            audio_fade_envelope_size=audio_fade_envelope_size,
            normaliser=normaliser,
            workers=min(workers, len(jobs)),
        )
    except Exception:  # pragma: no cover - environment specific
        _LOGGER.debug("Falling back to sequential audio rendering", exc_info=True)
        return None


__all__ = [
    "ChunkRenderPool",
    "ENV_WORKERS",
    "MAX_WORKERS",
    "open_chunk_pool",
    "resolve_worker_count",
]
