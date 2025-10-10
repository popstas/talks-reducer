"""Command-line helper for sending videos to the Talks Reducer server."""

from __future__ import annotations

import argparse
import asyncio
import shutil
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


def send_video(
    input_path: Path,
    output_path: Optional[Path],
    server_url: str,
    small: bool = False,
    *,
    silent_threshold: Optional[float] = None,
    sounded_speed: Optional[float] = None,
    silent_speed: Optional[float] = None,
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
    :class:`ProcessingAborted` exception is raised.
    """

    if not input_path.exists():
        raise FileNotFoundError(f"Input file does not exist: {input_path}")

    client_builder = client_factory or Client
    client = client_builder(server_url)
    submit_args: Tuple[Any, ...] = (
        gradio_file(str(input_path)),
        bool(small),
        silent_threshold,
        sounded_speed,
        silent_speed,
    )
    submit_kwargs: dict[str, Any] = {"api_name": "/process_video"}

    if job_factory is not None:
        job = job_factory(client, submit_args, submit_kwargs)
    else:
        job = client.submit(*submit_args, **submit_kwargs)

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

    if not download_path:
        download_path = video_path

    if not download_path:
        raise RuntimeError("Server did not return a processed file")

    _cancel_if_requested()

    download_source = Path(str(download_path))
    if output_path is None:
        destination = Path.cwd() / download_source.name
    else:
        destination = output_path
        if destination.is_dir():
            destination = destination / download_source.name

    destination.parent.mkdir(parents=True, exist_ok=True)
    if download_source.resolve() != destination.resolve():
        shutil.copy2(download_source, destination)

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
    if current is None and isinstance(progress, (int, float)) and total:
        current = int(progress / total)

    callback(desc or "Processing", progress, total, str(unit_name or ""))


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

    destination, summary, log_text = send_video(
        input_path=args.input.expanduser(),
        output_path=args.output.expanduser() if args.output else None,
        server_url=args.server,
        small=args.small,
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
