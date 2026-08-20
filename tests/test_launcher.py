"""Tests for the PyInstaller launcher script."""

from __future__ import annotations

import multiprocessing
import runpy
from pathlib import Path

LAUNCHER = Path(__file__).resolve().parents[1] / "launcher.py"


def test_launcher_prepares_multiprocessing_before_starting_the_app(monkeypatch):
    """Frozen builds re-run the launcher per worker, so the bootstrap comes first."""

    events: list[str] = []

    monkeypatch.setattr(
        multiprocessing, "freeze_support", lambda: events.append("freeze_support")
    )
    monkeypatch.setattr("talks_reducer.gui.main", lambda: events.append("gui") or True)

    runpy.run_path(str(LAUNCHER), run_name="__main__")

    assert events == ["freeze_support", "gui"]
