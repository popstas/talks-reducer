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
    assert calls == [(str(exe), str(video), "720p", 5, "hevc", True, None)]


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


def test_build_args_emits_preset_flag() -> None:
    """A preset payload emits ``--preset NAME`` instead of the legacy flags."""

    assert dock_server.build_args(
        "v.mp4", "720p", 5, "hevc", False, preset="My Preset"
    ) == [
        "v.mp4",
        "--preset",
        "My Preset",
    ]
    assert dock_server.build_args("v.mp4", "480p", 10, "av1", True, preset="Fast") == [
        "v.mp4",
        "--preset",
        "Fast",
        "--open-location",
        "--auto-close",
    ]


def test_handle_process_routes_preset(tmp_path, monkeypatch) -> None:
    """A known preset name skips the legacy validation and spawns via --preset."""

    video = tmp_path / "clip.mkv"
    video.write_bytes(b"data")
    exe = tmp_path / "talks-reducer.exe"
    exe.write_bytes(b"exe")

    monkeypatch.setattr(dock_server, "_preset_names", lambda: ["720p fast"])

    calls: list[tuple] = []
    monkeypatch.setattr(
        dock_server,
        "start_talks_reducer",
        lambda *args: calls.append(args),
    )

    status, message = dock_server.handle_process(
        {
            "file": str(video),
            "preset": "720p fast",
            "exe": str(exe),
            "autoClose": False,
        }
    )

    assert status == 202
    assert calls == [(str(exe), str(video), "", None, "h264", False, "720p fast")]


def test_handle_process_rejects_unknown_preset(tmp_path, monkeypatch) -> None:
    """An unknown preset name is rejected with the list of valid names."""

    video = tmp_path / "clip.mkv"
    video.write_bytes(b"data")

    monkeypatch.setattr(dock_server, "_preset_names", lambda: ["720p fast"])
    monkeypatch.setattr(dock_server, "start_talks_reducer", lambda *args: None)

    status, message = dock_server.handle_process(
        {"file": str(video), "preset": "missing"}
    )

    assert status == 400
    assert "Unknown preset" in message
    assert "720p fast" in message


def test_get_presets_returns_store(monkeypatch) -> None:
    """``GET /presets`` returns the stored presets as a JSON list of dicts."""

    from talks_reducer import presets as presets_module

    sample = [
        presets_module.Preset(
            name="720p fast",
            resolution="720p",
            silent_speed=10.0,
            sounded_speed=1.0,
            silent_threshold=0.01,
            video_codec="h264",
        )
    ]
    monkeypatch.setattr(presets_module, "load_presets", lambda *a, **k: sample)

    httpd = dock_server.DockServer(("127.0.0.1", 0), dock_server.DEFAULT_EXE)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        port = httpd.server_address[1]
        conn = HTTPConnection("127.0.0.1", port)
        conn.request("GET", "/presets")
        response = conn.getresponse()
        body = response.read()
        assert response.status == 200
        assert "application/json" in response.getheader("Content-Type")
        data = json.loads(body)
        assert data == [
            {
                "name": "720p fast",
                "resolution": "720p",
                "silent_speed": 10.0,
                "sounded_speed": 1.0,
                "silent_threshold": 0.01,
                "video_codec": "h264",
            }
        ]
        conn.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_get_presets_serializes_sparse_preset(monkeypatch) -> None:
    """A sparse preset is returned with only its defined fields."""

    from talks_reducer import presets as presets_module

    sample = [presets_module.Preset(name="codec only", video_codec="hevc")]
    monkeypatch.setattr(presets_module, "load_presets", lambda *a, **k: sample)

    httpd = dock_server.DockServer(("127.0.0.1", 0), dock_server.DEFAULT_EXE)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        port = httpd.server_address[1]
        conn = HTTPConnection("127.0.0.1", port)
        conn.request("GET", "/presets")
        response = conn.getresponse()
        data = json.loads(response.read())
        assert data == [{"name": "codec only", "video_codec": "hevc"}]
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
