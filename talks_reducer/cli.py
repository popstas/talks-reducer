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
from .timecode import parse_timecode
from .version_utils import resolve_version


class _ListPresetsAction(argparse.Action):
    """Print the stored preset names and exit, mirroring ``--version``.

    Implemented as an argparse action so ``--list-presets`` works without the
    otherwise-required ``input_file`` positional, exiting during parsing before
    the required-argument check runs.
    """

    def __init__(self, option_strings, dest, **kwargs):
        kwargs.setdefault("nargs", 0)
        kwargs.setdefault("default", argparse.SUPPRESS)
        super().__init__(option_strings, dest, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        from . import presets as presets_module

        loaded = presets_module.load_presets()
        if loaded:
            for preset in loaded:
                print(preset.name)
        else:
            print("No presets are defined.")
        parser.exit()


def _build_parser() -> argparse.ArgumentParser:
    """Create the argument parser used by the command line interface."""

    parser = argparse.ArgumentParser(
        description="Modifies a video file to play at different speeds when there is sound vs. silence.",
    )

    # Add version argument
    pkg_version = resolve_version()

    parser.set_defaults(optimize=True)

    parser.add_argument(
        "--version",
        action="version",
        version=f"talks-reducer {pkg_version}",
    )

    parser.add_argument(
        "--preset",
        dest="preset",
        default=None,
        help=(
            "Apply a saved preset by name as the base configuration before any "
            "explicit flags. Explicit flags still override the preset. Use "
            "--list-presets to see the available names."
        ),
    )
    parser.add_argument(
        "--list-presets",
        action=_ListPresetsAction,
        help="Print the names of the saved presets and exit.",
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
        help="Base directory for temporary working folders. Each run creates a unique subdirectory inside it and removes that subdirectory when finished, so parallel invocations do not collide.",
    )
    parser.add_argument(
        "-t",
        "--silent_threshold",
        "--silent-threshold",
        type=float,
        dest="silent_threshold",
        help="The volume amount that frames' audio needs to surpass to be considered sounded. Defaults to 0.01.",
    )
    parser.add_argument(
        "-S",
        "--sounded_speed",
        "--sounded-speed",
        type=float,
        dest="sounded_speed",
        help="The speed that sounded (spoken) frames should be played at. Defaults to 1.",
    )
    parser.add_argument(
        "-s",
        "--silent_speed",
        "--silent-speed",
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
        "--keyframe-interval",
        type=float,
        dest="keyframe_interval_seconds",
        help="Override the keyframe spacing in seconds when using --small. Defaults to 30.",
    )
    parser.add_argument(
        "--video-codec",
        choices=["h264", "hevc", "av1", "mp3"],
        default="h264",
        help=(
            "Select the video encoder used for the final render (default: h264 — "
            "about 10%% faster and widely compatible). Pick hevc (h.265) for "
            "roughly 25%% smaller files or av1 (no advantages) for experimental "
            "runs. Choose mp3 to export an audio-only .mp3 file instead of a video."
        ),
    )
    parser.add_argument(
        "--add-codec-suffix",
        dest="add_codec_suffix",
        action="store_true",
        help="Append the selected video codec to the default output filename.",
    )
    parser.add_argument(
        "--prefer-global-ffmpeg",
        action="store_true",
        help="Use an FFmpeg binary from PATH before falling back to the bundled static build.",
    )
    parser.add_argument(
        "--small",
        action="store_true",
        help="Apply small file optimizations: resize video to 720p (or 480p with --480), audio to 128k bitrate, best compression (uses CUDA if available).",
    )
    parser.add_argument(
        "--no-small",
        dest="small",
        action="store_false",
        default=False,
        help="Force-disable the small preset, overriding a stored --small preference (unchecks the GUI Small video box on a seeded launch).",
    )
    parser.add_argument(
        "--480",
        dest="small_480",
        action="store_true",
        help="Use with --small to scale video to 480p instead of 720p.",
    )
    parser.add_argument(
        "--720",
        dest="small_480",
        action="store_false",
        default=False,
        help="Force the 720p small preset, overriding a stored 480p preference (unchecks the GUI 480p box on a seeded launch).",
    )
    parser.add_argument(
        "--no-optimize",
        dest="optimize",
        action="store_false",
        help="Disable the tuned encoding presets and use the fastest CUDA-oriented settings instead.",
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
    parser.add_argument(
        "--cut-start",
        dest="cut_start_seconds",
        type=parse_timecode,
        default=0.0,
        help=(
            "Keep only the fragment starting at this timestamp before processing. "
            "Accepts seconds (12.5) or HH:MM:SS[.ms] (00:01:45). Defaults to 0 (start of video)."
        ),
    )
    parser.add_argument(
        "--cut-end",
        dest="cut_end_seconds",
        type=parse_timecode,
        default=0.0,
        help=(
            "Stop keeping the fragment at this timestamp before processing. "
            "Accepts seconds (12.5) or HH:MM:SS[.ms] (00:01:45). Defaults to 0 (until end of video)."
        ),
    )
    parser.add_argument(
        "--open-location",
        dest="open_location",
        action="store_true",
        help=(
            "GUI only: reveal each exported file in the system file manager after "
            "it finishes, regardless of the saved 'Open after convert' setting."
        ),
    )
    parser.add_argument(
        "--auto-close",
        dest="auto_close",
        action="store_true",
        help="GUI only: close the window after all queued files finish successfully.",
    )
    return parser


def _detect_explicit_args(argv_list: Sequence[str]) -> set:
    """Return the set of destination names the user passed explicitly.

    A fresh parser is built with every action default replaced by
    :data:`argparse.SUPPRESS` so the resulting namespace contains attributes only
    for arguments that actually appeared on the command line. This lets
    ``--preset`` fill in fields without clobbering flags the user set explicitly.
    """

    parser = _build_parser()
    for action in parser._actions:
        action.default = argparse.SUPPRESS
    namespace = parser.parse_args(list(argv_list))
    return set(vars(namespace).keys())


def _apply_preset_to_args(
    parsed_args: argparse.Namespace, preset: object, explicit: set
) -> None:
    """Apply *preset* fields onto *parsed_args* where not explicitly provided.

    Presets are sparse: a field the preset leaves unset (``None``) is skipped so
    it inherits the parser default or a stored preference instead of being forced.
    When present, resolution is expanded to the ``small``/``small_480`` tri-state
    so a preset can force ``--no-small``; each field is only written when the user
    did not pass the corresponding flag, preserving explicit-flag precedence.
    """

    resolution = getattr(preset, "resolution", None)
    if resolution is not None:
        if resolution == "1080p":
            small, small_480 = False, False
        elif resolution == "480p":
            small, small_480 = True, True
        else:  # "720p" and any unexpected value.
            small, small_480 = True, False

        if "small" not in explicit:
            parsed_args.small = small
        if "small_480" not in explicit:
            # ``small_480`` is only meaningful alongside ``small``; when the
            # effective small flag is off (e.g. an explicit ``--no-small``
            # overriding a 480p preset) never leave 480p scaling on, or the output
            # name gains a stray ``480`` marker with no rescale behind it.
            parsed_args.small_480 = small_480 and bool(
                getattr(parsed_args, "small", small)
            )

    if (
        getattr(preset, "silent_speed", None) is not None
        and "silent_speed" not in explicit
    ):
        parsed_args.silent_speed = float(preset.silent_speed)
    if (
        getattr(preset, "sounded_speed", None) is not None
        and "sounded_speed" not in explicit
    ):
        parsed_args.sounded_speed = float(preset.sounded_speed)
    if (
        getattr(preset, "silent_threshold", None) is not None
        and "silent_threshold" not in explicit
    ):
        parsed_args.silent_threshold = float(preset.silent_threshold)
    if (
        getattr(preset, "video_codec", None) is not None
        and "video_codec" not in explicit
    ):
        parsed_args.video_codec = str(preset.video_codec)


def gather_input_files(
    paths: List[str], *, allow_audio_only: bool = False
) -> List[str]:
    """Expand provided paths into a flat list of processable media files.

    By default only files that contain a video stream are collected. When
    ``allow_audio_only`` is True (e.g. the mp3 codec is selected) audio-only
    files such as ``.m4a`` are also accepted as long as they carry an audio
    stream.
    """

    def _is_accepted(candidate: str) -> bool:
        if audio.is_valid_video_file(candidate):
            return True
        return allow_audio_only and audio.is_valid_input_file(candidate)

    files: List[str] = []
    for input_path in paths:
        if os.path.isfile(input_path) and _is_accepted(input_path):
            files.append(os.path.abspath(input_path))
        elif os.path.isdir(input_path):
            for file in os.listdir(input_path):
                candidate = os.path.join(input_path, file)
                if _is_accepted(candidate):
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

        cut_start = float(getattr(parsed_args, "cut_start_seconds", 0.0) or 0.0)
        cut_end = float(getattr(parsed_args, "cut_end_seconds", 0.0) or 0.0)
        if cut_end and cut_end <= cut_start:
            return 1, [
                "Error: --cut-end must be greater than --cut-start "
                f"(got --cut-start {cut_start:g}, --cut-end {cut_end:g})."
            ]

        allow_audio_only = (
            str(getattr(parsed_args, "video_codec", "") or "").strip().lower() == "mp3"
        )
        files = self._gather_files(
            parsed_args.input_file, allow_audio_only=allow_audio_only
        )

        # Check if any files were found
        if not files:
            media_kind = "media" if allow_audio_only else "video"
            error_messages: List[str] = []
            for input_path in parsed_args.input_file:
                if os.path.isfile(input_path):
                    # File exists but was rejected - check if it's a valid input.
                    accepted = audio.is_valid_video_file(input_path) or (
                        allow_audio_only and audio.is_valid_input_file(input_path)
                    )
                    if not accepted:
                        error_messages.append(
                            f"Error: '{input_path}' is not a valid {media_kind} file."
                        )
                    else:
                        error_messages.append(
                            f"Error: '{input_path}' could not be processed."
                        )
                elif os.path.isdir(input_path):
                    error_messages.append(
                        f"Error: No valid {media_kind} files found in '{input_path}'."
                    )
                else:
                    error_messages.append(
                        f"Error: '{input_path}' does not exist or is not accessible."
                    )
            return 1, error_messages

        args: Dict[str, object] = {
            key: value for key, value in vars(parsed_args).items() if value is not None
        }
        del args["input_file"]

        if "host" in args:
            del args["host"]

        if len(files) > 1 and "output_file" in args:
            del args["output_file"]

        if getattr(parsed_args, "small_480", False) and not getattr(
            parsed_args, "small", False
        ):
            print(
                "Warning: --480 has no effect unless --small is also provided.",
                file=sys.stderr,
            )

        error_messages = []
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
            if "keyframe_interval_seconds" in local_options:
                option_kwargs["keyframe_interval_seconds"] = float(
                    local_options["keyframe_interval_seconds"]
                )
            if "video_codec" in local_options:
                option_kwargs["video_codec"] = str(local_options["video_codec"])
            if local_options.get("add_codec_suffix"):
                option_kwargs["add_codec_suffix"] = True
            if "optimize" in local_options:
                option_kwargs["optimize"] = bool(local_options["optimize"])
            if "small" in local_options:
                option_kwargs["small"] = bool(local_options["small"])
            if local_options.get("small_480"):
                option_kwargs["small_target_height"] = 480
            if "prefer_global_ffmpeg" in local_options:
                option_kwargs["prefer_global_ffmpeg"] = bool(
                    local_options["prefer_global_ffmpeg"]
                )
            if "cut_start_seconds" in local_options:
                option_kwargs["cut_start_seconds"] = float(
                    local_options["cut_start_seconds"]
                )
            if "cut_end_seconds" in local_options:
                option_kwargs["cut_end_seconds"] = float(
                    local_options["cut_end_seconds"]
                )
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
                time_str = f"time: {time_ratio * 100:.0f}%"
                output_duration = getattr(result, "output_duration", None)
                if output_duration:
                    mins, secs = divmod(int(round(output_duration)), 60)
                    time_str += f" ({mins}:{secs:02d})"
                summary_parts.append(time_str)
            if size_ratio is not None:
                size_str = f"size: {size_ratio * 100:.0f}%"
                if result.output_file.exists():
                    size_bytes = result.output_file.stat().st_size
                    value = float(size_bytes)
                    for unit in ("B", "KB", "MB", "GB"):
                        if abs(value) < 1024:
                            size_label = (
                                f"{value:.0f}{unit}"
                                if unit == "B"
                                else f"{value:.1f}{unit}"
                            )
                            break
                        value /= 1024
                    else:
                        size_label = f"{value:.1f}TB"
                    size_str += f" ({size_label})"
                summary_parts.append(size_str)
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

        remote_option_values: Dict[str, object] = {}
        if parsed_args.silent_threshold is not None:
            remote_option_values["silent_threshold"] = float(
                parsed_args.silent_threshold
            )
        if parsed_args.silent_speed is not None:
            remote_option_values["silent_speed"] = float(parsed_args.silent_speed)
        if parsed_args.sounded_speed is not None:
            remote_option_values["sounded_speed"] = float(parsed_args.sounded_speed)
        if getattr(parsed_args, "video_codec", None):
            remote_option_values["video_codec"] = str(parsed_args.video_codec)
        if getattr(parsed_args, "add_codec_suffix", False):
            remote_option_values["add_codec_suffix"] = True
        if getattr(parsed_args, "prefer_global_ffmpeg", False):
            remote_option_values["prefer_global_ffmpeg"] = True
        if getattr(parsed_args, "optimize", True) is False:
            remote_option_values["optimize"] = False
        cut_start_value = float(getattr(parsed_args, "cut_start_seconds", 0.0) or 0.0)
        cut_end_value = float(getattr(parsed_args, "cut_end_seconds", 0.0) or 0.0)
        if cut_start_value > 0.0 or cut_end_value > 0.0:
            remote_option_values["cut_enabled"] = True
            remote_option_values["cut_start_seconds"] = cut_start_value
            remote_option_values["cut_end_seconds"] = cut_end_value

        unsupported_options: List[str] = []
        for name in (
            "frame_spreadage",
            "sample_rate",
            "temp_folder",
            "keyframe_interval_seconds",
        ):
            if getattr(parsed_args, name) is not None:
                unsupported_options.append(f"--{name.replace('_', '-')}")

        if unsupported_options:
            print(
                "Warning: the following options are ignored when using --url: "
                + ", ".join(sorted(unsupported_options)),
                file=sys.stderr,
            )

        small_480_mode = bool(getattr(parsed_args, "small_480", False)) and bool(
            getattr(parsed_args, "small", False)
        )
        if small_480_mode:
            remote_option_values["small_480"] = True

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
                    small_480=small_480_mode,
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


def _launch_dock_server(argv: Sequence[str]) -> bool:
    """Launch the OBS processing dock HTTP server in-process."""

    try:
        dock_module = import_module(".dock_server", __package__)
    except ImportError:
        return False

    dock_main = getattr(dock_module, "main", None)
    if dock_main is None:
        return False

    dock_main(list(argv))
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

    if argv_list and argv_list[0] in {"server-tray", "serve-tray"}:
        if not _launch_server_tray(argv_list[1:]):
            print("Server tray mode is unavailable.", file=sys.stderr)
            sys.exit(1)
        return

    if argv_list and argv_list[0] in {"server", "serve"}:
        if not _launch_server(argv_list[1:]):
            print("Gradio server mode is unavailable.", file=sys.stderr)
            sys.exit(1)
        return

    if argv_list and argv_list[0] in {"dock-server", "obs-dock"}:
        if not _launch_dock_server(argv_list[1:]):
            print("Dock server mode is unavailable.", file=sys.stderr)
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

    preset_name = getattr(parsed_args, "preset", None)
    if preset_name:
        from . import presets as presets_module

        loaded = presets_module.load_presets()
        preset = presets_module.find_preset(preset_name, loaded)
        if preset is None:
            valid = ", ".join(item.name for item in loaded) or "(none)"
            parser.error(f"unknown preset '{preset_name}'. Valid presets: {valid}")
        explicit = _detect_explicit_args(argv_list)
        _apply_preset_to_args(parsed_args, preset, explicit)

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
