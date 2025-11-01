"""Tests for :mod:`talks_reducer.ffmpeg`."""

from __future__ import annotations

import io
import sys
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
    monkeypatch.setattr(ffmpeg.os.path, "isfile", lambda path: path == expected_ffprobe)
    monkeypatch.setattr(ffmpeg, "shutil_which", lambda path: None)

    result = ffmpeg.find_ffprobe()

    assert result == ffmpeg.os.path.abspath(expected_ffprobe)


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


def test_check_cuda_available_detects_nvenc(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    def fake_run(args, **kwargs):
        if "-hwaccels" in args:
            return SimpleNamespace(stdout="cuda\n", returncode=0)
        if "-encoders" in args:
            return SimpleNamespace(stdout="encoder h264_nvenc", returncode=0)
        raise AssertionError(f"Unexpected args: {args}")

    monkeypatch.setattr(ffmpeg.subprocess, "run", fake_run)

    assert ffmpeg.check_cuda_available()


def test_check_cuda_available_handles_missing_nvenc(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    def fake_run(args, **kwargs):
        if "-hwaccels" in args:
            return SimpleNamespace(stdout="cuda\n", returncode=0)
        if "-encoders" in args:
            return SimpleNamespace(stdout="encoder libx264", returncode=0)
        raise AssertionError(f"Unexpected args: {args}")

    monkeypatch.setattr(ffmpeg.subprocess, "run", fake_run)

    assert not ffmpeg.check_cuda_available()


def test_check_cuda_available_requires_cuda_hwaccel(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    def fake_run(args, **kwargs):
        if "-hwaccels" in args:
            return SimpleNamespace(stdout="qsv\nonevapi", returncode=0)
        if "-encoders" in args:
            return SimpleNamespace(stdout="encoder h264_nvenc", returncode=0)
        raise AssertionError(f"Unexpected args: {args}")

    monkeypatch.setattr(ffmpeg.subprocess, "run", fake_run)

    assert not ffmpeg.check_cuda_available()


def test_check_cuda_available_handles_errors(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    def failing_run(args, **kwargs):
        return SimpleNamespace(stdout="", returncode=1)

    monkeypatch.setattr(ffmpeg.subprocess, "run", failing_run)
    assert not ffmpeg.check_cuda_available()

    def raise_timeout(*args, **kwargs):
        raise ffmpeg.subprocess.TimeoutExpired(cmd=args, timeout=5)

    monkeypatch.setattr(ffmpeg.subprocess, "run", raise_timeout)
    assert not ffmpeg.check_cuda_available()

    def raise_called_process_error(args, **kwargs):
        raise ffmpeg.subprocess.CalledProcessError(returncode=1, cmd=args)

    monkeypatch.setattr(ffmpeg.subprocess, "run", raise_called_process_error)
    assert not ffmpeg.check_cuda_available()

    def raise_file_not_found(args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(ffmpeg.subprocess, "run", raise_file_not_found)
    assert not ffmpeg.check_cuda_available()


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


def test_build_video_commands_small_cuda(monkeypatch):
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    command, fallback, use_cuda = ffmpeg.build_video_commands(
        "input.mp4",
        "audio.wav",
        "filter.txt",
        "output.mp4",
        cuda_available=True,
        optimize=True,
        small=True,
        frame_rate=30.0,
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
        cuda_available=False,
        optimize=True,
        small=True,
        frame_rate=30.0,
    )

    assert "-c:v libx265" in command
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
        cuda_available=False,
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
        cuda_available=True,
        optimize=True,
        small=False,
        frame_rate=30.0,
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
        cuda_available=False,
        optimize=True,
        small=False,
        frame_rate=30.0,
    )

    assert "-c:v libx265" in command
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
        cuda_available=True,
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
        cuda_available=False,
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
        cuda_available=True,
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
        cuda_available=False,
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
        cuda_available=True,
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
        cuda_available=True,
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
        cuda_available=False,
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

    assert "frame=   10" in reporter.logs[0]
    assert any("warning" in log for log in reporter.logs)
    assert reporter.tasks[0].current == 10
    assert reporter.tasks[0].finished
    assert callbacks and isinstance(callbacks[0], FakeProcess)
    assert "stderr" in captured_kwargs["kwargs"]
    assert "frame=" in fake_stderr.getvalue()
