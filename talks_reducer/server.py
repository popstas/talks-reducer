"""Gradio-powered simple server for running Talks Reducer in a browser."""

from __future__ import annotations

import atexit
import json
import shutil
import socket
import sys
import tempfile
import time
from collections import deque
from contextlib import AbstractContextManager, suppress
from dataclasses import dataclass
from pathlib import Path
from queue import SimpleQueue
from threading import Event, Lock, Thread
from typing import Callable, Iterator, Optional, Sequence, cast

import gradio as gr

from talks_reducer.ffmpeg import FFmpegNotFoundError, is_global_ffmpeg_available
from talks_reducer.icons import find_icon_path
from talks_reducer.models import ProcessingOptions, ProcessingResult
from talks_reducer.pipeline import (
    ProcessingAborted,
    _input_to_output_filename,
    speed_up_video,
)
from talks_reducer.presets import (
    Preset,
    find_preset,
    get_selected_preset,
    load_presets,
    set_selected_preset,
)
from talks_reducer.progress import (
    CallbackProgressHandle,
    ProgressHandle,
    SignalProgressReporter,
)
from talks_reducer.server_args import build_server_parser
from talks_reducer.version_utils import resolve_version


class _GradioProgressHandle(CallbackProgressHandle):
    """Translate pipeline progress updates into Gradio progress callbacks."""

    def __init__(
        self,
        reporter: "GradioProgressReporter",
        *,
        desc: str,
        total: Optional[int],
        unit: str,
    ) -> None:
        self._reporter = reporter
        super().__init__(
            desc=desc.strip() or "Processing",
            total=total,
            on_start=self._on_start,
            on_update=self._on_update,
            infer_total_on_finish=True,
        )
        self._unit = unit

    def _on_start(self, desc: str, total: Optional[int]) -> None:
        self._reporter._start_task(desc, total)

    def _on_update(self, current: int, total: Optional[int], desc: str) -> None:
        self._reporter._update_progress(current, total, desc)


class GradioProgressReporter(SignalProgressReporter):
    """Progress reporter that forwards updates to Gradio's progress widget."""

    def __init__(
        self,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        *,
        log_callback: Optional[Callable[[str], None]] = None,
        max_log_lines: int = 500,
    ) -> None:
        super().__init__()
        self._progress_callback = progress_callback
        self._log_callback = log_callback
        self._max_log_lines = max_log_lines
        self._active_desc = "Processing"
        self.logs: list[str] = []
        self._stop_event = Event()

    def stop_requested(self) -> bool:
        """Return ``True`` once a client cancellation has requested a stop."""

        return self._stop_event.is_set()

    def request_stop(self) -> None:
        """Signal the running pipeline to abort at its next stop check."""

        self._stop_event.set()

    def log(self, message: str) -> None:
        """Collect log messages for display in the web interface."""

        text = message.strip()
        if not text:
            return
        self.logs.append(text)
        if len(self.logs) > self._max_log_lines:
            self.logs = self.logs[-self._max_log_lines :]
        if self._log_callback is not None:
            self._log_callback(text)

    def task(
        self,
        *,
        desc: str = "",
        total: Optional[int] = None,
        unit: str = "",
    ) -> AbstractContextManager[ProgressHandle]:
        """Create a context manager bridging pipeline progress to Gradio."""

        return _GradioProgressHandle(self, desc=desc, total=total, unit=unit)

    # Internal helpers -------------------------------------------------

    def _start_task(self, desc: str, total: Optional[int]) -> None:
        self._active_desc = desc or "Processing"
        self._update_progress(0, total, self._active_desc)

    def _update_progress(
        self, current: int, total: Optional[int], desc: Optional[str]
    ) -> None:
        if self._progress_callback is None:
            return
        if total is None or total <= 0:
            total_value = max(1, int(current) + 1 if current >= 0 else 1)
            bounded_current = max(0, int(current))
        else:
            total_value = max(int(total), 1, int(current))
            bounded_current = max(0, min(int(current), int(total_value)))
        display_desc = desc or self._active_desc
        self._progress_callback(bounded_current, total_value, display_desc)


def _format_progress_percent(received: int, total: Optional[int]) -> str:
    """Return a compact ``n/total (xx%)`` description for transfer logging."""

    if total and total > 0:
        percent = min(int(received * 100 / total), 100)
        return f"{_format_file_size(received)}/{_format_file_size(total)} ({percent}%)"
    return _format_file_size(received)


class TransferProgressMiddleware:
    """ASGI middleware that logs incremental upload/download byte progress.

    Gradio handles file uploads and downloads through its own HTTP routes, so
    the pipeline never observes those transfers. This middleware watches the raw
    request/response byte streams for the upload and ``file=`` download routes
    and logs progress to the server console as the bytes flow, mirroring the
    client-side ``Uploading``/``Downloading`` progress.
    """

    def __init__(
        self,
        app: Callable,
        *,
        log: Optional[Callable[[str], None]] = None,
        step_percent: int = 20,
    ) -> None:
        self.app = app
        self._log = log or (lambda message: print(message, flush=True))
        self._step_percent = max(1, int(step_percent))

    def _make_reporter(
        self, label: str, total: Optional[int]
    ) -> Callable[[int, bool], None]:
        last_step = {"value": -1}

        def report(received: int, final: bool) -> None:
            if total and total > 0:
                step = int(received * 100 / total) // self._step_percent
            else:
                step = received // (8 * 1024 * 1024)
            if final or step != last_step["value"]:
                last_step["value"] = step
                self._log(f"{label}: {_format_progress_percent(received, total)}")

        return report

    @staticmethod
    def _content_length(raw_headers: object) -> Optional[int]:
        for key, value in raw_headers or []:
            if key.lower() == b"content-length":
                with suppress(TypeError, ValueError):
                    return int(value.decode("latin-1"))
        return None

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "") or ""
        method = scope.get("method", "GET")
        is_upload = method == "POST" and path.rstrip("/").endswith("upload")
        is_download = method == "GET" and "file=" in path

        if not is_upload and not is_download:
            await self.app(scope, receive, send)
            return

        if is_upload:
            total = self._content_length(scope.get("headers"))
            report = self._make_reporter("Receiving upload", total)
            received = 0

            async def wrapped_receive() -> dict:
                nonlocal received
                message = await receive()
                if message.get("type") == "http.request":
                    body = message.get("body", b"")
                    if body:
                        received += len(body)
                        report(received, not message.get("more_body", False))
                return message

            await self.app(scope, wrapped_receive, send)
            return

        sent = {"value": 0}
        reporter: dict[str, Optional[Callable[[int, bool], None]]] = {"fn": None}

        async def wrapped_send(message: dict) -> None:
            message_type = message.get("type")
            if message_type == "http.response.start":
                total = self._content_length(message.get("headers"))
                filename = path.split("file=", 1)[-1].rsplit("/", 1)[-1] or "file"
                reporter["fn"] = self._make_reporter(
                    f"Sending download {filename}", total
                )
            elif message_type == "http.response.body":
                body = message.get("body", b"")
                if body:
                    sent["value"] += len(body)
                if reporter["fn"] is not None:
                    reporter["fn"](sent["value"], not message.get("more_body", False))
            await send(message)

        await self.app(scope, receive, wrapped_send)


_ACTIVITY_MAXLEN = 100


@dataclass(frozen=True)
class ActivityEntry:
    """A single recorded client request against the server."""

    timestamp: float
    client_ip: str
    action: str

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable representation of the entry."""

        return {
            "timestamp": self.timestamp,
            "client_ip": self.client_ip,
            "action": self.action,
        }


class ActivityRecorder:
    """Bounded, thread-safe recorder of recent client activity."""

    def __init__(self, maxlen: int = _ACTIVITY_MAXLEN) -> None:
        self._entries: "deque[ActivityEntry]" = deque(maxlen=max(1, int(maxlen)))
        self._lock = Lock()

    def record(
        self, client_ip: str, action: str, *, timestamp: Optional[float] = None
    ) -> ActivityEntry:
        """Append an activity entry and return it."""

        entry = ActivityEntry(
            timestamp=time.time() if timestamp is None else float(timestamp),
            client_ip=client_ip or "unknown",
            action=action,
        )
        with self._lock:
            self._entries.append(entry)
        return entry

    def snapshot(self) -> list[ActivityEntry]:
        """Return a copy of the recorded entries, oldest first."""

        with self._lock:
            return list(self._entries)

    def clear(self) -> None:
        """Remove all recorded entries (primarily for tests)."""

        with self._lock:
            self._entries.clear()


_ACTIVITY_RECORDER = ActivityRecorder()


def _classify_activity(method: str, path: str) -> Optional[str]:
    """Map an HTTP request to a human-readable action, or ``None`` to skip."""

    raw = path or ""
    normalized = raw.rstrip("/")
    if method == "POST" and normalized.endswith("upload"):
        return "upload"
    if method == "GET" and "file=" in raw:
        return "download"
    # The Gradio Python client submits the queued ``process_video`` function by
    # POSTing to the ``queue/join`` route; the function is identified by
    # ``fn_index`` in the request body, not in the path, so the path never
    # contains ``process_video``. This app binds a single queued function, so
    # every ``queue/join`` POST corresponds to one processing request. Also
    # match the REST ``/call/process_video`` path used by direct API clients.
    if method == "POST" and (
        normalized.endswith("queue/join") or "process_video" in raw
    ):
        return "process"
    return None


class ActivityMiddleware:
    """ASGI middleware recording client activity and serving ``/activity``.

    It records meaningful client requests (upload/download/process) into a
    bounded :class:`ActivityRecorder` and answers ``GET /activity`` with a small
    JSON payload describing recent activity plus the server identity. All other
    requests are passed through untouched, so existing routes are unaffected.
    """

    def __init__(
        self,
        app: Callable,
        *,
        recorder: Optional[ActivityRecorder] = None,
        identity_factory: Optional[Callable[[], str]] = None,
    ) -> None:
        self.app = app
        self._recorder = recorder if recorder is not None else _ACTIVITY_RECORDER
        self._identity_factory = identity_factory or _describe_server_host

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "") or ""
        method = scope.get("method", "GET")

        if method == "GET" and path.rstrip("/") == "/activity":
            await self._send_activity(scope, send)
            return

        action = _classify_activity(method, path)
        if action is not None:
            self._recorder.record(self._client_ip(scope), action)

        await self.app(scope, receive, send)

    @staticmethod
    def _client_ip(scope: dict) -> str:
        for key, value in scope.get("headers") or []:
            if key.lower() == b"x-forwarded-for":
                with suppress(Exception):
                    forwarded = value.decode("latin-1").split(",")[0].strip()
                    if forwarded:
                        return forwarded
        client = scope.get("client")
        if isinstance(client, (tuple, list)) and client:
            return str(client[0])
        return "unknown"

    def payload(self, scope: Optional[dict] = None) -> dict[str, object]:
        """Build the JSON payload returned from ``GET /activity``."""

        entries = [entry.as_dict() for entry in self._recorder.snapshot()]
        identity = self._identity_factory()
        url = self._server_url(scope)
        return {
            "server": {"identity": identity, "url": url},
            "entries": entries,
        }

    @staticmethod
    def _server_url(scope: Optional[dict]) -> Optional[str]:
        port: Optional[int] = None
        if scope is not None:
            server_addr = scope.get("server")
            if isinstance(server_addr, (tuple, list)) and len(server_addr) >= 2:
                with suppress(TypeError, ValueError):
                    port = int(server_addr[1])
        ip_address = _resolve_host_ip()
        if not ip_address or port is None:
            return None
        return f"http://{ip_address}:{port}/"

    async def _send_activity(self, scope: dict, send: Callable) -> None:
        body = json.dumps(self.payload(scope)).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


_PWA_ICON_FILENAMES = ("app-256.png", "app.png")
_PWA_ICON_PATH = find_icon_path(filenames=_PWA_ICON_FILENAMES)
_PWA_ICON_ROUTE = "/talks-reducer-icon.png"


def _build_pwa_manifest() -> dict[str, object]:
    """Return the web app manifest describing the installable Talks Reducer PWA."""

    app_version = resolve_version()
    version_suffix = (
        f" v{app_version}" if app_version and app_version != "unknown" else ""
    )
    return {
        "name": f"Talks Reducer Web UI{version_suffix}",
        "short_name": "Talks Reducer",
        "icons": [
            {
                "src": _PWA_ICON_ROUTE,
                "sizes": "256x256",
                "type": "image/png",
                "purpose": "any",
            }
        ],
        "start_url": "./",
        "display": "standalone",
    }


class PWAManifestMiddleware:
    """ASGI middleware overriding the PWA manifest and serving its icon.

    Gradio auto-generates ``/manifest.json`` referencing its own bundled logo, so
    an installed Progressive Web App would otherwise display the Gradio icon. This
    middleware answers ``GET /manifest.json`` with a manifest pointing at the
    Talks Reducer icon and serves that icon from :data:`_PWA_ICON_ROUTE`. Every
    other request is passed through untouched.
    """

    def __init__(
        self,
        app: Callable,
        *,
        icon_path: Optional[Path | str] = None,
        manifest_factory: Optional[Callable[[], dict[str, object]]] = None,
    ) -> None:
        self.app = app
        resolved_icon = icon_path if icon_path is not None else _PWA_ICON_PATH
        self._icon_path = Path(resolved_icon) if resolved_icon else None
        self._manifest_factory = manifest_factory or _build_pwa_manifest

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope.get("type") == "http" and scope.get("method", "GET") == "GET":
            path = (scope.get("path", "") or "").rstrip("/")
            if path == "/manifest.json":
                await self._send_manifest(send)
                return
            if self._icon_path is not None and path == _PWA_ICON_ROUTE.rstrip("/"):
                await self._send_icon(send)
                return

        await self.app(scope, receive, send)

    async def _send_manifest(self, send: Callable) -> None:
        body = json.dumps(self._manifest_factory()).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/manifest+json"),
                    (b"content-length", str(len(body)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def _send_icon(self, send: Callable) -> None:
        try:
            data = Path(self._icon_path).read_bytes()
        except OSError:
            await self._send_not_found(send)
            return

        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"image/png"),
                    (b"content-length", str(len(data)).encode("latin-1")),
                    (b"cache-control", b"public, max-age=86400"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": data})

    @staticmethod
    async def _send_not_found(send: Callable) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 404,
                "headers": [(b"content-length", b"0")],
            }
        )
        await send({"type": "http.response.body", "body": b""})


def build_launch_app_kwargs() -> dict[str, object]:
    """Return ``app_kwargs`` enabling server-side transfer progress logging."""

    try:
        from starlette.middleware import Middleware
    except Exception:  # pragma: no cover - starlette ships with gradio
        return {}

    return {
        "middleware": [
            Middleware(PWAManifestMiddleware),
            Middleware(TransferProgressMiddleware),
            Middleware(ActivityMiddleware),
        ]
    }


_FAVICON_FILENAMES = (
    ("app.ico", "app-256.png", "app.png")
    if sys.platform.startswith("win")
    else ("app-256.png", "app.png", "app.ico")
)
_FAVICON_PATH = find_icon_path(filenames=_FAVICON_FILENAMES)
_FAVICON_PATH_STR = str(_FAVICON_PATH) if _FAVICON_PATH else None
_WORKSPACES: list[Path] = []


def _allocate_workspace() -> Path:
    """Create and remember a workspace directory for a single request."""

    path = Path(tempfile.mkdtemp(prefix="talks_reducer_web_"))
    _WORKSPACES.append(path)
    return path


def _cleanup_workspaces() -> None:
    """Remove any workspaces that remain when the process exits."""

    for workspace in _WORKSPACES:
        if workspace.exists():
            with suppress(Exception):
                shutil.rmtree(workspace)
    _WORKSPACES.clear()


def _iter_interface_ipv4_addresses() -> Iterator[str]:
    """Yield IPv4 addresses bound to the local machine's interfaces.

    ``getaddrinfo`` on the hostname surfaces interface addresses on Windows and
    macOS; on Linux the hostname often resolves only to loopback, so the
    per-interface ``SIOCGIFADDR`` lookup below recovers addresses such as a LAN
    ``192.168.x.x`` that no other source exposes.
    """

    with suppress(OSError):
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, family=socket.AF_INET):
            with suppress(IndexError, TypeError):
                address = info[4][0]
                if address:
                    yield str(address)

    yield from _iter_posix_interface_ipv4_addresses()


def _iter_posix_interface_ipv4_addresses() -> Iterator[str]:
    """Yield IPv4 addresses by querying each interface via ``SIOCGIFADDR``.

    Linux-only (relies on ``fcntl`` and the Linux ioctl number); other platforms
    yield nothing and rely on the ``getaddrinfo`` source instead.
    """

    try:
        import fcntl
        import struct
    except ImportError:  # pragma: no cover - non-POSIX platforms
        return
    if not hasattr(socket, "if_nameindex"):  # pragma: no cover - older platforms
        return

    siocgifaddr = 0x8915  # Linux ioctl request for an interface IPv4 address.
    interfaces: list = []
    with suppress(OSError):
        interfaces = list(socket.if_nameindex())

    for _index, name in interfaces:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            packed = fcntl.ioctl(
                sock.fileno(),
                siocgifaddr,
                struct.pack("256s", name.encode("utf-8")[:15]),
            )
            yield socket.inet_ntoa(packed[20:24])
        except OSError:
            continue
        finally:
            sock.close()


def _preferred_lan_ip(
    interface_addresses: Callable[[], Iterator[str]] = _iter_interface_ipv4_addresses,
) -> str:
    """Return a ``192.168.x.x`` interface address when one exists, else ``""``.

    Home and office LANs almost always live in ``192.168.0.0/16``, so this is the
    address other machines on the network can reach. It is matched explicitly
    (rather than "any private range") so a VPN tunnel (``10.x``) or a container
    bridge (``172.16–31.x``) is never advertised as the server URL.
    """

    for address in interface_addresses():
        if address and address.startswith("192.168."):
            return address
    return ""


def _resolve_host_ip() -> str:
    """Return the best-effort LAN IP address for the server, or ``""``.

    Prefer a directly-connected ``192.168.x.x`` LAN address when present: with a
    VPN active the default route (and thus the ``8.8.8.8`` probe below) points at
    the tunnel, e.g. ``10.x``, which other machines on the local network cannot
    reach. Otherwise fall back to the interface used to reach an external host
    (``connect`` on a UDP socket only fixes the default destination, so it works
    offline and never blocks) and finally the resolved hostname, skipping
    loopback addresses (``127.x``) that ``/etc/hosts`` entries like ``127.0.1.1``
    would otherwise yield.
    """

    preferred = _preferred_lan_ip()
    if preferred:
        return preferred

    with suppress(OSError):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            probed_ip = probe.getsockname()[0]
            if probed_ip and not probed_ip.startswith("127."):
                return probed_ip

    hostname = socket.gethostname().strip()
    with suppress(OSError):
        resolved_ip = socket.gethostbyname(hostname or "localhost")
        if resolved_ip and not resolved_ip.startswith("127."):
            return resolved_ip
    return ""


def _describe_server_host() -> str:
    """Return a human-readable description of the server hostname and IP."""

    hostname = socket.gethostname().strip()
    ip_address = _resolve_host_ip()

    if hostname and ip_address and hostname != ip_address:
        return f"{hostname} ({ip_address})"
    if ip_address:
        return ip_address
    if hostname:
        return hostname
    return "unknown"


def _build_output_path(
    input_path: Path,
    workspace: Path,
    small: bool,
    *,
    small_480: bool = False,
    add_codec_suffix: bool = False,
    video_codec: str = "h264",
    silent_speed: float | None = None,
    sounded_speed: float | None = None,
) -> Path:
    """Mirror the CLI output naming scheme inside the workspace directory."""

    normalized_codec = str(video_codec or "h264").strip().lower()
    target_height = 480 if small and small_480 else None
    output_name = _input_to_output_filename(
        input_path,
        small,
        target_height,
        video_codec=normalized_codec,
        add_codec_suffix=add_codec_suffix,
        silent_speed=silent_speed,
        sounded_speed=sounded_speed,
    )
    return workspace / output_name.name


def _format_duration(seconds: float) -> str:
    """Return a compact human-readable duration string."""

    if seconds <= 0:
        return "0s"
    total_seconds = int(round(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes or hours:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def _format_file_size(num_bytes: int) -> str:
    """Return a compact human-readable file size string."""

    size = float(max(0, int(num_bytes)))
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def _format_duration_compact(seconds: float) -> str:
    """Return a no-space compact duration like ``1h12m12s`` or ``59m34s``."""

    if seconds <= 0:
        return "0s"
    total_seconds = int(round(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes or hours:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return "".join(parts)


def _format_size_compact(num_bytes: int) -> str:
    """Return a compact single-letter size like ``506M`` or ``1.2G``."""

    size = float(max(0, int(num_bytes)))
    for unit in ("B", "K", "M", "G"):
        if size < 1024.0:
            if unit == "B":
                return f"{int(size)}{unit}"
            if size >= 10:
                return f"{int(round(size))}{unit}"
            return f"{size:.1f}{unit}"
        size /= 1024.0
    return f"{size:.1f}T"


def _format_summary_compact(result: ProcessingResult) -> str:
    """Produce the two headline result lines (duration + size)."""

    lines: list[str] = []

    duration_suffix = ""
    if result.original_duration > 0:
        pct = round(result.output_duration / result.original_duration * 100)
        duration_suffix = f" ({pct}%)"
    lines.append(
        "**Duration:** "
        f"{_format_duration_compact(result.original_duration)} -> "
        f"{_format_duration_compact(result.output_duration)}{duration_suffix}"
    )

    try:
        input_bytes = result.input_file.stat().st_size
        output_bytes = result.output_file.stat().st_size
    except OSError:
        input_bytes = output_bytes = 0
    if input_bytes > 0 and output_bytes > 0:
        size_pct = round(output_bytes / input_bytes * 100)
        lines.append(
            "**Size:** "
            f"{_format_size_compact(input_bytes)} -> "
            f"{_format_size_compact(output_bytes)} ({size_pct}%)"
        )

    return "\n".join(lines)


def _format_details(result: ProcessingResult) -> str:
    """Produce the collapsible detail lines shown under the summary."""

    return "\n".join(
        [
            f"**Input:** `{result.input_file.name}`",
            f"**Output:** `{result.output_file.name}`",
            f"**Chunks merged:** {result.chunk_count}",
            f"**Encoder:** {'CUDA' if result.used_cuda else 'CPU'}",
        ]
    )


def _format_summary(result: ProcessingResult) -> str:
    """Full summary for the API path: compact headline plus detail lines."""

    compact = _format_summary_compact(result)
    details = _format_details(result)
    return f"{compact}\n{details}" if compact else details


PipelineEvent = tuple[str, object]


def _default_reporter_factory(
    progress_callback: Optional[Callable[[int, int, str], None]],
    log_callback: Callable[[str], None],
) -> SignalProgressReporter:
    """Construct a :class:`GradioProgressReporter` with the given callbacks."""

    return GradioProgressReporter(
        progress_callback=progress_callback,
        log_callback=log_callback,
    )


def run_pipeline_job(
    options: ProcessingOptions,
    *,
    speed_up: Callable[[ProcessingOptions, SignalProgressReporter], ProcessingResult],
    reporter_factory: Callable[
        [Optional[Callable[[int, int, str], None]], Callable[[str], None]],
        SignalProgressReporter,
    ],
    events: SimpleQueue[PipelineEvent],
    enable_progress: bool = True,
    start_in_thread: bool = True,
) -> Iterator[PipelineEvent]:
    """Execute the processing pipeline and yield emitted events."""

    def _emit(kind: str, payload: object) -> None:
        events.put((kind, payload))

    progress_callback: Optional[Callable[[int, int, str], None]] = None
    if enable_progress:
        progress_callback = lambda current, total, desc: _emit(
            "progress", (current, total, desc)
        )

    reporter = reporter_factory(
        progress_callback, lambda message: _emit("log", message)
    )

    def _worker() -> None:
        try:
            result = speed_up(options, reporter=reporter)
        except ProcessingAborted:
            # A client cancellation tripped ``request_stop``; unwind quietly
            # instead of surfacing a "Failed to process" error to the user.
            reporter.log("Processing cancelled.")
        except FFmpegNotFoundError as exc:  # pragma: no cover - depends on runtime env
            _emit("error", gr.Error(str(exc)))
        except FileNotFoundError as exc:
            _emit("error", gr.Error(str(exc)))
        except Exception as exc:  # pragma: no cover - defensive fallback
            reporter.log(f"Error: {exc}")
            _emit("error", gr.Error(f"Failed to process the video: {exc}"))
        else:
            reporter.log("Processing complete.")
            _emit("result", result)
        finally:
            _emit("done", None)

    thread: Optional[Thread] = None
    if start_in_thread:
        thread = Thread(target=_worker, daemon=True)
        thread.start()
    else:
        _worker()

    try:
        while True:
            kind, payload = events.get()
            if kind == "done":
                break
            yield (kind, payload)
    finally:
        if thread is not None:
            # When the consumer stops early (gradio closing the generator on a
            # client cancel), signal the worker to abort so ``join`` returns at
            # the next stop check instead of blocking until the full job ends.
            request_stop = getattr(reporter, "request_stop", None)
            if callable(request_stop):
                request_stop()
            thread.join()


@dataclass
class ProcessVideoDependencies:
    """Container for dependencies used by :func:`process_video`."""

    speed_up: Callable[
        [ProcessingOptions, SignalProgressReporter], ProcessingResult
    ] = speed_up_video
    reporter_factory: Callable[
        [Optional[Callable[[int, int, str], None]], Callable[[str], None]],
        SignalProgressReporter,
    ] = _default_reporter_factory
    queue_factory: Callable[[], SimpleQueue[PipelineEvent]] = SimpleQueue
    run_pipeline_job_func: Callable[..., Iterator[PipelineEvent]] = run_pipeline_job
    start_in_thread: bool = True


def _coerce_file_path(value: object) -> Optional[str]:
    """Normalize a Gradio file input to a local filepath string.

    The ``gr.api`` endpoint delivers uploads as a FileData dict (with a
    ``path`` key) rather than the filepath string the ``gr.File`` UI component
    resolves, so accept either form.
    """

    if isinstance(value, dict):
        path = value.get("path") or value.get("name")
        return str(path) if path else None
    if value is None:
        return None
    return str(value)


def _stream_pipeline(
    file_path: Optional[str],
    small_video: bool,
    small_480: bool,
    optimize: bool,
    video_codec: str,
    add_codec_suffix: bool,
    use_global_ffmpeg: bool,
    silent_threshold: Optional[float],
    sounded_speed: Optional[float],
    silent_speed: Optional[float],
    cut_enabled: bool,
    cut_start_seconds: Optional[float],
    cut_end_seconds: Optional[float],
    dependencies: Optional["ProcessVideoDependencies"],
) -> Iterator[tuple[str, object]]:
    """Run the pipeline, yielding semantic events shared by both handlers.

    Yields ``("log", full_log)`` on each log update (including the initial
    upload receipt), ``("progress", (current, total, desc))`` for progress, and
    finally ``("done", (result, full_log))``. Raises ``gr.Error`` on failure.
    """

    file_path = _coerce_file_path(file_path)
    if not file_path:
        raise gr.Error("Please upload a video file to begin processing.")

    input_path = Path(file_path)
    if not input_path.exists():
        raise gr.Error("The uploaded file is no longer available on the server.")

    upload_size = input_path.stat().st_size
    upload_received_message = (
        f"Upload received: {input_path.name} ({_format_file_size(upload_size)})"
    )

    codec_value = (video_codec or "h264").strip().lower()
    if codec_value not in {"h264", "hevc", "av1", "mp3"}:
        codec_value = "h264"

    normalized_sounded_speed: Optional[float] = None
    if sounded_speed is not None:
        normalized_sounded_speed = float(sounded_speed)

    normalized_silent_speed: Optional[float] = None
    if silent_speed is not None:
        normalized_silent_speed = float(silent_speed)

    workspace = _allocate_workspace()
    temp_folder = workspace / "temp"
    output_file = _build_output_path(
        input_path,
        workspace,
        small_video,
        small_480=small_480,
        add_codec_suffix=add_codec_suffix,
        video_codec=codec_value,
        silent_speed=normalized_silent_speed,
        sounded_speed=normalized_sounded_speed,
    )

    deps = dependencies or ProcessVideoDependencies()
    events = deps.queue_factory()

    option_kwargs: dict[str, float | str | bool] = {
        "video_codec": codec_value,
        "prefer_global_ffmpeg": bool(use_global_ffmpeg),
        "optimize": bool(optimize),
    }
    if add_codec_suffix:
        option_kwargs["add_codec_suffix"] = True
    if silent_threshold is not None:
        option_kwargs["silent_threshold"] = float(silent_threshold)
    if normalized_sounded_speed is not None:
        option_kwargs["sounded_speed"] = normalized_sounded_speed
    if normalized_silent_speed is not None:
        option_kwargs["silent_speed"] = normalized_silent_speed
    if small_video and small_480:
        option_kwargs["small_target_height"] = 480
    if cut_enabled:
        option_kwargs["cut_start_seconds"] = float(cut_start_seconds or 0.0)
        option_kwargs["cut_end_seconds"] = float(cut_end_seconds or 0.0)

    options = ProcessingOptions(
        input_file=input_path,
        output_file=output_file,
        temp_folder=temp_folder,
        small=small_video,
        **option_kwargs,
    )

    event_stream = deps.run_pipeline_job_func(
        options,
        speed_up=deps.speed_up,
        reporter_factory=deps.reporter_factory,
        events=events,
        enable_progress=True,
        start_in_thread=deps.start_in_thread,
    )

    collected_logs: list[str] = [upload_received_message]
    final_result: Optional[ProcessingResult] = None
    error: Optional[gr.Error] = None

    yield ("log", "\n".join(collected_logs))

    for kind, payload in event_stream:
        if kind == "log":
            text = str(payload).strip()
            if text:
                collected_logs.append(text)
                yield ("log", "\n".join(collected_logs))
        elif kind == "progress":
            yield ("progress", payload)
        elif kind == "result":
            final_result = payload  # type: ignore[assignment]
        elif kind == "error":
            error = payload  # type: ignore[assignment]

    if error is not None:
        raise error
    if final_result is None:
        raise gr.Error("Failed to process the video.")

    yield ("done", (final_result, "\n".join(collected_logs)))


def _resolution_to_flags(resolution: str) -> tuple[bool, bool]:
    """Map the Resolution radio to ``(small, small_480)``."""

    if resolution == "480p":
        return True, True
    if resolution == "720p":
        return True, False
    return False, False


_SPEEDUP_SILENT_SPEEDS: dict[str, float] = {"1×": 1.0, "5×": 5.0, "10×": 10.0}


def _speedup_to_silent_speed(label: str) -> float:
    """Map the Speedup radio label to a silent-speed multiplier."""

    return _SPEEDUP_SILENT_SPEEDS.get(label, 10.0)


def _preset_resolution_to_radio(resolution: str) -> str:
    """Map a preset's resolution tri-state onto the Resolution radio label.

    A ``1080p`` preset (and any unexpected value) selects ``"No change"`` — the
    radio label whose ``(small, small_480)`` flags are ``(False, False)`` — so
    the preset forces full resolution rather than inheriting a persisted
    ``--small`` default.
    """

    if resolution == "480p":
        return "480p"
    if resolution == "720p":
        return "720p"
    return "No change"


def _silent_speed_to_speedup_label(speed: float) -> Optional[str]:
    """Return the Speedup radio label matching *speed*, or ``None`` when custom.

    Presets may carry a silent speed the three-option radio cannot represent
    (e.g. ``7.0``); in that case the caller leaves the radio untouched and relies
    on the Silent speed slider, which is the value the pipeline actually reads.
    """

    for label, value in _SPEEDUP_SILENT_SPEEDS.items():
        if abs(value - float(speed)) < 1e-9:
            return label
    return None


def preset_to_web_controls(preset: Preset) -> dict[str, object]:
    """Map *preset* to the Web UI control values it should apply.

    Presets are sparse, so only the params the preset defines appear in the
    returned mapping; a caller leaves every other control untouched. When present,
    keys are the ``resolution`` radio label (``"No change"`` for a ``1080p``
    preset), the matching ``speedup`` radio label (``None`` when the silent speed
    is not one of the radio's presets), the ``video_codec`` dropdown value, and
    the numeric ``silent_speed`` / ``silent_threshold`` / ``sounded_speed`` slider
    values.
    """

    controls: dict[str, object] = {}
    if preset.resolution is not None:
        controls["resolution"] = _preset_resolution_to_radio(preset.resolution)
    if preset.silent_speed is not None:
        controls["speedup"] = _silent_speed_to_speedup_label(preset.silent_speed)
        controls["silent_speed"] = float(preset.silent_speed)
    if preset.video_codec is not None:
        controls["video_codec"] = str(preset.video_codec)
    if preset.silent_threshold is not None:
        controls["silent_threshold"] = float(preset.silent_threshold)
    if preset.sounded_speed is not None:
        controls["sounded_speed"] = float(preset.sounded_speed)
    return controls


def resolve_initial_web_preset(preset_list: Sequence[Preset]) -> Optional[Preset]:
    """Return the preset the Web UI should open on: remembered, else the first.

    Restores the persisted ``selected_preset`` when it still exists in
    *preset_list*; otherwise defaults to the first preset so the dropdown opens on
    a concrete selection instead of blank. Returns ``None`` when no presets exist.
    """

    remembered = get_selected_preset()
    preset = find_preset(remembered, preset_list) if remembered else None
    if preset is None and preset_list:
        preset = preset_list[0]
    return preset


def process_video_ui(
    file_path: Optional[str],
    resolution: str,
    silent_speed: Optional[float],
    video_codec: str,
    optimize: bool,
    add_codec_suffix: bool,
    use_global_ffmpeg: bool,
    sounded_speed: Optional[float],
    silent_threshold: Optional[float],
    cut_enabled: bool,
    cut_start_seconds: Optional[float],
    cut_end_seconds: Optional[float],
    progress: Optional[gr.Progress] = gr.Progress(track_tqdm=False),
    *,
    dependencies: Optional[ProcessVideoDependencies] = None,
) -> Iterator[tuple[Optional[str], str, str, str, Optional[str]]]:
    """Browser handler: map the new controls and yield 5-tuples.

    The 5-tuple is ``(video, log, summary_compact, details, download)``.
    ``silent_speed`` is the Advanced slider value (the Speedup radio writes into
    that slider), so a custom slider value is honored.
    """

    small_video, small_480 = _resolution_to_flags(resolution)

    for kind, payload in _stream_pipeline(
        file_path,
        small_video,
        small_480,
        optimize,
        video_codec,
        add_codec_suffix,
        use_global_ffmpeg,
        silent_threshold,
        sounded_speed,
        silent_speed,
        cut_enabled,
        cut_start_seconds,
        cut_end_seconds,
        dependencies,
    ):
        if kind == "log":
            yield (
                gr.update(),
                cast(str, payload),
                gr.update(),
                gr.update(),
                gr.update(),
            )
        elif kind == "progress":
            if progress is not None:
                current, total, desc = cast(tuple[int, int, str], payload)
                percent = current / total if total > 0 else 0
                progress(percent, total=total, desc=desc)
        elif kind == "done":
            final_result, log_text = cast(tuple[ProcessingResult, str], payload)
            compact = _format_summary_compact(final_result)
            details = _format_details(final_result)
            output_path = str(final_result.output_file)
            is_audio_only = Path(final_result.output_file).suffix.lower() == ".mp3"
            yield (
                None if is_audio_only else output_path,
                log_text,
                compact,
                details,
                output_path,
            )


def process_video_api(
    file_path: Optional[str],
    small_video: bool,
    small_480: bool = False,
    optimize: bool = True,
    video_codec: str = "h264",
    add_codec_suffix: bool = False,
    use_global_ffmpeg: bool = False,
    silent_threshold: Optional[float] = None,
    sounded_speed: Optional[float] = None,
    silent_speed: Optional[float] = None,
    cut_enabled: bool = False,
    cut_start_seconds: Optional[float] = None,
    cut_end_seconds: Optional[float] = None,
) -> Iterator[tuple[Optional[str], str, str, Optional[str]]]:
    """Clean-signature wrapper registered via ``gr.api`` (requires type hints).

    Preserves the 13-arg positional contract and 4-tuple output that
    ``service_client`` depends on.
    """

    yield from process_video(
        file_path,
        small_video,
        small_480,
        optimize,
        video_codec,
        add_codec_suffix,
        use_global_ffmpeg,
        silent_threshold,
        sounded_speed,
        silent_speed,
        cut_enabled,
        cut_start_seconds,
        cut_end_seconds,
    )


def process_video(
    file_path: Optional[str],
    small_video: bool,
    small_480: bool = False,
    optimize: bool = True,
    video_codec: str = "h264",
    add_codec_suffix: bool = False,
    use_global_ffmpeg: bool = False,
    silent_threshold: Optional[float] = None,
    sounded_speed: Optional[float] = None,
    silent_speed: Optional[float] = None,
    cut_enabled: bool = False,
    cut_start_seconds: Optional[float] = None,
    cut_end_seconds: Optional[float] = None,
    progress: Optional[gr.Progress] = gr.Progress(track_tqdm=False),
    *,
    dependencies: Optional[ProcessVideoDependencies] = None,
) -> Iterator[tuple[Optional[str], str, str, Optional[str]]]:
    """Run the Talks Reducer pipeline for a single uploaded file."""

    for kind, payload in _stream_pipeline(
        file_path,
        small_video,
        small_480,
        optimize,
        video_codec,
        add_codec_suffix,
        use_global_ffmpeg,
        silent_threshold,
        sounded_speed,
        silent_speed,
        cut_enabled,
        cut_start_seconds,
        cut_end_seconds,
        dependencies,
    ):
        if kind == "log":
            yield (gr.update(), cast(str, payload), gr.update(), gr.update())
        elif kind == "progress":
            if progress is not None:
                current, total, desc = cast(tuple[int, int, str], payload)
                percent = current / total if total > 0 else 0
                progress(percent, total=total, desc=desc)
        elif kind == "done":
            final_result, log_text = cast(tuple[ProcessingResult, str], payload)
            summary = _format_summary(final_result)
            output_path = str(final_result.output_file)
            is_audio_only = Path(final_result.output_file).suffix.lower() == ".mp3"
            yield (
                None if is_audio_only else output_path,
                log_text,
                summary,
                output_path,
            )


_WEB_UI_CSS = ".tr-codec { max-width: 22rem; } .tr-codec .wrap { min-height: 0; }"


def build_interface(
    concurrency_limit: int = 1,
    presets: Optional[Sequence[Preset]] = None,
) -> gr.Blocks:
    """Construct the Gradio Blocks application for the simple web UI.

    *concurrency_limit* sets how many ``process_video`` jobs the queue runs at
    once. It only affects concurrent clients' processing — file downloads are
    served on a direct route outside the queue, so it does not change a single
    transfer's speed.

    *presets* supplies the named presets shown in the Preset dropdown; when
    ``None`` they are loaded (and seeded on first run) from the shared
    ``settings.json`` via :func:`talks_reducer.presets.load_presets`.
    """

    preset_list = list(presets) if presets is not None else load_presets()

    server_identity = _describe_server_host()
    global_ffmpeg_available = is_global_ffmpeg_available()

    app_version = resolve_version()
    version_suffix = (
        f" v{app_version}" if app_version and app_version != "unknown" else ""
    )

    with gr.Blocks(title=f"Talks Reducer Web UI{version_suffix}") as demo:
        gr.Markdown(f"## Talks Reducer Web UI{version_suffix}")
        with gr.Accordion("About", open=False):
            gr.Markdown(f"""
                Drop a video or audio file below. Pick a **Resolution** and
                **Speedup**, choose the **Video codec**, and processing starts on
                upload. Open **Advanced** for encoder toggles and fine-grained
                speed/threshold controls.

                Video will be rendered on server **{server_identity}**.
                """.strip())

        file_input = gr.File(
            label="Video or audio file",
            file_types=["video", "audio"],
            type="filepath",
        )

        preset_choices = [preset.name for preset in preset_list]
        default_preset = resolve_initial_web_preset(preset_list)
        initial_controls = (
            preset_to_web_controls(default_preset) if default_preset is not None else {}
        )

        def _initial(key: str, fallback: object) -> object:
            value = initial_controls.get(key, fallback)
            return fallback if value is None else value

        preset_dropdown = gr.Dropdown(
            choices=preset_choices,
            value=default_preset.name if default_preset is not None else None,
            label="Preset",
            visible=bool(preset_choices),
        )

        resolution_radio = gr.Radio(
            choices=["No change", "720p", "480p"],
            value=_initial("resolution", "720p"),
            label="Resolution",
        )
        speedup_radio = gr.Radio(
            choices=["1×", "5×", "10×"],
            value=_initial("speedup", "10×"),
            label="Speedup",
        )
        codec_dropdown = gr.Dropdown(
            choices=[
                ("h.265 (25% smaller)", "hevc"),
                ("h.264 (10% faster)", "h264"),
                ("av1 (no advantages)", "av1"),
                ("mp3 (audio only)", "mp3"),
            ],
            value=_initial("video_codec", "hevc"),
            label="Video codec",
            elem_classes=["tr-codec"],
        )

        cut_enabled_checkbox = gr.Checkbox(label="Cut video", value=False)
        with gr.Row(visible=False) as cut_row:
            cut_start_input = gr.Number(
                value=0.0, minimum=0.0, label="Cut start (seconds)"
            )
            cut_end_input = gr.Number(value=0.0, minimum=0.0, label="Cut end (seconds)")

        global_ffmpeg_info = (
            "Prefer the FFmpeg binary from PATH instead of the bundled build."
            if global_ffmpeg_available
            else "Global FFmpeg not detected; the bundled build will be used."
        )
        with gr.Accordion("Advanced", open=False):
            optimize_checkbox = gr.Checkbox(label="Optimized encoding", value=True)
            use_global_ffmpeg_checkbox = gr.Checkbox(
                label="Use global FFmpeg",
                value=False,
                info=global_ffmpeg_info,
                interactive=global_ffmpeg_available,
            )
            add_codec_suffix_checkbox = gr.Checkbox(
                label="Append codec to filename",
                value=False,
                info="Append the selected codec (e.g. _h264) to the output filename.",
            )
            silent_speed_input = gr.Slider(
                minimum=1.0,
                maximum=10.0,
                value=_initial("silent_speed", 10.0),
                step=0.1,
                label="Silent speed",
            )
            sounded_speed_input = gr.Slider(
                minimum=0.5,
                maximum=3.0,
                value=_initial("sounded_speed", 1.0),
                step=0.01,
                label="Sounded speed",
            )
            silent_threshold_input = gr.Slider(
                minimum=0.0,
                maximum=1.0,
                value=_initial("silent_threshold", 0.01),
                step=0.01,
                label="Silent threshold",
            )

        video_output = gr.Video(label="Processed video")
        summary_output = gr.Markdown()
        with gr.Accordion("Details", open=False):
            details_output = gr.Markdown()
        download_output = gr.File(label="Download processed file", interactive=False)
        with gr.Accordion("Log", open=False):
            log_output = gr.Textbox(label="Log", lines=12, interactive=False)

        speedup_radio.change(
            lambda label: gr.update(value=_speedup_to_silent_speed(label)),
            inputs=speedup_radio,
            outputs=silent_speed_input,
        )

        def _apply_preset(
            name: Optional[str],
        ) -> tuple[object, object, object, object, object, object]:
            """Fan the selected preset onto the resolution/speed/codec controls."""

            preset = find_preset(name, preset_list) if name else None
            if preset is None:
                return (
                    gr.update(),
                    gr.update(),
                    gr.update(),
                    gr.update(),
                    gr.update(),
                    gr.update(),
                )
            # Persist the choice so the dropdown reopens on it (shared with the
            # desktop GUI via ``settings.json``). Best-effort: a read-only config
            # must not break applying the preset to the controls.
            with suppress(Exception):
                set_selected_preset(preset.name)
            controls = preset_to_web_controls(preset)

            def _upd(key: str) -> object:
                return (
                    gr.update(value=controls[key]) if key in controls else gr.update()
                )

            speedup = controls.get("speedup")
            return (
                _upd("resolution"),
                gr.update() if speedup is None else gr.update(value=speedup),
                _upd("silent_speed"),
                _upd("video_codec"),
                _upd("silent_threshold"),
                _upd("sounded_speed"),
            )

        preset_dropdown.change(
            _apply_preset,
            inputs=preset_dropdown,
            outputs=[
                resolution_radio,
                speedup_radio,
                silent_speed_input,
                codec_dropdown,
                silent_threshold_input,
                sounded_speed_input,
            ],
        )
        cut_enabled_checkbox.change(
            lambda enabled: gr.update(visible=bool(enabled)),
            inputs=cut_enabled_checkbox,
            outputs=cut_row,
        )

        file_input.upload(
            process_video_ui,
            inputs=[
                file_input,
                resolution_radio,
                silent_speed_input,
                codec_dropdown,
                optimize_checkbox,
                add_codec_suffix_checkbox,
                use_global_ffmpeg_checkbox,
                sounded_speed_input,
                silent_threshold_input,
                cut_enabled_checkbox,
                cut_start_input,
                cut_end_input,
            ],
            outputs=[
                video_output,
                log_output,
                summary_output,
                details_output,
                download_output,
            ],
            queue=True,
        )

        gr.api(process_video_api, api_name="process_video")

    demo.queue(default_concurrency_limit=max(1, concurrency_limit))
    return demo


def main(argv: Optional[Sequence[str]] = None) -> None:
    """Launch the Gradio server from the command line."""

    parser = build_server_parser(
        description="Launch the Talks Reducer web UI.", default_open_browser=True
    )
    args = parser.parse_args(argv)

    demo = build_interface(concurrency_limit=getattr(args, "concurrency", 1))
    demo.launch(
        server_name=args.host,
        server_port=args.port,
        share=args.share,
        inbrowser=args.open_browser,
        favicon_path=_FAVICON_PATH_STR,
        app_kwargs=build_launch_app_kwargs(),
        pwa=True,
        css=_WEB_UI_CSS,
    )


atexit.register(_cleanup_workspaces)


__all__ = [
    "ActivityEntry",
    "ActivityMiddleware",
    "ActivityRecorder",
    "GradioProgressReporter",
    "PWAManifestMiddleware",
    "TransferProgressMiddleware",
    "build_interface",
    "build_launch_app_kwargs",
    "main",
    "preset_to_web_controls",
    "process_video",
    "process_video_api",
    "process_video_ui",
]


if __name__ == "__main__":  # pragma: no cover - convenience entry point
    main()
