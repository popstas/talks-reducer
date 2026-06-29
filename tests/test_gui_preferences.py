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


def test_start_in_server_tray_round_trip(tmp_path):
    config_path = tmp_path / "settings.json"
    prefs = GUIPreferences(config_path)

    assert prefs.get("start_in_server_tray", False) is False

    prefs.update("start_in_server_tray", True)

    loaded = load_settings(config_path)
    assert loaded["start_in_server_tray"] is True

    reloaded = GUIPreferences(config_path)
    assert reloaded.get("start_in_server_tray", False) is True


def test_on_start_in_server_tray_change_persists_and_dispatches(tmp_path):
    config_path = tmp_path / "settings.json"
    prefs = GUIPreferences(config_path)
    dispatched: list[bool] = []
    gui = SimpleNamespace(
        preferences=prefs,
        start_in_server_tray_var=SimpleNamespace(get=lambda: True),
        _apply_server_tray_toggle=lambda value: dispatched.append(value),
    )

    PreferenceController(gui).on_start_in_server_tray_change()

    assert dispatched == [True]
    loaded = load_settings(config_path)
    assert loaded["start_in_server_tray"] is True


def test_on_start_in_server_tray_change_reverts_on_failure(tmp_path):
    """A failed enable spawn reverts the optimistic ``True`` write to ``False``.

    Enabling persists ``True`` before spawning so the relaunched managed GUI
    child reads the up-to-date value, but if the spawn raises the write is
    rolled back so a failed relaunch leaves the toggle effectively off.
    """

    config_path = tmp_path / "settings.json"
    prefs = GUIPreferences(config_path)

    def _raise(_value):
        raise RuntimeError("spawn failed")

    gui = SimpleNamespace(
        preferences=prefs,
        start_in_server_tray_var=SimpleNamespace(get=lambda: True),
        _apply_server_tray_toggle=_raise,
    )

    with pytest.raises(RuntimeError):
        PreferenceController(gui).on_start_in_server_tray_change()

    assert load_settings(config_path).get("start_in_server_tray", False) is False


def test_on_start_in_server_tray_change_enable_persists_before_dispatch(tmp_path):
    """Enabling must write ``True`` before the relaunch spawn to avoid a stale read.

    The spawned server-tray's managed GUI child cold-starts and seeds its
    checkbox from ``settings.json``; if the write lagged the spawn it could read
    a stale ``False`` and show the toggle unchecked while running under tray
    mode. The dispatch records what was on disk at call time.
    """

    config_path = tmp_path / "settings.json"
    prefs = GUIPreferences(config_path)
    observed: list[object] = []

    def _record(_value):
        observed.append(load_settings(config_path).get("start_in_server_tray"))

    gui = SimpleNamespace(
        preferences=prefs,
        start_in_server_tray_var=SimpleNamespace(get=lambda: True),
        _apply_server_tray_toggle=_record,
    )

    PreferenceController(gui).on_start_in_server_tray_change()

    assert observed == [True]
    assert load_settings(config_path)["start_in_server_tray"] is True


def test_on_start_in_server_tray_change_disable_persists_before_dispatch(tmp_path):
    """Disabling must write ``False`` before the relaunch spawn to avoid loops.

    The spawned plain GUI cold-starts and re-reads ``settings.json``; if the
    write lagged the spawn it could read a stale ``True`` and boot back into
    server-tray mode. The dispatch records what was on disk at call time.
    """

    config_path = tmp_path / "settings.json"
    prefs = GUIPreferences(config_path)
    prefs.update("start_in_server_tray", True)
    observed: list[object] = []

    def _record(_value):
        observed.append(load_settings(config_path).get("start_in_server_tray"))

    gui = SimpleNamespace(
        preferences=prefs,
        start_in_server_tray_var=SimpleNamespace(get=lambda: False),
        _apply_server_tray_toggle=_record,
    )

    PreferenceController(gui).on_start_in_server_tray_change()

    assert observed == [False]
    assert load_settings(config_path)["start_in_server_tray"] is False


def test_on_start_in_server_tray_change_aborts_when_persist_fails(tmp_path):
    """A failed persistence write aborts the relaunch and restores the toggle.

    ``settings.json`` is unwritable, so ``update`` reports failure. Spawning a
    relaunch that would cold-start from the stale file is worse than not
    switching, so no dispatch happens and the checkbox is reset to the stored
    value.
    """

    config_path = tmp_path / "settings.json"
    prefs = GUIPreferences(config_path)
    # Force every write to fail without touching the real filesystem.
    prefs.save = lambda: False  # type: ignore[method-assign]

    dispatched: list[bool] = []

    class _Var:
        def __init__(self, value: bool) -> None:
            self.value = value
            self.set_calls: list[bool] = []

        def get(self) -> bool:
            return self.value

        def set(self, value: bool) -> None:
            self.set_calls.append(value)
            self.value = value

    var = _Var(True)
    gui = SimpleNamespace(
        preferences=prefs,
        start_in_server_tray_var=var,
        _apply_server_tray_toggle=lambda value: dispatched.append(value),
    )

    PreferenceController(gui).on_start_in_server_tray_change()

    assert dispatched == []
    assert var.set_calls == [False]
    assert load_settings(config_path).get("start_in_server_tray", False) is False


def test_on_start_in_server_tray_change_restore_does_not_redispatch(tmp_path):
    """The restore after a failed write must not re-enter and relaunch.

    Reproduces the real-Tk scenario: a standalone GUI has ``True`` persisted,
    the user unchecks the box, and the ``False`` write fails. Rollback restores
    the in-memory ``True`` and ``_restore_server_tray_var`` sets the variable
    back to ``True``. In real Tk that ``set`` re-fires the ``write`` trace, so
    the fake var here invokes the controller again. Without the re-entrancy
    guard the re-entry would call ``_apply_server_tray_toggle(True)`` and spawn
    server-tray — exactly the relaunch the failed write was meant to abort.
    """

    config_path = tmp_path / "settings.json"
    prefs = GUIPreferences(config_path, settings={"start_in_server_tray": True})
    # Force every write to fail without touching the real filesystem.
    prefs.save = lambda: False  # type: ignore[method-assign]

    dispatched: list[bool] = []
    controller_box: list[PreferenceController] = []

    class _ReentrantVar:
        """Fake ``BooleanVar`` whose ``set`` re-fires the write trace."""

        def __init__(self, value: bool) -> None:
            self.value = value
            self.set_calls: list[bool] = []

        def get(self) -> bool:
            return self.value

        def set(self, value: bool) -> None:
            self.set_calls.append(value)
            self.value = value
            controller_box[0].on_start_in_server_tray_change()

    var = _ReentrantVar(False)
    gui = SimpleNamespace(
        preferences=prefs,
        start_in_server_tray_var=var,
        _apply_server_tray_toggle=lambda value: dispatched.append(value),
    )

    controller = PreferenceController(gui)
    controller_box.append(controller)

    controller.on_start_in_server_tray_change()

    assert dispatched == []
    assert var.set_calls == [True]
    assert load_settings(config_path).get("start_in_server_tray", False) is False


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
