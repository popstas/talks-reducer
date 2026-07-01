"""Command-line helper for sending videos to the Talks Reducer server."""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
import threading
import time
from contextlib import suppress
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Optional, Sequence, Tuple

from gradio_client import Client
from gradio_client import file as gradio_file
from gradio_client.client import Status, StatusUpdate

try:
    from .pipeline import ProcessingAborted
except ImportError:  # pragma: no cover - allow running as script
    from talks_reducer.pipeline import ProcessingAborted


# Installing the upload/download progress hooks mutates module-global
# ``httpx`` attributes on ``gradio_client.client``. Serialize the patched
# regions so concurrent :func:`send_video` calls in one process cannot clobber
# or misattribute each other's hooks while a transfer is in flight.
_TRANSFER_PATCH_LOCK = threading.Lock()


class _ProgressFileReader:
    """Proxy a binary file object and report each chunk read to a callback.

    ``httpx`` reads multipart file fields in 64 KiB chunks while it streams the
    request body to the socket. Wrapping the file object lets us emit byte-level
    upload progress without re-implementing the gradio upload route.
    """

    def __init__(self, fileobj: Any, on_bytes: Callable[[int], None]) -> None:
        self._file = fileobj
        self._on_bytes = on_bytes

    def read(self, size: int = -1) -> bytes:
        chunk = self._file.read(size)
        if chunk:
            self._on_bytes(len(chunk))
        return chunk

    def __getattr__(self, name: str) -> Any:
        return getattr(self._file, name)


class _ThrottledEmitter:
    """Forward progress events at most once per ``min_interval`` seconds.

    Byte-level upload/download callbacks fire once per network chunk — hundreds
    to thousands of times per second on a fast LAN — which floods the GUI event
    loop and adds backpressure to the transfer itself. Coalescing to ~10 Hz keeps
    the progress bar and speed readout responsive without the per-chunk overhead.
    Pass ``force=True`` for events that must always be delivered (the initial 0%
    and the terminal 100%).
    """

    def __init__(
        self,
        callback: Callable[[str, Optional[int], Optional[int], str], None],
        *,
        min_interval: float = 0.1,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self._callback = callback
        self._min_interval = min_interval
        self._clock = clock if clock is not None else time.monotonic
        self._last_emit: Optional[float] = None

    def __call__(
        self,
        desc: str,
        current: Optional[int],
        total: Optional[int],
        unit: str,
        *,
        force: bool = False,
    ) -> None:
        now = self._clock()
        if (
            force
            or self._last_emit is None
            or now - self._last_emit >= self._min_interval
        ):
            self._last_emit = now
            self._callback(desc, current, total, unit)


def _wrap_upload_files(files: Any, on_bytes: Callable[[int], None]) -> Any:
    """Return *files* with each readable file object wrapped for progress."""

    items = files.items() if isinstance(files, dict) else files
    wrapped = []
    for field, spec in items:
        if (
            isinstance(spec, (list, tuple))
            and len(spec) >= 2
            and hasattr(spec[1], "read")
        ):
            spec = (spec[0], _ProgressFileReader(spec[1], on_bytes), *tuple(spec[2:]))
        wrapped.append((field, spec))
    return wrapped


class _ProgressResponse:
    """Wrap an ``httpx`` streaming response to report download progress."""

    def __init__(
        self,
        response: Any,
        progress_callback: Callable[[str, Optional[int], Optional[int], str], None],
    ) -> None:
        self._response = response
        self._progress_callback = progress_callback

    def iter_bytes(self, *args: Any, **kwargs: Any) -> Any:
        total: Optional[int] = None
        with suppress(TypeError, ValueError, AttributeError):
            content_length = self._response.headers.get("content-length")
            if content_length is not None:
                total = int(content_length)
        received = 0
        self._progress_callback("Downloading:", 0, total, "bytes")
        for chunk in self._response.iter_bytes(*args, **kwargs):
            received += len(chunk)
            self._progress_callback("Downloading:", received, total, "bytes")
            yield chunk

    def __getattr__(self, name: str) -> Any:
        return getattr(self._response, name)


class _MonotonicDownloadProgress:
    """Collapse repeated download 0→100 cycles into a single monotonic sequence.

    The gradio client downloads file outputs more than once per job — intermediate
    streamed outputs and the multiple file output components (the response is a
    ``(video, log, summary, download)`` tuple whose first and last fields are
    files) each trigger ``_download_file``. Every invocation drives a fresh
    :class:`_ProgressResponse` through a full 0→100 byte cycle, so the
    ``"Downloading:"`` desc would otherwise reach 100% several times. Wrapping the
    real callback forwards only strictly increasing download fractions, so exactly
    one 0→100 sequence (with a single terminal 100%) reaches the GUI bar.

    Non-``"Downloading:"`` events (upload, processing) pass through untouched.
    """

    def __init__(
        self,
        callback: Callable[[str, Optional[int], Optional[int], str], None],
    ) -> None:
        self._callback = callback
        self._max_fraction = -1.0

    def __call__(
        self,
        desc: str,
        current: Optional[int],
        total: Optional[int],
        unit: str,
    ) -> None:
        if desc != "Downloading:":
            self._callback(desc, current, total, unit)
            return

        if total and total > 0 and current is not None:
            fraction = max(0.0, min(1.0, current / total))
        elif current is None:
            fraction = 0.0
        else:
            # Without a known total the GUI bar cannot move, so there is no
            # percentage to dedupe against. Forward as-is.
            self._callback(desc, current, total, unit)
            return

        if fraction <= self._max_fraction:
            return
        self._max_fraction = fraction
        self._callback(desc, current, total, unit)


class _ProgressStreamContext:
    """Context-manager proxy that yields a :class:`_ProgressResponse`."""

    def __init__(
        self,
        context_manager: Any,
        progress_callback: Callable[[str, Optional[int], Optional[int], str], None],
    ) -> None:
        self._context_manager = context_manager
        self._progress_callback = progress_callback

    def __enter__(self) -> _ProgressResponse:
        response = self._context_manager.__enter__()
        return _ProgressResponse(response, self._progress_callback)

    def __exit__(self, *exc_info: Any) -> Any:
        return self._context_manager.__exit__(*exc_info)


def _install_transfer_progress(
    client: Any,
    api_name: Optional[str],
    upload_total: Optional[int],
    progress_callback: Callable[[str, Optional[int], Optional[int], str], None],
    should_cancel: Optional[Callable[[], bool]] = None,
) -> bool:
    """Patch the gradio endpoint to stream byte-level upload/download progress.

    Returns ``True`` when the endpoint was patched. Callers that receive
    ``False`` (for example because a stub client without real endpoints was
    supplied) should emit the synthetic upload-complete event themselves.

    When *should_cancel* is supplied it is polled once per uploaded chunk so a
    stop request aborts the in-flight upload within a single ~64 KiB chunk
    instead of only after the whole file has been sent.
    """

    try:
        fn_index = client._infer_fn_index(api_name, None)
        endpoint = client.endpoints[fn_index]
    except Exception:  # pragma: no cover - defensive (stub clients, API changes)
        return False

    original_upload = getattr(endpoint, "_upload_file", None)
    original_download = getattr(endpoint, "_download_file", None)
    if not callable(original_upload) or not callable(original_download):
        return False

    import gradio_client.client as gradio_client_module

    # Persist the dedupe state across every ``_download_file`` invocation in this
    # transfer so repeated 0→100 cycles collapse into one monotonic sequence.
    # When ``send_video`` builds the client with ``download_files=False`` gradio
    # never calls ``_download_file`` (the single download is streamed directly),
    # so this dedupe only matters for stub/legacy clients that still auto-download.
    download_progress = _MonotonicDownloadProgress(progress_callback)

    def upload_file(file_obj: Any, data_index: int = 0) -> Any:
        sent = 0
        # Coalesce the per-chunk upload events; the guaranteed completion event
        # below is emitted directly so the ``Uploading`` band still finishes.
        throttled = _ThrottledEmitter(progress_callback)

        def _on_bytes(count: int) -> None:
            nonlocal sent
            if should_cancel is not None and should_cancel():
                # Raise mid-stream so httpx tears down the in-flight POST instead
                # of finishing the upload before the cancel is noticed.
                raise ProcessingAborted("Remote processing cancelled by user.")
            sent += count
            current = min(sent, upload_total) if upload_total else sent
            throttled("Uploading:", current, upload_total, "bytes")

        with _TRANSFER_PATCH_LOCK:
            original_post = gradio_client_module.httpx.post

            def post(*args: Any, **kwargs: Any) -> Any:
                files = kwargs.get("files")
                if files:
                    kwargs["files"] = _wrap_upload_files(files, _on_bytes)
                return original_post(*args, **kwargs)

            gradio_client_module.httpx.post = post
            try:
                result = original_upload(file_obj, data_index)
            finally:
                gradio_client_module.httpx.post = original_post

        # Only report the upload as complete once every byte was sent. Emitting
        # this from a ``finally`` block would flash 100% even when the transfer
        # raised mid-stream (e.g. a dropped connection).
        if upload_total:
            progress_callback("Uploading:", upload_total, upload_total, "bytes")
        return result

    def download_file(payload: Any) -> Any:
        with _TRANSFER_PATCH_LOCK:
            original_stream = gradio_client_module.httpx.stream

            def stream(*args: Any, **kwargs: Any) -> Any:
                return _ProgressStreamContext(
                    original_stream(*args, **kwargs), download_progress
                )

            gradio_client_module.httpx.stream = stream
            try:
                return original_download(payload)
            finally:
                gradio_client_module.httpx.stream = original_stream

    endpoint._upload_file = upload_file
    endpoint._download_file = download_file
    return True


class StreamingJob:
    """Adapter that provides a consistent interface for streaming jobs."""

    def __init__(self, job: Any) -> None:
        self._job = job

    @property
    def raw(self) -> Any:
        """Return the wrapped job instance."""

        return self._job

    @property
    def supports_streaming(self) -> bool:
        """Return ``True`` when the remote job can stream async updates."""

        communicator = getattr(self._job, "communicator", None)
        return communicator is not None

    async def async_iter_updates(self) -> AsyncIterator[Any]:
        """Yield updates from the wrapped job asynchronously."""

        async for update in self._job:  # type: ignore[async-for]
            yield update

    def status(self) -> Any:
        """Return the latest status update from the job when available."""

        status_method = getattr(self._job, "status", None)
        if callable(status_method):
            return status_method()
        raise AttributeError("Wrapped job does not expose a status() method")

    def outputs(self) -> Any:
        """Return cached outputs from the job when available."""

        outputs_method = getattr(self._job, "outputs", None)
        if callable(outputs_method):
            return outputs_method()
        raise AttributeError("Wrapped job does not expose an outputs() method")

    def cancel(self) -> None:
        """Cancel the remote job when supported."""

        cancel_method = getattr(self._job, "cancel", None)
        if callable(cancel_method):
            cancel_method()


def _build_client(client_builder: Callable[..., Client], server_url: str) -> Client:
    """Return a gradio client with auto-download disabled when supported.

    Disabling ``download_files`` stops gradio from fetching every file output:
    the processed video is returned to both a ``gr.Video`` preview and a
    ``gr.File`` download component, so the default behavior downloads the same
    file twice. Stub factories and older gradio releases that do not accept the
    keyword fall back to the legacy positional construction (and keep gradio's
    own download path).
    """

    try:
        return client_builder(server_url, download_files=False)
    except TypeError:
        return client_builder(server_url)


def _filedata_get(filedata: Any, key: str) -> Any:
    """Return *key* from a FileData mapping or object, or ``None``."""

    if isinstance(filedata, dict):
        return filedata.get(key)
    return getattr(filedata, key, None)


def _filedata_name(target: Any) -> str:
    """Return the destination filename for a download *target*.

    *target* is either a plain path string (stub/legacy clients) or a FileData
    mapping/object (when gradio auto-download is disabled).
    """

    if isinstance(target, str):
        return Path(target).name
    orig_name = _filedata_get(target, "orig_name")
    if isinstance(orig_name, str) and orig_name:
        return Path(orig_name).name
    path = _filedata_get(target, "path") or _filedata_get(target, "url") or ""
    return Path(str(path)).name


def _resolve_filedata_url(client: Any, filedata: Any, server_url: str) -> str:
    """Build the server URL to download *filedata*, mirroring gradio_client."""

    base = (
        getattr(client, "src_prefixed", None)
        or getattr(client, "src", None)
        or server_url
        or ""
    )
    if base and not base.endswith("/"):
        base = base + "/"

    url = _filedata_get(filedata, "url")
    if url:
        if not str(url).startswith(("http://", "https://")):
            url = base + str(url).lstrip("/")
        return str(url)

    path = _filedata_get(filedata, "path")
    if path:
        return base + "file=" + str(path)

    raise RuntimeError("Server did not return a processed file")


def _download_filedata(
    client: Any,
    filedata: Any,
    destination: Path,
    progress_callback: Optional[
        Callable[[str, Optional[int], Optional[int], str], None]
    ],
    cancel_check: Optional[Callable[[], None]],
    server_url: str,
    *,
    chunk_size: int = 1024 * 1024,
) -> Path:
    """Stream the single processed file to *destination* with throttled progress.

    Issues exactly one ``httpx`` GET (so the gr.Video/gr.File pair is fetched
    once, not twice) using a 1 MiB chunk size and ~10 Hz progress events instead
    of gradio's per-8 KB callback storm.
    """

    import gradio_client.client as gradio_client_module

    url = _resolve_filedata_url(client, filedata, server_url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    emitter = (
        _ThrottledEmitter(progress_callback) if progress_callback is not None else None
    )

    with gradio_client_module.httpx.stream(
        "GET",
        url,
        headers=getattr(client, "headers", None),
        cookies=getattr(client, "cookies", None),
        verify=getattr(client, "ssl_verify", True),
        follow_redirects=True,
        **(getattr(client, "httpx_kwargs", {}) or {}),
    ) as response:
        response.raise_for_status()
        total: Optional[int] = None
        with suppress(TypeError, ValueError, AttributeError):
            content_length = response.headers.get("content-length")
            if content_length is not None:
                total = int(content_length)

        received = 0
        if emitter is not None:
            emitter("Downloading:", 0, total, "bytes", force=True)

        with open(destination, "wb") as handle:
            for chunk in response.iter_bytes(chunk_size=chunk_size):
                if cancel_check is not None:
                    cancel_check()
                handle.write(chunk)
                received += len(chunk)
                if emitter is not None:
                    is_final = total is not None and received >= total
                    emitter("Downloading:", received, total, "bytes", force=is_final)

        if emitter is not None:
            emitter("Downloading:", received, total, "bytes", force=True)

    return destination


def send_video(
    input_path: Path,
    output_path: Optional[Path],
    server_url: str,
    small: bool = False,
    small_480: bool = False,
    optimize: bool = True,
    video_codec: str = "hevc",
    add_codec_suffix: bool = False,
    prefer_global_ffmpeg: bool = False,
    *,
    silent_threshold: Optional[float] = None,
    sounded_speed: Optional[float] = None,
    silent_speed: Optional[float] = None,
    cut_enabled: bool = False,
    cut_start_seconds: Optional[float] = None,
    cut_end_seconds: Optional[float] = None,
    log_callback: Optional[Callable[[str], None]] = None,
    stream_updates: bool = False,
    should_cancel: Optional[Callable[[], bool]] = None,
    progress_callback: Optional[
        Callable[[str, Optional[int], Optional[int], str], None]
    ] = None,
    client_factory: Optional[Callable[[str], Client]] = None,
    job_factory: Optional[
        Callable[[Client, Tuple[Any, ...], dict[str, Any]], Any]
    ] = None,
) -> Tuple[Path, str, str]:
    """Upload *input_path* to the Gradio server and download the processed video.

    When *should_cancel* returns ``True`` the remote job is cancelled and a
    :class:`ProcessingAborted` exception is raised. Set *optimize* to ``False``
    to switch to the fastest CUDA-oriented preset when available, and set
    *prefer_global_ffmpeg* when the PATH-provided FFmpeg offers hardware
    encoders that the bundled static build omits.
    """

    if not input_path.exists():
        raise FileNotFoundError(f"Input file does not exist: {input_path}")

    client_builder = client_factory or Client
    client = _build_client(client_builder, server_url)
    submit_args: Tuple[Any, ...] = (
        gradio_file(str(input_path)),
        bool(small),
        bool(small_480),
        bool(optimize),
        str(video_codec),
        bool(add_codec_suffix),
        bool(prefer_global_ffmpeg),
        silent_threshold,
        sounded_speed,
        silent_speed,
        bool(cut_enabled),
        cut_start_seconds,
        cut_end_seconds,
    )
    submit_kwargs: dict[str, Any] = {"api_name": "/process_video"}

    upload_total: Optional[int] = None
    transfer_progress_installed = False
    if progress_callback is not None:
        try:
            upload_total = input_path.stat().st_size
        except OSError:  # pragma: no cover - defensive
            upload_total = None
        progress_callback("Uploading:", 0, upload_total, "bytes")
        # Patch the endpoint so the real upload (which runs lazily inside the
        # submitted job, not when ``submit`` returns) streams byte-level progress
        # instead of jumping straight to 100%.
        transfer_progress_installed = _install_transfer_progress(
            client,
            submit_kwargs.get("api_name"),
            upload_total,
            progress_callback,
            should_cancel,
        )

    if job_factory is not None:
        job = job_factory(client, submit_args, submit_kwargs)
    else:
        job = client.submit(*submit_args, **submit_kwargs)

    if progress_callback is not None and not transfer_progress_installed:
        # Stub clients without real endpoints (or older gradio APIs) cannot
        # stream the upload; fall back to reporting it complete so the
        # ``Uploading`` band still finishes.
        progress_callback("Uploading:", upload_total, upload_total, "bytes")

    streaming_job = StreamingJob(job)

    cancelled = False

    def _cancel_if_requested() -> None:
        nonlocal cancelled
        if should_cancel and should_cancel():
            if not cancelled:
                with suppress(Exception):
                    streaming_job.cancel()
                cancelled = True
            raise ProcessingAborted("Remote processing cancelled by user.")

    printed_lines = 0

    def _emit_new_lines(log_text: str) -> None:
        nonlocal printed_lines
        if log_callback is None or not log_text:
            return
        lines = log_text.splitlines()
        if printed_lines < len(lines):
            for line in lines[printed_lines:]:
                log_callback(line)
            printed_lines = len(lines)

    consumed_stream = False

    if stream_updates:
        stream_kwargs: dict[str, object] = {"progress_callback": progress_callback}
        if should_cancel is not None:
            stream_kwargs["cancel_callback"] = _cancel_if_requested
        consumed_stream = _stream_job_updates(
            streaming_job,
            _emit_new_lines,
            **stream_kwargs,
        )

    if not consumed_stream:
        for output in job:
            _cancel_if_requested()
            if not isinstance(output, (list, tuple)) or len(output) != 4:
                continue
            log_text_candidate = output[1] or ""
            if isinstance(log_text_candidate, str):
                _emit_new_lines(log_text_candidate)

    _cancel_if_requested()

    try:
        prediction = job.result()
    except Exception:
        _cancel_if_requested()
        raise

    try:
        video_path, log_text, summary, download_path = prediction
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise RuntimeError("Unexpected response from server") from exc

    if isinstance(log_text, str):
        _emit_new_lines(log_text)
    else:
        log_text = ""

    target = download_path or video_path
    if not target:
        raise RuntimeError("Server did not return a processed file")

    _cancel_if_requested()

    name = _filedata_name(target)
    if output_path is None:
        destination = Path.cwd() / name
    else:
        destination = output_path
        if destination.is_dir():
            destination = destination / name

    if isinstance(target, str):
        # Stub/legacy clients (gradio auto-download still active) hand back a
        # local path; copy it as before.
        download_source = Path(target)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if download_source.resolve() != destination.resolve():
            shutil.copy2(download_source, destination)
    else:
        # ``download_files=False`` leaves outputs as FileData; download the one
        # processed file ourselves instead of letting gradio fetch every file
        # output (the gr.Video preview and the gr.File download both point at the
        # same file, which would otherwise transfer the video twice).
        _download_filedata(
            client,
            target,
            destination,
            progress_callback,
            _cancel_if_requested,
            server_url,
        )

    if not isinstance(summary, str):
        summary = ""
    if not isinstance(log_text, str):
        log_text = ""

    return destination, summary, log_text


def _coerce_int(value: object) -> Optional[int]:
    """Return *value* as an ``int`` when possible."""

    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _emit_progress_update(
    callback: Callable[[str, Optional[int], Optional[int], str], None],
    unit: object,
) -> None:
    """Normalize a progress unit and forward it to *callback*."""

    if unit is None:
        return

    if hasattr(unit, "__dict__"):
        data = unit
        desc = getattr(data, "desc", None)
        length = getattr(data, "length", None)
        index = getattr(data, "index", None)
        progress = getattr(data, "progress", None)
        unit_name = getattr(data, "unit", None)
    elif isinstance(unit, dict):
        desc = unit.get("desc")
        length = unit.get("length")
        index = unit.get("index")
        progress = unit.get("progress")
        unit_name = unit.get("unit")
    else:
        return

    total = _coerce_int(length)
    current = _coerce_int(index)
    if current is None and isinstance(progress, (int, float)):
        progress_value = float(progress)
        if total and 0.0 <= progress_value <= 1.0:
            current = int(round(progress_value * total))
        else:
            current = int(progress_value)

    callback(desc or "Processing", current, total, str(unit_name or ""))


async def _pump_job_updates(
    job: StreamingJob,
    emit_log: Callable[[str], None],
    progress_callback: Optional[
        Callable[[str, Optional[int], Optional[int], str], None]
    ],
    cancel_callback: Optional[Callable[[], None]] = None,
) -> None:
    """Consume asynchronous updates from *job* and emit logs and progress."""

    async for update in job.async_iter_updates():
        if cancel_callback:
            cancel_callback()
        update_type = getattr(update, "type", "status")
        if update_type == "output":
            outputs = getattr(update, "outputs", None) or []
            if isinstance(outputs, (list, tuple)) and len(outputs) == 4:
                log_text_candidate = outputs[1] or ""
                if isinstance(log_text_candidate, str):
                    emit_log(log_text_candidate)
            if getattr(update, "final", False):
                break
            continue

        status_update: StatusUpdate = update  # type: ignore[assignment]
        log_entry = getattr(status_update, "log", None)
        if log_entry:
            message = (
                log_entry[0] if isinstance(log_entry, (list, tuple)) else log_entry
            )
            if isinstance(message, str):
                emit_log(message)

        if progress_callback and status_update.progress_data:
            for unit in status_update.progress_data:
                _emit_progress_update(progress_callback, unit)

        if status_update.code in {Status.FINISHED, Status.CANCELLED}:
            break


def _poll_job_updates(
    job,
    emit_log: Callable[[str], None],
    progress_callback: Optional[
        Callable[[str, Optional[int], Optional[int], str], None]
    ],
    *,
    cancel_callback: Optional[Callable[[], None]] = None,
    interval: float = 0.25,
) -> None:
    """Poll *job* for outputs and status updates when async streaming is unavailable."""

    streaming_job = job if isinstance(job, StreamingJob) else StreamingJob(job)
    raw_job = streaming_job.raw

    while True:
        if cancel_callback:
            cancel_callback()
        if hasattr(raw_job, "done") and raw_job.done():
            break

        status: Optional[StatusUpdate] = None
        with suppress(Exception):
            status = streaming_job.status()  # type: ignore[assignment]

        if status is not None:
            if progress_callback:
                progress_data = getattr(status, "progress_data", None)
                if progress_data:
                    for unit in progress_data:
                        _emit_progress_update(progress_callback, unit)
            log_entry = getattr(status, "log", None)
            if log_entry:
                message = (
                    log_entry[0] if isinstance(log_entry, (list, tuple)) else log_entry
                )
                if isinstance(message, str):
                    emit_log(message)

        outputs = []
        with suppress(Exception):
            outputs = streaming_job.outputs()
        if outputs:
            latest = outputs[-1]
            if isinstance(latest, (list, tuple)) and len(latest) == 4:
                log_text_candidate = latest[1] or ""
                if isinstance(log_text_candidate, str):
                    emit_log(log_text_candidate)

        time.sleep(interval)


def _stream_job_updates(
    job: StreamingJob,
    emit_log: Callable[[str], None],
    *,
    progress_callback: Optional[
        Callable[[str, Optional[int], Optional[int], str], None]
    ] = None,
    cancel_callback: Optional[Callable[[], None]] = None,
) -> bool:
    """Attempt to stream updates directly from *job*.

    Returns ``True`` when streaming occurred, ``False`` when the legacy
    generator-based fallback should be used.
    """

    if not job.supports_streaming:
        return False

    try:
        asyncio.run(
            _pump_job_updates(
                job,
                emit_log,
                progress_callback,
                cancel_callback,
            )
        )
    except ProcessingAborted:
        # Cancellation must propagate; it is a ``RuntimeError`` subclass but is
        # not the "no running event loop" error the polling fallback handles.
        raise
    except RuntimeError:
        _poll_job_updates(
            job,
            emit_log,
            progress_callback,
            cancel_callback=cancel_callback,
        )

    return True


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Send a video to a running talks-reducer server and download the result.",
    )
    parser.set_defaults(optimize=True)
    parser.add_argument("input", type=Path, help="Path to the video file to upload.")
    parser.add_argument(
        "--server",
        default="http://127.0.0.1:9005/",
        help="Base URL for the talks-reducer server (default: http://127.0.0.1:9005/).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Where to store the processed video. Defaults to the working directory.",
    )
    parser.add_argument(
        "--small",
        action="store_true",
        help="Toggle the 'Small video' preset before processing.",
    )
    parser.add_argument(
        "--480",
        dest="small_480",
        action="store_true",
        help="Combine with --small to target 480p instead of 720p.",
    )
    parser.add_argument(
        "--no-optimize",
        dest="optimize",
        action="store_false",
        help="Disable the tuned presets and request the fastest CUDA-oriented settings instead.",
    )
    parser.add_argument(
        "--video-codec",
        choices=["h264", "hevc", "av1", "mp3"],
        default="hevc",
        help=(
            "Select the video encoder used for the render (default: hevc — "
            "h.265 for roughly 25%% smaller files). Switch to h264 (about 10%% "
            "faster) or av1 (no advantages) when you want different trade-offs, "
            "or mp3 to export an audio-only file."
        ),
    )
    parser.add_argument(
        "--prefer-global-ffmpeg",
        action="store_true",
        help="Use the FFmpeg binary available on PATH before falling back to the bundled copy.",
    )
    parser.add_argument(
        "--print-log",
        action="store_true",
        help="Print the server log after processing completes.",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Stream remote progress updates while waiting for the result.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    printed_log_header = False

    def _stream(line: str) -> None:
        nonlocal printed_log_header
        if not printed_log_header:
            print("\nServer log:", flush=True)
            printed_log_header = True
        print(line, flush=True)

    progress_state: dict[str, tuple[Optional[int], Optional[int], str]] = {}

    def _progress(
        desc: str, current: Optional[int], total: Optional[int], unit: str
    ) -> None:
        key = desc or "Processing"
        state = (current, total, unit)
        if progress_state.get(key) == state:
            return
        progress_state[key] = state

        parts: list[str] = []
        if current is not None and total and total > 0:
            percent = (current / total) * 100
            parts.append(f"{current}/{total}")
            parts.append(f"{percent:.1f}%")
        elif current is not None:
            parts.append(str(current))
        if unit:
            parts.append(unit)
        message = " ".join(parts).strip()
        print(f"{key}: {message or 'update'}", flush=True)

    if args.small_480 and not args.small:
        print(
            "Warning: --480 has no effect unless --small is also provided.",
            file=sys.stderr,
        )

    small_480_mode = bool(args.small and args.small_480)

    destination, summary, log_text = send_video(
        input_path=args.input.expanduser(),
        output_path=args.output.expanduser() if args.output else None,
        server_url=args.server,
        small=args.small,
        small_480=small_480_mode,
        optimize=bool(args.optimize),
        video_codec=str(args.video_codec),
        prefer_global_ffmpeg=bool(args.prefer_global_ffmpeg),
        log_callback=_stream if args.print_log else None,
        stream_updates=args.stream,
        progress_callback=_progress if args.stream else None,
    )

    print(summary)
    print(f"Saved processed video to {destination}")
    if args.print_log and log_text.strip() and not printed_log_header:
        print("\nServer log:\n" + log_text)


if __name__ == "__main__":  # pragma: no cover
    main()
