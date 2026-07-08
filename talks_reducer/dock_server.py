"""Local HTTP server backing the OBS processing dock.

The server hosts the dock UI (``dock.html``) and accepts ``POST /process``
requests that launch Talks Reducer for the recording chosen in OBS. It runs as
the ``talks-reducer dock-server`` subcommand, replacing the previous Node.js
helper and its PowerShell window-hiding wrapper: the frozen GUI executable is
windowless, so a single detached process serves the dock and dies cleanly when
the launcher (e.g. Task Scheduler) stops it.

Only the standard library is imported at module load so an idle server keeps a
small memory footprint; the heavy processing pipeline is never imported here.
Each job spawns the Talks Reducer executable as a separate process, mirroring
the original Node.js behaviour.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from .icons import find_icon_path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 17890
DEFAULT_EXE = r"%LOCALAPPDATA%\Programs\talks-reducer\talks-reducer.exe"
ALLOWED_CODECS: Tuple[str, ...] = ("h264", "hevc", "av1", "mp3")
ALLOWED_RESOLUTIONS: Tuple[str, ...] = ("1080p", "720p", "480p")
ALLOWED_SPEEDS: Tuple[int, ...] = (1, 5, 10)
MAX_BODY_BYTES = 1024 * 1024

_CREATE_NO_WINDOW = 0x08000000

_WIN_ENV_RE = re.compile(r"%([^%]+)%")

_DOCK_HTML_RELATIVE_PATHS: Sequence[Path] = (
    Path("resources"),
    Path("talks_reducer") / "resources",
)


def resolve_dock_html() -> Optional[Path]:
    """Return the bundled ``dock.html`` path, or ``None`` when it is missing."""

    return find_icon_path(
        filenames=["dock.html"],
        relative_paths=_DOCK_HTML_RELATIVE_PATHS,
    )


def default_exe_setting() -> str:
    """Return the default Talks Reducer executable path for new jobs."""

    return os.environ.get("OBS_DOCK_EXE") or DEFAULT_EXE


def _expand_win_env(value: str) -> str:
    """Expand ``%VAR%`` placeholders on any platform (unlike os.path.expandvars).

    ``os.path.expandvars`` only understands ``%VAR%`` on Windows, so port the
    Node.js server's cross-platform behaviour: substitute known variables and
    leave unknown ones untouched.
    """

    return _WIN_ENV_RE.sub(
        lambda match: os.environ.get(match.group(1), match.group(0)), value
    )


def resolve_exe_path(raw: Optional[str]) -> str:
    """Expand Windows environment variables and normalise the executable path."""

    trimmed = (raw or default_exe_setting()).strip()
    return os.path.normpath(_expand_win_env(trimmed))


def build_args(
    input_file: str,
    resolution: str,
    speed: int,
    codec: str,
    auto_close: bool,
) -> List[str]:
    """Translate dock options into Talks Reducer command line arguments."""

    args: List[str] = [input_file]

    if resolution == "1080p":
        args.append("--no-small")
    elif resolution == "720p":
        args.append("--small")
    elif resolution == "480p":
        args.extend(["--small", "--480"])

    args.extend(["--silent-speed", str(speed)])
    args.extend(["--video-codec", codec])

    if auto_close:
        args.extend(["--open-location", "--auto-close"])

    return args


def start_talks_reducer(
    exe_path: str,
    input_file: str,
    resolution: str,
    speed: int,
    codec: str,
    auto_close: bool,
) -> None:
    """Spawn the Talks Reducer executable for a single dock job."""

    args = build_args(input_file, resolution, speed, codec, auto_close)
    creationflags = _CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen([exe_path, *args], creationflags=creationflags)


def handle_process(payload: dict, default_exe: Optional[str] = None) -> Tuple[int, str]:
    """Validate a dock request and launch Talks Reducer.

    Return an ``(status_code, message)`` pair mirroring the original Node.js
    server's responses so the dock UI keeps behaving identically.
    """

    input_file = str(payload.get("file") or "").strip()
    resolution = str(payload.get("resolution") or "").strip()
    codec = str(payload.get("codec") or "hevc").strip()
    auto_close = bool(payload.get("autoClose"))
    exe_path = resolve_exe_path(payload.get("exe") or default_exe)

    try:
        speed: Optional[int] = int(payload.get("speed"))
    except (TypeError, ValueError):
        speed = None

    if not input_file:
        return 400, "Missing file path"
    if not os.path.isfile(input_file):
        return 400, f"File not found: {input_file}"
    if speed not in ALLOWED_SPEEDS:
        return 400, "Speed must be 1, 5, or 10"
    if resolution not in ALLOWED_RESOLUTIONS:
        return 400, "Resolution must be 1080p, 720p, or 480p"
    if codec not in ALLOWED_CODECS:
        return 400, "Codec must be h264, hevc, av1, or mp3"
    if not os.path.isfile(exe_path):
        return 400, f"Executable not found: {exe_path}"

    start_talks_reducer(exe_path, input_file, resolution, speed, codec, auto_close)
    return 202, f"Started talks-reducer: {exe_path}"


class _DockRequestHandler(BaseHTTPRequestHandler):
    """Serve the dock UI and process jobs on ``POST /process``."""

    server_version = "TalksReducerDock/1.0"

    def _send(
        self,
        status: int,
        body: bytes | str = b"",
        content_type: str = "text/plain; charset=utf-8",
    ) -> None:
        payload = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def do_OPTIONS(self) -> None:  # noqa: N802 - required handler name
        self._send(204)

    def do_GET(self) -> None:  # noqa: N802 - required handler name
        path = urlsplit(self.path).path
        if path in ("/", "/dock.html", "/index.html"):
            html = resolve_dock_html()
            if html is None:
                self._send(404, "dock.html not found")
                return
            self._send(
                200,
                html.read_bytes(),
                content_type="text/html; charset=utf-8",
            )
            return
        self._send(404, "Not found")

    def do_POST(self) -> None:  # noqa: N802 - required handler name
        if urlsplit(self.path).path != "/process":
            self._send(404, "Not found")
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._send(400, "Invalid Content-Length")
            return

        if length > MAX_BODY_BYTES:
            self._send(413, "Request body is too large")
            return

        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError) as exc:
            self._send(400, f"Invalid JSON: {exc}")
            return

        try:
            status, message = handle_process(payload, self.server.default_exe)
        except Exception as exc:  # pragma: no cover - defensive guard
            self._send(500, f"Server error: {exc}")
            return

        self._send(status, message)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Silence the default per-request logging (server runs windowless)."""


class DockServer(ThreadingHTTPServer):
    """Threading HTTP server carrying the default executable for jobs."""

    daemon_threads = True

    def __init__(self, address: Tuple[str, int], default_exe: str) -> None:
        super().__init__(address, _DockRequestHandler)
        self.default_exe = default_exe


def _build_parser() -> argparse.ArgumentParser:
    """Create the argument parser for the ``dock-server`` subcommand."""

    parser = argparse.ArgumentParser(
        prog="talks-reducer dock-server",
        description="Serve the OBS processing dock and launch Talks Reducer jobs.",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Interface to bind. Defaults to {DEFAULT_HOST}.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("OBS_DOCK_PORT", DEFAULT_PORT)),
        help=f"Port to listen on. Defaults to {DEFAULT_PORT} (env OBS_DOCK_PORT).",
    )
    parser.add_argument(
        "--exe",
        default=default_exe_setting(),
        help="Default Talks Reducer executable when a request omits one.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    """Run the OBS processing dock server until interrupted."""

    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    httpd = DockServer((args.host, args.port), args.exe)
    url = f"http://{args.host}:{args.port}/"
    print(f"OBS Processing Dock server: {url}")
    print(f"Dock UI:   {url}")
    print(f"Default talks-reducer: {resolve_exe_path(args.exe)}")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover - interactive shutdown
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":  # pragma: no cover - module executed directly
    main()
