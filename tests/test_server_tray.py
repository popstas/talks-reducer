"""Tests for the server tray integration helpers."""

from __future__ import annotations

import sys
import threading
import time as time_module
from typing import Any, Callable, List, Optional

import pytest

from talks_reducer import server_tray


class DummyMenu:
    def __init__(self, *items: Any) -> None:
        self.items = items


class DummyMenuItem:
    def __init__(
        self,
        label: str,
        action: Optional[Callable[..., Any]],
        *,
        default: bool = False,
        enabled: bool = True,
    ) -> None:
        self.label = label
        self.action = action
        self.default = default
        self.enabled = enabled


class DummyIcon:
    def __init__(
        self, name: str, icon_image: Any, title: str, *, menu: DummyMenu
    ) -> None:
        self.name = name
        self.icon_image = icon_image
        self.title = title
        self.menu = menu
        self.visible = True
        self.run_called = False
        self.run_detached_called = False
        self.stop_called = 0
        self.notifications: List[str] = []

    def run(self) -> None:
        self.run_called = True

    def run_detached(self) -> None:
        self.run_detached_called = True

    def stop(self) -> None:
        self.stop_called += 1

    def notify(self, message: str) -> None:
        self.notifications.append(message)


class DummyTrayBackend:
    def __init__(self) -> None:
        self.icons: List[DummyIcon] = []

    def Menu(self, *items: Any) -> DummyMenu:  # noqa: N802 - match pystray API
        return DummyMenu(*items)

    def MenuItem(self, *args: Any, **kwargs: Any) -> DummyMenuItem:  # noqa: N802
        return DummyMenuItem(*args, **kwargs)

    def Icon(self, *args: Any, **kwargs: Any) -> DummyIcon:  # noqa: N802
        icon = DummyIcon(*args, **kwargs)
        self.icons.append(icon)
        return icon


class DummyServer:
    def __init__(self, local_url: Any, share_url: Optional[Any] = None) -> None:
        self.local_url = local_url
        self.share_url = share_url
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class DummyDemo:
    def __init__(self, server: DummyServer, record: List[dict]) -> None:
        self._server = server
        self._record = record

    def launch(self, **kwargs: Any) -> DummyServer:
        self._record.append(kwargs)
        return self._server


class DummyURL:
    """Lightweight wrapper that mimics objects returning URLs via ``__str__``."""

    def __init__(self, value: str) -> None:
        self._value = value

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self._value

    def __repr__(self) -> str:  # pragma: no cover - trivial debug helper
        return f"DummyURL({self._value!r})"


@pytest.fixture()
def fast_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch ``server_tray.time.sleep`` to avoid slow polling in tests."""

    monkeypatch.setattr(server_tray.time, "sleep", lambda _seconds: None)


def test_headless_mode_runs_and_opens_browser(
    monkeypatch: pytest.MonkeyPatch, fast_sleep: None
) -> None:
    open_calls: List[str] = []
    launch_calls: List[dict] = []
    backend = DummyTrayBackend()
    server = DummyServer(DummyURL("http://0.0.0.0:1234/"))
    demo = DummyDemo(server, launch_calls)

    app = server_tray._ServerTrayApplication(
        host="0.0.0.0",
        port=1234,
        share=False,
        open_browser=True,
        tray_mode="headless",
        tray_backend=backend,
        build_interface=lambda: demo,
        open_browser_callback=open_calls.append,
    )

    runner = threading.Thread(target=app.run, daemon=True)
    runner.start()

    assert app._ready_event.wait(timeout=1.0)

    for _ in range(20):
        if open_calls:
            break
        time_module.sleep(0.05)

    assert open_calls == ["http://127.0.0.1:1234/"]
    assert launch_calls == [
        {
            "server_name": "0.0.0.0",
            "server_port": 1234,
            "share": False,
            "inbrowser": False,
            "prevent_thread_lock": True,
            "show_error": True,
        }
    ]

    app.stop()
    runner.join(timeout=2.0)
    assert not runner.is_alive()
    assert server.close_calls >= 1


def test_headless_mode_uses_stringified_share_url(
    monkeypatch: pytest.MonkeyPatch, fast_sleep: None
) -> None:
    open_calls: List[str] = []
    backend = DummyTrayBackend()
    server = DummyServer(
        DummyURL("http://0.0.0.0:4321/"), share_url=DummyURL("https://example.test/")
    )
    demo = DummyDemo(server, [])

    app = server_tray._ServerTrayApplication(
        host="0.0.0.0",
        port=4321,
        share=True,
        open_browser=True,
        tray_mode="headless",
        tray_backend=backend,
        build_interface=lambda: demo,
        open_browser_callback=open_calls.append,
    )

    runner = threading.Thread(target=app.run, daemon=True)
    runner.start()

    assert app._ready_event.wait(timeout=1.0)

    for _ in range(20):
        if open_calls:
            break
        time_module.sleep(0.05)

    assert open_calls == ["https://example.test/"]

    app.stop()
    runner.join(timeout=2.0)
    assert not runner.is_alive()


def test_pystray_detached_mode_stops_icon(
    monkeypatch: pytest.MonkeyPatch, fast_sleep: None
) -> None:
    backend = DummyTrayBackend()
    server = DummyServer("http://127.0.0.1:9005/")
    demo = DummyDemo(server, [])

    app = server_tray._ServerTrayApplication(
        host="127.0.0.1",
        port=9005,
        share=False,
        open_browser=False,
        tray_mode="pystray-detached",
        tray_backend=backend,
        build_interface=lambda: demo,
        open_browser_callback=lambda _url: None,
    )

    runner = threading.Thread(target=app.run, daemon=True)
    runner.start()

    assert app._ready_event.wait(timeout=1.0)

    app.stop()
    runner.join(timeout=2.0)
    assert not runner.is_alive()

    assert backend.icons, "Icon should be created in detached tray mode"
    icon = backend.icons[0]
    assert icon.run_detached_called is True
    assert icon.stop_called >= 1


def test_launch_gui_resets_completed_process(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = DummyTrayBackend()
    server = DummyServer("http://127.0.0.1:9005/")
    demo = DummyDemo(server, [])

    app = server_tray._ServerTrayApplication(
        host="127.0.0.1",
        port=9005,
        share=False,
        open_browser=False,
        tray_mode="pystray",
        tray_backend=backend,
        build_interface=lambda: demo,
        open_browser_callback=lambda _url: None,
    )

    class FakeProcess:
        def __init__(self) -> None:
            self.args: Optional[List[str]] = None
            self.wait_calls = 0
            self.terminate_called = False
            self.kill_called = False
            self._done = threading.Event()

        def wait(self, timeout: Optional[float] = None) -> int:
            self.wait_calls += 1
            self._done.set()
            return 0

        def poll(self) -> Optional[int]:
            return 0 if self._done.is_set() else None

        def terminate(self) -> None:
            self.terminate_called = True

        def kill(self) -> None:
            self.kill_called = True

    fake_process = FakeProcess()

    def fake_popen(args: List[str], **_kwargs: Any) -> FakeProcess:
        fake_process.args = list(args)
        return fake_process

    monkeypatch.setattr(server_tray.subprocess, "Popen", fake_popen)

    app._launch_gui()

    assert fake_process.args == [sys.executable, "-m", "talks_reducer.gui"]
    assert fake_process._done.wait(timeout=1.0)

    for _ in range(20):
        if app._gui_process is None:
            break
        time_module.sleep(0.05)

    assert app._gui_process is None
    assert fake_process.wait_calls == 1
    assert fake_process.terminate_called is False
    assert fake_process.kill_called is False
    assert app._gui_is_running() is False
