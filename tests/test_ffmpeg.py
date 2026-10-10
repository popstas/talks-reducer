"""Tests for :mod:`talks_reducer.ffmpeg`."""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional

import pytest

from talks_reducer import ffmpeg


@pytest.fixture(autouse=True)
def stub_static_ffmpeg(monkeypatch):
    """Prevent tests from invoking real static-ffmpeg downloads."""

    stub = SimpleNamespace(add_paths=lambda: False)
    monkeypatch.setitem(sys.modules, "static_ffmpeg", stub)
    monkeypatch.setattr(ffmpeg, "_ENCODER_LISTING", {}, raising=False)
    monkeypatch.setattr(ffmpeg, "_ENCODER_OPTIONS", {}, raising=False)
    monkeypatch.setattr(
        ffmpeg, "_FFMPEG_PATH_CACHE", {False: None, True: None}, raising=False
    )
    monkeypatch.setattr(
        ffmpeg, "_FFPROBE_PATH_CACHE", {False: None, True: None}, raising=False
    )
    monkeypatch.setattr(ffmpeg, "_GLOBAL_FFMPEG_AVAILABLE", None, raising=False)
    yield
    sys.modules.pop("static_ffmpeg", None)


class DummyProgressReporter(ffmpeg.ProgressReporter):
    """Progress reporter used to capture progress updates in tests."""

    def __init__(self) -> None:
        self.logs: List[str] = []
        self.tasks: List["DummyTask"] = []

    def log(self, message: str) -> None:  # pragma: no cover - interface method
        self.logs.append(message)

    def task(
        self,
        *,
        desc: str = "",
        total: Optional[int] = None,
        unit: str = "",
    ) -> "DummyTaskManager":
        task = DummyTask(desc=desc, total=total, unit=unit)
        self.tasks.append(task)
        return DummyTaskManager(task)


class DummyTask:
    def __init__(self, *, desc: str, total: Optional[int], unit: str) -> None:
        self.desc = desc
        self.requested_total = total
        self.unit = unit
        self.current = 0
        self.total = total
        self.finished = False

    def ensure_total(self, value: int) -> None:
        if self.total is None or value > self.total:
            self.total = value

    def advance(self, amount: int) -> None:
        self.current += amount

    def finish(self) -> None:
        self.finished = True


class DummyTaskManager:
    def __init__(self, task: DummyTask) -> None:
        self.task = task

    def __enter__(self) -> DummyTask:
        return self.task

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_find_ffmpeg_prefers_env_file(monkeypatch):
    fake_path = "/custom/ffmpeg"
    monkeypatch.setenv("TALKS_REDUCER_FFMPEG", fake_path)
    monkeypatch.setattr(ffmpeg.os.path, "isfile", lambda path: path == fake_path)
    monkeypatch.setattr(ffmpeg, "shutil_which", lambda path: None)

    result = ffmpeg.find_ffmpeg()

    assert result == ffmpeg.os.path.abspath(fake_path)


def test_find_ffmpeg_uses_env_name_via_which(monkeypatch):
    monkeypatch.setenv("TALKS_REDUCER_FFMPEG", "ffmpeg")
    monkeypatch.setattr(ffmpeg.os.path, "isfile", lambda path: False)
    monkeypatch.setattr(
        ffmpeg,
        "shutil_which",
        lambda path: "/usr/bin/ffmpeg" if path == "ffmpeg" else None,
    )

    result = ffmpeg.find_ffmpeg()

    assert result == "ffmpeg"


def test_find_ffmpeg_returns_none_when_missing(monkeypatch):
    for env_var in ["TALKS_REDUCER_FFMPEG", "FFMPEG_PATH"]:
        monkeypatch.delenv(env_var, raising=False)

    monkeypatch.setattr(ffmpeg.os.path, "isfile", lambda path: False)
    monkeypatch.setattr(ffmpeg, "shutil_which", lambda path: None)

    # Ensure bundled ffmpeg path does not resolve
    def raise_error():  # pragma: no cover - simple stub
        raise RuntimeError

    monkeypatch.setitem(
        sys.modules, "static_ffmpeg", SimpleNamespace(add_paths=raise_error)
    )

    assert ffmpeg.find_ffmpeg() is None


def test_find_ffprobe_prefers_env_file(monkeypatch):
    fake_path = "/custom/ffprobe"
    monkeypatch.setenv("TALKS_REDUCER_FFPROBE", fake_path)
    monkeypatch.setattr(ffmpeg.os.path, "isfile", lambda path: path == fake_path)
    monkeypatch.setattr(ffmpeg, "shutil_which", lambda path: None)

    result = ffmpeg.find_ffprobe()

    assert result == ffmpeg.os.path.abspath(fake_path)


def test_find_ffprobe_from_ffmpeg_directory(monkeypatch):
    fake_ffmpeg_path = "/opt/bin/ffmpeg"
    expected_ffprobe = "/opt/bin/ffprobe"
    monkeypatch.setattr(
        ffmpeg, "find_ffmpeg", lambda prefer_global=False: fake_ffmpeg_path
    )
    monkeypatch.setattr(
        ffmpeg.os.path,
        "isfile",
        lambda path: path == expected_ffprobe
        or ffmpeg.os.path.normpath(path) == ffmpeg.os.path.normpath(expected_ffprobe),
    )
    monkeypatch.setattr(ffmpeg, "shutil_which", lambda path: None)

    result = ffmpeg.find_ffprobe()

    assert result is not None
    # Result should be the absolute path or the original path
    assert (
        result == ffmpeg.os.path.abspath(expected_ffprobe) or result == expected_ffprobe
    )


def test_find_ffprobe_returns_none_when_missing(monkeypatch):
    for env_var in ["TALKS_REDUCER_FFPROBE", "FFPROBE_PATH"]:
        monkeypatch.delenv(env_var, raising=False)

    monkeypatch.setattr(ffmpeg.os.path, "isfile", lambda path: False)
    monkeypatch.setattr(ffmpeg, "shutil_which", lambda path: None)
    monkeypatch.setattr(ffmpeg, "find_ffmpeg", lambda prefer_global=False: None)

    assert ffmpeg.find_ffprobe() is None


def test_resolve_ffmpeg_path_raises(monkeypatch):
    monkeypatch.setattr(ffmpeg, "find_ffmpeg", lambda prefer_global=False: None)

    with pytest.raises(ffmpeg.FFmpegNotFoundError):
        ffmpeg._resolve_ffmpeg_path()


def test_resolve_ffprobe_path_raises(monkeypatch):
    monkeypatch.setattr(ffmpeg, "find_ffprobe", lambda prefer_global=False: None)

    with pytest.raises(ffmpeg.FFmpegNotFoundError):
        ffmpeg._resolve_ffprobe_path()


def test_get_ffmpeg_path_caches(monkeypatch):
    calls: List[str] = []

    def fake_resolve(*, prefer_global: bool = False) -> str:
        calls.append("global" if prefer_global else "bundled")
        return "cached-global" if prefer_global else "cached-ffmpeg"

    monkeypatch.setattr(ffmpeg, "_resolve_ffmpeg_path", fake_resolve)
    monkeypatch.setattr(
        ffmpeg, "_FFMPEG_PATH_CACHE", {False: None, True: None}, raising=False
    )

    assert ffmpeg.get_ffmpeg_path() == "cached-ffmpeg"
    assert ffmpeg.get_ffmpeg_path() == "cached-ffmpeg"
    assert ffmpeg.get_ffmpeg_path(prefer_global=True) == "cached-global"
    assert ffmpeg.get_ffmpeg_path(prefer_global=True) == "cached-global"
    assert calls == ["bundled", "global"]


def test_get_ffprobe_path_caches(monkeypatch):
    calls: List[str] = []

    def fake_resolve(*, prefer_global: bool = False) -> str:
        calls.append("global" if prefer_global else "bundled")
        return "cached-global" if prefer_global else "cached-ffprobe"

    monkeypatch.setattr(ffmpeg, "_resolve_ffprobe_path", fake_resolve)
    monkeypatch.setattr(
        ffmpeg, "_FFPROBE_PATH_CACHE", {False: None, True: None}, raising=False
    )

    assert ffmpeg.get_ffprobe_path() == "cached-ffprobe"
    assert ffmpeg.get_ffprobe_path() == "cached-ffprobe"
    assert ffmpeg.get_ffprobe_path(prefer_global=True) == "cached-global"
    assert ffmpeg.get_ffprobe_path(prefer_global=True) == "cached-global"
    assert calls == ["bundled", "global"]


def test_is_global_ffmpeg_available_when_only_system(monkeypatch):
    monkeypatch.setattr(ffmpeg, "find_ffmpeg", lambda prefer_global=False: "ffmpeg")
    monkeypatch.setattr(ffmpeg, "_find_static_ffmpeg", lambda: None)
    monkeypatch.setattr(
        ffmpeg,
        "shutil_which",
        lambda cmd: "/usr/bin/ffmpeg" if cmd == "ffmpeg" else None,
    )

    assert ffmpeg.is_global_ffmpeg_available() is True


def test_is_global_ffmpeg_available_false_when_matches_static(monkeypatch):
    monkeypatch.setattr(ffmpeg, "find_ffmpeg", lambda prefer_global=False: "ffmpeg")
    monkeypatch.setattr(ffmpeg, "_find_static_ffmpeg", lambda: "/opt/static/ffmpeg")
    monkeypatch.setattr(
        ffmpeg.os.path,
        "isfile",
        lambda path: path in {"/opt/static/ffmpeg"},
    )
    monkeypatch.setattr(
        ffmpeg,
        "shutil_which",
        lambda cmd: "/opt/static/ffmpeg" if cmd == "ffmpeg" else None,
    )
    monkeypatch.setattr(
        ffmpeg.os.path,
        "samefile",
        lambda left, right: ffmpeg.os.path.normcase(left)
        == ffmpeg.os.path.normcase(right),
    )

    assert ffmpeg.is_global_ffmpeg_available() is False


def test_is_global_ffmpeg_available_true_when_both_present(monkeypatch):
    monkeypatch.setattr(
        ffmpeg,
        "find_ffmpeg",
        lambda prefer_global=False: (
            "/usr/bin/ffmpeg" if prefer_global else "/opt/static/ffmpeg"
        ),
    )
    monkeypatch.setattr(ffmpeg, "_find_static_ffmpeg", lambda: "/opt/static/ffmpeg")
    monkeypatch.setattr(ffmpeg.os.path, "isfile", lambda path: True)
    monkeypatch.setattr(
        ffmpeg.os.path,
        "samefile",
        lambda left, right: ffmpeg.os.path.normcase(left)
        == ffmpeg.os.path.normcase(right),
    )

    assert ffmpeg.is_global_ffmpeg_available() is True


def _stub_hardware_probe(
    monkeypatch,
    *,
    platform="win32",
    listed=(),
    working=(),
    trial_error=None,
    timeouts=(),
):
    """Fake the encoder listing and trial encodes; return the encoders trialled."""

    monkeypatch.setattr(ffmpeg.sys, "platform", platform)
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    trials: List[str] = []

    def fake_run(args, **kwargs):
        if "-encoders" in args:
            listing = "\n".join(f" V..... {name}" for name in listed)
            return SimpleNamespace(stdout=listing, returncode=0)
        if "-hwaccels" in args:
            return SimpleNamespace(stdout="videotoolbox\n", returncode=0)
        if "-c:v" in args:
            encoder = args[args.index("-c:v") + 1]
            trials.append(encoder)
            if encoder in timeouts:
                raise ffmpeg.subprocess.TimeoutExpired(cmd="ffmpeg", timeout=10)
            if trial_error is not None:
                raise trial_error
            return SimpleNamespace(
                stdout="", stderr="", returncode=0 if encoder in working else 1
            )
        raise AssertionError(f"Unexpected args: {args}")

    monkeypatch.setattr(ffmpeg.subprocess, "run", fake_run)
    return trials


ALL_HEVC = ("hevc_nvenc", "hevc_amf", "hevc_qsv")


def test_detect_hardware_backend_prefers_first_working_candidate(monkeypatch):
    trials = _stub_hardware_probe(
        monkeypatch, listed=ALL_HEVC, working=("hevc_amf", "hevc_qsv")
    )

    assert ffmpeg.detect_hardware_backend("hevc") == "amf"
    assert trials == ["hevc_nvenc", "hevc_amf"]


def test_detect_hardware_backend_skips_unlisted_encoders(monkeypatch):
    trials = _stub_hardware_probe(
        monkeypatch, listed=("hevc_qsv",), working=("hevc_qsv",)
    )

    assert ffmpeg.detect_hardware_backend("hevc") == "qsv"
    assert trials == ["hevc_qsv"]


def test_detect_hardware_backend_h264_only_probes_nvenc(monkeypatch):
    """QSV/AMF H.264 stays on libx264, so probing them would be wasted time."""

    trials = _stub_hardware_probe(
        monkeypatch,
        listed=("h264_nvenc", "h264_amf", "h264_qsv"),
        working=("h264_qsv",),
    )

    assert ffmpeg.detect_hardware_backend("h264") is None
    assert trials == ["h264_nvenc"]


def test_detect_hardware_backend_probes_each_codec_separately(monkeypatch):
    """Pre-Arc Intel encodes HEVC but not AV1."""

    _stub_hardware_probe(
        monkeypatch, listed=("hevc_qsv", "av1_qsv"), working=("hevc_qsv",)
    )

    assert ffmpeg.detect_hardware_backend("hevc") == "qsv"
    assert ffmpeg.detect_hardware_backend("av1") is None


def test_detect_hardware_backend_ignores_non_video_codecs(monkeypatch):
    def unexpected_run(*args, **kwargs):
        raise AssertionError("mp3 must not probe GPU encoders")

    monkeypatch.setattr(ffmpeg.subprocess, "run", unexpected_run)
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    assert ffmpeg.detect_hardware_backend("mp3") is None


def test_detect_hardware_backend_normalises_codec_name(monkeypatch):
    trials = _stub_hardware_probe(
        monkeypatch, listed=("hevc_qsv",), working=("hevc_qsv",)
    )

    assert ffmpeg.detect_hardware_backend(" HEVC ") == "qsv"
    assert trials == ["hevc_qsv"]


def test_detect_hardware_backend_uses_videotoolbox_on_macos(monkeypatch):
    trials = _stub_hardware_probe(
        monkeypatch,
        platform="darwin",
        listed=("hevc_videotoolbox", "hevc_nvenc", "av1_qsv"),
    )

    assert ffmpeg.detect_hardware_backend("hevc") == "videotoolbox"
    assert ffmpeg.detect_hardware_backend("av1") is None
    assert trials == []


def test_detect_hardware_backend_failed_videotoolbox_probe_is_not_persisted(
    monkeypatch, tmp_path
):
    """A failed ``-hwaccels`` probe says nothing about VideoToolbox, so it must not persist."""

    binary = _fake_ffmpeg_binary(tmp_path)
    monkeypatch.setattr(ffmpeg.sys, "platform", "darwin")
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    def fake_run(args, **kwargs):
        if "-hwaccels" in args:
            return SimpleNamespace(stdout="", returncode=1)
        if "-encoders" in args:
            return SimpleNamespace(stdout=" V..... hevc_videotoolbox", returncode=0)
        raise AssertionError(f"Unexpected args: {args}")

    monkeypatch.setattr(ffmpeg.subprocess, "run", fake_run)

    assert ffmpeg.detect_hardware_backend("hevc", binary) is None
    assert not ffmpeg._hardware_cache_path().exists()


def test_detect_hardware_backend_timeout_is_not_persisted(monkeypatch, tmp_path):
    """A timed-out trial may be a slow driver start, so it must not stick for 30 days."""

    binary = _fake_ffmpeg_binary(tmp_path)
    trials = _stub_hardware_probe(monkeypatch, listed=ALL_HEVC, timeouts=ALL_HEVC)

    assert ffmpeg.detect_hardware_backend("hevc", binary) is None
    assert not ffmpeg._hardware_cache_path().exists()

    assert ffmpeg.detect_hardware_backend("hevc", binary) is None
    assert trials == ["hevc_nvenc", "hevc_amf", "hevc_qsv"]

    ffmpeg._HARDWARE_BACKEND_CACHE.clear()
    assert ffmpeg.detect_hardware_backend("hevc", binary) is None
    assert len(trials) == 6


def test_detect_hardware_backend_spawn_error_is_not_persisted(monkeypatch, tmp_path):
    binary = _fake_ffmpeg_binary(tmp_path)
    _stub_hardware_probe(
        monkeypatch, listed=("hevc_qsv",), trial_error=OSError("spawn failed")
    )

    assert ffmpeg.detect_hardware_backend("hevc", binary) is None
    assert not ffmpeg._hardware_cache_path().exists()


def test_detect_hardware_backend_listing_failure_is_not_persisted(
    monkeypatch, tmp_path
):
    """A failed ``-encoders`` probe says nothing about the GPU, unlike an empty list."""

    binary = _fake_ffmpeg_binary(tmp_path)
    monkeypatch.setattr(ffmpeg.sys, "platform", "win32")
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    def fake_run(args, **kwargs):
        if "-encoders" in args:
            return SimpleNamespace(stdout="", returncode=1)
        raise AssertionError(f"Unexpected args: {args}")

    monkeypatch.setattr(ffmpeg.subprocess, "run", fake_run)

    assert ffmpeg.detect_hardware_backend("hevc", binary) is None
    assert not ffmpeg._hardware_cache_path().exists()


def test_detect_hardware_backend_skips_persisting_after_inconclusive_candidate(
    monkeypatch, tmp_path
):
    """A timed-out NVENC trial must not lock in QSV for 30 days."""

    binary = _fake_ffmpeg_binary(tmp_path)
    trials = _stub_hardware_probe(
        monkeypatch,
        listed=ALL_HEVC,
        working=("hevc_qsv",),
        timeouts=("hevc_nvenc",),
    )

    assert ffmpeg.detect_hardware_backend("hevc", binary) == "qsv"
    assert not ffmpeg._hardware_cache_path().exists()

    assert ffmpeg.detect_hardware_backend("hevc", binary) == "qsv"
    assert trials == ["hevc_nvenc", "hevc_amf", "hevc_qsv"]


def test_detect_hardware_backend_persists_conclusive_success(monkeypatch, tmp_path):
    binary = _fake_ffmpeg_binary(tmp_path)
    _stub_hardware_probe(monkeypatch, listed=ALL_HEVC, working=("hevc_qsv",))

    assert ffmpeg.detect_hardware_backend("hevc", binary) == "qsv"

    stored = json.loads(ffmpeg._hardware_cache_path().read_text(encoding="utf-8"))
    assert stored["hardware_backend"]["codecs"]["hevc"]["backend"] == "qsv"


def test_detect_hardware_backend_memoizes_in_process(monkeypatch):
    trials = _stub_hardware_probe(monkeypatch, listed=ALL_HEVC, working=("hevc_qsv",))

    assert ffmpeg.detect_hardware_backend("hevc") == "qsv"
    assert ffmpeg.detect_hardware_backend("hevc") == "qsv"
    assert trials == ["hevc_nvenc", "hevc_amf", "hevc_qsv"]


def test_detect_hardware_backend_reads_disk_cache_without_probing(
    monkeypatch, tmp_path
):
    binary = _fake_ffmpeg_binary(tmp_path)
    ffmpeg._write_cached_backend(
        ffmpeg._ffmpeg_fingerprint(binary),
        "hevc",
        {"backend": "qsv", "checked_at": int(ffmpeg.time.time())},
    )

    def unexpected_run(*args, **kwargs):
        raise AssertionError("a fresh cache entry must not re-probe")

    monkeypatch.setattr(ffmpeg.subprocess, "run", unexpected_run)

    assert ffmpeg.detect_hardware_backend("hevc", binary) == "qsv"


def test_detect_hardware_backend_writes_disk_cache(monkeypatch, tmp_path):
    binary = _fake_ffmpeg_binary(tmp_path)
    _stub_hardware_probe(monkeypatch, listed=ALL_HEVC)

    assert ffmpeg.detect_hardware_backend("hevc", binary) is None

    stored = json.loads(ffmpeg._hardware_cache_path().read_text(encoding="utf-8"))
    record = stored["hardware_backend"]["codecs"]["hevc"]
    assert record["backend"] is None
    assert isinstance(record["checked_at"], int)


def test_invalidate_hardware_backend_cache_forces_reprobe(monkeypatch, tmp_path):
    binary = _fake_ffmpeg_binary(tmp_path)
    trials = _stub_hardware_probe(
        monkeypatch, listed=("hevc_qsv",), working=("hevc_qsv",)
    )
    ffmpeg.detect_hardware_backend("hevc", binary)

    ffmpeg.invalidate_hardware_backend_cache("hevc", binary)

    assert ffmpeg.detect_hardware_backend("hevc", binary) == "qsv"
    assert trials == ["hevc_qsv", "hevc_qsv"]


def test_check_cuda_available_requires_working_nvenc(monkeypatch):
    """Listing NVENC is not enough: gyan.dev builds list it on every machine."""

    _stub_hardware_probe(monkeypatch, listed=("h264_nvenc",))

    assert not ffmpeg.check_cuda_available()


def test_check_cuda_available_detects_working_nvenc(monkeypatch):
    _stub_hardware_probe(monkeypatch, listed=("h264_nvenc",), working=("h264_nvenc",))

    assert ffmpeg.check_cuda_available()


def test_check_cuda_available_handles_listing_failure(monkeypatch):
    monkeypatch.setattr(ffmpeg.sys, "platform", "linux")
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(
        ffmpeg.subprocess,
        "run",
        lambda args, **kwargs: SimpleNamespace(stdout="", returncode=1),
    )

    assert not ffmpeg.check_cuda_available()


def test_normalize_video_codec():
    assert ffmpeg.normalize_video_codec(" HEVC ") == "hevc"
    assert ffmpeg.normalize_video_codec("av1") == "av1"
    assert ffmpeg.normalize_video_codec(None) == "h264"
    assert ffmpeg.normalize_video_codec("vp9") == "h264"


def _stub_videotoolbox_probe(monkeypatch, *, hwaccels: str, encoders: str) -> None:
    """Point FFmpeg probes at canned ``-hwaccels``/``-encoders`` listings."""

    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    def fake_run(args, **kwargs):
        if "-hwaccels" in args:
            return SimpleNamespace(stdout=hwaccels, returncode=0)
        if "-encoders" in args:
            return SimpleNamespace(stdout=encoders, returncode=0)
        raise AssertionError(f"Unexpected args: {args}")

    monkeypatch.setattr(ffmpeg.subprocess, "run", fake_run)


def test_check_videotoolbox_available_detects_encoder(monkeypatch):
    monkeypatch.setattr(ffmpeg.sys, "platform", "darwin")
    _stub_videotoolbox_probe(
        monkeypatch,
        hwaccels="videotoolbox\n",
        encoders="encoder h264_videotoolbox",
    )

    assert ffmpeg.check_videotoolbox_available()


def test_check_videotoolbox_available_requires_encoder(monkeypatch):
    monkeypatch.setattr(ffmpeg.sys, "platform", "darwin")
    _stub_videotoolbox_probe(
        monkeypatch,
        hwaccels="videotoolbox\n",
        encoders="encoder libx264",
    )

    assert not ffmpeg.check_videotoolbox_available()


def test_check_videotoolbox_available_requires_hwaccel(monkeypatch):
    monkeypatch.setattr(ffmpeg.sys, "platform", "darwin")
    _stub_videotoolbox_probe(
        monkeypatch,
        hwaccels="cuda\n",
        encoders="encoder h264_videotoolbox",
    )

    assert not ffmpeg.check_videotoolbox_available()


def test_check_videotoolbox_available_skips_other_platforms(monkeypatch):
    monkeypatch.setattr(ffmpeg.sys, "platform", "linux")

    def unexpected_run(*args, **kwargs):
        raise AssertionError("FFmpeg must not be probed outside macOS")

    monkeypatch.setattr(ffmpeg.subprocess, "run", unexpected_run)

    assert not ffmpeg.check_videotoolbox_available()


def test_encoder_supports_option_reads_encoder_help(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    calls: List[List[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return SimpleNamespace(
            stdout=(
                "h264_videotoolbox AVOptions:\n"
                "  -allow_sw   <boolean>  Allow software encoding\n"
                "  -spatial_aq <int>      Set to 1 to enable spatial AQ\n"
            ),
            returncode=0,
        )

    monkeypatch.setattr(ffmpeg.subprocess, "run", fake_run)

    assert ffmpeg.encoder_supports_option("h264_videotoolbox", "spatial_aq")
    assert not ffmpeg.encoder_supports_option("h264_videotoolbox", "prio_speed")
    # The help output is probed once and reused for both lookups.
    assert len(calls) == 1
    assert "-h" in calls[0] and "encoder=h264_videotoolbox" in calls[0]


def test_encoder_supports_option_handles_probe_failure(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(
        ffmpeg.subprocess,
        "run",
        lambda args, **kwargs: SimpleNamespace(stdout="", returncode=1),
    )

    assert not ffmpeg.encoder_supports_option("h264_videotoolbox", "spatial_aq")


def test_build_video_commands_videotoolbox_adds_spatial_aq_when_supported(monkeypatch):
    """FFmpeg 7.1+ gains ``-spatial_aq``, which suits flat screen recordings."""

    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(
        ffmpeg,
        "encoder_available",
        lambda name, ffmpeg_path=None: name == "hevc_videotoolbox",
    )
    monkeypatch.setattr(
        ffmpeg,
        "encoder_supports_option",
        lambda name, option, ffmpeg_path=None: option == "spatial_aq",
    )

    command, _fallback, use_gpu = ffmpeg.build_video_commands(
        "input.mp4",
        "audio.wav",
        "filter.txt",
        "output.mp4",
        hardware_backend="videotoolbox",
        optimize=True,
        small=False,
        frame_rate=30.0,
        video_codec="hevc",
    )

    assert "-spatial_aq 1" in command
    assert use_gpu


def test_build_video_commands_h264_keeps_software_encoder_on_videotoolbox(monkeypatch):
    """H.264 stays on libx264: Apple's media engine is the slower option there."""

    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(
        ffmpeg, "encoder_available", lambda name, ffmpeg_path=None: True
    )

    command, fallback, use_gpu = ffmpeg.build_video_commands(
        "input.mp4",
        "audio.wav",
        "filter.txt",
        "output.mp4",
        hardware_backend="videotoolbox",
        optimize=True,
        small=False,
        frame_rate=30.0,
    )

    assert "-c:v libx264" in command
    assert "videotoolbox" not in command
    assert fallback is None
    assert not use_gpu


def test_build_video_commands_hevc_videotoolbox(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(
        ffmpeg,
        "encoder_available",
        lambda name, ffmpeg_path=None: name == "hevc_videotoolbox",
    )
    monkeypatch.setattr(
        ffmpeg,
        "encoder_supports_option",
        lambda name, option, ffmpeg_path=None: True,
    )

    command, fallback, use_gpu = ffmpeg.build_video_commands(
        "input.mp4",
        "audio.wav",
        "filter.txt",
        "output.mp4",
        hardware_backend="videotoolbox",
        optimize=False,
        small=False,
        frame_rate=30.0,
        video_codec="hevc",
    )

    assert "-c:v hevc_videotoolbox" in command
    assert "-q:v 68" in command
    assert "-prio_speed 1" in command
    assert use_gpu
    assert fallback is not None
    assert "-c:v libx265" in fallback


def test_build_video_commands_videotoolbox_falls_back_to_cpu(monkeypatch):
    """A macOS build without the encoder must keep the software plan."""

    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(
        ffmpeg, "encoder_available", lambda name, ffmpeg_path=None: False
    )

    command, fallback, use_gpu = ffmpeg.build_video_commands(
        "input.mp4",
        "audio.wav",
        "filter.txt",
        "output.mp4",
        hardware_backend="videotoolbox",
        optimize=True,
        small=False,
        frame_rate=30.0,
        video_codec="hevc",
    )

    assert "-c:v libx265" in command
    assert fallback is None
    assert not use_gpu


def test_build_video_commands_av1_ignores_videotoolbox(monkeypatch):
    """Apple ships no AV1 encoder, so AV1 must stay on the software plan."""

    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(
        ffmpeg, "encoder_available", lambda name, ffmpeg_path=None: True
    )

    command, fallback, use_gpu = ffmpeg.build_video_commands(
        "input.mp4",
        "audio.wav",
        "filter.txt",
        "output.mp4",
        hardware_backend="videotoolbox",
        optimize=True,
        small=False,
        frame_rate=30.0,
        video_codec="av1",
    )

    assert "-c:v libsvtav1" in command
    assert "videotoolbox" not in command
    assert fallback is None
    assert not use_gpu


def test_build_extract_audio_command(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    command = ffmpeg.build_extract_audio_command(
        "input.mp4",
        "output.wav",
        sample_rate=44100,
        audio_bitrate="192k",
        hwaccel=["-hwaccel", "cuda"],
    )

    expected = (
        '"/usr/bin/ffmpeg" -hwaccel cuda -i "input.mp4" '
        '-ab 192k -ac 2 -ar 44100 -vn "output.wav" -hide_banner -loglevel warning -stats'
    )
    assert command == expected


def test_build_audio_only_command_uses_processed_wav(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    command = ffmpeg.build_audio_only_command(
        "input.mp4",
        "audioNew.wav",
        "talk_speedup.mp3",
    )

    expected = (
        '"/usr/bin/ffmpeg" -y -i "audioNew.wav" -vn -map 0:a:0 '
        '-c:a libmp3lame -q:a 2 "talk_speedup.mp3" '
        "-loglevel warning -stats -hide_banner"
    )
    assert command == expected
    assert "libmp3lame" in command
    assert "-q:a 2" in command
    assert "-vn" in command
    # The processed WAV is the source; the original input is not referenced.
    assert "input.mp4" not in command


def test_build_audio_only_command_falls_back_to_input_with_trim(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    command = ffmpeg.build_audio_only_command(
        "input.mp4",
        None,
        "talk.mp3",
        cut_start_seconds=10.0,
        cut_end_seconds=60.0,
    )

    assert '-ss 10 -t 50 -i "input.mp4"' in command
    assert "libmp3lame" in command
    assert "-q:a 2" in command
    assert command.rstrip().endswith("-loglevel warning -stats -hide_banner")
    assert '"talk.mp3"' in command


def test_build_audio_only_command_input_without_trim(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    command = ffmpeg.build_audio_only_command(
        "input.mp4",
        None,
        "talk.mp3",
    )

    assert '"/usr/bin/ffmpeg" -y -i "input.mp4"' in command
    assert "-ss" not in command


def test_build_trim_input_args_full_range():
    assert ffmpeg.build_trim_input_args(10.0, 60.0) == ["-ss 10", "-t 50"]


def test_build_trim_input_args_start_only():
    assert ffmpeg.build_trim_input_args(10.5, 0.0) == ["-ss 10.5"]


def test_build_trim_input_args_no_trim():
    assert ffmpeg.build_trim_input_args(0.0, 0.0) == []


def test_build_trim_input_args_end_only():
    assert ffmpeg.build_trim_input_args(0.0, 30.0) == ["-t 30"]


def test_build_trim_input_args_inverted_range_is_no_trim():
    assert ffmpeg.build_trim_input_args(30.0, 10.0) == []


def test_build_extract_audio_command_with_trim(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    command = ffmpeg.build_extract_audio_command(
        "input.mp4",
        "output.wav",
        sample_rate=44100,
        audio_bitrate="192k",
        cut_start_seconds=10.0,
        cut_end_seconds=60.0,
    )

    assert '-ss 10 -t 50 -i "input.mp4"' in command


def test_build_extract_audio_command_start_only_trim(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    command = ffmpeg.build_extract_audio_command(
        "input.mp4",
        "output.wav",
        sample_rate=44100,
        audio_bitrate="192k",
        cut_start_seconds=10.0,
        cut_end_seconds=0.0,
    )

    assert '-ss 10 -i "input.mp4"' in command
    assert "-t " not in command


def test_build_extract_audio_command_no_trim_unchanged(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    command = ffmpeg.build_extract_audio_command(
        "input.mp4",
        "output.wav",
        sample_rate=44100,
        audio_bitrate="192k",
    )

    assert "-ss " not in command
    assert "-t " not in command


def test_get_video_duration_parses_ffprobe_output(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffprobe_path", lambda: "/usr/bin/ffprobe")

    def fake_run(command, **kwargs):
        assert command[0] == "/usr/bin/ffprobe"
        assert "format=duration" in command
        return SimpleNamespace(returncode=0, stdout="123.45\n", stderr="")

    monkeypatch.setattr(ffmpeg.subprocess, "run", fake_run)

    assert ffmpeg.get_video_duration("input.mp4") == pytest.approx(123.45)


def test_get_video_duration_returns_zero_on_error(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffprobe_path", lambda: "/usr/bin/ffprobe")

    def fake_run(command, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(ffmpeg.subprocess, "run", fake_run)

    assert ffmpeg.get_video_duration("missing.mp4") == 0.0


def test_get_video_duration_handles_missing_ffprobe(monkeypatch):
    def raise_not_found():
        raise ffmpeg.FFmpegNotFoundError("no ffprobe")

    monkeypatch.setattr(ffmpeg, "get_ffprobe_path", raise_not_found)

    assert ffmpeg.get_video_duration("input.mp4") == 0.0


def test_get_video_duration_handles_invalid_output(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffprobe_path", lambda: "/usr/bin/ffprobe")

    def fake_run(command, **kwargs):
        return SimpleNamespace(returncode=0, stdout="N/A\n", stderr="")

    monkeypatch.setattr(ffmpeg.subprocess, "run", fake_run)

    assert ffmpeg.get_video_duration("input.mp4") == 0.0


def test_build_video_commands_with_trim(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    command, _fallback, _use_cuda = ffmpeg.build_video_commands(
        "input.mp4",
        "audio.wav",
        "filter.txt",
        "output.mp4",
        hardware_backend=None,
        optimize=True,
        small=True,
        frame_rate=30.0,
        cut_start_seconds=10.0,
        cut_end_seconds=60.0,
    )

    assert '-ss 10 -t 50 -i "input.mp4"' in command
    # The processed audio stream is already trimmed; it must not be re-trimmed.
    assert '-ss 10 -t 50 -i "audio.wav"' not in command


def test_build_video_commands_no_trim_unchanged(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    command, _fallback, _use_cuda = ffmpeg.build_video_commands(
        "input.mp4",
        "audio.wav",
        "filter.txt",
        "output.mp4",
        hardware_backend=None,
        optimize=True,
        small=True,
        frame_rate=30.0,
    )

    assert "-ss " not in command


def test_build_video_commands_keep_input_audio(monkeypatch):
    """Passing ``keep_input_audio`` re-muxes the input's audio via stream copy."""

    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    command, fallback, use_cuda = ffmpeg.build_video_commands(
        "input.mp4",
        None,
        None,
        "output.mp4",
        hardware_backend=None,
        optimize=True,
        small=False,
        frame_rate=30.0,
        keep_input_audio=True,
    )

    assert "-map 0:v:0 -map 0:a?" in command
    assert "-c:a copy" in command
    assert "-an" not in command
    assert "-c:a aac" not in command
    assert command.count('-i "') == 1


def test_build_video_commands_small_cuda(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(
        ffmpeg, "encoder_available", lambda name, ffmpeg_path=None: False
    )

    command, fallback, use_cuda = ffmpeg.build_video_commands(
        "input.mp4",
        "audio.wav",
        "filter.txt",
        "output.mp4",
        hardware_backend="cuda",
        optimize=True,
        small=True,
        frame_rate=30.0,
        video_codec="hevc",
    )

    assert "-c:v libx265" in command
    assert "-preset medium" in command
    assert "-crf 28" in command
    assert "-forced-idr 1" not in command
    assert "-g 900" in command
    assert "-keyint_min 900" in command
    assert "-force_key_frames expr:gte(t,n_forced*30)" in command
    assert fallback is None
    assert not use_cuda


def test_build_video_commands_small_cpu(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    command, fallback, use_cuda = ffmpeg.build_video_commands(
        "input.mp4",
        "audio.wav",
        "filter.txt",
        "output.mp4",
        hardware_backend=None,
        optimize=True,
        small=True,
        frame_rate=30.0,
    )

    assert "-c:v libx264" in command
    assert "-g 900" in command
    assert "-keyint_min 900" in command
    assert "-force_key_frames expr:gte(t,n_forced*30)" in command
    assert "-forced-idr 1" not in command
    assert fallback is None
    assert not use_cuda


def test_build_video_commands_custom_keyframe_interval(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    command, fallback, use_cuda = ffmpeg.build_video_commands(
        "input.mp4",
        "audio.wav",
        "filter.txt",
        "output.mp4",
        hardware_backend=None,
        optimize=True,
        small=True,
        frame_rate=30.0,
        keyframe_interval_seconds=1.5,
    )

    assert "-g 45" in command
    assert "-keyint_min 45" in command
    assert "-force_key_frames expr:gte(t,n_forced*1.5)" in command
    assert fallback is None
    assert not use_cuda


def test_build_video_commands_large_cuda(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(
        ffmpeg, "encoder_available", lambda name, ffmpeg_path=None: False
    )

    command, fallback, use_cuda = ffmpeg.build_video_commands(
        "input.mp4",
        "audio.wav",
        "filter.txt",
        "output.mp4",
        hardware_backend="cuda",
        optimize=True,
        small=False,
        frame_rate=30.0,
        video_codec="hevc",
    )

    assert "-hwaccel cuda" in command
    assert "-filter_complex_threads 1" not in command
    assert "-c:v libx265" in command
    assert "-g 900" in command
    assert "-keyint_min 900" in command
    assert fallback is None
    assert not use_cuda


def test_build_video_commands_large_cpu(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(
        ffmpeg, "encoder_available", lambda name, ffmpeg_path=None: False
    )

    command, fallback, use_cuda = ffmpeg.build_video_commands(
        "input.mp4",
        "audio.wav",
        "filter.txt",
        "output.mp4",
        hardware_backend=None,
        optimize=True,
        small=False,
        frame_rate=30.0,
    )

    assert "-c:v libx264" in command
    assert "-g 900" in command
    assert "-keyint_min 900" in command
    assert fallback is None
    assert not use_cuda


def test_build_video_commands_large_cuda_fast(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    def fake_encoder_available(name: str, ffmpeg_path: Optional[str] = None) -> bool:
        return name == "hevc_nvenc"

    monkeypatch.setattr(ffmpeg, "encoder_available", fake_encoder_available)

    command, fallback, use_cuda = ffmpeg.build_video_commands(
        "input.mp4",
        "audio.wav",
        "filter.txt",
        "output.mp4",
        hardware_backend="cuda",
        optimize=False,
        small=False,
        frame_rate=30.0,
        video_codec="hevc",
    )

    assert "-hwaccel cuda" in command
    assert "-filter_complex_threads 1" in command
    assert "-c:v hevc_nvenc" in command
    assert "-preset p1" in command
    assert "-rc constqp" in command
    assert "-qp 28" in command
    assert "-g 900" not in command
    assert fallback is not None
    assert "-c:v libx265" in fallback
    assert "-preset ultrafast" in fallback
    assert use_cuda


def test_build_video_commands_hevc_cpu_no_optimize(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(
        ffmpeg, "encoder_available", lambda name, ffmpeg_path=None: False
    )

    command, fallback, use_cuda = ffmpeg.build_video_commands(
        "input.mp4",
        "audio.wav",
        "filter.txt",
        "output.mp4",
        hardware_backend=None,
        optimize=False,
        small=False,
        frame_rate=30.0,
        video_codec="hevc",
    )

    assert "-c:v libx265" in command
    assert "-preset ultrafast" in command
    assert "-crf 30" in command
    assert "-g 900" not in command
    assert fallback is None
    assert not use_cuda


def test_build_video_commands_av1_cuda(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    def fake_encoder_available(name: str, ffmpeg_path: Optional[str] = None) -> bool:
        return name == "av1_nvenc"

    monkeypatch.setattr(ffmpeg, "encoder_available", fake_encoder_available)

    command, fallback, use_cuda = ffmpeg.build_video_commands(
        "input.mp4",
        "audio.wav",
        "filter.txt",
        "output.mp4",
        hardware_backend="cuda",
        optimize=True,
        small=True,
        frame_rate=30.0,
        video_codec="av1",
    )

    assert "-c:v av1_nvenc" in command
    assert "-preset p6" in command
    assert "-rc vbr" in command
    assert "-b:v 0" in command
    assert "-cq 36" in command
    assert "-spatial-aq 1" in command
    assert "-temporal-aq 1" in command
    assert "-g 900" in command
    assert fallback is not None
    assert "-c:v libaom-av1" in fallback
    assert "-row-mt 1" in fallback
    assert use_cuda


def test_build_video_commands_av1_cpu(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(
        ffmpeg, "encoder_available", lambda name, ffmpeg_path=None: False
    )

    command, fallback, use_cuda = ffmpeg.build_video_commands(
        "input.mp4",
        "audio.wav",
        "filter.txt",
        "output.mp4",
        hardware_backend=None,
        optimize=True,
        small=False,
        frame_rate=30.0,
        video_codec="av1",
    )

    assert "-c:v av1_nvenc" not in command
    assert "-c:v libaom-av1" in command
    assert "-crf 32" in command
    assert "-g 900" in command
    assert fallback is None
    assert not use_cuda


def test_build_video_commands_av1_cuda_svt_fallback(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    def fake_encoder_available(name: str, ffmpeg_path: Optional[str] = None) -> bool:
        return name in {"libsvtav1", "av1_nvenc"}

    monkeypatch.setattr(ffmpeg, "encoder_available", fake_encoder_available)

    command, fallback, use_cuda = ffmpeg.build_video_commands(
        "input.mp4",
        "audio.wav",
        "filter.txt",
        "output.mp4",
        hardware_backend="cuda",
        optimize=True,
        small=True,
        frame_rate=30.0,
        video_codec="av1",
    )

    assert "-c:v av1_nvenc" in command
    assert fallback is not None
    assert "-c:v libsvtav1" in fallback
    assert "-preset 6" in fallback
    assert use_cuda


def test_build_video_commands_hevc_cuda(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    def fake_encoder_available(name: str, ffmpeg_path: Optional[str] = None) -> bool:
        return name == "hevc_nvenc"

    monkeypatch.setattr(ffmpeg, "encoder_available", fake_encoder_available)

    command, fallback, use_cuda = ffmpeg.build_video_commands(
        "input.mp4",
        "audio.wav",
        "filter.txt",
        "output.mp4",
        hardware_backend="cuda",
        optimize=True,
        small=True,
        frame_rate=30.0,
        video_codec="hevc",
    )

    assert "-c:v hevc_nvenc" in command
    assert "-preset p6" in command
    assert "-rc vbr" in command
    assert "-b:v 0" in command
    assert "-cq 32" in command
    assert "-spatial-aq 1" in command
    assert "-temporal-aq 1" in command
    assert "-rc-lookahead 32" in command
    assert "-multipass fullres" in command
    assert "-g 900" in command
    assert fallback is not None
    assert "-c:v libx265" in fallback
    assert "-preset medium" in fallback
    assert use_cuda


def test_build_video_commands_hevc_cpu(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(
        ffmpeg, "encoder_available", lambda name, ffmpeg_path=None: False
    )

    command, fallback, use_cuda = ffmpeg.build_video_commands(
        "input.mp4",
        "audio.wav",
        "filter.txt",
        "output.mp4",
        hardware_backend=None,
        optimize=True,
        small=False,
        frame_rate=30.0,
        video_codec="hevc",
    )

    assert "-c:v hevc_nvenc" not in command
    assert "-c:v libx265" in command
    assert "-crf 28" in command
    assert "-g 900" in command
    assert fallback is None
    assert not use_cuda


class FakeStream:
    def __init__(self, lines: List[str]) -> None:
        self._lines = lines
        self._index = 0

    def readline(self) -> str:
        if self._index < len(self._lines):
            line = self._lines[self._index]
            self._index += 1
            return line
        return ""

    def read(self) -> str:
        return ""


class FakeProcess:
    def __init__(self, lines: List[str]) -> None:
        self.stderr = FakeStream(lines)
        self.stdout = io.StringIO("")
        self._lines = lines
        self.returncode = 0

    def poll(self) -> Optional[int]:
        if self.stderr._index >= len(self._lines):
            return 0
        return None

    def wait(self) -> None:
        self.returncode = 0


def test_run_timed_ffmpeg_command_reports_progress(monkeypatch):
    reporter = DummyProgressReporter()
    fake_lines = [
        "frame=   10 fps=30.0 q=-1.0\n",
        "warning: something\n",
        "encoded successfully\n",
    ]

    captured_kwargs = {}

    def fake_popen(args, **kwargs):
        captured_kwargs["args"] = args
        captured_kwargs["kwargs"] = kwargs
        return FakeProcess(fake_lines)

    fake_stderr = io.StringIO()
    monkeypatch.setattr(ffmpeg.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(ffmpeg.sys, "stderr", fake_stderr)

    callbacks: List[FakeProcess] = []

    def process_callback(proc):
        callbacks.append(proc)

    ffmpeg.run_timed_ffmpeg_command(
        "ffmpeg -i input.mp4",
        reporter=reporter,
        desc="Processing",
        total=100,
        process_callback=process_callback,
    )

    assert not any("frame=" in log for log in reporter.logs)
    assert any("warning" in log for log in reporter.logs)
    assert any("encoded successfully" in log for log in reporter.logs)
    assert reporter.tasks[0].current == 10
    assert reporter.tasks[0].finished
    assert callbacks and isinstance(callbacks[0], FakeProcess)
    assert "stderr" in captured_kwargs["kwargs"]
    assert "frame=" in fake_stderr.getvalue()


class StallingStream:
    """A fake stderr stream that produces one line then blocks forever."""

    def __init__(self) -> None:
        import threading

        self._calls = 0
        self._unblock = threading.Event()

    def readline(self) -> str:
        self._calls += 1
        if self._calls == 1:
            return "frame=   1 fps=30.0\n"
        # Block until the process is killed (unblock event set)
        self._unblock.wait()
        return ""

    def read(self) -> str:
        return ""


class StallingProcess:
    def __init__(self) -> None:
        self.stderr = StallingStream()
        self.stdout = io.StringIO("")
        self.returncode = None
        self._killed = False

    def poll(self) -> Optional[int]:
        if self._killed:
            return -9
        return None  # always running

    def wait(self, timeout=None) -> None:
        self._killed = True
        self.stderr._unblock.set()
        self.returncode = -9

    def terminate(self) -> None:
        self._killed = True
        self.stderr._unblock.set()
        self.returncode = -9

    def kill(self) -> None:
        self._killed = True
        self.stderr._unblock.set()
        self.returncode = -9

    @property
    def pid(self):
        return 99999


def test_run_timed_ffmpeg_command_stall_timeout(monkeypatch):
    """FFmpegStallTimeout is raised when no output arrives within the deadline."""
    reporter = DummyProgressReporter()

    proc = StallingProcess()

    def fake_popen(args, **kwargs):
        return proc

    monkeypatch.setattr(ffmpeg.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(ffmpeg.sys, "stderr", io.StringIO())
    monkeypatch.setattr(ffmpeg, "_force_kill_process", lambda p: p.kill())

    with pytest.raises(ffmpeg.FFmpegStallTimeout, match="no output"):
        ffmpeg.run_timed_ffmpeg_command(
            "ffmpeg -i input.mp4",
            reporter=reporter,
            stall_timeout=2,  # 2 seconds for a fast test
        )

    assert any("no output" in log for log in reporter.logs)


def _fake_ffmpeg_binary(tmp_path) -> str:
    """Create a file that stands in for the FFmpeg binary so it can be stat'ed."""

    binary = tmp_path / "ffmpeg.exe"
    binary.write_bytes(b"binary")
    return str(binary)


def test_ffmpeg_fingerprint_describes_binary(tmp_path):
    path = _fake_ffmpeg_binary(tmp_path)

    fingerprint = ffmpeg._ffmpeg_fingerprint(path)

    assert fingerprint == {
        "path": os.path.abspath(path),
        "size": 6,
        "mtime": int(Path(path).stat().st_mtime),
    }


def test_ffmpeg_fingerprint_is_none_for_missing_binary(tmp_path):
    assert ffmpeg._ffmpeg_fingerprint(str(tmp_path / "missing.exe")) is None


def test_cached_backend_round_trip(tmp_path):
    fingerprint = ffmpeg._ffmpeg_fingerprint(_fake_ffmpeg_binary(tmp_path))

    assert ffmpeg._write_cached_backend(
        fingerprint, "hevc", {"backend": "qsv", "checked_at": 1000}
    )

    assert ffmpeg._read_cached_backend(fingerprint, "hevc", now=1060) == (True, "qsv")
    assert ffmpeg._read_cached_backend(fingerprint, "av1", now=1060) == (False, None)


def test_cached_backend_stores_absent_gpu(tmp_path):
    fingerprint = ffmpeg._ffmpeg_fingerprint(_fake_ffmpeg_binary(tmp_path))
    ffmpeg._write_cached_backend(
        fingerprint, "hevc", {"backend": None, "checked_at": 1000}
    )

    assert ffmpeg._read_cached_backend(fingerprint, "hevc", now=1060) == (True, None)


def test_cached_backend_expires_after_thirty_days(tmp_path):
    fingerprint = ffmpeg._ffmpeg_fingerprint(_fake_ffmpeg_binary(tmp_path))
    ffmpeg._write_cached_backend(
        fingerprint, "hevc", {"backend": "qsv", "checked_at": 1000}
    )
    max_age = ffmpeg.HARDWARE_CACHE_MAX_AGE_SECONDS

    assert ffmpeg._read_cached_backend(fingerprint, "hevc", now=1000 + max_age - 1)[0]
    assert not ffmpeg._read_cached_backend(fingerprint, "hevc", now=1000 + max_age)[0]


def test_cached_backend_rejects_changed_ffmpeg(tmp_path):
    path = _fake_ffmpeg_binary(tmp_path)
    old = ffmpeg._ffmpeg_fingerprint(path)
    ffmpeg._write_cached_backend(old, "hevc", {"backend": "qsv", "checked_at": 1000})

    Path(path).write_bytes(b"a newer and longer binary")
    new = ffmpeg._ffmpeg_fingerprint(path)

    assert ffmpeg._read_cached_backend(new, "hevc", now=1060) == (False, None)


@pytest.mark.parametrize(
    "record",
    [
        {"backend": "vulkan", "checked_at": 1000},
        {"backend": "qsv", "checked_at": "yesterday"},
        {"backend": "qsv", "checked_at": True},
        {"backend": "qsv"},
        "qsv",
    ],
)
def test_cached_backend_rejects_malformed_record(tmp_path, record):
    fingerprint = ffmpeg._ffmpeg_fingerprint(_fake_ffmpeg_binary(tmp_path))
    ffmpeg._hardware_cache_path().write_text(
        json.dumps(
            {"hardware_backend": {"ffmpeg": fingerprint, "codecs": {"hevc": record}}}
        ),
        encoding="utf-8",
    )

    assert ffmpeg._read_cached_backend(fingerprint, "hevc", now=1060) == (False, None)


def test_cached_backend_rejects_malformed_entry(tmp_path):
    fingerprint = ffmpeg._ffmpeg_fingerprint(_fake_ffmpeg_binary(tmp_path))
    ffmpeg._hardware_cache_path().write_text(
        json.dumps({"hardware_backend": "qsv"}), encoding="utf-8"
    )

    assert ffmpeg._read_cached_backend(fingerprint, "hevc", now=1060) == (False, None)


def test_write_cached_backend_keeps_other_settings(tmp_path):
    settings_path = ffmpeg._hardware_cache_path()
    settings_path.write_text(
        json.dumps({"presets": [], "theme": "dark"}), encoding="utf-8"
    )
    fingerprint = ffmpeg._ffmpeg_fingerprint(_fake_ffmpeg_binary(tmp_path))

    assert ffmpeg._write_cached_backend(
        fingerprint, "hevc", {"backend": "qsv", "checked_at": 1000}
    )

    stored = json.loads(settings_path.read_text(encoding="utf-8"))
    assert stored["presets"] == []
    assert stored["theme"] == "dark"


def test_write_cached_backend_skips_unreadable_settings(tmp_path):
    settings_path = ffmpeg._hardware_cache_path()
    settings_path.write_text("{not json", encoding="utf-8")
    fingerprint = ffmpeg._ffmpeg_fingerprint(_fake_ffmpeg_binary(tmp_path))

    assert not ffmpeg._write_cached_backend(
        fingerprint, "hevc", {"backend": "qsv", "checked_at": 1000}
    )
    assert settings_path.read_text(encoding="utf-8") == "{not json"


def test_write_cached_backend_removes_one_codec(tmp_path):
    fingerprint = ffmpeg._ffmpeg_fingerprint(_fake_ffmpeg_binary(tmp_path))
    record = {"backend": "qsv", "checked_at": 1000}
    ffmpeg._write_cached_backend(fingerprint, "hevc", record)
    ffmpeg._write_cached_backend(fingerprint, "av1", record)

    assert ffmpeg._write_cached_backend(fingerprint, "hevc", None)

    assert ffmpeg._read_cached_backend(fingerprint, "hevc", now=1060) == (False, None)
    assert ffmpeg._read_cached_backend(fingerprint, "av1", now=1060) == (True, "qsv")


def test_write_cached_backend_resets_entry_for_new_ffmpeg(tmp_path):
    path = _fake_ffmpeg_binary(tmp_path)
    old = ffmpeg._ffmpeg_fingerprint(path)
    ffmpeg._write_cached_backend(old, "hevc", {"backend": "qsv", "checked_at": 1000})
    Path(path).write_bytes(b"a newer and longer binary")
    new = ffmpeg._ffmpeg_fingerprint(path)

    ffmpeg._write_cached_backend(new, "av1", {"backend": None, "checked_at": 1000})

    stored = json.loads(ffmpeg._hardware_cache_path().read_text(encoding="utf-8"))
    assert stored["hardware_backend"] == {
        "ffmpeg": new,
        "codecs": {"av1": {"backend": None, "checked_at": 1000}},
    }


def _build_with_backend(monkeypatch, backend, *, codec, optimize=True, listed=True):
    """Build commands with every encoder reported as present (or absent)."""

    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(
        ffmpeg, "encoder_available", lambda name, ffmpeg_path=None: listed
    )
    return ffmpeg.build_video_commands(
        "input.mp4",
        "audio.wav",
        "filter.txt",
        "output.mp4",
        hardware_backend=backend,
        optimize=optimize,
        small=False,
        frame_rate=30.0,
        video_codec=codec,
    )


def test_build_video_commands_hevc_qsv_optimized(monkeypatch):
    command, fallback, use_gpu = _build_with_backend(monkeypatch, "qsv", codec="hevc")

    assert "-c:v hevc_qsv" in command
    assert "-preset medium" in command
    assert "-global_quality 28" in command
    assert "-g 900" in command
    assert "-hwaccel" not in command
    assert use_gpu
    assert fallback is not None and "-c:v libx265" in fallback


def test_build_video_commands_av1_qsv_fast(monkeypatch):
    command, fallback, use_gpu = _build_with_backend(
        monkeypatch, "qsv", codec="av1", optimize=False
    )

    assert "-c:v av1_qsv" in command
    assert "-preset veryfast" in command
    assert "-global_quality 32" in command
    assert use_gpu
    assert fallback is not None and "-c:v libaom-av1" in fallback


def test_build_video_commands_hevc_amf_optimized(monkeypatch):
    command, fallback, use_gpu = _build_with_backend(monkeypatch, "amf", codec="hevc")

    assert "-c:v hevc_amf" in command
    assert "-quality balanced" in command
    assert "-rc cqp" in command
    assert "-qp_i 26" in command
    assert "-qp_p 28" in command
    assert use_gpu
    assert fallback is not None and "-c:v libx265" in fallback


def test_build_video_commands_av1_amf_fast(monkeypatch):
    command, _fallback, use_gpu = _build_with_backend(
        monkeypatch, "amf", codec="av1", optimize=False
    )

    assert "-c:v av1_amf" in command
    assert "-quality speed" in command
    assert "-qp_i 30" in command
    assert "-qp_p 32" in command
    assert use_gpu


@pytest.mark.parametrize("backend", ["qsv", "amf"])
def test_build_video_commands_h264_stays_on_libx264(monkeypatch, backend):
    """H.264 on QSV was slower and larger than libx264 veryfast in benchmarks."""

    command, fallback, use_gpu = _build_with_backend(monkeypatch, backend, codec="h264")

    assert "-c:v libx264" in command
    assert backend not in command
    assert fallback is None
    assert not use_gpu


def test_build_video_commands_qsv_without_listed_encoder_uses_cpu(monkeypatch):
    command, fallback, use_gpu = _build_with_backend(
        monkeypatch, "qsv", codec="hevc", listed=False
    )

    assert "-c:v libx265" in command
    assert fallback is None
    assert not use_gpu


def test_build_video_commands_cuda_decodes_on_gpu(monkeypatch):
    command, fallback, _use_gpu = _build_with_backend(monkeypatch, "cuda", codec="hevc")

    assert "-hwaccel cuda" in command
    assert fallback is not None and "-hwaccel" not in fallback
