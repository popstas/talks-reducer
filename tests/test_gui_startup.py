from __future__ import annotations

from types import SimpleNamespace
from typing import List

import pytest

from talks_reducer.gui import startup


def test_main_launches_gui_when_no_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    created: List[SimpleNamespace] = []

    class DummyApp(SimpleNamespace):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.ran = False
            created.append(self)

        def run(self) -> None:  # pragma: no cover - simple stub
            self.ran = True

    monkeypatch.setattr(startup, "TalksReducerGUI", DummyApp)
    monkeypatch.setattr(startup, "_check_tkinter_available", lambda: (True, ""))

    cli_calls: list[list[str]] = []

    def fake_cli(args: List[str]) -> None:
        cli_calls.append(list(args))

    monkeypatch.setattr(startup, "cli_main", fake_cli)

    result = startup.main([])

    assert result is True
    assert cli_calls == []
    assert created and created[0].ran is True


def test_main_delegates_to_cli_when_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(startup, "TalksReducerGUI", object)

    received: list[list[str]] = []

    def fake_cli(args: List[str]) -> None:
        received.append(list(args))

    monkeypatch.setattr(startup, "cli_main", fake_cli)

    result = startup.main(["input.mp4"])

    assert result is False
    assert received == [["input.mp4"]]


def test_parse_seeded_launch_extracts_file_and_settings(tmp_path) -> None:
    video = tmp_path / "talk.mp4"
    video.write_bytes(b"data")

    seeded = startup._parse_seeded_launch(
        ["--small", "--silent_speed", "5", str(video)]
    )

    assert seeded is not None
    input_files, settings = seeded
    assert input_files == [str(video)]
    assert settings["small"] is True
    assert settings["silent_speed"] == 5.0
    # Unspecified options are not seeded so stored preferences are preserved.
    assert "video_codec" not in settings
    assert "optimize" not in settings


def test_parse_seeded_launch_accepts_hyphenated_flags(tmp_path) -> None:
    """The documented ``--silent-speed`` shortcut form must seed the GUI too."""

    video = tmp_path / "talk.mp4"
    video.write_bytes(b"data")

    seeded = startup._parse_seeded_launch(
        ["--small", "--silent-speed", "5", str(video)]
    )

    assert seeded is not None
    input_files, settings = seeded
    assert input_files == [str(video)]
    assert settings["small"] is True
    assert settings["silent_speed"] == 5.0


def test_parse_seeded_launch_maps_host_to_server_url(tmp_path) -> None:
    video = tmp_path / "talk.mp4"
    video.write_bytes(b"data")

    seeded = startup._parse_seeded_launch(["--host", "localhost", str(video)])

    assert seeded is not None
    _, settings = seeded
    assert settings["server_url"] == "http://localhost:9005"


def test_parse_seeded_launch_returns_none_without_existing_file(tmp_path) -> None:
    missing = tmp_path / "missing.mp4"

    assert startup._parse_seeded_launch(["--small", str(missing)]) is None


def test_parse_seeded_launch_returns_none_for_unknown_flag(tmp_path) -> None:
    video = tmp_path / "talk.mp4"
    video.write_bytes(b"data")

    assert startup._parse_seeded_launch(["--definitely-unknown", str(video)]) is None


def test_main_seeds_gui_with_args_and_positional_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    video = tmp_path / "talk.mp4"
    video.write_bytes(b"data")

    created: list[dict] = []

    class DummyApp:
        def __init__(self, initial_inputs=None, *, auto_run=False, cli_settings=None):
            created.append(
                {
                    "initial_inputs": list(initial_inputs or []),
                    "auto_run": auto_run,
                    "cli_settings": dict(cli_settings or {}),
                }
            )
            self.ran = False

        def run(self) -> None:
            self.ran = True

    monkeypatch.setattr(startup, "TalksReducerGUI", DummyApp)
    monkeypatch.setattr(startup.sys, "platform", "win32")

    cli_calls: list[list[str]] = []
    monkeypatch.setattr(startup, "cli_main", lambda args: cli_calls.append(list(args)))

    result = startup.main(["--small", "--silent_speed", "5", str(video)])

    assert result is True
    assert cli_calls == []
    assert created and created[0]["initial_inputs"] == [str(video)]
    assert created[0]["auto_run"] is True
    assert created[0]["cli_settings"]["small"] is True
    assert created[0]["cli_settings"]["silent_speed"] == 5.0


def test_main_falls_back_to_cli_without_positional_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args, **kwargs):  # pragma: no cover - should not be called
        raise AssertionError("GUI should not launch without an existing file")

    monkeypatch.setattr(startup, "TalksReducerGUI", fail)
    monkeypatch.setattr(startup.sys, "platform", "win32")

    cli_calls: list[list[str]] = []
    monkeypatch.setattr(startup, "cli_main", lambda args: cli_calls.append(list(args)))

    result = startup.main(["--help-me", "nope.mp4"])

    assert result is False
    assert cli_calls == [["--help-me", "nope.mp4"]]


def test_main_server_forwards_with_gui_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    tray_calls: list[list[str]] = []

    tray_module = SimpleNamespace(main=lambda argv: tray_calls.append(list(argv)))

    monkeypatch.setattr(
        startup.importlib,
        "import_module",
        lambda name: tray_module,
    )

    result = startup.main(["--server", "--with-gui"])

    assert result is False
    assert tray_calls == [["--with-gui"]]


def test_main_handles_missing_tkinter(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(*args, **kwargs):  # pragma: no cover - should not be called
        raise AssertionError("GUI should not start when tkinter is unavailable")

    monkeypatch.setattr(startup, "TalksReducerGUI", fail)
    monkeypatch.setattr(startup, "_check_tkinter_available", lambda: (False, "missing"))

    result = startup.main([])

    captured = capsys.readouterr()

    assert result is False
    assert "GUI not available" in captured.out


def test_check_tkinter_available_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        startup.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout='{"status": "ok"}\n', stderr=""),
    )

    available, message = startup._check_tkinter_available()

    assert available is True
    assert message == ""


def test_check_tkinter_available_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        startup.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout='{"status": "import_error", "error": "ModuleNotFoundError: tk"}\n',
            stderr="",
        ),
    )

    available, message = startup._check_tkinter_available()

    assert available is False
    assert "tkinter is not installed" in message


def test_check_tkinter_available_init_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        startup.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout='{"status": "init_error", "error": "RuntimeError: display"}\n',
            stderr="",
        ),
    )

    available, message = startup._check_tkinter_available()

    assert available is False
    assert "could not open a window" in message


def test_check_tkinter_available_handles_invalid_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        startup.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="not json\n", stderr=""),
    )

    available, message = startup._check_tkinter_available()

    assert available is False
    assert message == "not json"


def test_check_tkinter_available_handles_missing_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        startup.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="\n", stderr="\n"),
    )

    available, message = startup._check_tkinter_available()

    assert available is False
    assert message == "Window creation failed"
