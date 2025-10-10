"""Gradio-powered simple server for running Talks Reducer in a browser."""

from __future__ import annotations

import argparse
import atexit
import shutil
import socket
import sys
import tempfile
from contextlib import AbstractContextManager, suppress
from dataclasses import dataclass
from pathlib import Path
from queue import SimpleQueue
from threading import Thread
from typing import Callable, Iterator, Optional, Sequence, cast

import gradio as gr

from talks_reducer.ffmpeg import FFmpegNotFoundError
from talks_reducer.icons import find_icon_path
from talks_reducer.models import ProcessingOptions, ProcessingResult
from talks_reducer.pipeline import speed_up_video
from talks_reducer.progress import ProgressHandle, SignalProgressReporter
from talks_reducer.version_utils import resolve_version


class _GradioProgressHandle(AbstractContextManager[ProgressHandle]):
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
        self._desc = desc.strip() or "Processing"
        self._unit = unit
        self._total = total
        self._current = 0
        self._reporter._start_task(self._desc, self._total)

    @property
    def current(self) -> int:
        """Return the number of processed units reported so far."""

        return self._current

    def ensure_total(self, total: int) -> None:
        """Update the total units when FFmpeg discovers a larger frame count."""

        if total > 0 and (self._total is None or total > self._total):
            self._total = total
            self._reporter._update_progress(self._current, self._total, self._desc)

    def advance(self, amount: int) -> None:
        """Advance the current progress and notify the UI."""

        if amount <= 0:
            return
        self._current += amount
        self._reporter._update_progress(self._current, self._total, self._desc)

    def finish(self) -> None:
        """Fill the progress bar when FFmpeg completes."""

        if self._total is not None:
            self._current = self._total
        else:
            # Without a known total, treat the final frame count as the total so the
            # progress bar reaches 100%.
            inferred_total = self._current if self._current > 0 else 1
            self._reporter._update_progress(self._current, inferred_total, self._desc)
            return
        self._reporter._update_progress(self._current, self._total, self._desc)

    def __enter__(self) -> "_GradioProgressHandle":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self.finish()
        return False


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


_FAVICON_FILENAMES = (
    ("app.ico", "app.png") if sys.platform.startswith("win") else ("app.png", "app.ico")
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


def _describe_server_host() -> str:
    """Return a human-readable description of the server hostname and IP."""

    hostname = socket.gethostname().strip()
    ip_address = ""

    with suppress(OSError):
        resolved_ip = socket.gethostbyname(hostname or "localhost")
        if resolved_ip:
            ip_address = resolved_ip

    if hostname and ip_address and hostname != ip_address:
        return f"{hostname} ({ip_address})"
    if ip_address:
        return ip_address
    if hostname:
        return hostname
    return "unknown"


def _build_output_path(input_path: Path, workspace: Path, small: bool) -> Path:
    """Mirror the CLI output naming scheme inside the workspace directory."""

    suffix = input_path.suffix or ".mp4"
    stem = input_path.stem
    marker = "_speedup_small" if small else "_speedup"
    return workspace / f"{stem}{marker}{suffix}"


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

    workspace = _allocate_workspace()
    temp_folder = workspace / "temp"
    output_file = _build_output_path(input_path, workspace, small_video)

    deps = dependencies or ProcessVideoDependencies()
    events = deps.queue_factory()

    option_kwargs: dict[str, float] = {}
    if silent_threshold is not None:
        option_kwargs["silent_threshold"] = float(silent_threshold)
    if sounded_speed is not None:
        option_kwargs["sounded_speed"] = float(sounded_speed)
    if silent_speed is not None:
        option_kwargs["silent_speed"] = float(silent_speed)

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

    collected_logs: list[str] = []
    final_result: Optional[ProcessingResult] = None
    error: Optional[gr.Error] = None

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


def build_interface() -> gr.Blocks:
    """Construct the Gradio Blocks application for the simple web UI."""

    server_identity = _describe_server_host()

    app_version = resolve_version()
    version_suffix = (
        f" v{app_version}" if app_version and app_version != "unknown" else ""
    )

    with gr.Blocks(title=f"Talks Reducer Web UI{version_suffix}") as demo:
        gr.Markdown(
            f"""
            ## Talks Reducer Web UI{version_suffix}
            Drop a video into the zone below or click to browse. **Small video** is enabled
            by default to apply the 720p/128k preset before processing starts—clear it to
            keep the original resolution.

            Video will be rendered on server **{server_identity}**.
            """.strip()
        )

        with gr.Column():
            file_input = gr.File(
                label="Video file",
                file_types=["video"],
                type="filepath",
            )

        with gr.Row():
            small_checkbox = gr.Checkbox(label="Small video", value=True)

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
                step=0.05,
                label="Sounded speed",
            )
            silent_threshold_input = gr.Slider(
                minimum=0.0,
                maximum=1.0,
                value=0.05,
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
                silent_threshold_input,
                sounded_speed_input,
                silent_speed_input,
            ],
            outputs=[video_output, log_output, summary_output, download_output],
            queue=True,
            api_name="process_video",
        )

    demo.queue(default_concurrency_limit=1)
    return demo


def main(argv: Optional[Sequence[str]] = None) -> None:
    """Launch the Gradio server from the command line."""

    parser = argparse.ArgumentParser(description="Launch the Talks Reducer web UI.")
    parser.add_argument(
        "--host", dest="host", default="0.0.0.0", help="Custom host to bind."
    )
    parser.add_argument(
        "--port",
        dest="port",
        type=int,
        default=9005,
        help="Port number for the web server (default: 9005).",
    )
    parser.add_argument(
        "--share",
        action="store_true",
        help="Create a temporary public Gradio link.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not automatically open the browser window.",
    )

    args = parser.parse_args(argv)

    demo = build_interface()
    demo.launch(
        server_name=args.host,
        server_port=args.port,
        share=args.share,
        inbrowser=not args.no_browser,
        favicon_path=_FAVICON_PATH_STR,
    )


atexit.register(_cleanup_workspaces)


__all__ = [
    "GradioProgressReporter",
    "build_interface",
    "main",
    "process_video",
]


if __name__ == "__main__":  # pragma: no cover - convenience entry point
    main()
