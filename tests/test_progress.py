"""Tests for progress reporting utilities."""

from __future__ import annotations

import sys
from typing import Any

import pytest

from talks_reducer import progress


class _FakeBar:
    """Simple tqdm replacement recording lifecycle events."""

    def __init__(self, *, total: int | None = None) -> None:
        self.total = total
        self.n = 0
        self.update_calls: list[int] = []
        self.closed = False

    def update(self, amount: int) -> None:
        self.update_calls.append(amount)
        self.n += amount

    def close(self) -> None:
        self.closed = True


def test_null_progress_reporter_task_is_stateful() -> None:
    reporter = progress.NullProgressReporter()

    with reporter.task(total=5) as handle:
        assert handle.current == 0
        assert getattr(handle, "total") == 5

        handle.ensure_total(10)
        assert getattr(handle, "total") == 10

        handle.advance(3)
        assert handle.current == 3

        handle.finish()
        assert handle.current == getattr(handle, "total")


def test_tqdm_progress_handle_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    reporter = progress.TqdmProgressReporter()
    recorded: dict[str, Any] = {}

    def fake_tqdm(*args: Any, **kwargs: Any) -> _FakeBar:
        bar = _FakeBar(total=kwargs.get("total"))
        recorded["args"] = args
        recorded["kwargs"] = kwargs
        recorded["bar"] = bar
        return bar

    monkeypatch.setattr(progress, "tqdm", fake_tqdm)

    with reporter.task(desc="Processing", total=5, unit="frames") as handle:
        assert isinstance(handle, progress._TqdmProgressHandle)
        assert recorded["args"] == ()
        assert recorded["kwargs"] == {
            "total": 5,
            "desc": "Processing",
            "unit": "frames",
            "bar_format": reporter._bar_format,
            "file": sys.stderr,
        }

        assert handle.bar is recorded["bar"]

        handle.ensure_total(10)
        assert recorded["bar"].total == 10

        handle.ensure_total(8)
        assert recorded["bar"].total == 10

        handle.advance(4)
        assert recorded["bar"].n == 4
        assert handle.current == 4

    assert recorded["bar"].n == 10
    assert recorded["bar"].update_calls == [4, 6]
    assert recorded["bar"].closed is True


def test_tqdm_progress_reporter_log_uses_tqdm_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reporter = progress.TqdmProgressReporter()
    calls: list[str] = []

    def fake_write(message: str) -> None:
        calls.append(message)

    monkeypatch.setattr(progress.tqdm, "write", fake_write)

    reporter.log("hello world")

    assert calls == ["hello world"]
