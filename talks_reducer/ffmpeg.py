"""Utilities for discovering and invoking FFmpeg commands."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from shutil import which as _shutil_which
from typing import List, NamedTuple, Optional, Sequence, Tuple

from . import config
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
_ENCODER_OPTIONS: dict[tuple[str, str], str] = {}

HARDWARE_BACKENDS = ("cuda", "amf", "qsv", "videotoolbox")
HARDWARE_BACKEND_LABELS = {
    "cuda": "CUDA",
    "amf": "AMF",
    "qsv": "QSV",
    "videotoolbox": "VideoToolbox",
}
HARDWARE_CACHE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60

# (fingerprint-or-path, codec) -> backend. Guarded by the lock because the GUI
# renders on a worker thread and the server can run several jobs at once.
_HARDWARE_BACKEND_CACHE: dict[tuple, Optional[str]] = {}
_HARDWARE_BACKEND_LOCK = threading.Lock()


def _hardware_cache_path() -> Path:
    """Return the settings file that stores the hardware detection cache."""

    return config.determine_config_path()


def _ffmpeg_fingerprint(ffmpeg_path: str) -> Optional[dict[str, object]]:
    """Identify the FFmpeg binary so a cached probe is dropped when it changes.

    Returns ``None`` when the binary cannot be stat'ed (for example a bare
    ``ffmpeg`` name); such runs keep their probe results in memory only.
    """

    try:
        resolved = os.path.abspath(ffmpeg_path)
        stat = os.stat(resolved)
    except OSError:
        return None
    return {"path": resolved, "size": stat.st_size, "mtime": int(stat.st_mtime)}


def _read_cached_backend(
    fingerprint: dict[str, object], codec: str, now: float
) -> Tuple[bool, Optional[str]]:
    """Return ``(hit, backend)`` for *codec* from the on-disk cache.

    A record only counts when it belongs to the same FFmpeg binary, names a
    known backend (or ``None`` for "no GPU"), and is younger than
    :data:`HARDWARE_CACHE_MAX_AGE_SECONDS`. Anything else is a miss.
    """

    settings = config.load_settings(_hardware_cache_path())
    entry = settings.get(config.HARDWARE_BACKEND_KEY)
    if not isinstance(entry, dict) or entry.get("ffmpeg") != fingerprint:
        return False, None
    codecs = entry.get("codecs")
    record = codecs.get(codec) if isinstance(codecs, dict) else None
    if not isinstance(record, dict) or "backend" not in record:
        return False, None

    backend = record["backend"]
    checked_at = record.get("checked_at")
    if backend is not None and backend not in HARDWARE_BACKENDS:
        return False, None
    if isinstance(checked_at, bool) or not isinstance(checked_at, (int, float)):
        return False, None
    if not 0 <= now - checked_at < HARDWARE_CACHE_MAX_AGE_SECONDS:
        return False, None
    return True, backend


def _write_cached_backend(
    fingerprint: dict[str, object], codec: str, record: Optional[dict[str, object]]
) -> bool:
    """Store *record* for *codec* on disk, or remove it when *record* is ``None``.

    The settings file is shared with the GUI and presets, so it is re-read
    strictly first and left untouched when that read fails — rewriting it from
    an empty dict would delete every other setting. An entry written for a
    different FFmpeg binary is replaced wholesale, since its other codec
    records describe that old binary.
    """

    path = _hardware_cache_path()
    try:
        settings = config.read_settings_strict(path)
    except config.SettingsReadError:
        return False

    entry = settings.get(config.HARDWARE_BACKEND_KEY)
    codecs: dict[str, object] = {}
    if (
        isinstance(entry, dict)
        and entry.get("ffmpeg") == fingerprint
        and isinstance(entry.get("codecs"), dict)
    ):
        codecs = dict(entry["codecs"])

    if record is None:
        if codec not in codecs:
            return True
        codecs.pop(codec)
    else:
        codecs[codec] = record

    settings[config.HARDWARE_BACKEND_KEY] = {"ffmpeg": fingerprint, "codecs": codecs}
    return config.save_settings(path, settings)


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
        OSError,
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


def encoder_supports_option(
    encoder_name: str, option: str, ffmpeg_path: Optional[str] = None
) -> bool:
    """Return True if *encoder_name* accepts ``-option`` in this FFmpeg build.

    Encoder options come and go between FFmpeg releases — ``-spatial_aq`` only
    reached the VideoToolbox encoders in 7.1, while ``static-ffmpeg`` still
    bundles 7.0 — and an unknown option makes FFmpeg reject the whole command
    line rather than ignore it. The per-encoder help output is cached because
    each probe spawns a process.
    """

    ffmpeg_path = ffmpeg_path or get_ffmpeg_path()
    cache_key = (os.path.abspath(ffmpeg_path), encoder_name.lower())
    listing = _ENCODER_OPTIONS.get(cache_key)
    if listing is None:
        output = _probe_ffmpeg_output(
            [ffmpeg_path, "-hide_banner", "-h", f"encoder={encoder_name}"]
        )
        if output is None:
            return False
        listing = output.lower()
        _ENCODER_OPTIONS[cache_key] = listing

    return (
        re.search(rf"^\s*-{re.escape(option.lower())}\b", listing, re.MULTILINE)
        is not None
    )


def check_cuda_available(ffmpeg_path: Optional[str] = None) -> bool:
    """Return whether NVENC can actually encode on this machine.

    Kept for callers outside the pipeline; it now delegates to the trial-encode
    detection, because the encoder listing alone reports NVENC on machines
    without an NVIDIA GPU.
    """

    return detect_hardware_backend("h264", ffmpeg_path) == "cuda"


def check_videotoolbox_available(ffmpeg_path: Optional[str] = None) -> bool:
    """Return whether Apple VideoToolbox encoders are usable in the FFmpeg build.

    VideoToolbox only exists on macOS, so the platform is checked first to avoid
    probing FFmpeg on systems that can never provide it.
    """

    if sys.platform != "darwin":
        return False

    ffmpeg_path = ffmpeg_path or get_ffmpeg_path()

    hwaccels_output = _probe_ffmpeg_output([ffmpeg_path, "-hide_banner", "-hwaccels"])
    if not hwaccels_output or "videotoolbox" not in hwaccels_output.lower():
        return False

    return any(
        encoder_available(encoder, ffmpeg_path=ffmpeg_path)
        for encoder in ("hevc_videotoolbox", "h264_videotoolbox")
    )


_HARDWARE_CANDIDATES = {
    # H.264 lists only NVENC: QSV, AMF and VideoToolbox H.264 stay on libx264
    # (see ``resolve_encoder_plan``), so probing them would cost time for nothing.
    "h264": ("cuda",),
    "hevc": ("cuda", "amf", "qsv", "videotoolbox"),
    # No Apple AV1 encoder exists.
    "av1": ("cuda", "amf", "qsv"),
}
_TRIAL_ENCODER_SUFFIXES = {"cuda": "nvenc", "amf": "amf", "qsv": "qsv"}
_TRIAL_ENCODE_TIMEOUT_SECONDS = 10


def normalize_video_codec(value: Optional[str]) -> str:
    """Return ``h264``, ``hevc`` or ``av1`` for a user-supplied codec name.

    Unknown values map to ``h264``, matching the encoder plan's default.
    """

    codec = (value or "h264").strip().lower()
    return codec if codec in _HARDWARE_CANDIDATES else "h264"


def _backend_supported_on_platform(backend: str) -> bool:
    """Return whether *backend* can exist on the current operating system."""

    if backend == "videotoolbox":
        return sys.platform == "darwin"
    return sys.platform == "win32" or sys.platform.startswith("linux")


def _trial_encode(ffmpeg_path: str, encoder: str) -> Optional[bool]:
    """Encode one tiny frame with *encoder* and report whether FFmpeg succeeded.

    Returns ``True`` when FFmpeg exits 0, ``False`` when it exits non-zero, and
    ``None`` when the trial could not run to completion (a timeout or a spawn
    error). ``None`` is inconclusive: a slow first driver start looks the same.

    The encoder listing is not a capability signal: the gyan.dev builds that
    ``static-ffmpeg`` bundles list every NVENC, AMF and QSV encoder whatever GPU
    is installed, and only fail once the encoder is opened.
    """

    creationflags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
    try:
        result = subprocess.run(
            [
                ffmpeg_path,
                "-hide_banner",
                "-v",
                "quiet",
                "-f",
                "lavfi",
                "-i",
                "color=black:size=256x144:duration=0.04",
                "-frames:v",
                "1",
                "-c:v",
                encoder,
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            timeout=_TRIAL_ENCODE_TIMEOUT_SECONDS,
            creationflags=creationflags,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    return result.returncode == 0


def _probe_backend(backend: str, codec: str, ffmpeg_path: str) -> Optional[bool]:
    """Return whether *backend* can encode *codec*: ``True``, ``False`` or ``None``.

    ``None`` means inconclusive, because the encoder listing or, for VideoToolbox,
    the ``-hwaccels`` listing could not be obtained, or the trial encode could not
    run. A listed encoder that fails its trial is a conclusive ``False``.
    """

    if not _backend_supported_on_platform(backend):
        return False
    if backend == "videotoolbox":
        if (
            _probe_ffmpeg_output([ffmpeg_path, "-hide_banner", "-hwaccels"]) is None
            or _get_encoder_listing(ffmpeg_path) is None
        ):
            return None
        return check_videotoolbox_available(ffmpeg_path)
    if _get_encoder_listing(ffmpeg_path) is None:
        return None
    encoder = f"{codec}_{_TRIAL_ENCODER_SUFFIXES[backend]}"
    if not encoder_available(encoder, ffmpeg_path=ffmpeg_path):
        return False
    return _trial_encode(ffmpeg_path, encoder)


def _first_working_backend(
    candidates: Tuple[str, ...], codec: str, ffmpeg_path: str
) -> Tuple[Optional[str], bool]:
    """Return ``(backend, conclusive)`` for the first candidate that works.

    Candidates are tried in priority order and the search stops at the first
    success. The result is conclusive only when every candidate tried was
    conclusive, so an inconclusive higher-priority probe keeps a lower-priority
    success out of the disk cache.
    """

    conclusive = True
    for candidate in candidates:
        result = _probe_backend(candidate, codec, ffmpeg_path)
        if result is None:
            conclusive = False
        elif result:
            return candidate, conclusive
    return None, conclusive


def _hardware_memory_key(
    ffmpeg_path: str, fingerprint: Optional[dict[str, object]], codec: str
) -> tuple:
    """Key the in-process cache by binary identity, falling back to its path."""

    identity = (
        tuple(sorted(fingerprint.items()))
        if fingerprint is not None
        else os.path.abspath(ffmpeg_path)
    )
    return (identity, codec)


def detect_hardware_backend(
    codec: str, ffmpeg_path: Optional[str] = None
) -> Optional[str]:
    """Return the hardware backend that will encode *codec*, or ``None``.

    Candidates are tried in priority order (discrete GPUs before Intel's iGPU)
    with a one-frame trial encode. The answer is cached per codec in memory, and
    in ``settings.json`` for :data:`HARDWARE_CACHE_MAX_AGE_SECONDS` keyed by the
    FFmpeg binary's fingerprint, but only when every probe was conclusive. A
    timed-out trial or a failed encoder listing is inconclusive: it stays in
    memory and is re-checked by the next run. Detection is per codec because
    support differs: Intel before Arc, AMD before RDNA3 and NVIDIA before RTX 40
    encode HEVC but not AV1. Non-video codecs such as ``mp3`` return ``None``
    without probing.
    """

    codec = (codec or "").strip().lower()
    candidates = _HARDWARE_CANDIDATES.get(codec)
    if candidates is None:
        return None

    ffmpeg_path = ffmpeg_path or get_ffmpeg_path()
    fingerprint = _ffmpeg_fingerprint(ffmpeg_path)
    memory_key = _hardware_memory_key(ffmpeg_path, fingerprint, codec)

    with _HARDWARE_BACKEND_LOCK:
        if memory_key in _HARDWARE_BACKEND_CACHE:
            return _HARDWARE_BACKEND_CACHE[memory_key]

        now = time.time()
        if fingerprint is not None:
            hit, cached = _read_cached_backend(fingerprint, codec, now)
            if hit:
                _HARDWARE_BACKEND_CACHE[memory_key] = cached
                return cached

        backend, conclusive = _first_working_backend(candidates, codec, ffmpeg_path)
        _HARDWARE_BACKEND_CACHE[memory_key] = backend
        if fingerprint is not None and conclusive:
            _write_cached_backend(
                fingerprint, codec, {"backend": backend, "checked_at": int(now)}
            )
        return backend


def invalidate_hardware_backend_cache(
    codec: str, ffmpeg_path: Optional[str] = None
) -> None:
    """Forget the cached backend for *codec* so the next run probes again.

    Called when a GPU encode fails for real, which means the cached answer no
    longer matches the machine (a removed eGPU, a broken driver).
    """

    codec = (codec or "").strip().lower()
    ffmpeg_path = ffmpeg_path or get_ffmpeg_path()
    fingerprint = _ffmpeg_fingerprint(ffmpeg_path)
    with _HARDWARE_BACKEND_LOCK:
        _HARDWARE_BACKEND_CACHE.pop(
            _hardware_memory_key(ffmpeg_path, fingerprint, codec), None
        )
        if fingerprint is not None:
            _write_cached_backend(fingerprint, codec, None)


# Quality on the VideoToolbox 1-100 scale that matches the size the software
# encoder produces for the same clip. Only HEVC is listed because only HEVC uses
# the hardware encoder — see ``resolve_encoder_plan``.
_VIDEOTOOLBOX_QUALITY = {"hevc": 68}


def _videotoolbox_encoder_args(
    encoder: str,
    *,
    profile: str,
    quality: int,
    extra_keyframe_args: Sequence[str],
    ffmpeg_path: Optional[str] = None,
) -> List[str]:
    """Return VideoToolbox encoder flags for the requested quality *profile*.

    VideoToolbox exposes neither ``-crf`` nor ``-preset``: quality is requested
    through ``-q:v`` on a 1-100 scale where higher means better, and extra speed
    is requested through ``-prio_speed``.

    ``-spatial_aq`` spends more bits on the flat areas that dominate slide and
    screen recordings, but it only exists from FFmpeg 7.1 onwards while
    ``static-ffmpeg`` still bundles 7.0, so it is probed rather than assumed.
    """

    args = [f"-c:v {encoder}", f"-q:v {quality}"]
    if profile == "fast":
        args.append("-prio_speed 1")
    elif encoder_supports_option(encoder, "spatial_aq", ffmpeg_path=ffmpeg_path):
        args.append("-spatial_aq 1")

    return args + list(extra_keyframe_args)


def _force_kill_process(process: subprocess.Popen) -> None:
    """Terminate an FFmpeg process forcefully, including its process group."""

    import signal
    import time

    if process.poll() is not None:
        return

    try:
        if sys.platform != "win32":
            # Kill the entire process group on Unix
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        else:
            process.terminate()
    except (OSError, ProcessLookupError):
        pass

    # Wait up to 2 seconds for graceful exit, then SIGKILL
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            if sys.platform != "win32":
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            else:
                process.kill()
        except (OSError, ProcessLookupError):
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass


class FFmpegStallTimeout(RuntimeError):
    """Raised when FFmpeg produces no output for too long."""


#: Default number of seconds to wait before declaring FFmpeg stalled.
DEFAULT_STALL_TIMEOUT = 600  # 10 minutes


def run_timed_ffmpeg_command(
    command: str,
    *,
    reporter: Optional[ProgressReporter] = None,
    desc: str = "",
    total: Optional[int] = None,
    unit: str = "frames",
    process_callback: Optional[callable] = None,
    stop_requested: Optional[callable] = None,
    stall_timeout: float = DEFAULT_STALL_TIMEOUT,
) -> None:
    """Execute an FFmpeg command while streaming progress information.

    Args:
        process_callback: Optional callback that receives the subprocess.Popen object
        stop_requested: Optional callable returning True when processing should abort
        stall_timeout: Seconds to wait for new output before aborting. Set to 0 to
            disable the watchdog.
    """

    import queue
    import shlex
    import threading
    import time

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

    # Use a new session on Unix so we can kill the whole process group
    popen_kwargs: dict = {}
    if sys.platform != "win32":
        popen_kwargs["start_new_session"] = True

    try:
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            bufsize=1,
            errors="replace",
            creationflags=creationflags,
            **popen_kwargs,
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"Error starting FFmpeg: {exc}", file=sys.stderr)
        raise

    # Notify callback with process object
    if process_callback:
        process_callback(process)

    # Feed stderr lines into a queue so the main loop can poll with a timeout
    # instead of blocking indefinitely on readline().
    line_queue: queue.Queue[Optional[str]] = queue.Queue()

    def _reader() -> None:
        try:
            for ln in iter(process.stderr.readline, ""):
                line_queue.put(ln)
        finally:
            line_queue.put(None)  # sentinel: EOF

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()

    progress_reporter = reporter or TqdmProgressReporter()
    task_manager = progress_reporter.task(desc=desc, total=total, unit=unit)
    with task_manager as progress:
        last_output_time = time.monotonic()
        last_logged_percent = -1
        last_milestone_time = 0.0

        while True:
            # Check stop flag
            if stop_requested is not None and stop_requested():
                _force_kill_process(process)
                raise subprocess.CalledProcessError(-15, args)

            # Poll the queue with a short timeout so we can re-check the
            # stop flag and the stall watchdog regularly.
            try:
                line = line_queue.get(timeout=1.0)
            except queue.Empty:
                # No output yet — check if the stall timeout has elapsed.
                if (
                    stall_timeout > 0
                    and time.monotonic() - last_output_time >= stall_timeout
                ):
                    minutes = int(stall_timeout // 60)
                    msg = (
                        f"FFmpeg produced no output for {minutes} minutes, " "aborting"
                    )
                    progress_reporter.log(msg)
                    print(f"\n{msg}", file=sys.stderr)
                    _force_kill_process(process)
                    raise FFmpegStallTimeout(msg)
                continue

            if line is None:
                # EOF sentinel — reader thread finished
                break

            if not line.strip():
                continue

            last_output_time = time.monotonic()

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
                for keyword in ["error", "warning", "encoded successfully"]
            ):
                progress_reporter.log(line.strip())

            match = re.search(r"frame=\s*(\d+)", line)
            if match:
                try:
                    new_frame = int(match.group(1))
                    progress.ensure_total(new_frame)
                    progress.advance(new_frame - progress.current)
                    if total is not None and total > 0:
                        percent = min(int(new_frame * 100 / total), 100)
                        milestone = (percent // 10) * 10
                        if milestone > last_logged_percent and milestone < 100:
                            progress_reporter.log(f"{desc} {milestone}%")
                            last_logged_percent = milestone
                    elif time.monotonic() - last_milestone_time >= 30:
                        progress_reporter.log(f"{desc} {new_frame} frames")
                        last_milestone_time = time.monotonic()
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


def build_trim_input_args(
    cut_start_seconds: float = 0.0,
    cut_end_seconds: float = 0.0,
) -> List[str]:
    """Return input-level ``-ss``/``-t`` flags for a keep-range trim.

    The trim keeps the ``[cut_start_seconds, cut_end_seconds]`` fragment of the
    input. ``cut_end_seconds`` of ``0`` means "until end of file", so only
    ``-ss`` is emitted; when both bounds are ``0`` (or otherwise produce no
    trim) an empty list is returned and the command is left unchanged. ``-t``
    (duration) is preferred over ``-to`` because a pre-input ``-ss`` combined
    with ``-to`` is interpreted inconsistently across FFmpeg versions.
    """

    start = float(cut_start_seconds or 0.0)
    end = float(cut_end_seconds or 0.0)

    # An inverted range (end <= start) keeps nothing, so emit no trim rather
    # than silently degrading to "keep from start to EOF".
    if end > 0 and end <= start:
        return []

    args: List[str] = []
    if start > 0:
        args.append(f"-ss {start:.6g}")
    if end > 0:
        duration = end - start
        if duration > 0:
            args.append(f"-t {duration:.6g}")
    return args


def get_video_duration(
    input_file: str,
    ffprobe_path: Optional[str] = None,
) -> float:
    """Return the duration of ``input_file`` in seconds via ffprobe.

    Returns ``0.0`` when ffprobe is unavailable, the file cannot be probed, or
    the reported duration is missing/invalid so callers can degrade gracefully.
    """

    try:
        ffprobe_path = ffprobe_path or get_ffprobe_path()
    except FFmpegNotFoundError:
        return 0.0

    command = [
        ffprobe_path,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        input_file,
    ]

    creationflags = 0
    if sys.platform == "win32":
        # CREATE_NO_WINDOW = 0x08000000
        creationflags = 0x08000000

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=creationflags,
        )
    except (
        subprocess.TimeoutExpired,
        subprocess.CalledProcessError,
        FileNotFoundError,
    ):
        return 0.0

    if result.returncode != 0:
        return 0.0

    raw = (result.stdout or "").strip()
    try:
        duration = float(raw)
    except (TypeError, ValueError):
        return 0.0

    return duration if duration > 0 else 0.0


def build_extract_audio_command(
    input_file: str,
    output_wav: str,
    sample_rate: int,
    audio_bitrate: str,
    hwaccel: Optional[List[str]] = None,
    ffmpeg_path: Optional[str] = None,
    cut_start_seconds: float = 0.0,
    cut_end_seconds: float = 0.0,
) -> str:
    """Build the FFmpeg command used to extract audio into a temporary WAV file."""

    hwaccel = hwaccel or []
    ffmpeg_path = ffmpeg_path or get_ffmpeg_path()
    command_parts: List[str] = [f'"{ffmpeg_path}"']
    command_parts.extend(hwaccel)
    command_parts.extend(build_trim_input_args(cut_start_seconds, cut_end_seconds))
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


def build_audio_only_command(
    input_file: str,
    audio_file: Optional[str],
    output_file: str,
    *,
    ffmpeg_path: Optional[str] = None,
    cut_start_seconds: float = 0.0,
    cut_end_seconds: float = 0.0,
    quality: str = "2",
) -> str:
    """Build the FFmpeg command that renders an audio-only ``.mp3`` output.

    When ``audio_file`` (the already silence-trimmed/speed-adjusted WAV) is
    provided it is used directly as the source, since the trim and speed are
    already baked into it. Otherwise the original ``input_file`` is used and the
    keep-range ``-ss``/``-t`` flags from ``build_trim_input_args`` are applied.
    The audio is encoded with ``libmp3lame`` at the fixed VBR ``-q:a`` quality
    (default ``2``, ~190 kbps). No CUDA and no fallback command.
    """

    ffmpeg_path = ffmpeg_path or get_ffmpeg_path()
    command_parts: List[str] = [f'"{ffmpeg_path}"', "-y"]

    if audio_file:
        command_parts.append(f'-i "{audio_file}"')
    else:
        command_parts.extend(build_trim_input_args(cut_start_seconds, cut_end_seconds))
        command_parts.append(f'-i "{input_file}"')

    command_parts.extend(
        [
            "-vn",
            "-map 0:a:0",
            "-c:a libmp3lame",
            f"-q:a {quality}",
            f'"{output_file}"',
            "-loglevel warning -stats -hide_banner",
        ]
    )
    return " ".join(command_parts)


class _HardwareEncoderSpec(NamedTuple):
    """FFmpeg arguments for one hardware encoder, per quality profile."""

    encoder: str
    optimized: Tuple[str, ...]
    fast: Tuple[str, ...]


# The QSV -global_quality values (hevc 29, av1 31) were calibrated to VMAF ~91
# — the level the CPU H.264/H.265 defaults reach — with a sweep on a Core Ultra
# 5 125H (Arc iGPU) over a 1080p60 screen recording scaled to 720p, and checked
# at 480p; see "Calibration results" in
# docs/superpowers/specs/2026-10-10-qsv-amf-hardware-encoding-design.md.
# The AMF values mirror the NVENC fast-profile QP scale set in
# resolve_encoder_plan below and are NOT calibrated on real AMD hardware. CQP is
# used because every VCN generation supports it, unlike QVBR.
_HARDWARE_ENCODER_ARGS: dict[Tuple[str, str], _HardwareEncoderSpec] = {
    ("qsv", "hevc"): _HardwareEncoderSpec(
        "hevc_qsv",
        optimized=("-preset medium", "-global_quality 29"),
        fast=("-preset veryfast", "-global_quality 29"),
    ),
    ("qsv", "av1"): _HardwareEncoderSpec(
        "av1_qsv",
        optimized=("-preset medium", "-global_quality 31"),
        fast=("-preset veryfast", "-global_quality 31"),
    ),
    ("amf", "hevc"): _HardwareEncoderSpec(
        "hevc_amf",
        optimized=("-quality balanced", "-rc cqp", "-qp_i 26", "-qp_p 28"),
        fast=("-quality speed", "-rc cqp", "-qp_i 26", "-qp_p 28"),
    ),
    ("amf", "av1"): _HardwareEncoderSpec(
        "av1_amf",
        optimized=("-quality balanced", "-rc cqp", "-qp_i 30", "-qp_p 32"),
        fast=("-quality speed", "-rc cqp", "-qp_i 30", "-qp_p 32"),
    ),
}


def _table_encoder_args(
    backend: Optional[str],
    codec: str,
    *,
    profile: str,
    extra_keyframe_args: Sequence[str],
    ffmpeg_path: Optional[str],
) -> Optional[List[str]]:
    """Return QSV/AMF encoder flags for *codec*, or ``None`` when not applicable.

    ``hevc_qsv`` ignores ``-force_key_frames`` (it emits a keyframe only at
    frame zero unless ``-forced_idr 1`` is also set; ``av1_qsv`` honours it), so
    the QSV backend keeps ``-g``/``-keyint_min`` and drops the forced-keyframe
    expression for both codecs.
    """

    spec = _HARDWARE_ENCODER_ARGS.get((backend or "", codec))
    if spec is None or not encoder_available(spec.encoder, ffmpeg_path=ffmpeg_path):
        return None
    profile_args = spec.fast if profile == "fast" else spec.optimized
    keyframe_args = list(extra_keyframe_args)
    if backend == "qsv":
        keyframe_args = [
            arg for arg in keyframe_args if not arg.startswith("-force_key_frames")
        ]
    return [f"-c:v {spec.encoder}", *profile_args, *keyframe_args]


def build_video_commands(
    input_file: str,
    audio_file: Optional[str],
    filter_script: Optional[str],
    output_file: str,
    *,
    ffmpeg_path: Optional[str] = None,
    hardware_backend: Optional[str] = None,
    optimize: bool,
    small: bool,
    frame_rate: Optional[float] = None,
    keyframe_interval_seconds: float = 30.0,
    video_codec: str = "h264",
    keep_input_audio: bool = False,
    cut_start_seconds: float = 0.0,
    cut_end_seconds: float = 0.0,
) -> Tuple[str, Optional[str], bool]:
    """Create the FFmpeg command strings used to render the final video output.

    Args:
        input_file: Path to the input video file.
        audio_file: Optional path to the processed audio file. If None and
            ``keep_input_audio`` is False, the video is encoded without audio.
        filter_script: Optional path to the filter script file. If None, video will be re-encoded without speed modification.
        output_file: Path to the output video file.
        hardware_backend: The backend :func:`detect_hardware_backend` returned
            for this codec (``"cuda"``, ``"amf"``, ``"qsv"``, ``"videotoolbox"``)
            or ``None`` for the CPU. Only CUDA also decodes on the GPU; QSV and
            AMF decode on the CPU because the filter graph runs there anyway.
        frame_rate: Optional source frame rate used to size GOP/keyframe spacing for
            the small preset when generating hardware/software encoder commands.
        keep_input_audio: When True and ``audio_file`` is None, map the audio
            track from the input file directly into the output using stream
            copy (``-c:a copy``) instead of disabling audio.
    """

    ffmpeg_path = ffmpeg_path or get_ffmpeg_path()
    global_parts: List[str] = [f'"{ffmpeg_path}"', "-y"]
    hwaccel_args: List[str] = []

    if hardware_backend == "cuda" and not small:
        hwaccel_args = ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
        global_parts.extend(hwaccel_args)

    trim_args = build_trim_input_args(cut_start_seconds, cut_end_seconds)
    input_parts = trim_args + [f'-i "{input_file}"']
    if audio_file:
        input_parts.append(f'-i "{audio_file}"')

    output_parts: List[str] = []
    if audio_file:
        output_parts.append("-map 0:v:0 -map 1:a")
    elif keep_input_audio:
        output_parts.append("-map 0:v:0 -map 0:a?")
    else:
        output_parts.append("-map 0:v:0")

    if filter_script:
        output_parts.append(f'-filter_script:v "{filter_script}"')

    codec_choice = normalize_video_codec(video_codec)

    video_encoder_args: List[str]
    fallback_encoder_args: List[str] = []
    use_gpu_encoder = False

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
        backend: Optional[str],
        codec: str,
        extra_keyframe_args: Sequence[str],
        profile: str,
    ) -> Tuple[List[str], List[str], bool]:
        primary_args: List[str]
        fallback_args: List[str] = []
        uses_gpu = False

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

            table_args = _table_encoder_args(
                backend,
                "av1",
                profile=profile,
                extra_keyframe_args=extra_keyframe_args,
                ffmpeg_path=ffmpeg_path,
            )
            if backend == "cuda" and encoder_available(
                "av1_nvenc", ffmpeg_path=ffmpeg_path
            ):
                uses_gpu = True
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
            elif table_args is not None:
                uses_gpu = True
                primary_args = table_args
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
            table_args = _table_encoder_args(
                backend,
                "hevc",
                profile=profile,
                extra_keyframe_args=extra_keyframe_args,
                ffmpeg_path=ffmpeg_path,
            )
            if backend == "cuda" and encoder_available(
                "hevc_nvenc", ffmpeg_path=ffmpeg_path
            ):
                uses_gpu = True
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
            elif backend == "videotoolbox" and encoder_available(
                "hevc_videotoolbox", ffmpeg_path=ffmpeg_path
            ):
                uses_gpu = True
                primary_args = _videotoolbox_encoder_args(
                    "hevc_videotoolbox",
                    profile=profile,
                    quality=_VIDEOTOOLBOX_QUALITY["hevc"],
                    extra_keyframe_args=extra_keyframe_args,
                    ffmpeg_path=ffmpeg_path,
                )
                fallback_args = cpu_encoder_args
            elif table_args is not None:
                uses_gpu = True
                primary_args = table_args
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
            if backend == "cuda":
                uses_gpu = True
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
            # H.264 deliberately stays on libx264 even when VideoToolbox, QSV or
            # AMF is available: Apple's media engine caps out around 290 fps at
            # 1080p, and Intel QSV on a Core Ultra 5 125H managed 390 fps with a
            # 55% larger file, while libx264 -preset veryfast reaches 500-600 fps
            # across the CPU cores. HEVC and AV1 are the opposite — see above.

        return primary_args, fallback_args, uses_gpu

    primary_plan, primary_fallback, primary_uses_gpu = resolve_encoder_plan(
        backend=hardware_backend,
        codec=codec_choice,
        extra_keyframe_args=keyframe_args,
        profile=quality_profile,
    )

    video_encoder_args = primary_plan
    fallback_encoder_args = primary_fallback
    use_gpu_encoder = primary_uses_gpu

    audio_parts: List[str] = []
    if audio_file:
        audio_parts.append("-c:a aac")
    elif keep_input_audio:
        audio_parts.append("-c:a copy")
    else:
        audio_parts.append("-an")  # No audio

    audio_parts.extend(
        [
            f'"{output_file}"',
            "-loglevel warning -stats -hide_banner",
        ]
    )

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

    return command_str, fallback_command_str, use_gpu_encoder


__all__ = [
    "FFmpegNotFoundError",
    "FFmpegStallTimeout",
    "DEFAULT_STALL_TIMEOUT",
    "find_ffmpeg",
    "find_ffprobe",
    "get_ffmpeg_path",
    "get_ffprobe_path",
    "check_cuda_available",
    "check_videotoolbox_available",
    "detect_hardware_backend",
    "invalidate_hardware_backend_cache",
    "normalize_video_codec",
    "HARDWARE_BACKEND_LABELS",
    "run_timed_ffmpeg_command",
    "build_trim_input_args",
    "build_extract_audio_command",
    "get_video_duration",
    "build_video_commands",
    "shutil_which",
]
