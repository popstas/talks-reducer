from __future__ import annotations

from pathlib import Path

from talks_reducer.gui.app import _resolve_prefer_global_ffmpeg
from talks_reducer.gui.preferences import GUIPreferences


def _make_preferences(tmp_path: Path, settings: dict) -> GUIPreferences:
    return GUIPreferences(tmp_path / "settings.json", settings=settings)


def test_first_start_enables_when_global_ffmpeg_found(tmp_path):
    settings: dict = {}
    prefs = _make_preferences(tmp_path, settings)

    result = _resolve_prefer_global_ffmpeg(prefs, global_ffmpeg_available=True)

    assert result is True
    # The detected default is persisted so it survives the next launch.
    assert settings["use_global_ffmpeg"] is True


def test_first_start_stays_off_when_no_global_ffmpeg(tmp_path):
    settings: dict = {}
    prefs = _make_preferences(tmp_path, settings)

    result = _resolve_prefer_global_ffmpeg(prefs, global_ffmpeg_available=False)

    assert result is False
    assert settings["use_global_ffmpeg"] is False


def test_stored_preference_is_respected_when_available(tmp_path):
    prefs = _make_preferences(tmp_path, {"use_global_ffmpeg": False})

    result = _resolve_prefer_global_ffmpeg(prefs, global_ffmpeg_available=True)

    # A user who turned it off keeps it off even though a binary exists.
    assert result is False


def test_stored_enabled_preference_is_respected(tmp_path):
    prefs = _make_preferences(tmp_path, {"use_global_ffmpeg": True})

    result = _resolve_prefer_global_ffmpeg(prefs, global_ffmpeg_available=True)

    assert result is True


def test_stored_enabled_cleared_when_binary_missing(tmp_path):
    settings = {"use_global_ffmpeg": True}
    prefs = _make_preferences(tmp_path, settings)

    result = _resolve_prefer_global_ffmpeg(prefs, global_ffmpeg_available=False)

    assert result is False
    assert settings["use_global_ffmpeg"] is False
