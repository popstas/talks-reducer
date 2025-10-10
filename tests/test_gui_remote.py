import urllib.error
from types import SimpleNamespace

import pytest

from talks_reducer.gui import remote as remote_module
from talks_reducer.gui.remote import (
    check_remote_server,
    format_server_host,
    normalize_server_url,
)


class DummyResponse:
    def __init__(self, status: int | None = None, code: int | None = None) -> None:
        self.status = status
        self._code = code

    def __enter__(self) -> "DummyResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def getcode(self) -> int | None:
        return self._code


def test_normalize_server_url_adds_scheme_and_slash() -> None:
    result = normalize_server_url("example.com")
    assert result == "http://example.com/"


def test_format_server_host_removes_scheme_and_port() -> None:
    host = format_server_host("https://example.com:9005/api")
    assert host == "example.com"


def test_check_remote_server_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_urlopen(request, timeout=5.0):  # noqa: ANN001
        calls.append((request.full_url, timeout))
        return DummyResponse(status=200)

    monkeypatch.setattr(remote_module.urllib.request, "urlopen", fake_urlopen)

    messages: list[str] = []
    statuses: list[tuple[str, str]] = []

    def record_status(status: str, message: str) -> None:
        statuses.append((status, message))

    success = check_remote_server(
        "http://example.com",
        success_status="Idle",
        waiting_status="Error",
        failure_status="Error",
        on_log=messages.append,
        on_status=record_status,
        sleep=remote_module.time.sleep,
    )

    assert success is True
    assert messages == ["Server example.com is ready"]
    assert statuses == [("Idle", "Server example.com is ready")]
    assert calls == [("http://example.com/", 5.0)]


def test_check_remote_server_stops_when_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fake_urlopen(*_args, **_kwargs):  # noqa: ANN001
        nonlocal called
        called = True
        raise AssertionError("urlopen should not be called when stopped")

    monkeypatch.setattr(remote_module.urllib.request, "urlopen", fake_urlopen)

    stopped = False

    def stop_check() -> bool:
        return True

    def on_stop() -> None:
        nonlocal stopped
        stopped = True

    success = check_remote_server(
        "http://example.com",
        success_status="Idle",
        waiting_status="Error",
        failure_status="Error",
        on_log=lambda _msg: None,
        on_status=lambda _status, _msg: None,
        stop_check=stop_check,
        on_stop=on_stop,
        sleep=remote_module.time.sleep,
    )

    assert not success
    assert stopped is True
    assert called is False


def test_check_remote_server_failure_switches_and_alerts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def fake_urlopen(*_args, **_kwargs):  # noqa: ANN001
        nonlocal attempts
        attempts += 1
        raise urllib.error.URLError("boom")

    monkeypatch.setattr(remote_module.urllib.request, "urlopen", fake_urlopen)

    delays: list[float] = []

    def fake_sleep(duration: float) -> None:
        delays.append(duration)

    monkeypatch.setattr(remote_module.time, "sleep", fake_sleep)

    logs: list[str] = []
    statuses: list[tuple[str, str]] = []
    switch_called = False
    alerts: list[SimpleNamespace] = []

    def on_switch() -> None:
        nonlocal switch_called
        switch_called = True

    def on_alert(title: str, message: str) -> None:
        alerts.append(SimpleNamespace(title=title, message=message))

    success = check_remote_server(
        "http://example.com",
        success_status="Idle",
        waiting_status="Waiting",
        failure_status="Error",
        on_log=logs.append,
        on_status=lambda status, message: statuses.append((status, message)),
        switch_to_local_on_failure=True,
        alert_on_failure=True,
        warning_title="Server unavailable",
        warning_message="Server {host} unreachable after {max_attempts} tries",
        failure_message="Server {host} unreachable after {max_attempts} tries",
        max_attempts=3,
        delay=0.1,
        on_switch_to_local=on_switch,
        on_alert=on_alert,
        sleep=remote_module.time.sleep,
    )

    assert success is False
    assert attempts == 3
    assert logs == [
        "Waiting server example.com (attempt 1/3)",
        "Waiting server example.com (attempt 2/3)",
        "Server example.com unreachable after 3 tries",
    ]
    assert statuses[0] == ("Waiting", "Waiting server example.com (attempt 1/3)")
    assert statuses[1] == ("Waiting", "Waiting server example.com (attempt 2/3)")
    assert statuses[2] == ("Error", "Server example.com unreachable after 3 tries")
    assert delays == [0.1, 0.1]
    assert switch_called is True
    assert alerts and alerts[0].title == "Server unavailable"
    assert alerts[0].message == "Server example.com unreachable after 3 tries"
