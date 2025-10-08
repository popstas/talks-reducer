"""Command line interface for the talks reducer package."""

from __future__ import annotations

import argparse
import os
import sys
import time
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from . import audio

try:
    from .__about__ import __version__ as _about_version
except Exception:  # pragma: no cover - fallback if metadata file missing
    _about_version = ""
from .ffmpeg import FFmpegNotFoundError
from .models import ProcessingOptions, default_temp_folder
from .pipeline import speed_up_video
from .progress import TqdmProgressReporter


def _build_parser() -> argparse.ArgumentParser:
    """Create the argument parser used by the command line interface."""

    parser = argparse.ArgumentParser(
        description="Modifies a video file to play at different speeds when there is sound vs. silence.",
    )

    # Add version argument
    pkg_version = _resolve_version()

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
    return parser


def _resolve_version() -> str:
    """Determine the package version for CLI reporting."""

    if _about_version:
        return _about_version

    try:
        return version("talks-reducer")
    except (PackageNotFoundError, Exception):
        return "unknown"


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


def _process_via_server(
    files: Sequence[str], parsed_args: argparse.Namespace, *, start_time: float
) -> None:
    """Upload *files* to the configured server and download the results."""

    try:
        from . import service_client
    except ImportError as exc:  # pragma: no cover - optional dependency guard
        print(
            "Server mode requires the gradio_client dependency." f" ({exc})",
            file=sys.stderr,
        )
        sys.exit(1)

    server_url = parsed_args.server_url
    if not server_url:
        return

    output_override: Optional[Path] = None
    if parsed_args.output_file and len(files) == 1:
        output_override = Path(parsed_args.output_file).expanduser()
    elif parsed_args.output_file and len(files) > 1:
        print(
            "Warning: --output is ignored when processing multiple files via the server.",
            file=sys.stderr,
        )

    unsupported_options = []
    for name in (
        "silent_threshold",
        "silent_speed",
        "sounded_speed",
        "frame_spreadage",
        "sample_rate",
        "temp_folder",
    ):
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
        try:
            destination, summary, log_text = service_client.send_video(
                input_path=Path(file),
                output_path=output_override,
                server_url=server_url,
                small=bool(parsed_args.small),
            )
        except Exception as exc:  # pragma: no cover - network failure safeguard
            print(f"Failed to process {basename}: {exc}", file=sys.stderr)
            sys.exit(1)

        print(summary)
        print(f"Saved processed video to {destination}")
        if log_text.strip():
            print("\nServer log:\n" + log_text)

    _print_total_time(start_time)


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
    """Attempt to launch the Gradio web server with the provided arguments."""

    try:
        server_module = import_module(".server", __package__)
    except ImportError:
        return False

    server_main = getattr(server_module, "main", None)
    if server_main is None:
        return False

    server_main(list(argv))
    return True


def main(argv: Optional[Sequence[str]] = None) -> None:
    """Entry point for the command line interface.

    Launch the GUI when run without arguments, otherwise defer to the CLI.
    """

    if argv is None:
        argv_list = sys.argv[1:]
    else:
        argv_list = list(argv)

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
    start_time = time.time()

    files = gather_input_files(parsed_args.input_file)

    args: Dict[str, object] = {
        k: v for k, v in vars(parsed_args).items() if v is not None
    }
    del args["input_file"]

    if len(files) > 1 and "output_file" in args:
        del args["output_file"]

    if parsed_args.server_url:
        _process_via_server(files, parsed_args, start_time=start_time)
        return

    reporter = TqdmProgressReporter()

    for index, file in enumerate(files):
        print(f"Processing file {index + 1}/{len(files)} '{os.path.basename(file)}'")
        local_options = dict(args)

        option_kwargs: Dict[str, object] = {"input_file": Path(file)}

        if "output_file" in local_options:
            option_kwargs["output_file"] = Path(local_options["output_file"])
        if "temp_folder" in local_options:
            option_kwargs["temp_folder"] = Path(local_options["temp_folder"])
        if "silent_threshold" in local_options:
            option_kwargs["silent_threshold"] = float(local_options["silent_threshold"])
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
            result = speed_up_video(options, reporter=reporter)
        except FFmpegNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)

        reporter.log(f"Completed: {result.output_file}")
        summary_parts = []
        time_ratio = getattr(result, "time_ratio", None)
        size_ratio = getattr(result, "size_ratio", None)
        if time_ratio is not None:
            summary_parts.append(f"{time_ratio * 100:.0f}% time")
        if size_ratio is not None:
            summary_parts.append(f"{size_ratio * 100:.0f}% size")
        if summary_parts:
            reporter.log("Result: " + ", ".join(summary_parts))

    _print_total_time(start_time)


if __name__ == "__main__":
    main()
