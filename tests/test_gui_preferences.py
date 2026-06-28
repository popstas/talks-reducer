from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from talks_reducer.gui.preferences import (
    GUIPreferences,
    PreferenceController,
    determine_config_path,
    load_settings,
)


def test_determine_config_path_windows(tmp_path):
    env = {"APPDATA": "C:/Users/example/AppData/Roaming"}
    result = determine_config_path(platform="win32", env=env, home=tmp_path)
    assert result == Path(env["APPDATA"]) / "talks-reducer" / "settings.json"


def test_determine_config_path_macos(tmp_path):
    result = determine_config_path(platform="darwin", env={}, home=tmp_path)
    assert (
        result
        == tmp_path
        / "Library"
        / "Application Support"
        / "talks-reducer"
        / "settings.json"
    )


def test_determine_config_path_linux_xdg(tmp_path):
    env = {"XDG_CONFIG_HOME": str(tmp_path / "config")}
    result = determine_config_path(platform="linux", env=env, home=tmp_path)
    assert result == Path(env["XDG_CONFIG_HOME"]) / "talks-reducer" / "settings.json"


def test_determine_config_path_linux_home(tmp_path):
    result = determine_config_path(platform="linux", env={}, home=tmp_path)
    assert result == tmp_path / ".config" / "talks-reducer" / "settings.json"


def test_get_float_converts_strings_and_persists(tmp_path):
    config_path = tmp_path / "settings.json"
    prefs = GUIPreferences(config_path, {"value": "2.5"})

    result = prefs.get_float("value", 1.0)

    assert result == pytest.approx(2.5)
    assert prefs.data["value"] == pytest.approx(2.5)

    with config_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    assert data["value"] == pytest.approx(2.5)


def test_save_and_load_round_trip(tmp_path):
    config_path = tmp_path / "settings.json"
    prefs = GUIPreferences(config_path)
    prefs.update("simple_mode", True)
    prefs.update("threshold", 0.5)

    loaded = load_settings(config_path)
    assert loaded == {"simple_mode": True, "threshold": 0.5}

    prefs.update("threshold", 0.75)
    reloaded = load_settings(config_path)
    assert reloaded["threshold"] == pytest.approx(0.75)


def test_on_cut_change_persists_values(tmp_path):
    config_path = tmp_path / "settings.json"
    prefs = GUIPreferences(config_path)
    gui = SimpleNamespace(
        preferences=prefs,
        cut_enabled_var=SimpleNamespace(get=lambda: True),
        cut_start_var=SimpleNamespace(get=lambda: 12.5),
        cut_end_var=SimpleNamespace(get=lambda: 90.0),
    )

    PreferenceController(gui).on_cut_change()

    loaded = load_settings(config_path)
    assert loaded["cut_enabled"] is True
    assert loaded["cut_start"] == pytest.approx(12.5)
    assert loaded["cut_end"] == pytest.approx(90.0)


def test_on_video_codec_change_persists_mp3(tmp_path):
    config_path = tmp_path / "settings.json"
    prefs = GUIPreferences(config_path)
    recorded: list[str] = []
    gui = SimpleNamespace(
        preferences=prefs,
        video_codec_var=SimpleNamespace(
            get=lambda: "mp3", set=lambda value: recorded.append(value)
        ),
    )

    PreferenceController(gui).on_video_codec_change()

    assert recorded == []
    loaded = load_settings(config_path)
    assert loaded["video_codec"] == "mp3"


def test_on_video_codec_change_resets_unknown_codec(tmp_path):
    config_path = tmp_path / "settings.json"
    prefs = GUIPreferences(config_path)
    recorded: list[str] = []
    gui = SimpleNamespace(
        preferences=prefs,
        video_codec_var=SimpleNamespace(
            get=lambda: "bogus", set=lambda value: recorded.append(value)
        ),
    )

    PreferenceController(gui).on_video_codec_change()

    assert recorded == ["h264"]
    loaded = load_settings(config_path)
    assert loaded["video_codec"] == "h264"


def test_on_cut_change_handles_invalid_values(tmp_path):
    config_path = tmp_path / "settings.json"
    prefs = GUIPreferences(config_path)
    gui = SimpleNamespace(
        preferences=prefs,
        cut_enabled_var=SimpleNamespace(get=lambda: False),
        cut_start_var=SimpleNamespace(get=lambda: "bad"),
        cut_end_var=SimpleNamespace(get=lambda: None),
    )

    PreferenceController(gui).on_cut_change()

    loaded = load_settings(config_path)
    assert loaded["cut_enabled"] is False
    assert loaded["cut_start"] == pytest.approx(0.0)
    assert loaded["cut_end"] == pytest.approx(0.0)
