"""Command line interface for the talks reducer package."""

from __future__ import annotations

import argparse
import os
import time
from typing import Dict, List

from . import audio
from .pipeline import speed_up_video


def _build_parser() -> argparse.ArgumentParser:
    """Create the argument parser used by the command line interface."""

    parser = argparse.ArgumentParser(
        description="Modifies a video file to play at different speeds when there is sound vs. silence.",
    )
    parser.add_argument(
        "-i",
        "--input_file",
        type=str,
        dest="input_file",
        nargs="+",
        required=True,
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
        default="TEMP",
        help="The file path of the temporary working folder.",
    )
    parser.add_argument(
        "-t",
        "--silent_threshold",
        type=float,
        dest="silent_threshold",
        help="The volume amount that frames' audio needs to surpass to be considered sounded. Defaults to 0.03.",
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
    return parser


def _gather_input_files(paths: List[str]) -> List[str]:
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


def main() -> None:
    """Entry point for the command line interface."""

    parser = _build_parser()
    parsed_args = parser.parse_args()
    start_time = time.time()

    files = _gather_input_files(parsed_args.input_file)

    args: Dict[str, object] = {
        k: v for k, v in vars(parsed_args).items() if v is not None
    }
    del args["input_file"]

    if len(files) > 1 and "output_file" in args:
        del args["output_file"]

    for index, file in enumerate(files):
        print(f"Processing file {index + 1}/{len(files)} '{os.path.basename(file)}'")
        local_options = dict(args)
        local_options["input_file"] = file
        local_options["small"] = bool(local_options.get("small", False))
        speed_up_video(**local_options)

    end_time = time.time()
    total_time = end_time - start_time
    hours, remainder = divmod(total_time, 3600)
    minutes, seconds = divmod(remainder, 60)
    print(f"\nTime: {int(hours)}h {int(minutes)}m {seconds:.2f}s")


if __name__ == "__main__":
    main()
