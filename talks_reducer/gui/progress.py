"""Progress helpers that bridge the pipeline with the Tkinter GUI."""

from __future__ import annotations

from typing import Callable, Optional

from ..progress import ProgressHandle, SignalProgressReporter


class _GuiProgressHandle(ProgressHandle):
    """Simple progress handle that records totals but only logs milestones."""

    def __init__(self, log_callback: Callable[[str], None], desc: str) -> None:
        self._log_callback = log_callback
        self._desc = desc
        self._current = 0
        self._total: Optional[int] = None
        if desc:
            self._log_callback(f"{desc} started")

    @property
    def current(self) -> int:
        return self._current

    def ensure_total(self, total: int) -> None:
        if self._total is None or total > self._total:
            self._total = total

    def advance(self, amount: int) -> None:
        if amount > 0:
            self._current += amount

    def finish(self) -> None:
        if self._total is not None:
            self._current = self._total
        if self._desc:
            self._log_callback(f"{self._desc} completed")

    def __enter__(self) -> "_GuiProgressHandle":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self.finish()
        return False


class _TkProgressReporter(SignalProgressReporter):
    """Progress reporter that forwards updates to the GUI thread."""

    def __init__(
        self,
        log_callback: Callable[[str], None],
        process_callback: Optional[Callable] = None,
        *,
        stop_callback: Optional[Callable[[], bool]] = None,
    ) -> None:
        self._log_callback = log_callback
        self.process_callback = process_callback
        self._stop_callback = stop_callback

    def log(self, message: str) -> None:
        self._log_callback(message)
        print(message, flush=True)

    def task(
        self, *, desc: str = "", total: Optional[int] = None, unit: str = ""
    ) -> _GuiProgressHandle:
        del total, unit
        return _GuiProgressHandle(self._log_callback, desc)

    def stop_requested(self) -> bool:
        """Return ``True`` when the GUI has asked to cancel processing."""

        if self._stop_callback is None:
            return False
        return bool(self._stop_callback())


__all__ = ["_GuiProgressHandle", "_TkProgressReporter"]
