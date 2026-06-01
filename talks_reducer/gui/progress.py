"""Progress helpers that bridge the pipeline with the Tkinter GUI."""

from __future__ import annotations

from typing import Callable, Optional

from ..progress import CallbackProgressHandle, ProgressHandle, SignalProgressReporter

# Stable percentage bands for each known pipeline stage. Mapping per-task
# progress into these bands keeps the desktop GUI progress bar advancing
# monotonically across upload, audio, and final-encode phases instead of
# resetting to zero whenever a new task begins.
STAGE_PROGRESS_RANGES: tuple[tuple[str, float, float], ...] = (
    ("uploading:", 0.0, 5.0),
    ("extracting audio:", 5.0, 20.0),
    ("audio processing:", 20.0, 35.0),
    ("generating final", 35.0, 100.0),
)


def map_stage_progress(
    desc: str, current: Optional[int], total: Optional[int]
) -> Optional[float]:
    """Map a per-task progress fraction onto the overall progress-bar percentage.

    Known pipeline stages occupy fixed percentage bands (see
    :data:`STAGE_PROGRESS_RANGES`) so the bar never moves backwards between
    stages. The ``"generating final"`` prefix intentionally matches both
    ``"Generating final:"`` and ``"Generating final (fallback):"``. Unknown task
    descriptions preserve the full 0-100 range.

    Returns ``None`` when *total* is missing or non-positive because a fraction
    cannot be derived.
    """

    if not total or total <= 0:
        return None
    fraction = 0.0 if current is None else current / total
    fraction = max(0.0, min(1.0, fraction))
    key = (desc or "").strip().lower()
    for prefix, start, end in STAGE_PROGRESS_RANGES:
        if key.startswith(prefix):
            return start + fraction * (end - start)
    return fraction * 100.0


class _GuiProgressHandle(CallbackProgressHandle):
    """Simple progress handle that records totals but only logs milestones."""

    def __init__(
        self,
        log_callback: Callable[[str], None],
        desc: str,
        *,
        total: Optional[int] = None,
        progress_callback: Optional[Callable[[float], None]] = None,
        stage_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._log_callback = log_callback
        self._progress_callback = progress_callback
        self._stage_callback = stage_callback
        self._last_reported_value: Optional[float] = None
        super().__init__(
            desc=desc,
            total=total,
            on_start=self._on_start,
            on_update=self._on_update if progress_callback else None,
            on_finish=self._on_finish,
        )

    def _on_start(self, desc: str, total: Optional[int]) -> None:
        del total
        if desc and self._stage_callback is not None:
            # Notify the GUI as soon as the structured stage opens so the
            # synthetic audio fallback timer can be cancelled before it overwrites
            # the status with synthetic percentages.
            self._stage_callback(desc)
        if desc:
            self._log_callback(f"{desc} started")

    def _on_update(self, current: int, total: Optional[int], desc: str) -> None:
        if self._progress_callback is None:
            return
        bar_value = map_stage_progress(desc, current, total)
        if bar_value is None or bar_value == self._last_reported_value:
            return
        self._last_reported_value = bar_value
        self._progress_callback(bar_value)

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
        progress_callback: Optional[Callable[[float], None]] = None,
        stage_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__()
        self._log_callback = log_callback
        self.process_callback = process_callback
        self._stop_callback = stop_callback
        self._progress_callback = progress_callback
        self._stage_callback = stage_callback

    def log(self, message: str) -> None:
        self._log_callback(message)
        print(message, flush=True)

    def task(
        self, *, desc: str = "", total: Optional[int] = None, unit: str = ""
    ) -> _GuiProgressHandle:
        del unit
        return _GuiProgressHandle(
            self._log_callback,
            desc,
            total=total,
            progress_callback=self._progress_callback,
            stage_callback=self._stage_callback,
        )

    def stop_requested(self) -> bool:
        """Return ``True`` when the GUI has asked to cancel processing."""

        if self._stop_callback is None:
            return False
        return bool(self._stop_callback())


__all__ = [
    "STAGE_PROGRESS_RANGES",
    "map_stage_progress",
    "_GuiProgressHandle",
    "_TkProgressReporter",
]
