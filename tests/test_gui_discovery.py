"""Tests for :mod:`talks_reducer.gui.discovery`."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Callable, List

import pytest

from talks_reducer.gui import discovery as discovery_module


class StubButton:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def configure(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


class StubVar:
    def __init__(self) -> None:
        self.value: str | None = None

    def set(self, value: str) -> None:
        self.value = value


class StubMessageBox:
    def __init__(self) -> None:
        self.errors: list[tuple[str, str]] = []
        self.infos: list[tuple[str, str]] = []

    def showerror(self, title: str, message: str) -> None:
        self.errors.append((title, message))

    def showinfo(self, title: str, message: str) -> None:
        self.infos.append((title, message))


class StubGUI:
    def __init__(self) -> None:
        self._discovery_thread = None
        self.server_discover_button = StubButton()
        self.server_url_var = StubVar()
        self.logs: list[str] = []
        self.tk = SimpleNamespace(DISABLED="disabled", NORMAL="normal")
        self.messagebox = StubMessageBox()
        self._scheduled_callbacks: list[Callable[[], None]] = []

    def _append_log(self, message: str) -> None:
        self.logs.append(message)

    def _schedule_on_ui_thread(self, callback: Callable[[], None]) -> None:
        self._scheduled_callbacks.append(callback)
        callback()


class DummyThread:
    def __init__(self, target: Callable[[], None], daemon: bool) -> None:
        self.target = target
        self.daemon = daemon
        self.started = False

    def start(self) -> None:
        self.started = True
        self.target()

    def is_alive(self) -> bool:
        return self.started


@pytest.fixture()
def stub_gui() -> StubGUI:
    return StubGUI()


def test_start_discovery_launches_background_thread(
    monkeypatch: pytest.MonkeyPatch, stub_gui: StubGUI
) -> None:
    calls: list[tuple[int, int]] = []

    def fake_discover_servers(
        *, progress_callback: Callable[[int, int], None]
    ) -> List[str]:
        progress_callback(1, 2)
        calls.append((1, 2))
        return ["http://server-one", "http://server-two"]

    monkeypatch.setattr(
        discovery_module, "core_discover_servers", fake_discover_servers
    )
    monkeypatch.setattr(
        discovery_module.threading,
        "Thread",
        lambda target, daemon: DummyThread(target, daemon),
    )

    recorded_urls: list[List[str]] = []

    def fake_show_results(gui: StubGUI, urls: List[str]) -> None:  # noqa: D401
        """Record displayed URLs."""

        recorded_urls.append(urls)

    monkeypatch.setattr(discovery_module, "show_discovery_results", fake_show_results)

    discovery_module.start_discovery(stub_gui)

    assert isinstance(stub_gui._discovery_thread, DummyThread)
    assert stub_gui._discovery_thread.started is True
    assert stub_gui.server_discover_button.calls[0] == {
        "state": "disabled",
        "text": "Discovering…",
    }
    assert {"text": "1 / 2"} in stub_gui.server_discover_button.calls
    assert {
        "state": "normal",
        "text": "Discover",
    } in stub_gui.server_discover_button.calls
    assert stub_gui.logs == [
        "Discovering Talks Reducer servers on port 9005…",
        "Discovered 2 servers.",
    ]
    assert calls == [(1, 2)]
    assert recorded_urls == [["http://server-one", "http://server-two"]]


def test_start_discovery_skips_when_thread_running(stub_gui: StubGUI) -> None:
    class AliveThread:
        @staticmethod
        def is_alive() -> bool:
            return True

    stub_gui._discovery_thread = AliveThread()

    discovery_module.start_discovery(stub_gui)

    assert stub_gui.server_discover_button.calls == []
    assert stub_gui.logs == []


def test_on_discovery_failed_reports_error(stub_gui: StubGUI) -> None:
    error = RuntimeError("boom")

    discovery_module.on_discovery_failed(stub_gui, error)

    assert stub_gui.server_discover_button.calls == [
        {"state": "normal", "text": "Discover"}
    ]
    assert stub_gui.logs == ["Discovery failed: boom"]
    assert stub_gui.messagebox.errors == [
        ("Discovery failed", "Discovery failed: boom")
    ]


def test_on_discovery_complete_handles_empty_result(stub_gui: StubGUI) -> None:
    discovery_module.on_discovery_complete(stub_gui, [])

    assert stub_gui.server_discover_button.calls == [
        {"state": "normal", "text": "Discover"}
    ]
    assert stub_gui.logs == ["No Talks Reducer servers were found."]
    assert stub_gui.messagebox.infos == [
        ("No servers found", "No Talks Reducer servers responded on port 9005."),
    ]


def test_on_discovery_complete_sets_single_url(stub_gui: StubGUI) -> None:
    discovery_module.on_discovery_complete(stub_gui, ["http://server"])

    assert stub_gui.server_discover_button.calls == [
        {"state": "normal", "text": "Discover"}
    ]
    assert stub_gui.server_url_var.value == "http://server"
    assert stub_gui.logs == ["Discovered 1 server."]
