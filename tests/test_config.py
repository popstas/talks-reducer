from __future__ import annotations

import json
from pathlib import Path

import pytest

from talks_reducer.config import (
    determine_config_path,
    load_settings,
    save_settings,
)


def test_determine_config_path_windows(tmp_path):
    env = {"APPDATA": "C:/Users/example/AppData/Roaming"}
    result = determine_config_path(platform="win32", env=env, home=tmp_path)
    assert result == Path(env["APPDATA"]) / "talks-reducer" / "settings.json"


def test_determine_config_path_windows_without_appdata(tmp_path):
    result = determine_config_path(platform="win32", env={}, home=tmp_path)
    assert (
        result == tmp_path / "AppData" / "Roaming" / "talks-reducer" / "settings.json"
    )


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


def test_load_settings_missing_file_returns_empty(tmp_path):
    assert load_settings(tmp_path / "missing.json") == {}


def test_load_settings_malformed_json_returns_empty(tmp_path):
    config_path = tmp_path / "settings.json"
    config_path.write_text("{not valid json", encoding="utf-8")
    assert load_settings(config_path) == {}


def test_load_settings_non_dict_returns_empty(tmp_path):
    config_path = tmp_path / "settings.json"
    config_path.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_settings(config_path) == {}


def test_save_and_load_round_trip(tmp_path):
    config_path = tmp_path / "nested" / "settings.json"
    payload = {"simple_mode": True, "threshold": 0.5}

    assert save_settings(config_path, payload) is True
    assert config_path.exists()

    loaded = load_settings(config_path)
    assert loaded == payload

    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    assert raw == payload


def test_save_settings_reports_failure(tmp_path):
    # A path whose parent is an existing file cannot be created.
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    config_path = blocker / "settings.json"

    assert save_settings(config_path, {"a": 1}) is False
