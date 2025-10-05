"""Progress reporting utilities shared by the CLI and GUI layers."""

from __future__ import annotations

import sys
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

from tqdm import tqdm


@runtime_checkable
class ProgressHandle(Protocol):
    """Represents a single progress task that can be updated incrementally."""

    @property
    def current(self) -> int:
        """Return the number of processed units."""

    def ensure_total(self, total: int) -> None:
        """Increase the total units when FFmpeg reports a larger frame count."""

    def advance(self, amount: int) -> None:
        """Advance the progress cursor by ``amount`` units."""

    def finish(self) -> None:
        """Mark the task as finished, filling in any remaining progress."""


@runtime_checkable
class ProgressReporter(Protocol):
    """Interface used by the pipeline to stream progress information."""

    def log(self, message: str) -> None:
        """Emit an informational log message to the user interface."""

    def task(
        self, *, desc: str = "", total: Optional[int] = None, unit: str = ""
    ) -> AbstractContextManager[ProgressHandle]:
        """Return a context manager managing a :class:`ProgressHandle`."""


@dataclass
class _NullProgressHandle:
    """No-op implementation for environments that do not need progress."""

    total: Optional[int] = None
    current: int = 0

    def ensure_total(self, total: int) -> None:
        self.total = max(self.total or 0, total)

    def advance(self, amount: int) -> None:
        self.current += amount

    def finish(self) -> None:
        if self.total is not None:
            self.current = self.total


class NullProgressReporter(ProgressReporter):
    """Progress reporter that ignores all output."""

    def log(self, message: str) -> None:  # pragma: no cover - intentional no-op
        del message

    def task(
        self, *, desc: str = "", total: Optional[int] = None, unit: str = ""
    ) -> AbstractContextManager[ProgressHandle]:
        del desc, unit

        class _Context(AbstractContextManager[ProgressHandle]):
            def __init__(self, handle: _NullProgressHandle) -> None:
                self._handle = handle

            def __enter__(self) -> ProgressHandle:
                return self._handle

            def __exit__(self, exc_type, exc, tb) -> bool:
                return False

        return _Context(_NullProgressHandle(total=total))


@dataclass
class _TqdmProgressHandle(AbstractContextManager[ProgressHandle]):
    """Wraps a :class:`tqdm.tqdm` instance to match :class:`ProgressHandle`."""

    bar: tqdm

    @property
    def current(self) -> int:
        return int(self.bar.n)

    def ensure_total(self, total: int) -> None:
        if self.bar.total is None or total > self.bar.total:
            self.bar.total = total

    def advance(self, amount: int) -> None:
        if amount > 0:
            self.bar.update(amount)

    def finish(self) -> None:
        if self.bar.total is not None and self.bar.n < self.bar.total:
            self.bar.update(self.bar.total - self.bar.n)

    def __enter__(self) -> ProgressHandle:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self.finish()
        self.bar.close()
        return False


class TqdmProgressReporter(ProgressReporter):
    """Adapter that renders pipeline progress using :mod:`tqdm`."""

    def __init__(self) -> None:
        self._bar_format = (
            "{desc:<20} {percentage:3.0f}%"
            "|{bar:10}|"
            " {n_fmt:>6}/{total_fmt:>6} [{elapsed:^5}<{remaining:^5}, {rate_fmt}{postfix}]"
        )

    def log(self, message: str) -> None:
        tqdm.write(message)

    def task(
        self, *, desc: str = "", total: Optional[int] = None, unit: str = ""
    ) -> AbstractContextManager[ProgressHandle]:
        bar = tqdm(
            total=total,
            desc=desc,
            unit=unit,
            bar_format=self._bar_format,
            file=sys.stderr,
        )
        return _TqdmProgressHandle(bar)


class SignalProgressReporter(NullProgressReporter):
    """Placeholder implementation for GUI integrations.

    UI front-ends can subclass this type and emit framework-specific signals when
    progress updates arrive.
    """

    pass


__all__ = [
    "ProgressHandle",
    "ProgressReporter",
    "NullProgressReporter",
    "TqdmProgressReporter",
    "SignalProgressReporter",
]
