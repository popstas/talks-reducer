"""Pytest configuration for local package imports."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(autouse=True)
def isolate_hardware_backend_cache(monkeypatch, tmp_path):
    """Keep GPU detection from reading or writing the real ``settings.json``."""

    from talks_reducer import ffmpeg

    monkeypatch.setattr(
        ffmpeg, "_hardware_cache_path", lambda: tmp_path / "settings.json"
    )
    monkeypatch.setattr(ffmpeg, "_HARDWARE_BACKEND_CACHE", {})
