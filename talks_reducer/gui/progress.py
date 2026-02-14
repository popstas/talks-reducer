"""Progress helpers that bridge the pipeline with the Tkinter GUI."""

from __future__ import annotations

from typing import Callable, Optional

from ..progress import CallbackProgressHandle, ProgressHandle, SignalProgressReporter


class _GuiProgressHandle(CallbackProgressHandle):
    """Simple progress handle that records totals but only logs milestones."""

    def __init__(self, log_callback: Callable[[str], None], desc: str) -> None:
        self._log_callback = log_callback
        super().__init__(
            desc=desc,
            on_start=self._on_start,
            on_finish=self._on_finish,
        )

    def _on_start(self, desc: str, total: Optional[int]) -> None:
        del total
        if desc:
            self._log_callback(f"{desc} started")

    def _on_finish(self, current: int, total: Optional[int], desc: str) -> None:
        del current, total
        if desc:
            self._log_callback(f"{desc} completed")


class _TkProgressReporter(SignalProgressReporter):
    """Progress reporter that forwards updates to the GUI thread."""

    def __init__(
        self,
        log_callback: Callable[[str], None],
        process_callback: Optional[Callable] = None,
        *,
        stop_callback: Optional[Callable[[], bool]] = None,
    ) -> None:
        super().__init__()
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
