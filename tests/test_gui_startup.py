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
