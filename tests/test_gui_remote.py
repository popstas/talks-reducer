import urllib.error
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Optional

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


class _StubButton:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def configure(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


class StubGUI:
    """Lightweight stand-in for :class:`TalksReducerGUI` used in tests."""

    def __init__(self) -> None:
        self._stop_requested = False
        self.logs: list[str] = []
        self.status_history: list[tuple[str, str | None]] = []
        self.scheduled_callbacks: list[Callable[[], None]] = []
        self.error_dialogs: list[tuple[str, str]] = []
        self.warning_dialogs: list[tuple[str, str]] = []
        self._clear_called = False
        self.opened_paths: list[Path] = []
        self._last_output: Path | None = None
        self._last_time_ratio: float | None = None
        self._last_size_ratio: float | None = None
        self.open_button = _StubButton()
        self.tk = SimpleNamespace(NORMAL="normal")
        self.messagebox = SimpleNamespace(
            showerror=self._record_error,
            showwarning=self._record_warning,
        )

    def _append_log(self, message: str) -> None:
        self.logs.append(message)

    def _schedule_on_ui_thread(self, callback):  # noqa: ANN001
        self.scheduled_callbacks.append(callback)
        callback()

    def _set_status(self, status: str, message: str | None = None) -> None:
        self.status_history.append((status, message))

    def _record_error(self, title: str, message: str) -> None:
        self.error_dialogs.append((title, message))

    def _record_warning(self, title: str, message: str) -> None:
        self.warning_dialogs.append((title, message))

    def _clear_input_files(self) -> None:
        self._clear_called = True

    def _open_in_file_manager(self, path: Path) -> None:
        self.opened_paths.append(path)


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


def test_process_files_via_server_handles_missing_client_module(tmp_path: Path) -> None:
    gui = StubGUI()

    def load_client() -> object:
        raise ModuleNotFoundError("gradio_client not installed")

    result = remote_module.process_files_via_server(
        gui,
        files=[str(tmp_path / "input.mp4")],
        args={},
        server_url="http://example.com",
        open_after_convert=False,
        default_remote_destination=lambda path, small, small_480, **_: path,  # noqa: ARG005
        parse_summary=lambda text: (None, None),  # noqa: ARG005
        load_service_client=load_client,
        check_server=lambda *args, **kwargs: True,  # noqa: ANN002,ANN003
    )

    assert result is False
    assert gui.logs and "Server client unavailable" in gui.logs[0]
    assert gui.error_dialogs == [
        (
            "Server unavailable",
            "Remote processing requires the gradio_client package.",
        )
    ]
    assert gui.status_history[-1] == ("Error", None)


def test_process_files_via_server_returns_false_when_server_unavailable(
    tmp_path: Path,
) -> None:
    gui = StubGUI()
    send_calls: list[dict[str, object]] = []

    def load_client() -> object:
        return SimpleNamespace(
            send_video=lambda **kwargs: send_calls.append(kwargs)  # noqa: ARG005
        )

    result = remote_module.process_files_via_server(
        gui,
        files=[str(tmp_path / "input.mp4")],
        args={},
        server_url="http://example.com",
        open_after_convert=False,
        default_remote_destination=lambda path, small, small_480, **_: path,  # noqa: ARG005
        parse_summary=lambda text: (None, None),  # noqa: ARG005
        load_service_client=load_client,
        check_server=lambda *args, **kwargs: False,  # noqa: ANN002,ANN003
    )

    assert result is False
    assert send_calls == []


def test_process_files_via_server_processes_each_file(tmp_path: Path) -> None:
    gui = StubGUI()
    summary_calls: list[str] = []
    send_calls: list[dict[str, object]] = []

    def load_client() -> object:
        def send_video(**kwargs: object) -> tuple[str, str, str]:
            send_calls.append(kwargs)
            return (
                str(tmp_path / "output.mp4"),
                "Summary line\nDetails",
                "Server log entry",
            )

        return SimpleNamespace(send_video=send_video)

    def parse_summary(summary: str) -> tuple[Optional[float], Optional[float]]:
        summary_calls.append(summary)
        return 0.5, 0.25

    output_override = tmp_path / "custom_output.mp4"

    result = remote_module.process_files_via_server(
        gui,
        files=[str(tmp_path / "input.mp4")],
        args={"output_file": str(output_override), "silent_threshold": 0.2},
        server_url="http://example.com",
        open_after_convert=False,
        default_remote_destination=lambda path, small, small_480, **_: tmp_path
        / "fallback.mp4",  # noqa: ARG005
        parse_summary=parse_summary,
        load_service_client=load_client,
        check_server=lambda *args, **kwargs: True,  # noqa: ANN002,ANN003
    )

    assert result is True
    assert gui._last_output == tmp_path / "output.mp4"
    assert gui._last_time_ratio == 0.5
    assert gui._last_size_ratio == 0.25
    assert "Uploading 1/1: input.mp4" in gui.logs[0]
    assert "Server log:" in gui.logs
    assert any("Server log entry" == line for line in gui.logs)
    assert summary_calls == ["Summary line\nDetails"]
    assert send_calls and send_calls[0]["output_path"] == output_override
    assert gui.open_button.calls[-1] == {"state": "normal"}
    assert gui._clear_called is True


def test_process_files_via_server_includes_small_480_suffix(tmp_path: Path) -> None:
    gui = StubGUI()
    captured: list[tuple[Path, bool, bool, dict[str, object]]] = []

    def load_client() -> object:
        return SimpleNamespace(
            send_video=lambda **kwargs: (
                str(tmp_path / "clip_speedup_small_480.mp4"),
                "Summary",
                "",
            )
        )

    def default_destination(
        path: Path, small: bool, small_480: bool, **kwargs: object
    ) -> Path:
        captured.append((path, small, small_480, dict(kwargs)))
        return tmp_path / (path.stem + "_speedup_small_480" + path.suffix)

    result = remote_module.process_files_via_server(
        gui,
        files=[str(tmp_path / "clip.mp4")],
        args={"small": True, "small_target_height": 480},
        server_url="http://example.com",
        open_after_convert=False,
        default_remote_destination=default_destination,
        parse_summary=lambda _summary: (None, None),  # noqa: ARG005
        load_service_client=load_client,
        check_server=lambda *args, **kwargs: True,  # noqa: ANN002,ANN003
    )

    assert result is True
    assert captured
    _, small_flag, small_480_flag, extra = captured[0]
    assert small_flag is True
    assert small_480_flag is True
    assert extra.get("add_codec_suffix") is False


def test_process_files_via_server_passes_speed_options(tmp_path: Path) -> None:
    gui = StubGUI()
    captured_kwargs: dict[str, object] = {}

    def load_client() -> object:
        return SimpleNamespace(
            send_video=lambda **kwargs: (
                str(tmp_path / "clip_av1.mp4"),
                "Summary",
                "",
            )
        )

    def default_destination(
        path: Path, small: bool, small_480: bool, **kwargs: object
    ) -> Path:
        captured_kwargs.update(kwargs)
        return tmp_path / f"{path.stem}_av1{path.suffix}"

    result = remote_module.process_files_via_server(
        gui,
        files=[str(tmp_path / "clip.mp4")],
        args={
            "silent_speed": 1.0,
            "sounded_speed": 1.0,
            "video_codec": "av1",
            "add_codec_suffix": False,
        },
        server_url="http://example.com",
        open_after_convert=False,
        default_remote_destination=default_destination,
        parse_summary=lambda _summary: (None, None),  # noqa: ARG005
        load_service_client=load_client,
        check_server=lambda *args, **kwargs: True,  # noqa: ANN002,ANN003
    )

    assert result is True
    assert captured_kwargs.get("silent_speed") == 1.0
    assert captured_kwargs.get("sounded_speed") == 1.0
    assert captured_kwargs.get("video_codec") == "av1"
