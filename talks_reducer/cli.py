"""Command line interface for the talks reducer package."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from importlib import import_module
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from . import audio
from .ffmpeg import FFmpegNotFoundError
from .models import ProcessingOptions, default_temp_folder
from .pipeline import speed_up_video
from .progress import TqdmProgressReporter
from .version_utils import resolve_version


def _build_parser() -> argparse.ArgumentParser:
    """Create the argument parser used by the command line interface."""

    parser = argparse.ArgumentParser(
        description="Modifies a video file to play at different speeds when there is sound vs. silence.",
    )

    # Add version argument
    pkg_version = resolve_version()

    parser.add_argument(
        "--version",
        action="version",
        version=f"talks-reducer {pkg_version}",
    )

    parser.add_argument(
        "input_file",
        type=str,
        nargs="+",
        help="The video file(s) you want modified. Can be one or more directories and / or single files.",
    )
    parser.add_argument(
        "-o",
        "--output_file",
        type=str,
        dest="output_file",
        help="The output file. Only usable if a single file is given. If not included, it'll append _ALTERED to the name.",
    )
    parser.add_argument(
        "--temp_folder",
        type=str,
        default=str(default_temp_folder()),
        help="The file path of the temporary working folder.",
    )
    parser.add_argument(
        "-t",
        "--silent_threshold",
        type=float,
        dest="silent_threshold",
        help="The volume amount that frames' audio needs to surpass to be considered sounded. Defaults to 0.05.",
    )
    parser.add_argument(
        "-S",
        "--sounded_speed",
        type=float,
        dest="sounded_speed",
        help="The speed that sounded (spoken) frames should be played at. Defaults to 1.",
    )
    parser.add_argument(
        "-s",
        "--silent_speed",
        type=float,
        dest="silent_speed",
        help="The speed that silent frames should be played at. Defaults to 4.",
    )
    parser.add_argument(
        "-fm",
        "--frame_margin",
        type=float,
        dest="frame_spreadage",
        help="Some silent frames adjacent to sounded frames are included to provide context. Defaults to 2.",
    )
    parser.add_argument(
        "-sr",
        "--sample_rate",
        type=float,
        dest="sample_rate",
        help="Sample rate of the input and output videos. Usually extracted automatically by FFmpeg.",
    )
    parser.add_argument(
        "--small",
        action="store_true",
        help="Apply small file optimizations: resize video to 720p, audio to 128k bitrate, best compression (uses CUDA if available).",
    )
    parser.add_argument(
        "--url",
        dest="server_url",
        default=None,
        help="Process videos via a Talks Reducer server at the provided base URL (for example, http://localhost:9005).",
    )
    parser.add_argument(
        "--host",
        dest="host",
        default=None,
        help="Shortcut for --url when targeting a Talks Reducer server on port 9005 (for example, localhost).",
    )
    parser.add_argument(
        "--server-stream",
        action="store_true",
        help="Stream remote progress updates when using --url.",
    )
    return parser


def gather_input_files(paths: List[str]) -> List[str]:
    """Expand provided paths into a flat list of files that contain audio streams."""

    files: List[str] = []
    for input_path in paths:
        if os.path.isfile(input_path) and audio.is_valid_input_file(input_path):
            files.append(os.path.abspath(input_path))
        elif os.path.isdir(input_path):
            for file in os.listdir(input_path):
                candidate = os.path.join(input_path, file)
                if audio.is_valid_input_file(candidate):
                    files.append(candidate)
    return files


def _print_total_time(start_time: float) -> None:
    """Print the elapsed processing time since *start_time*."""

    end_time = time.time()
    total_time = end_time - start_time
    hours, remainder = divmod(total_time, 3600)
    minutes, seconds = divmod(remainder, 60)
    print(f"\nTime: {int(hours)}h {int(minutes)}m {seconds:.2f}s")


class CliApplication:
    """Coordinator for CLI processing with dependency injection support."""

    def __init__(
        self,
        *,
        gather_files: Callable[[List[str]], List[str]],
        send_video: Optional[Callable[..., Tuple[Path, str, str]]],
        speed_up: Callable[[ProcessingOptions, object], object],
        reporter_factory: Callable[[], object],
        remote_error_message: Optional[str] = None,
    ) -> None:
        self._gather_files = gather_files
        self._send_video = send_video
        self._speed_up = speed_up
        self._reporter_factory = reporter_factory
        self._remote_error_message = remote_error_message

    def run(self, parsed_args: argparse.Namespace) -> Tuple[int, List[str]]:
        """Execute the CLI pipeline for *parsed_args*."""

        start_time = time.time()
        files = self._gather_files(parsed_args.input_file)

        args: Dict[str, object] = {
            key: value for key, value in vars(parsed_args).items() if value is not None
        }
        del args["input_file"]

        if "host" in args:
            del args["host"]

        if len(files) > 1 and "output_file" in args:
            del args["output_file"]

        error_messages: List[str] = []
        reporter_logs: List[str] = []

        if getattr(parsed_args, "server_url", None):
            remote_success, remote_errors, fallback_logs = self._process_via_server(
                files, parsed_args, start_time
            )
            error_messages.extend(remote_errors)
            reporter_logs.extend(fallback_logs)
            if remote_success:
                return 0, error_messages

        reporter = self._reporter_factory()
        for message in reporter_logs:
            reporter.log(message)

        for index, file in enumerate(files):
            print(
                f"Processing file {index + 1}/{len(files)} '{os.path.basename(file)}'"
            )
            local_options = dict(args)

            option_kwargs: Dict[str, object] = {"input_file": Path(file)}

            if "output_file" in local_options:
                option_kwargs["output_file"] = Path(local_options["output_file"])
            if "temp_folder" in local_options:
                option_kwargs["temp_folder"] = Path(local_options["temp_folder"])
            if "silent_threshold" in local_options:
                option_kwargs["silent_threshold"] = float(
                    local_options["silent_threshold"]
                )
            if "silent_speed" in local_options:
                option_kwargs["silent_speed"] = float(local_options["silent_speed"])
            if "sounded_speed" in local_options:
                option_kwargs["sounded_speed"] = float(local_options["sounded_speed"])
            if "frame_spreadage" in local_options:
                option_kwargs["frame_spreadage"] = int(local_options["frame_spreadage"])
            if "sample_rate" in local_options:
                option_kwargs["sample_rate"] = int(local_options["sample_rate"])
            if "small" in local_options:
                option_kwargs["small"] = bool(local_options["small"])
            options = ProcessingOptions(**option_kwargs)

            try:
                result = self._speed_up(options, reporter=reporter)
            except FFmpegNotFoundError as exc:
                message = str(exc)
                return 1, [*error_messages, message]

            reporter.log(f"Completed: {result.output_file}")
            summary_parts: List[str] = []
            time_ratio = getattr(result, "time_ratio", None)
            size_ratio = getattr(result, "size_ratio", None)
            if time_ratio is not None:
                summary_parts.append(f"{time_ratio * 100:.0f}% time")
            if size_ratio is not None:
                summary_parts.append(f"{size_ratio * 100:.0f}% size")
            if summary_parts:
                reporter.log("Result: " + ", ".join(summary_parts))

        _print_total_time(start_time)
        return 0, error_messages

    def _process_via_server(
        self,
        files: Sequence[str],
        parsed_args: argparse.Namespace,
        start_time: float,
    ) -> Tuple[bool, List[str], List[str]]:
        """Upload *files* to the configured server and download the results."""

        if not self._send_video:
            message = self._remote_error_message or "Server processing is unavailable."
            fallback_notice = "Falling back to local processing pipeline."
            return False, [message, fallback_notice], [message, fallback_notice]

        server_url = parsed_args.server_url
        if not server_url:
            message = "Server URL was not provided."
            fallback_notice = "Falling back to local processing pipeline."
            return False, [message, fallback_notice], [message, fallback_notice]

        output_override: Optional[Path] = None
        if parsed_args.output_file and len(files) == 1:
            output_override = Path(parsed_args.output_file).expanduser()
        elif parsed_args.output_file and len(files) > 1:
            print(
                "Warning: --output is ignored when processing multiple files via the server.",
                file=sys.stderr,
            )

        remote_option_values: Dict[str, float] = {}
        if parsed_args.silent_threshold is not None:
            remote_option_values["silent_threshold"] = float(
                parsed_args.silent_threshold
            )
        if parsed_args.silent_speed is not None:
            remote_option_values["silent_speed"] = float(parsed_args.silent_speed)
        if parsed_args.sounded_speed is not None:
            remote_option_values["sounded_speed"] = float(parsed_args.sounded_speed)

        unsupported_options: List[str] = []
        for name in ("frame_spreadage", "sample_rate", "temp_folder"):
            if getattr(parsed_args, name) is not None:
                unsupported_options.append(f"--{name.replace('_', '-')}")

        if unsupported_options:
            print(
                "Warning: the following options are ignored when using --url: "
                + ", ".join(sorted(unsupported_options)),
                file=sys.stderr,
            )

        for index, file in enumerate(files, start=1):
            basename = os.path.basename(file)
            print(
                f"Processing file {index}/{len(files)} '{basename}' via server {server_url}"
            )
            printed_log_header = False
            progress_state: dict[str, tuple[Optional[int], Optional[int], str]] = {}
            stream_updates = bool(getattr(parsed_args, "server_stream", False))

            def _stream_server_log(line: str) -> None:
                nonlocal printed_log_header
                if not printed_log_header:
                    print("\nServer log:", flush=True)
                    printed_log_header = True
                print(line, flush=True)

            def _stream_progress(
                desc: str, current: Optional[int], total: Optional[int], unit: str
            ) -> None:
                key = desc or "Processing"
                state = (current, total, unit)
                if progress_state.get(key) == state:
                    return
                progress_state[key] = state

                parts: List[str] = []
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

            try:
                destination, summary, log_text = self._send_video(
                    input_path=Path(file),
                    output_path=output_override,
                    server_url=server_url,
                    small=bool(parsed_args.small),
                    **remote_option_values,
                    log_callback=_stream_server_log,
                    stream_updates=stream_updates,
                    progress_callback=_stream_progress if stream_updates else None,
                )
            except Exception as exc:  # pragma: no cover - network failure safeguard
                message = f"Failed to process {basename} via server: {exc}"
                fallback_notice = "Falling back to local processing pipeline."
                return False, [message, fallback_notice], [message, fallback_notice]

            print(summary)
            print(f"Saved processed video to {destination}")
            if log_text.strip() and not printed_log_header:
                print("\nServer log:\n" + log_text)

        _print_total_time(start_time)
        return True, [], []


def _launch_gui(argv: Sequence[str]) -> bool:
    """Attempt to launch the GUI with the provided arguments."""

    try:
        gui_module = import_module(".gui", __package__)
    except ImportError:
        return False

    gui_main = getattr(gui_module, "main", None)
    if gui_main is None:
        return False

    return bool(gui_main(list(argv)))


def _launch_server(argv: Sequence[str]) -> bool:
    """Attempt to launch the Gradio server with the provided arguments."""

    try:
        server_module = import_module(".server", __package__)
    except ImportError:
        return False

    server_main = getattr(server_module, "main", None)
    if server_main is None:
        return False

    server_main(list(argv))
    return True


def _find_server_tray_binary() -> Optional[Path]:
    """Return the best available path to the server tray executable."""

    binary_name = "talks-reducer-server-tray"
    candidates: List[Path] = []

    which_path = shutil.which(binary_name)
    if which_path:
        candidates.append(Path(which_path))

    try:
        launcher_dir = Path(sys.argv[0]).resolve().parent
    except Exception:
        launcher_dir = None

    potential_names = [binary_name]
    if sys.platform == "win32":
        potential_names = [f"{binary_name}.exe", binary_name]

    if launcher_dir is not None:
        for name in potential_names:
            candidates.append(launcher_dir / name)

    for candidate in candidates:
        if candidate and candidate.exists() and os.access(candidate, os.X_OK):
            return candidate

    return None


def _should_hide_subprocess_console() -> bool:
    """Return ``True` ` when a detached Windows launch should hide the console."""

    if sys.platform != "win32":
        return False

    try:
        import ctypes
    except Exception:  # pragma: no cover - optional runtime dependency
        return False

    try:
        get_console_window = ctypes.windll.kernel32.GetConsoleWindow  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - platform specific guard
        return False

    try:
        handle = get_console_window()
    except Exception:  # pragma: no cover - defensive fallback
        return False

    return handle == 0


def _launch_server_tray_binary(argv: Sequence[str]) -> bool:
    """Launch the packaged server tray executable when available."""

    command = _find_server_tray_binary()
    if command is None:
        return False

    tray_args = [str(command), *list(argv)]

    run_kwargs: Dict[str, object] = {"check": False}

    if sys.platform == "win32":
        no_window_flag = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if no_window_flag and _should_hide_subprocess_console():
            run_kwargs["creationflags"] = no_window_flag

    try:
        result = subprocess.run(tray_args, **run_kwargs)
    except OSError:
        return False

    return result.returncode == 0


def _launch_server_tray(argv: Sequence[str]) -> bool:
    """Attempt to launch the server tray helper with the provided arguments."""

    if _launch_server_tray_binary(argv):
        return True

    try:
        tray_module = import_module(".server_tray", __package__)
    except ImportError:
        return False

    tray_main = getattr(tray_module, "main", None)
    if tray_main is None:
        return False

    tray_main(list(argv))
    return True


def main(argv: Optional[Sequence[str]] = None) -> None:
    """Entry point for the command line interface.

    Launch the GUI when run without arguments, otherwise defer to the CLI.
    """

    if argv is None:
        argv_list = sys.argv[1:]
    else:
        argv_list = list(argv)

    if "--server" in argv_list:
        index = argv_list.index("--server")
        tray_args = argv_list[index + 1 :]
        if not _launch_server_tray(tray_args):
            print("Server tray mode is unavailable.", file=sys.stderr)
            sys.exit(1)
        return

    if argv_list and argv_list[0] in {"server", "serve"}:
        if not _launch_server(argv_list[1:]):
            print("Gradio server mode is unavailable.", file=sys.stderr)
            sys.exit(1)
        return

    if not argv_list:
        if _launch_gui(argv_list):
            return

        parser = _build_parser()
        parser.print_help()
        return

    parser = _build_parser()
    parsed_args = parser.parse_args(argv_list)

    host_value = getattr(parsed_args, "host", None)
    if host_value:
        parsed_args.server_url = f"http://{host_value}:9005"

    send_video = None
    remote_error_message: Optional[str] = None
    try:  # pragma: no cover - optional dependency guard
        from . import service_client
    except ImportError as exc:
        remote_error_message = (
            "Server mode requires the gradio_client dependency. " f"({exc})"
        )
    else:
        send_video = service_client.send_video

    application = CliApplication(
        gather_files=gather_input_files,
        send_video=send_video,
        speed_up=speed_up_video,
        reporter_factory=TqdmProgressReporter,
        remote_error_message=remote_error_message,
    )

    exit_code, error_messages = application.run(parsed_args)
    for message in error_messages:
        print(message, file=sys.stderr)
    if exit_code:
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
