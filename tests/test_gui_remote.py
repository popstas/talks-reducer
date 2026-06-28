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

    DOWNLOAD_WAIT_STATUS = "Waiting for download…"

    def __init__(self) -> None:
        self._stop_requested = False
        self._download_wait_active = False
        self.download_wait_begin_count = 0
        self.download_wait_cancel_count = 0
        self.logs: list[str] = []
        self.progress_values: list[float] = []
        self._progress_value = 0.0
        self._progress_floor = 0.0
        self.progress_var = SimpleNamespace(
            get=lambda: self._progress_value,
            set=self._set_progress_value,
        )
        self.status_history: list[tuple[str, str | None]] = []
        self.stage_transitions: list[str] = []
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

    def _apply_stage_transition(self, desc: str) -> None:
        self.stage_transitions.append(desc)

    def _schedule_on_ui_thread(self, callback):  # noqa: ANN001
        self.scheduled_callbacks.append(callback)
        callback()

    def _set_status(self, status: str, message: str | None = None) -> None:
        self.status_history.append((status, message))

    def _set_progress(self, percentage: float) -> None:
        self.progress_values.append(percentage)
        self._progress_value = percentage

    def _set_progress_monotonic(self, percentage: float) -> None:
        # Mirror :meth:`TalksReducerGUI._set_progress_monotonic`: the floor is a
        # synchronous attribute so back-to-back worker-thread events never read a
        # stale value, even though the visible bar update is deferred.
        value = min(100.0, max(self._progress_floor, float(percentage)))
        self._progress_floor = value
        self._set_progress(value)

    def _reset_progress_baseline(self) -> None:
        self._progress_floor = 0.0
        self._set_progress(0.0)

    def _begin_download_wait(self) -> None:
        # Mirror :meth:`TalksReducerGUI._begin_download_wait`: emit the waiting
        # status immediately. The real GUI also reschedules a refresh timer; the
        # stub records the activation flag and call count instead of running a
        # wall-clock timer.
        self.download_wait_begin_count += 1
        self._download_wait_active = True
        self._set_status("processing", self.DOWNLOAD_WAIT_STATUS)

    def _cancel_download_wait(self) -> None:
        self.download_wait_cancel_count += 1
        self._download_wait_active = False

    def _set_progress_value(self, percentage: float) -> None:
        self._progress_value = percentage

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
            "Remote processing requires the gradio_client package.\n\n"
            "gradio_client not installed",
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


def test_process_files_via_server_streams_final_progress(tmp_path: Path) -> None:
    gui = StubGUI()
    captured_callback: dict[str, object] = {}

    def load_client() -> object:
        def send_video(**kwargs: object) -> tuple[str, str, str]:
            callback = kwargs.get("progress_callback")
            captured_callback["callback"] = callback
            assert callable(callback)
            callback("Audio processing:", 100, 100, "samples")
            callback("Generating final:", 30, 100, "frames")
            callback("Generating final:", 100, 100, "frames")
            return (str(tmp_path / "out.mp4"), "Summary", "")

        return SimpleNamespace(send_video=send_video)

    result = remote_module.process_files_via_server(
        gui,
        files=[str(tmp_path / "input.mp4")],
        args={},
        server_url="http://example.com",
        open_after_convert=False,
        default_remote_destination=lambda path, small, small_480, **_: path,  # noqa: ARG005
        parse_summary=lambda _summary: (None, None),  # noqa: ARG005
        load_service_client=load_client,
        check_server=lambda *args, **kwargs: True,  # noqa: ANN002,ANN003
    )

    assert result is True
    assert captured_callback["callback"] is not None
    # Audio processing complete -> 35, final 30% -> 35 + 0.3 * 65 = 54.5, final done -> 100.
    assert gui.progress_values == pytest.approx([35.0, 54.5, 100.0])
    assert ("processing", "Generating final: 30%") in gui.status_history
    assert ("processing", "Audio processing: 100%") in gui.status_history
    # Real streamed audio/final progress must drive the synthetic-timer
    # transitions so the fallback cannot keep overwriting the status.
    assert gui.stage_transitions == [
        "Audio processing:",
        "Generating final:",
        "Generating final:",
    ]


def test_process_files_via_server_progress_never_moves_backwards(
    tmp_path: Path,
) -> None:
    gui = StubGUI()

    def load_client() -> object:
        def send_video(**kwargs: object) -> tuple[str, str, str]:
            callback = kwargs.get("progress_callback")
            assert callable(callback)
            # A later stage reporting a lower mapped value (or a fresh task
            # restarting at current=0) must not drag the bar backwards.
            callback("Generating final:", 50, 100, "frames")
            callback("Audio processing:", 100, 100, "samples")
            callback("Generating final:", 0, 100, "frames")
            return (str(tmp_path / "out.mp4"), "Summary", "")

        return SimpleNamespace(send_video=send_video)

    result = remote_module.process_files_via_server(
        gui,
        files=[str(tmp_path / "input.mp4")],
        args={},
        server_url="http://example.com",
        open_after_convert=False,
        default_remote_destination=lambda path, small, small_480, **_: path,  # noqa: ARG005
        parse_summary=lambda _summary: (None, None),  # noqa: ARG005
        load_service_client=load_client,
        check_server=lambda *args, **kwargs: True,  # noqa: ANN002,ANN003
    )

    assert result is True
    # Generating final 50% -> 35 + 0.5 * 65 = 67.5, then both lower-mapped
    # updates are clamped to the running maximum.
    assert gui.progress_values == pytest.approx([67.5, 67.5, 67.5])


def test_process_files_via_server_resets_progress_between_files(
    tmp_path: Path,
) -> None:
    gui = StubGUI()
    call_index = {"count": 0}

    def load_client() -> object:
        def send_video(**kwargs: object) -> tuple[str, str, str]:
            callback = kwargs.get("progress_callback")
            assert callable(callback)
            call_index["count"] += 1
            if call_index["count"] == 1:
                # First file finishes the final encode at 100%.
                callback("Generating final:", 100, 100, "frames")
            else:
                # The second file's early audio progress maps below 100% and
                # must not stay pinned at the previous file's completed value.
                callback("Audio processing:", 100, 100, "samples")
            return (str(tmp_path / f"out{call_index['count']}.mp4"), "Summary", "")

        return SimpleNamespace(send_video=send_video)

    result = remote_module.process_files_via_server(
        gui,
        files=[str(tmp_path / "first.mp4"), str(tmp_path / "second.mp4")],
        args={},
        server_url="http://example.com",
        open_after_convert=False,
        default_remote_destination=lambda path, small, small_480, **_: path,  # noqa: ARG005
        parse_summary=lambda _summary: (None, None),  # noqa: ARG005
        load_service_client=load_client,
        check_server=lambda *args, **kwargs: True,  # noqa: ANN002,ANN003
    )

    assert result is True
    # File 1 -> 100, baseline reset before file 2 -> 0, file 2 audio -> 35.
    assert gui.progress_values == pytest.approx([100.0, 0.0, 35.0])


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


def test_process_files_via_server_preserves_mp3_codec(tmp_path: Path) -> None:
    gui = StubGUI()
    captured_kwargs: dict[str, object] = {}
    sent_kwargs: dict[str, object] = {}

    def load_client() -> object:
        def send_video(**kwargs: object) -> tuple[str, str, str]:
            sent_kwargs.update(kwargs)
            return (str(tmp_path / "clip.mp3"), "Summary", "")

        return SimpleNamespace(send_video=send_video)

    def default_destination(
        path: Path, small: bool, small_480: bool, **kwargs: object
    ) -> Path:
        captured_kwargs.update(kwargs)
        return tmp_path / f"{path.stem}.mp3"

    result = remote_module.process_files_via_server(
        gui,
        files=[str(tmp_path / "clip.mp4")],
        args={
            "video_codec": "mp3",
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
    assert captured_kwargs.get("video_codec") == "mp3"
    assert sent_kwargs.get("video_codec") == "mp3"


def test_process_files_via_server_forwards_cut_without_ignored_log(
    tmp_path: Path,
) -> None:
    gui = StubGUI()
    captured_send_kwargs: dict[str, object] = {}

    def load_client() -> object:
        def _send_video(**kwargs: object):
            captured_send_kwargs.update(kwargs)
            return (str(tmp_path / "clip.mp4"), "Summary", "")

        return SimpleNamespace(send_video=_send_video)

    result = remote_module.process_files_via_server(
        gui,
        files=[str(tmp_path / "clip.mp4")],
        args={
            "cut_start_seconds": 10.0,
            "cut_end_seconds": 30.0,
        },
        server_url="http://example.com",
        open_after_convert=False,
        default_remote_destination=lambda path, small, small_480, **kwargs: tmp_path
        / path.name,
        parse_summary=lambda _summary: (None, None),  # noqa: ARG005
        load_service_client=load_client,
        check_server=lambda *args, **kwargs: True,  # noqa: ANN002,ANN003
    )

    assert result is True
    # The trim values are actually forwarded to the remote service...
    assert captured_send_kwargs.get("cut_enabled") is True
    assert captured_send_kwargs.get("cut_start_seconds") == 10.0
    assert captured_send_kwargs.get("cut_end_seconds") == 30.0
    # ...so they must not be reported to the user as ignored.
    assert not any("ignores the following" in message for message in gui.logs)


def test_process_files_via_server_download_bar_reaches_100_once(
    tmp_path: Path,
) -> None:
    gui = StubGUI()

    def load_client() -> object:
        def send_video(**kwargs: object) -> tuple[str, str, str]:
            callback = kwargs.get("progress_callback")
            assert callable(callback)
            # The service client now delivers a single deduped 0→100 download
            # sequence; the GUI bar must follow it monotonically to 100 once.
            callback("Downloading:", 0, 100, "bytes")
            callback("Downloading:", 50, 100, "bytes")
            callback("Downloading:", 100, 100, "bytes")
            return (str(tmp_path / "out.mp4"), "Summary", "")

        return SimpleNamespace(send_video=send_video)

    result = remote_module.process_files_via_server(
        gui,
        files=[str(tmp_path / "input.mp4")],
        args={},
        server_url="http://example.com",
        open_after_convert=False,
        default_remote_destination=lambda path, small, small_480, **_: path,  # noqa: ARG005
        parse_summary=lambda _summary: (None, None),  # noqa: ARG005
        load_service_client=load_client,
        check_server=lambda *args, **kwargs: True,  # noqa: ANN002,ANN003
    )

    assert result is True
    # ``Downloading:`` is not a known stage band, so it maps to the raw 0-100 range.
    assert gui.progress_values == pytest.approx([0.0, 50.0, 100.0])
    # The bar reaches 100 exactly once and never decreases.
    assert gui.progress_values.count(100.0) == 1
    assert all(
        later >= earlier
        for earlier, later in zip(gui.progress_values, gui.progress_values[1:])
    )


def test_process_files_via_server_streams_upload_and_download(tmp_path: Path) -> None:
    gui = StubGUI()

    def load_client() -> object:
        def send_video(**kwargs: object) -> tuple[str, str, str]:
            callback = kwargs.get("progress_callback")
            assert callable(callback)
            # Byte-level upload progress maps into the 0-5% ``Uploading`` band.
            callback("Uploading:", 0, 100, "bytes")
            callback("Uploading:", 50, 100, "bytes")
            callback("Uploading:", 100, 100, "bytes")
            callback("Generating final:", 100, 100, "frames")
            # Download progress is reported back to the client after processing.
            callback("Downloading:", 0, 100, "bytes")
            callback("Downloading:", 100, 100, "bytes")
            return (str(tmp_path / "out.mp4"), "Summary", "")

        return SimpleNamespace(send_video=send_video)

    result = remote_module.process_files_via_server(
        gui,
        files=[str(tmp_path / "input.mp4")],
        args={},
        server_url="http://example.com",
        open_after_convert=False,
        default_remote_destination=lambda path, small, small_480, **_: path,  # noqa: ARG005
        parse_summary=lambda _summary: (None, None),  # noqa: ARG005
        load_service_client=load_client,
        check_server=lambda *args, **kwargs: True,  # noqa: ANN002,ANN003
    )

    assert result is True
    # Uploading 50% -> 0 + 0.5 * 5 = 2.5, 100% -> 5.0 before the final encode.
    assert gui.progress_values[:3] == pytest.approx([0.0, 2.5, 5.0])
    # The upload band and download phase both surface a percentage status.
    assert ("processing", "Uploading: 50%") in gui.status_history
    assert ("processing", "Downloading: 100%") in gui.status_history


def test_process_files_via_server_waits_for_download_after_processing(
    tmp_path: Path,
) -> None:
    gui = StubGUI()

    def load_client() -> object:
        def send_video(**kwargs: object) -> tuple[str, str, str]:
            callback = kwargs.get("progress_callback")
            assert callable(callback)
            # Final encode completes, then the server finalizes the file before
            # the download stream begins.
            callback("Generating final:", 100, 100, "frames")
            callback("Downloading:", 0, 100, "bytes")
            callback("Downloading:", 100, 100, "bytes")
            return (str(tmp_path / "out.mp4"), "Summary", "")

        return SimpleNamespace(send_video=send_video)

    result = remote_module.process_files_via_server(
        gui,
        files=[str(tmp_path / "input.mp4")],
        args={},
        server_url="http://example.com",
        open_after_convert=False,
        default_remote_destination=lambda path, small, small_480, **_: path,  # noqa: ARG005
        parse_summary=lambda _summary: (None, None),  # noqa: ARG005
        load_service_client=load_client,
        check_server=lambda *args, **kwargs: True,  # noqa: ANN002,ANN003
    )

    assert result is True
    statuses = gui.status_history
    waiting = ("processing", StubGUI.DOWNLOAD_WAIT_STATUS)
    final = ("processing", "Generating final: 100%")
    first_download = ("processing", "Downloading: 0%")
    assert waiting in statuses
    # The waiting status appears after the last processing event and before the
    # first download event.
    assert (
        statuses.index(final) < statuses.index(waiting) < statuses.index(first_download)
    )
    # The heartbeat starts exactly once and is cancelled when the download begins
    # (and again after ``send_video`` returns), leaving no active timer.
    assert gui.download_wait_begin_count == 1
    assert gui.download_wait_cancel_count >= 1
    assert gui._download_wait_active is False


def test_process_files_via_server_does_not_wait_without_final_completion(
    tmp_path: Path,
) -> None:
    gui = StubGUI()

    def load_client() -> object:
        def send_video(**kwargs: object) -> tuple[str, str, str]:
            callback = kwargs.get("progress_callback")
            assert callable(callback)
            # The final encode never reaches 100% in the streamed events, so the
            # waiting heartbeat must not start.
            callback("Generating final:", 30, 100, "frames")
            return (str(tmp_path / "out.mp4"), "Summary", "")

        return SimpleNamespace(send_video=send_video)

    result = remote_module.process_files_via_server(
        gui,
        files=[str(tmp_path / "input.mp4")],
        args={},
        server_url="http://example.com",
        open_after_convert=False,
        default_remote_destination=lambda path, small, small_480, **_: path,  # noqa: ARG005
        parse_summary=lambda _summary: (None, None),  # noqa: ARG005
        load_service_client=load_client,
        check_server=lambda *args, **kwargs: True,  # noqa: ANN002,ANN003
    )

    assert result is True
    assert gui.download_wait_begin_count == 0
    assert ("processing", StubGUI.DOWNLOAD_WAIT_STATUS) not in gui.status_history


def test_process_files_via_server_cancels_waiting_on_stop(tmp_path: Path) -> None:
    from talks_reducer.pipeline import ProcessingAborted

    gui = StubGUI()

    def load_client() -> object:
        def send_video(**kwargs: object) -> tuple[str, str, str]:
            callback = kwargs.get("progress_callback")
            assert callable(callback)
            # The final encode completes and the waiting heartbeat starts, then
            # the user requests a stop before any download bytes arrive.
            callback("Generating final:", 100, 100, "frames")
            gui._stop_requested = True
            raise ProcessingAborted("Remote processing cancelled by user.")

        return SimpleNamespace(send_video=send_video)

    with pytest.raises(ProcessingAborted):
        remote_module.process_files_via_server(
            gui,
            files=[str(tmp_path / "input.mp4")],
            args={},
            server_url="http://example.com",
            open_after_convert=False,
            default_remote_destination=lambda path, small, small_480, **_: path,  # noqa: ARG005
            parse_summary=lambda _summary: (None, None),  # noqa: ARG005
            load_service_client=load_client,
            check_server=lambda *args, **kwargs: True,  # noqa: ANN002,ANN003
        )

    # The waiting heartbeat started but was cancelled on the abort path, so no
    # timer lingers after the stop.
    assert gui.download_wait_begin_count == 1
    assert gui.download_wait_cancel_count >= 1
    assert gui._download_wait_active is False


def test_transfer_speed_tracker_reports_mb_per_second() -> None:
    clock = {"t": 0.0}
    tracker = remote_module._TransferSpeedTracker(
        min_interval=1.0, clock=lambda: clock["t"]
    )

    # The first sample only starts the window, so no rate is available yet.
    assert tracker.update("uploading:", 0) is None
    # A sample before the window elapses keeps the rate unknown.
    clock["t"] = 0.5
    assert tracker.update("uploading:", 2_000_000) is None
    # Once the interval elapses, report bytes/elapsed/1e6 since the window start.
    clock["t"] = 1.0
    assert tracker.update("uploading:", 5_500_000) == pytest.approx(5.5)


def test_transfer_speed_tracker_holds_rate_between_windows() -> None:
    clock = {"t": 0.0}
    tracker = remote_module._TransferSpeedTracker(
        min_interval=1.0, clock=lambda: clock["t"]
    )

    tracker.update("downloading:", 0)
    clock["t"] = 1.0
    assert tracker.update("downloading:", 3_000_000) == pytest.approx(3.0)
    # A sample inside the next window returns the last rate unchanged.
    clock["t"] = 1.2
    assert tracker.update("downloading:", 3_500_000) == pytest.approx(3.0)


def test_transfer_speed_tracker_resets_on_new_phase() -> None:
    clock = {"t": 0.0}
    tracker = remote_module._TransferSpeedTracker(
        min_interval=1.0, clock=lambda: clock["t"]
    )

    tracker.update("uploading:", 0)
    clock["t"] = 1.0
    assert tracker.update("uploading:", 4_000_000) == pytest.approx(4.0)
    # Switching to the download phase starts a fresh window.
    assert tracker.update("downloading:", 10) is None
    clock["t"] = 2.0
    assert tracker.update("downloading:", 1_000_010) == pytest.approx(1.0)


def test_transfer_speed_tracker_resets_when_bytes_restart() -> None:
    clock = {"t": 0.0}
    tracker = remote_module._TransferSpeedTracker(
        min_interval=1.0, clock=lambda: clock["t"]
    )

    tracker.update("downloading:", 5_000_000)
    clock["t"] = 1.0
    assert tracker.update("downloading:", 9_000_000) == pytest.approx(4.0)
    # A byte count below the window start signals a fresh 0→100 cycle.
    assert tracker.update("downloading:", 0) is None


def test_process_files_via_server_appends_transfer_speed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gui = StubGUI()
    # A deterministic monotonic clock (one read per ``_TransferSpeedTracker``
    # update) so the reported rate is stable across the streamed byte events.
    ticks = iter([0.0, 1.0, 2.0])
    monkeypatch.setattr(remote_module.time, "monotonic", lambda: next(ticks))

    def load_client() -> object:
        def send_video(**kwargs: object) -> tuple[str, str, str]:
            callback = kwargs.get("progress_callback")
            assert callable(callback)
            callback("Uploading:", 0, 10_000_000, "bytes")
            callback("Uploading:", 5_000_000, 10_000_000, "bytes")
            callback("Uploading:", 10_000_000, 10_000_000, "bytes")
            return (str(tmp_path / "out.mp4"), "Summary", "")

        return SimpleNamespace(send_video=send_video)

    result = remote_module.process_files_via_server(
        gui,
        files=[str(tmp_path / "input.mp4")],
        args={},
        server_url="http://example.com",
        open_after_convert=False,
        default_remote_destination=lambda path, small, small_480, **_: path,  # noqa: ARG005
        parse_summary=lambda _summary: (None, None),  # noqa: ARG005
        load_service_client=load_client,
        check_server=lambda *args, **kwargs: True,  # noqa: ANN002,ANN003
    )

    assert result is True
    speed_statuses = [
        message
        for _status, message in gui.status_history
        if message and "MB/s" in message
    ]
    # 5 MB over 1 s -> 5.0 MB/s at 50%, then another 5 MB over 1 s at 100%.
    assert "Uploading: 50%, 5.0 MB/s" in speed_statuses
    assert "Uploading: 100%, 5.0 MB/s" in speed_statuses
