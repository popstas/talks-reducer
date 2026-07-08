"""Tests for the OBS processing dock HTTP server."""

from __future__ import annotations

import json
from http.client import HTTPConnection
from threading import Thread

import pytest

from talks_reducer import cli, dock_server


def test_build_args_matches_dock_options() -> None:
    """Dock options translate into the same flags the Node.js server produced."""

    assert dock_server.build_args("v.mp4", "480p", 5, "hevc", True) == [
        "v.mp4",
        "--small",
        "--480",
        "--silent-speed",
        "5",
        "--video-codec",
        "hevc",
        "--open-location",
        "--auto-close",
    ]
    assert dock_server.build_args("v.mp4", "1080p", 1, "h264", False) == [
        "v.mp4",
        "--no-small",
        "--silent-speed",
        "1",
        "--video-codec",
        "h264",
    ]
    assert dock_server.build_args("v.mp4", "720p", 10, "av1", False)[1] == "--small"


def test_resolve_exe_path_expands_environment(monkeypatch) -> None:
    """Windows-style ``%VAR%`` placeholders are expanded and normalised."""

    monkeypatch.setenv("OBS_DOCK_TEST_ROOT", r"C:\Apps")
    resolved = dock_server.resolve_exe_path("%OBS_DOCK_TEST_ROOT%/talks-reducer.exe")
    assert resolved.endswith("talks-reducer.exe")
    assert "%OBS_DOCK_TEST_ROOT%" not in resolved


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"file": "", "speed": 5, "resolution": "720p"}, "Missing file path"),
        ({"file": "missing.mp4", "speed": 5, "resolution": "720p"}, "File not found"),
    ],
)
def test_handle_process_rejects_invalid_requests(payload, expected) -> None:
    """Invalid requests return a 400 before any process is spawned."""

    status, message = dock_server.handle_process(payload)
    assert status == 400
    assert expected in message


def test_handle_process_validates_and_spawns(tmp_path, monkeypatch) -> None:
    """A valid request launches Talks Reducer with the built arguments."""

    video = tmp_path / "clip.mkv"
    video.write_bytes(b"data")
    exe = tmp_path / "talks-reducer.exe"
    exe.write_bytes(b"exe")

    calls: list[tuple] = []
    monkeypatch.setattr(
        dock_server,
        "start_talks_reducer",
        lambda *args: calls.append(args),
    )

    status, message = dock_server.handle_process(
        {
            "file": str(video),
            "speed": 5,
            "resolution": "720p",
            "codec": "hevc",
            "autoClose": True,
            "exe": str(exe),
        }
    )

    assert status == 202
    assert str(exe) in message
    assert calls == [(str(exe), str(video), "720p", 5, "hevc", True)]


def test_resolve_dock_html_returns_bundled_file() -> None:
    """The bundled dock UI is discoverable via the shared resource resolver."""

    path = dock_server.resolve_dock_html()
    assert path is not None
    assert path.name == "dock.html"
    assert path.is_file()


def test_dock_server_serves_ui_and_rejects_bad_post(monkeypatch) -> None:
    """End-to-end: the server serves dock.html and validates POST bodies."""

    monkeypatch.setattr(dock_server, "start_talks_reducer", lambda *args: None)

    httpd = dock_server.DockServer(("127.0.0.1", 0), dock_server.DEFAULT_EXE)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        port = httpd.server_address[1]
        conn = HTTPConnection("127.0.0.1", port)

        conn.request("GET", "/")
        response = conn.getresponse()
        body = response.read()
        assert response.status == 200
        assert b"OBS Processing Dock" in body
        assert response.getheader("Access-Control-Allow-Origin") == "*"

        conn.request(
            "POST",
            "/process",
            body=json.dumps({"file": ""}),
            headers={"Content-Type": "application/json"},
        )
        response = conn.getresponse()
        assert response.status == 400
        assert b"Missing file path" in response.read()
        conn.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_cli_dispatches_dock_server(monkeypatch) -> None:
    """The ``dock-server`` keyword routes into the dock server entry point."""

    captured: list[list[str]] = []
    monkeypatch.setattr(
        dock_server, "main", lambda argv=None: captured.append(list(argv or []))
    )

    cli.main(["dock-server", "--port", "12345"])

    assert captured == [["--port", "12345"]]
