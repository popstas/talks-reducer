"""Gradio-powered simple server for running Talks Reducer in a browser."""

from __future__ import annotations

import argparse
import atexit
import shutil
import tempfile
from contextlib import AbstractContextManager, suppress
from pathlib import Path
from typing import Callable, Optional, Sequence

import gradio as gr

from talks_reducer.ffmpeg import FFmpegNotFoundError
from talks_reducer.models import ProcessingOptions, ProcessingResult
from talks_reducer.pipeline import speed_up_video
from talks_reducer.progress import ProgressHandle, SignalProgressReporter


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
        max_log_lines: int = 500,
    ) -> None:
        super().__init__()
        self._progress_callback = progress_callback
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


def process_video(
    file_path: Optional[str],
    small_video: bool,
    progress: Optional[gr.Progress] = gr.Progress(track_tqdm=False),
) -> tuple[Optional[str], str, str, Optional[str]]:
    """Run the Talks Reducer pipeline for a single uploaded file."""

    if not file_path:
        raise gr.Error("Please upload a video file to begin processing.")

    input_path = Path(file_path)
    if not input_path.exists():
        raise gr.Error("The uploaded file is no longer available on the server.")

    workspace = _allocate_workspace()
    temp_folder = workspace / "temp"
    output_file = _build_output_path(input_path, workspace, small_video)

    progress_callback: Optional[Callable[[int, int, str], None]] = None
    if progress is not None:

        def _callback(current: int, total: int, desc: str) -> None:
            progress(current, total=total, desc=desc)

        progress_callback = _callback

    reporter = GradioProgressReporter(progress_callback=progress_callback)

    options = ProcessingOptions(
        input_file=input_path,
        output_file=output_file,
        temp_folder=temp_folder,
        small=small_video,
    )

    try:
        result = speed_up_video(options, reporter=reporter)
    except FFmpegNotFoundError as exc:  # pragma: no cover - depends on runtime env
        raise gr.Error(str(exc)) from exc
    except FileNotFoundError as exc:
        raise gr.Error(str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive fallback
        reporter.log(f"Error: {exc}")
        raise gr.Error(f"Failed to process the video: {exc}") from exc

    reporter.log("Processing complete.")
    log_text = "\n".join(reporter.logs)
    summary = _format_summary(result)

    return (
        str(result.output_file),
        log_text,
        summary,
        str(result.output_file),
    )


def build_interface() -> gr.Blocks:
    """Construct the Gradio Blocks application for the simple web UI."""

    with gr.Blocks(title="Talks Reducer Web UI") as demo:
        gr.Markdown(
            """
            ## Talks Reducer — Simple Server
            Drop a video into the zone below or click to browse. **Small video** is enabled
            by default to apply the 720p/128k preset before processing starts—clear it to
            keep the original resolution.
            """.strip()
        )

        with gr.Row():
            file_input = gr.File(
                label="Video file",
                file_types=["video"],
                type="filepath",
            )
            small_checkbox = gr.Checkbox(label="Small video", value=True)

        video_output = gr.Video(label="Processed video")
        summary_output = gr.Markdown()
        download_output = gr.File(label="Download processed file", interactive=False)
        log_output = gr.Textbox(label="Log", lines=12, interactive=False)

        file_input.upload(
            process_video,
            inputs=[file_input, small_checkbox],
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
