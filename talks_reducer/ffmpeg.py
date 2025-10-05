"""Utilities for discovering and invoking FFmpeg commands."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from typing import List, Optional, Tuple

from .progress import ProgressReporter, TqdmProgressReporter


class FFmpegNotFoundError(RuntimeError):
    """Raised when FFmpeg cannot be located on the current machine."""


def find_ffmpeg() -> Optional[str]:
    """Locate the FFmpeg executable in common installation locations."""

    env_override = os.environ.get("TALKS_REDUCER_FFMPEG") or os.environ.get(
        "FFMPEG_PATH"
    )
    if env_override and (os.path.isfile(env_override) or shutil_which(env_override)):
        return (
            os.path.abspath(env_override)
            if os.path.isfile(env_override)
            else env_override
        )

    common_paths = [
        "C:\\ProgramData\\chocolatey\\bin\\ffmpeg.exe",
        "C:\\Program Files\\ffmpeg\\bin\\ffmpeg.exe",
        "C:\\ffmpeg\\bin\\ffmpeg.exe",
        "ffmpeg",
    ]

    for path in common_paths:
        if os.path.isfile(path) or shutil_which(path):
            return os.path.abspath(path) if os.path.isfile(path) else path

    return None


def _resolve_ffmpeg_path() -> str:
    """Resolve the FFmpeg executable path or raise ``FFmpegNotFoundError``."""

    ffmpeg_path = find_ffmpeg()
    if not ffmpeg_path:
        raise FFmpegNotFoundError(
            "FFmpeg not found. Install FFmpeg and add it to PATH or provide TALKS_REDUCER_FFMPEG."
        )

    print(f"Using FFmpeg at: {ffmpeg_path}")
    return ffmpeg_path


_FFMPEG_PATH: Optional[str] = None


def get_ffmpeg_path() -> str:
    """Return the cached FFmpeg path, resolving it on first use."""

    global _FFMPEG_PATH
    if _FFMPEG_PATH is None:
        _FFMPEG_PATH = _resolve_ffmpeg_path()
    return _FFMPEG_PATH


def check_cuda_available(ffmpeg_path: Optional[str] = None) -> bool:
    """Return whether CUDA hardware encoders are available in the FFmpeg build."""

    try:
        ffmpeg_path = ffmpeg_path or get_ffmpeg_path()
        result = subprocess.run(
            [ffmpeg_path, "-encoders"], capture_output=True, text=True, timeout=5
        )
    except (
        subprocess.TimeoutExpired,
        subprocess.CalledProcessError,
        FileNotFoundError,
    ):
        return False

    if result.returncode != 0:
        return False

    encoder_list = result.stdout.lower()
    return any(
        encoder in encoder_list for encoder in ["h264_nvenc", "hevc_nvenc", "nvenc"]
    )


def run_timed_ffmpeg_command(
    command: str,
    *,
    reporter: Optional[ProgressReporter] = None,
    desc: str = "",
    total: Optional[int] = None,
    unit: str = "frames",
) -> None:
    """Execute an FFmpeg command while streaming progress information."""

    import shlex

    try:
        args = shlex.split(command)
    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"Error parsing command: {exc}", file=sys.stderr)
        raise

    try:
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            bufsize=1,
            errors="replace",
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"Error starting FFmpeg: {exc}", file=sys.stderr)
        raise

    progress_reporter = reporter or TqdmProgressReporter()
    task_manager = progress_reporter.task(desc=desc, total=total, unit=unit)
    with task_manager as progress:
        while True:
            line = process.stderr.readline()
            if not line and process.poll() is not None:
                break

            if not line:
                continue

            sys.stderr.write(line)
            sys.stderr.flush()

            match = re.search(r"frame=\s*(\d+)", line)
            if match:
                try:
                    new_frame = int(match.group(1))
                    progress.ensure_total(new_frame)
                    progress.advance(new_frame - progress.current)
                except (ValueError, IndexError):
                    pass

        process.wait()

        if process.returncode != 0:
            error_output = process.stderr.read()
            print(
                f"\nFFmpeg error (return code {process.returncode}):", file=sys.stderr
            )
            print(error_output, file=sys.stderr)
            raise subprocess.CalledProcessError(process.returncode, args)

        progress.finish()


def build_extract_audio_command(
    input_file: str,
    output_wav: str,
    sample_rate: int,
    audio_bitrate: str,
    hwaccel: Optional[List[str]] = None,
    ffmpeg_path: Optional[str] = None,
) -> str:
    """Build the FFmpeg command used to extract audio into a temporary WAV file."""

    hwaccel = hwaccel or []
    ffmpeg_path = ffmpeg_path or get_ffmpeg_path()
    command_parts: List[str] = [f'"{ffmpeg_path}"']
    command_parts.extend(hwaccel)
    command_parts.extend(
        [
            f'-i "{input_file}"',
            f"-ab {audio_bitrate} -ac 2",
            f"-ar {sample_rate}",
            "-vn",
            f'"{output_wav}"',
            "-hide_banner -loglevel warning -stats",
        ]
    )
    return " ".join(command_parts)


def build_video_commands(
    input_file: str,
    audio_file: str,
    filter_script: str,
    output_file: str,
    *,
    ffmpeg_path: Optional[str] = None,
    cuda_available: bool,
    small: bool,
) -> Tuple[str, Optional[str], bool]:
    """Create the FFmpeg command strings used to render the final video output."""

    ffmpeg_path = ffmpeg_path or get_ffmpeg_path()
    global_parts: List[str] = [f'"{ffmpeg_path}"', "-y"]
    hwaccel_args: List[str] = []

    if cuda_available and not small:
        hwaccel_args = ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
        global_parts.extend(hwaccel_args)
    elif small and cuda_available:
        pass

    input_parts = [f'-i "{input_file}"', f'-i "{audio_file}"']

    output_parts = [
        "-map 0 -map -0:a -map 1:a",
        f'-filter_script:v "{filter_script}"',
    ]

    video_encoder_args: List[str]
    fallback_encoder_args: List[str] = []
    use_cuda_encoder = False

    if small:
        if cuda_available:
            use_cuda_encoder = True
            video_encoder_args = [
                "-c:v h264_nvenc",
                "-preset p1",
                "-cq 28",
                "-tune",
                "ll",
            ]
            fallback_encoder_args = [
                "-c:v libx264",
                "-preset veryfast",
                "-crf 24",
                "-tune",
                "zerolatency",
            ]
        else:
            video_encoder_args = [
                "-c:v libx264",
                "-preset veryfast",
                "-crf 24",
                "-tune",
                "zerolatency",
            ]
    else:
        global_parts.append("-filter_complex_threads 1")
        if cuda_available:
            video_encoder_args = ["-c:v h264_nvenc"]
            use_cuda_encoder = True
        else:
            video_encoder_args = ["-c:v copy"]

    audio_parts = ["-c:a aac", f'"{output_file}"', "-loglevel info -stats -hide_banner"]

    full_command_parts = (
        global_parts + input_parts + output_parts + video_encoder_args + audio_parts
    )
    command_str = " ".join(full_command_parts)

    fallback_command_str: Optional[str] = None
    if fallback_encoder_args:
        fallback_parts = (
            global_parts
            + input_parts
            + output_parts
            + fallback_encoder_args
            + audio_parts
        )
        fallback_command_str = " ".join(fallback_parts)

    return command_str, fallback_command_str, use_cuda_encoder


def shutil_which(cmd: str) -> Optional[str]:
    """Wrapper around :func:`shutil.which` for easier testing."""

    from shutil import which as _which

    return _which(cmd)
