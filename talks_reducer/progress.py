"""Progress reporting utilities shared by the CLI and GUI layers."""

from __future__ import annotations

import logging
import sys
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Protocol, runtime_checkable

from tqdm import tqdm

from .windows_taskbar import TaskbarProgressState

if TYPE_CHECKING:  # pragma: no cover - import for typing only
    from .windows_taskbar import TaskbarProgress


logger = logging.getLogger(__name__)


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


class _TaskbarTaskContext(AbstractContextManager[ProgressHandle]):
    """Context manager that wraps another progress task with taskbar updates."""

    def __init__(
        self,
        reporter: "TaskbarProgressReporter",
        context: AbstractContextManager[ProgressHandle],
        total: Optional[int],
    ) -> None:
        self._reporter = reporter
        self._context = context
        self._total = total

    def __enter__(self) -> ProgressHandle:
        handle = self._context.__enter__()
        self._reporter._start(total=self._total, current=handle.current)
        return _TaskbarProgressHandle(handle, self._reporter)

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            return self._context.__exit__(exc_type, exc, tb)
        finally:
            self._reporter._finalize()


@dataclass
class _TaskbarProgressHandle:
    """Progress handle proxy that mirrors events to the Windows taskbar."""

    _delegate: ProgressHandle
    _reporter: "TaskbarProgressReporter"

    @property
    def current(self) -> int:
        return self._delegate.current

    def ensure_total(self, total: int) -> None:
        self._delegate.ensure_total(total)
        self._reporter._on_total(total=total, current=self.current)

    def advance(self, amount: int) -> None:
        previous = self.current
        self._delegate.advance(amount)
        if amount > 0 and self.current != previous:
            self._reporter._on_advance(current=self.current)

    def finish(self) -> None:
        self._delegate.finish()
        self._reporter._on_finish(current=self.current)


class TaskbarProgressReporter(ProgressReporter):
    """Progress reporter that mirrors updates to the Windows taskbar."""

    def __init__(self, delegate: ProgressReporter, taskbar: "TaskbarProgress") -> None:
        self._delegate = delegate
        self._taskbar = taskbar
        self._enabled = True
        self._total: Optional[int] = None
        self._current: int = 0
        self._finalized = False
        logger.debug(
            "TaskbarProgressReporter initialised with delegate=%s taskbar=%s",
            type(delegate).__name__,
            taskbar,
        )

    def log(self, message: str) -> None:
        self._delegate.log(message)

    def task(
        self, *, desc: str = "", total: Optional[int] = None, unit: str = ""
    ) -> AbstractContextManager[ProgressHandle]:
        logger.debug(
            "Creating taskbar-mirrored task desc=%r total=%s unit=%r", desc, total, unit
        )
        context = self._delegate.task(desc=desc, total=total, unit=unit)
        self._finalized = False
        return _TaskbarTaskContext(self, context, total)

    # Internal hooks -----------------------------------------------------
    def _start(self, total: Optional[int], current: int) -> None:
        self._total = total
        self._current = current
        if not self._enabled:
            logger.debug(
                "Skipping taskbar start because reporter is disabled (total=%s current=%s)",
                total,
                current,
            )
            return
        try:
            if not total or total <= 0:
                logger.debug(
                    "Setting taskbar progress state to indeterminate (current=%s)",
                    current,
                )
                self._taskbar.set_progress_state(TaskbarProgressState.INDETERMINATE)
            else:
                logger.debug(
                    "Initialising taskbar progress (current=%s total=%s)",
                    current,
                    total,
                )
                self._taskbar.set_progress_state(TaskbarProgressState.NORMAL)
                self._taskbar.set_progress_value(current, total)
        except Exception as exc:  # pragma: no cover - Windows-specific logging
            self._disable(exc)

    def _on_total(self, total: int, current: int) -> None:
        if total <= 0:
            return
        self._total = max(self._total or 0, total)
        if not self._enabled or not self._total:
            logger.debug(
                "Skipping taskbar total update (enabled=%s total=%s current=%s)",
                self._enabled,
                self._total,
                current,
            )
            return
        try:
            logger.debug(
                "Updating taskbar total/current (total=%s current=%s)",
                self._total,
                current,
            )
            self._taskbar.set_progress_state(TaskbarProgressState.NORMAL)
            self._taskbar.set_progress_value(current, self._total)
        except Exception as exc:  # pragma: no cover - Windows-specific logging
            self._disable(exc)

    def _on_advance(self, current: int) -> None:
        self._current = current
        if not self._enabled or not self._total:
            logger.debug(
                "Skipping taskbar advance (enabled=%s total=%s current=%s)",
                self._enabled,
                self._total,
                current,
            )
            return
        try:
            logger.debug(
                "Advancing taskbar progress (current=%s total=%s)",
                current,
                self._total,
            )
            self._taskbar.set_progress_value(current, self._total)
        except Exception as exc:  # pragma: no cover - Windows-specific logging
            self._disable(exc)

    def _on_finish(self, current: int) -> None:
        self._current = current
        if not self._enabled:
            logger.debug(
                "Skipping taskbar finish because reporter is disabled (current=%s)",
                current,
            )
            return
        try:
            if self._total and self._total > 0:
                logger.debug(
                    "Finishing taskbar progress (current=%s total=%s)",
                    current,
                    self._total,
                )
                self._taskbar.set_progress_value(self._total, self._total)
            self._taskbar.clear()
            logger.debug("Cleared taskbar progress after finish")
        except Exception as exc:  # pragma: no cover - Windows-specific logging
            self._disable(exc)

    def _finalize(self) -> None:
        if self._finalized:
            logger.debug("Taskbar reporter already finalised; skipping cleanup")
            return
        self._finalized = True
        try:
            if self._enabled:
                self._taskbar.clear()
                logger.debug("Cleared taskbar progress during finalise")
        except Exception:  # pragma: no cover - best-effort cleanup
            pass
        finally:
            try:
                self._taskbar.close()
                logger.debug("Closed taskbar progress helper")
            except Exception:  # pragma: no cover - best-effort cleanup
                pass

    def _disable(self, exc: Exception) -> None:
        if not self._enabled:
            return
        self._enabled = False
        logger.debug(
            "Disabling Windows taskbar progress updates: %s", exc, exc_info=True
        )


__all__ = [
    "ProgressHandle",
    "ProgressReporter",
    "NullProgressReporter",
    "TqdmProgressReporter",
    "SignalProgressReporter",
    "TaskbarProgressReporter",
]
