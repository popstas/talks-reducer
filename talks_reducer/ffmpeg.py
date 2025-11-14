"""Utilities for discovering and invoking FFmpeg commands."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from shutil import which as _shutil_which
from typing import List, Optional, Sequence, Tuple

from .progress import ProgressReporter, TqdmProgressReporter


class FFmpegNotFoundError(RuntimeError):
    """Raised when FFmpeg cannot be located on the current machine."""


def shutil_which(cmd: str) -> Optional[str]:
    """Wrapper around :func:`shutil.which` for easier testing."""

    return _shutil_which(cmd)


def _search_known_paths(paths: List[str]) -> Optional[str]:
    """Return the first existing FFmpeg path from *paths*."""

    for path in paths:
        if os.path.isfile(path) or shutil_which(path):
            return os.path.abspath(path) if os.path.isfile(path) else path

    return None


def _find_static_ffmpeg() -> Optional[str]:
    """Return the FFmpeg path bundled with static-ffmpeg when available."""

    try:
        import static_ffmpeg

        static_ffmpeg.add_paths()
        bundled_path = shutil_which("ffmpeg")
        if bundled_path:
            return bundled_path
    except ImportError:
        return None
    except Exception:
        return None

    return None


def find_ffmpeg(*, prefer_global: bool = False) -> Optional[str]:
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
        "/usr/local/bin/ffmpeg",
        "/opt/homebrew/bin/ffmpeg",
        "/usr/bin/ffmpeg",
        "ffmpeg",
    ]

    static_path: Optional[str] = None
    if not prefer_global:
        static_path = _find_static_ffmpeg()
        if static_path:
            return static_path

    candidate = _search_known_paths(common_paths)
    if candidate:
        return candidate

    if prefer_global:
        static_path = _find_static_ffmpeg()
        if static_path:
            return static_path

    return None


def find_ffprobe(*, prefer_global: bool = False) -> Optional[str]:
    """Locate the ffprobe executable, typically in the same directory as FFmpeg."""

    env_override = os.environ.get("TALKS_REDUCER_FFPROBE") or os.environ.get(
        "FFPROBE_PATH"
    )
    if env_override and (os.path.isfile(env_override) or shutil_which(env_override)):
        return (
            os.path.abspath(env_override)
            if os.path.isfile(env_override)
            else env_override
        )

    # Try to find ffprobe in the same directory as FFmpeg
    ffmpeg_path = find_ffmpeg(prefer_global=prefer_global)
    if ffmpeg_path:
        ffmpeg_dir = os.path.dirname(ffmpeg_path)
        ffprobe_path = os.path.join(ffmpeg_dir, "ffprobe")
        if os.path.isfile(ffprobe_path) or shutil_which(ffprobe_path):
            return (
                os.path.abspath(ffprobe_path)
                if os.path.isfile(ffprobe_path)
                else ffprobe_path
            )

    # Fallback to common locations
    common_paths = [
        "C:\\ProgramData\\chocolatey\\bin\\ffprobe.exe",
        "C:\\Program Files\\ffmpeg\\bin\\ffprobe.exe",
        "C:\\ffmpeg\\bin\\ffprobe.exe",
        "/usr/local/bin/ffprobe",
        "/opt/homebrew/bin/ffprobe",
        "/usr/bin/ffprobe",
        "ffprobe",
    ]

    static_path: Optional[str] = None
    if not prefer_global:
        static_path = _find_static_ffmpeg()
        if static_path:
            ffprobe_candidate = os.path.join(os.path.dirname(static_path), "ffprobe")
            if os.path.isfile(ffprobe_candidate) or shutil_which(ffprobe_candidate):
                return (
                    os.path.abspath(ffprobe_candidate)
                    if os.path.isfile(ffprobe_candidate)
                    else ffprobe_candidate
                )

    candidate = _search_known_paths(common_paths)
    if candidate:
        return candidate

    if prefer_global:
        static_path = _find_static_ffmpeg()
        if static_path:
            ffprobe_candidate = os.path.join(os.path.dirname(static_path), "ffprobe")
            if os.path.isfile(ffprobe_candidate) or shutil_which(ffprobe_candidate):
                return (
                    os.path.abspath(ffprobe_candidate)
                    if os.path.isfile(ffprobe_candidate)
                    else ffprobe_candidate
                )

    return None


def _resolve_ffmpeg_path(*, prefer_global: bool = False) -> str:
    """Resolve the FFmpeg executable path or raise ``FFmpegNotFoundError``."""

    ffmpeg_path = find_ffmpeg(prefer_global=prefer_global)
    if not ffmpeg_path:
        raise FFmpegNotFoundError(
            "FFmpeg not found. Please install static-ffmpeg (pip install static-ffmpeg) "
            "or install FFmpeg manually and add it to PATH, or set TALKS_REDUCER_FFMPEG environment variable."
        )

    print(f"Using FFmpeg at: {ffmpeg_path}")
    return ffmpeg_path


def _resolve_ffprobe_path(*, prefer_global: bool = False) -> str:
    """Resolve the ffprobe executable path or raise ``FFmpegNotFoundError``."""

    ffprobe_path = find_ffprobe(prefer_global=prefer_global)
    if not ffprobe_path:
        raise FFmpegNotFoundError(
            "ffprobe not found. Install FFmpeg (which includes ffprobe) and add it to PATH."
        )

    return ffprobe_path


_FFMPEG_PATH_CACHE: dict[bool, Optional[str]] = {False: None, True: None}
_FFPROBE_PATH_CACHE: dict[bool, Optional[str]] = {False: None, True: None}
_GLOBAL_FFMPEG_AVAILABLE: Optional[bool] = None


def get_ffmpeg_path(prefer_global: bool = False) -> str:
    """Return the cached FFmpeg path, resolving it on first use."""

    cached = _FFMPEG_PATH_CACHE.get(prefer_global)
    if cached is None:
        cached = _resolve_ffmpeg_path(prefer_global=prefer_global)
        _FFMPEG_PATH_CACHE[prefer_global] = cached
    return cached


def get_ffprobe_path(prefer_global: bool = False) -> str:
    """Return the cached ffprobe path, resolving it on first use."""

    cached = _FFPROBE_PATH_CACHE.get(prefer_global)
    if cached is None:
        cached = _resolve_ffprobe_path(prefer_global=prefer_global)
        _FFPROBE_PATH_CACHE[prefer_global] = cached
    return cached


def _normalize_executable_path(candidate: Optional[str]) -> Optional[str]:
    """Return an absolute path for *candidate* when it can be resolved."""

    if not candidate:
        return None

    if os.path.isfile(candidate):
        return os.path.abspath(candidate)

    resolved = shutil_which(candidate)
    if resolved:
        return os.path.abspath(resolved)

    return os.path.abspath(candidate) if os.path.exists(candidate) else None


def is_global_ffmpeg_available() -> bool:
    """Return ``True`` when a non-bundled FFmpeg binary is available."""

    global _GLOBAL_FFMPEG_AVAILABLE
    if _GLOBAL_FFMPEG_AVAILABLE is not None:
        return _GLOBAL_FFMPEG_AVAILABLE

    global_candidate = _normalize_executable_path(find_ffmpeg(prefer_global=True))
    if not global_candidate:
        _GLOBAL_FFMPEG_AVAILABLE = False
        return False

    static_candidate = _normalize_executable_path(_find_static_ffmpeg())
    if static_candidate is None:
        _GLOBAL_FFMPEG_AVAILABLE = True
        return True

    try:
        same_binary = os.path.samefile(global_candidate, static_candidate)
    except (FileNotFoundError, OSError, ValueError):
        same_binary = os.path.normcase(global_candidate) == os.path.normcase(
            static_candidate
        )

    _GLOBAL_FFMPEG_AVAILABLE = not same_binary
    return _GLOBAL_FFMPEG_AVAILABLE


_ENCODER_LISTING: dict[str, str] = {}


def _probe_ffmpeg_output(args: List[str]) -> Optional[str]:
    """Return stdout from an FFmpeg invocation, handling common failures."""

    creationflags = 0
    if sys.platform == "win32":
        # CREATE_NO_WINDOW = 0x08000000
        creationflags = 0x08000000

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=creationflags,
        )
    except (
        subprocess.TimeoutExpired,
        subprocess.CalledProcessError,
        FileNotFoundError,
    ):
        return None

    if result.returncode != 0:
        return None

    return result.stdout


def _get_encoder_listing(ffmpeg_path: Optional[str] = None) -> Optional[str]:
    """Return the cached FFmpeg encoder listing output."""

    ffmpeg_path = ffmpeg_path or get_ffmpeg_path()
    cache_key = os.path.abspath(ffmpeg_path)
    if cache_key in _ENCODER_LISTING:
        return _ENCODER_LISTING[cache_key]

    output = _probe_ffmpeg_output([ffmpeg_path, "-hide_banner", "-encoders"])
    if output is None:
        return None

    normalized = output.lower()
    _ENCODER_LISTING[cache_key] = normalized
    return normalized


def encoder_available(encoder_name: str, ffmpeg_path: Optional[str] = None) -> bool:
    """Return True if ``encoder_name`` is listed in the FFmpeg encoder catalog."""

    listing = _get_encoder_listing(ffmpeg_path)
    if not listing:
        return False

    pattern = rf"\b{re.escape(encoder_name.lower())}\b"
    return re.search(pattern, listing) is not None


def check_cuda_available(ffmpeg_path: Optional[str] = None) -> bool:
    """Return whether CUDA hardware encoders are usable in the FFmpeg build."""

    ffmpeg_path = ffmpeg_path or get_ffmpeg_path()

    hwaccels_output = _probe_ffmpeg_output([ffmpeg_path, "-hide_banner", "-hwaccels"])
    if not hwaccels_output or "cuda" not in hwaccels_output.lower():
        return False

    encoder_output = _get_encoder_listing(ffmpeg_path)
    if not encoder_output:
        return False

    return any(
        encoder in encoder_output
        for encoder in ["h264_nvenc", "hevc_nvenc", "av1_nvenc", "nvenc"]
    )


def run_timed_ffmpeg_command(
    command: str,
    *,
    reporter: Optional[ProgressReporter] = None,
    desc: str = "",
    total: Optional[int] = None,
    unit: str = "frames",
    process_callback: Optional[callable] = None,
) -> None:
    """Execute an FFmpeg command while streaming progress information.

    Args:
        process_callback: Optional callback that receives the subprocess.Popen object
    """

    import shlex

    try:
        args = shlex.split(command)
    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"Error parsing command: {exc}", file=sys.stderr)
        raise

    # Hide console window on Windows
    creationflags = 0
    if sys.platform == "win32":
        # CREATE_NO_WINDOW = 0x08000000
        creationflags = 0x08000000

    try:
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            bufsize=1,
            errors="replace",
            creationflags=creationflags,
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"Error starting FFmpeg: {exc}", file=sys.stderr)
        raise

    # Notify callback with process object
    if process_callback:
        process_callback(process)

    progress_reporter = reporter or TqdmProgressReporter()
    task_manager = progress_reporter.task(desc=desc, total=total, unit=unit)
    with task_manager as progress:
        while True:
            line = process.stderr.readline()
            if not line and process.poll() is not None:
                break

            if not line:
                continue

            # Filter out excessive progress output, only show important lines
            if any(
                keyword in line.lower()
                for keyword in [
                    "error",
                    "warning",
                    "encoded successfully",
                    "frame=",
                    "time=",
                    "size=",
                    "bitrate=",
                    "speed=",
                ]
            ):
                sys.stderr.write(line)
                sys.stderr.flush()

            # Send FFmpeg output to reporter for GUI display (filtered)
            if any(
                keyword in line.lower()
                for keyword in ["error", "warning", "encoded successfully", "frame="]
            ):
                progress_reporter.log(line.strip())

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
    audio_file: Optional[str],
    filter_script: Optional[str],
    output_file: str,
    *,
    ffmpeg_path: Optional[str] = None,
    cuda_available: bool,
    optimize: bool,
    small: bool,
    frame_rate: Optional[float] = None,
    keyframe_interval_seconds: float = 30.0,
    video_codec: str = "hevc",
) -> Tuple[str, Optional[str], bool]:
    """Create the FFmpeg command strings used to render the final video output.

    Args:
        input_file: Path to the input video file.
        audio_file: Optional path to the processed audio file. If None, video will be encoded without audio.
        filter_script: Optional path to the filter script file. If None, video will be re-encoded without speed modification.
        output_file: Path to the output video file.
        frame_rate: Optional source frame rate used to size GOP/keyframe spacing for
            the small preset when generating hardware/software encoder commands.
    """

    ffmpeg_path = ffmpeg_path or get_ffmpeg_path()
    global_parts: List[str] = [f'"{ffmpeg_path}"', "-y"]
    hwaccel_args: List[str] = []

    if cuda_available and not small:
        hwaccel_args = ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
        global_parts.extend(hwaccel_args)

    input_parts = [f'-i "{input_file}"']
    if audio_file:
        input_parts.append(f'-i "{audio_file}"')

    output_parts: List[str] = []
    if audio_file:
        output_parts.append("-map 0:v:0 -map 1:a")
    else:
        output_parts.append("-map 0:v:0")

    if filter_script:
        output_parts.append(f'-filter_script:v "{filter_script}"')

    codec_choice = (video_codec or "hevc").strip().lower()
    if codec_choice not in {"h264", "hevc", "av1"}:
        codec_choice = "hevc"

    video_encoder_args: List[str]
    fallback_encoder_args: List[str] = []
    use_cuda_encoder = False

    keyframe_args: List[str] = []
    quality_profile = "optimized"
    if optimize:
        if keyframe_interval_seconds <= 0:
            keyframe_interval_seconds = 30.0
        formatted_interval = f"{keyframe_interval_seconds:.6g}"
        gop_size = 900
        if frame_rate and frame_rate > 0:
            gop_size = max(1, int(round(frame_rate * keyframe_interval_seconds)))
        keyframe_args = [
            f"-g {gop_size}",
            f"-keyint_min {gop_size}",
            f"-force_key_frames expr:gte(t,n_forced*{formatted_interval})",
        ]
    else:
        if not small:
            global_parts.append("-filter_complex_threads 1")
            quality_profile = "fast"

    def resolve_encoder_plan(
        *,
        prefer_cuda: bool,
        codec: str,
        extra_keyframe_args: Sequence[str],
        profile: str,
    ) -> Tuple[List[str], List[str], bool]:
        primary_args: List[str]
        fallback_args: List[str] = []
        uses_cuda = False

        if codec == "av1":
            if encoder_available("libsvtav1", ffmpeg_path=ffmpeg_path):
                cpu_encoder_base = ["-c:v libsvtav1", "-preset 6", "-crf 28", "-b:v 0"]
            else:
                cpu_encoder_base = ["-c:v libaom-av1", "-crf 32", "-b:v 0", "-row-mt 1"]

            if profile == "fast":
                cpu_encoder_args = cpu_encoder_base + list(extra_keyframe_args)
                if encoder_available("libaom-av1", ffmpeg_path=ffmpeg_path):
                    cpu_encoder_args = [
                        "-c:v libaom-av1",
                        "-crf 38",
                        "-b:v 0",
                        "-cpu-used 6",
                        "-row-mt 1",
                    ] + list(extra_keyframe_args)
            else:
                cpu_encoder_args = cpu_encoder_base + list(extra_keyframe_args)

            primary_args = cpu_encoder_args

            if prefer_cuda and encoder_available("av1_nvenc", ffmpeg_path=ffmpeg_path):
                uses_cuda = True
                if profile == "fast":
                    primary_args = [
                        "-c:v av1_nvenc",
                        "-preset p1",
                        "-rc constqp",
                        "-qp 32",
                    ] + list(extra_keyframe_args)
                else:
                    primary_args = [
                        "-c:v av1_nvenc",
                        "-preset p6",
                        "-rc vbr",
                        "-b:v 0",
                        "-cq 36",
                        "-spatial-aq 1",
                        "-temporal-aq 1",
                    ] + list(extra_keyframe_args)
                fallback_args = cpu_encoder_args
        elif codec == "hevc":
            if profile == "fast":
                cpu_encoder_args = [
                    "-c:v libx265",
                    "-preset ultrafast",
                    "-crf 30",
                ] + list(extra_keyframe_args)
            else:
                cpu_encoder_args = [
                    "-c:v libx265",
                    "-preset medium",
                    "-crf 28",
                ] + list(extra_keyframe_args)

            primary_args = cpu_encoder_args
            if prefer_cuda and encoder_available("hevc_nvenc", ffmpeg_path=ffmpeg_path):
                uses_cuda = True
                if profile == "fast":
                    primary_args = [
                        "-c:v hevc_nvenc",
                        "-preset p1",
                        "-rc constqp",
                        "-qp 28",
                    ] + list(extra_keyframe_args)
                else:
                    primary_args = [
                        "-c:v hevc_nvenc",
                        "-preset p6",
                        "-rc vbr",
                        "-b:v 0",
                        "-cq 32",
                        "-spatial-aq 1",
                        "-temporal-aq 1",
                        "-rc-lookahead 32",
                        "-multipass fullres",
                    ] + list(extra_keyframe_args)
                fallback_args = cpu_encoder_args
        else:
            if profile == "fast":
                cpu_encoder_args = [
                    "-c:v libx264",
                    "-preset ultrafast",
                    "-crf 24",
                ] + list(extra_keyframe_args)
            else:
                cpu_encoder_args = [
                    "-c:v libx264",
                    "-preset veryfast",
                    "-crf 24",
                    "-tune",
                    "zerolatency",
                ] + list(extra_keyframe_args)

            primary_args = cpu_encoder_args
            if prefer_cuda:
                uses_cuda = True
                if profile == "fast":
                    primary_args = [
                        "-c:v h264_nvenc",
                        "-preset p1",
                        "-rc constqp",
                        "-qp 23",
                    ] + list(extra_keyframe_args)
                else:
                    primary_args = [
                        "-c:v h264_nvenc",
                        "-preset p1",
                        "-cq 28",
                        "-tune",
                        "ll",
                        "-forced-idr 1",
                    ] + list(extra_keyframe_args)
                fallback_args = cpu_encoder_args

        return primary_args, fallback_args, uses_cuda

    primary_plan, primary_fallback, primary_uses_cuda = resolve_encoder_plan(
        prefer_cuda=cuda_available,
        codec=codec_choice,
        extra_keyframe_args=keyframe_args,
        profile=quality_profile,
    )

    video_encoder_args = primary_plan
    fallback_encoder_args = primary_fallback
    use_cuda_encoder = primary_uses_cuda

    audio_parts: List[str] = []
    if audio_file:
        audio_parts.append("-c:a aac")
    else:
        audio_parts.append("-an")  # No audio

    audio_parts.extend([
        f'"{output_file}"',
        "-loglevel warning -stats -hide_banner",
    ])

    full_command_parts = (
        global_parts + input_parts + output_parts + video_encoder_args + audio_parts
    )
    command_str = " ".join(full_command_parts)

    fallback_command_str: Optional[str] = None
    if fallback_encoder_args:
        fallback_global_parts = list(global_parts)
        if hwaccel_args:
            fallback_global_parts = [
                part for part in fallback_global_parts if part not in hwaccel_args
            ]
        fallback_parts = (
            fallback_global_parts
            + input_parts
            + output_parts
            + fallback_encoder_args
            + audio_parts
        )
        fallback_command_str = " ".join(fallback_parts)

    return command_str, fallback_command_str, use_cuda_encoder


__all__ = [
    "FFmpegNotFoundError",
    "find_ffmpeg",
    "find_ffprobe",
    "get_ffmpeg_path",
    "get_ffprobe_path",
    "check_cuda_available",
    "run_timed_ffmpeg_command",
    "build_extract_audio_command",
    "build_video_commands",
    "shutil_which",
]
