from __future__ import annotations

from typing import List

import pytest

from talks_reducer.gui import relaunch


def test_build_app_command_source_server_tray(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(relaunch.sys, "frozen", False, raising=False)
    monkeypatch.setattr(relaunch.sys, "executable", "/usr/bin/python3")

    command = relaunch.build_app_command("server-tray")

    assert command == [
        "/usr/bin/python3",
        "-m",
        "talks_reducer.server_tray",
        "--with-gui",
    ]


def test_build_app_command_source_gui(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(relaunch.sys, "frozen", False, raising=False)
    monkeypatch.setattr(relaunch.sys, "executable", "/usr/bin/python3")

    command = relaunch.build_app_command("gui")

    assert command == ["/usr/bin/python3", "-m", "talks_reducer.gui"]


def test_build_app_command_frozen_server_tray(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(relaunch.sys, "frozen", True, raising=False)
    monkeypatch.setattr(relaunch.sys, "executable", "/opt/TalksReducer.app/exe")

    command = relaunch.build_app_command("server-tray")

    assert command == ["/opt/TalksReducer.app/exe", "--server", "--with-gui"]


def test_build_app_command_frozen_gui(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(relaunch.sys, "frozen", True, raising=False)
    monkeypatch.setattr(relaunch.sys, "executable", "/opt/TalksReducer.app/exe")

    command = relaunch.build_app_command("gui")

    assert command == ["/opt/TalksReducer.app/exe"]


def test_build_app_command_appends_extra_args(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(relaunch.sys, "frozen", False, raising=False)
    monkeypatch.setattr(relaunch.sys, "executable", "/usr/bin/python3")

    command = relaunch.build_app_command(
        "gui", extra_args=["--server-managed", "--server-url", "http://x"]
    )

    assert command == [
        "/usr/bin/python3",
        "-m",
        "talks_reducer.gui",
        "--server-managed",
        "--server-url",
        "http://x",
    ]


def test_build_app_command_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError):
        relaunch.build_app_command("bogus")


def test_spawn_detached_posix(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class DummyPopen:
        def __init__(self, command: List[str], **kwargs: object) -> None:
            captured["command"] = command
            captured["kwargs"] = kwargs

    monkeypatch.setattr(relaunch.sys, "platform", "linux")
    monkeypatch.setattr(relaunch.subprocess, "Popen", DummyPopen)

    result = relaunch.spawn_detached(["a", "b"])

    assert isinstance(result, DummyPopen)
    assert captured["command"] == ["a", "b"]
    assert captured["kwargs"] == {"start_new_session": True}


def test_spawn_detached_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class DummyPopen:
        def __init__(self, command: List[str], **kwargs: object) -> None:
            captured["command"] = command
            captured["kwargs"] = kwargs

    monkeypatch.setattr(relaunch.sys, "platform", "win32")
    monkeypatch.setattr(relaunch.subprocess, "Popen", DummyPopen)

    relaunch.spawn_detached(["a", "b"])

    kwargs = captured["kwargs"]
    assert "creationflags" in kwargs
    detached = getattr(relaunch.subprocess, "DETACHED_PROCESS", 0x00000008)
    new_group = getattr(relaunch.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    assert kwargs["creationflags"] == detached | new_group
    assert "start_new_session" not in kwargs


def test_spawn_detached_propagates_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(command: List[str], **kwargs: object) -> None:
        raise OSError("nope")

    monkeypatch.setattr(relaunch.sys, "platform", "linux")
    monkeypatch.setattr(relaunch.subprocess, "Popen", boom)

    with pytest.raises(OSError):
        relaunch.spawn_detached(["a"])
