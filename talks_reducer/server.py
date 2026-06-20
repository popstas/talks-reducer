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
from threading import Lock, Thread
from typing import Callable, Iterator, Optional, Sequence, cast

import gradio as gr

from talks_reducer.ffmpeg import FFmpegNotFoundError, is_global_ffmpeg_available
from talks_reducer.icons import find_icon_path
from talks_reducer.models import ProcessingOptions, ProcessingResult
from talks_reducer.pipeline import _input_to_output_filename, speed_up_video
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


def build_launch_app_kwargs() -> dict[str, object]:
    """Return ``app_kwargs`` enabling server-side transfer progress logging."""

    try:
        from starlette.middleware import Middleware
    except Exception:  # pragma: no cover - starlette ships with gradio
        return {}

    return {
        "middleware": [
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


def _resolve_host_ip() -> str:
    """Return the best-effort LAN IP address for the server, or ``""``.

    Prefer the address of the interface used to reach an external host, which is
    the LAN-facing IP that other machines can connect to. ``connect`` on a UDP
    socket only fixes the default destination (no packets are sent), so this
    works offline and never blocks. Fall back to resolving the hostname, and in
    both cases skip loopback addresses (``127.x``) which ``/etc/hosts`` entries
    such as ``127.0.1.1`` would otherwise yield and which no other machine can
    reach.
    """

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
    video_codec: str = "hevc",
    silent_speed: float | None = None,
    sounded_speed: float | None = None,
) -> Path:
    """Mirror the CLI output naming scheme inside the workspace directory."""

    normalized_codec = str(video_codec or "hevc").strip().lower()
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


def _format_summary(result: ProcessingResult) -> str:
    """Produce a Markdown summary of the processing result."""

    lines = [
        f"**Input:** `{result.input_file.name}`",
        f"**Output:** `{result.output_file.name}`",
    ]

    duration_line = (
        f"**Duration:** {_format_duration(result.output_duration)}"
        f" ({_format_duration(result.original_duration)} original)"
    )
    if result.time_ratio is not None:
        duration_line += f" — {result.time_ratio * 100:.1f}% of the original"
    lines.append(duration_line)

    if result.size_ratio is not None:
        size_percent = result.size_ratio * 100
        lines.append(f"**Size:** {size_percent:.1f}% of the original file")

    lines.append(f"**Chunks merged:** {result.chunk_count}")
    lines.append(f"**Encoder:** {'CUDA' if result.used_cuda else 'CPU'}")

    return "\n".join(lines)


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


def process_video(
    file_path: Optional[str],
    small_video: bool,
    small_480: bool = False,
    optimize: bool = True,
    video_codec: str = "hevc",
    add_codec_suffix: bool = False,
    use_global_ffmpeg: bool = False,
    silent_threshold: Optional[float] = None,
    sounded_speed: Optional[float] = None,
    silent_speed: Optional[float] = None,
    progress: Optional[gr.Progress] = gr.Progress(track_tqdm=False),
    *,
    dependencies: Optional[ProcessVideoDependencies] = None,
) -> Iterator[tuple[Optional[str], str, str, Optional[str]]]:
    """Run the Talks Reducer pipeline for a single uploaded file."""

    if not file_path:
        raise gr.Error("Please upload a video file to begin processing.")

    input_path = Path(file_path)
    if not input_path.exists():
        raise gr.Error("The uploaded file is no longer available on the server.")

    upload_size = input_path.stat().st_size
    upload_received_message = (
        f"Upload received: {input_path.name} ({_format_file_size(upload_size)})"
    )

    codec_value = (video_codec or "hevc").strip().lower()
    if codec_value not in {"h264", "hevc", "av1"}:
        codec_value = "hevc"

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
        enable_progress=progress is not None,
        start_in_thread=deps.start_in_thread,
    )

    collected_logs: list[str] = [upload_received_message]
    final_result: Optional[ProcessingResult] = None
    error: Optional[gr.Error] = None

    yield (
        gr.update(),
        "\n".join(collected_logs),
        gr.update(),
        gr.update(),
    )

    for kind, payload in event_stream:
        if kind == "log":
            text = str(payload).strip()
            if text:
                collected_logs.append(text)
                yield (
                    gr.update(),
                    "\n".join(collected_logs),
                    gr.update(),
                    gr.update(),
                )
        elif kind == "progress":
            if progress is not None:
                current, total, desc = cast(tuple[int, int, str], payload)
                percent = current / total if total > 0 else 0
                progress(percent, total=total, desc=desc)
        elif kind == "result":
            final_result = payload  # type: ignore[assignment]
        elif kind == "error":
            error = payload  # type: ignore[assignment]

    if error is not None:
        raise error

    if final_result is None:
        raise gr.Error("Failed to process the video.")

    log_text = "\n".join(collected_logs)
    summary = _format_summary(final_result)

    yield (
        str(final_result.output_file),
        log_text,
        summary,
        str(final_result.output_file),
    )


def build_interface(concurrency_limit: int = 1) -> gr.Blocks:
    """Construct the Gradio Blocks application for the simple web UI.

    *concurrency_limit* sets how many ``process_video`` jobs the queue runs at
    once. It only affects concurrent clients' processing — file downloads are
    served on a direct route outside the queue, so it does not change a single
    transfer's speed.
    """

    server_identity = _describe_server_host()
    global_ffmpeg_available = is_global_ffmpeg_available()

    app_version = resolve_version()
    version_suffix = (
        f" v{app_version}" if app_version and app_version != "unknown" else ""
    )

    with gr.Blocks(title=f"Talks Reducer Web UI{version_suffix}") as demo:
        gr.Markdown(f"""
            ## Talks Reducer Web UI{version_suffix}
            Drop a video into the zone below or click to browse. **Small video** is enabled
            by default to apply the 720p/128k preset before processing starts—clear it to
            keep the original resolution or pair it with **Target 480p** to downscale
            further. Choose **Video codec** to switch between h.265 (≈25% smaller),
            h.264 (≈10% faster), and av1 (no advantages) compression, and enable
            **Use global FFmpeg** when your system install offers hardware encoders that the
            bundled build lacks.

            Video will be rendered on server **{server_identity}**.
            """.strip())

        with gr.Column():
            file_input = gr.File(
                label="Video file",
                file_types=["video"],
                type="filepath",
            )

        with gr.Row():
            small_checkbox = gr.Checkbox(label="Small video", value=True)
            small_480_checkbox = gr.Checkbox(label="Target 480p", value=False)
            optimize_checkbox = gr.Checkbox(label="Optimized encoding", value=True)

        codec_dropdown = gr.Dropdown(
            choices=[
                ("h.265 (25% smaller)", "hevc"),
                ("h.264 (10% faster)", "h264"),
                ("av1 (no advantages)", "av1"),
            ],
            value="hevc",
            label="Video codec",
        )

        global_ffmpeg_info = (
            "Prefer the FFmpeg binary from PATH instead of the bundled build."
            if global_ffmpeg_available
            else "Global FFmpeg not detected; the bundled build will be used."
        )
        add_codec_suffix_checkbox = gr.Checkbox(
            label="Append codec to filename",
            value=False,
            info="Append the selected codec (e.g. _h264) to the output filename.",
        )

        use_global_ffmpeg_checkbox = gr.Checkbox(
            label="Use global FFmpeg",
            value=False,
            info=global_ffmpeg_info,
            interactive=global_ffmpeg_available,
        )

        with gr.Column():
            silent_speed_input = gr.Slider(
                minimum=1.0,
                maximum=10.0,
                value=4.0,
                step=0.1,
                label="Silent speed",
            )
            sounded_speed_input = gr.Slider(
                minimum=0.5,
                maximum=3.0,
                value=1.0,
                step=0.01,
                label="Sounded speed",
            )
            silent_threshold_input = gr.Slider(
                minimum=0.0,
                maximum=1.0,
                value=0.01,
                step=0.01,
                label="Silent threshold",
            )

        video_output = gr.Video(label="Processed video")
        summary_output = gr.Markdown()
        download_output = gr.File(label="Download processed file", interactive=False)
        log_output = gr.Textbox(label="Log", lines=12, interactive=False)

        file_input.upload(
            process_video,
            inputs=[
                file_input,
                small_checkbox,
                small_480_checkbox,
                optimize_checkbox,
                codec_dropdown,
                add_codec_suffix_checkbox,
                use_global_ffmpeg_checkbox,
                silent_threshold_input,
                sounded_speed_input,
                silent_speed_input,
            ],
            outputs=[video_output, log_output, summary_output, download_output],
            queue=True,
            api_name="process_video",
        )

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
    )


atexit.register(_cleanup_workspaces)


__all__ = [
    "ActivityEntry",
    "ActivityMiddleware",
    "ActivityRecorder",
    "GradioProgressReporter",
    "TransferProgressMiddleware",
    "build_interface",
    "build_launch_app_kwargs",
    "main",
    "process_video",
]


if __name__ == "__main__":  # pragma: no cover - convenience entry point
    main()
