from __future__ import annotations

import sys
from pathlib import Path
from queue import SimpleQueue
from typing import Iterator

import gradio as gr
import pytest
from PIL import Image

from talks_reducer import server, server_tray
from talks_reducer.models import ProcessingOptions, ProcessingResult


class DummyProgress:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int, str]] = []

    def __call__(self, current: int, *, total: int, desc: str) -> None:
        self.calls.append((current, total, desc))


class DummyProgressWidget:
    def __init__(self) -> None:
        self.calls: list[tuple[float, int, str]] = []

    def __call__(self, percent: float, *, total: int, desc: str) -> None:
        self.calls.append((percent, total, desc))


def _stub_reporter_factory(progress_callback, log_callback):
    class _Reporter(server.SignalProgressReporter):
        def __init__(self) -> None:
            super().__init__()
            self._progress_callback = progress_callback
            self._log_callback = log_callback

        def log(self, message: str) -> None:  # pragma: no cover - simple forwarding
            if self._log_callback is not None:
                self._log_callback(message)

        def progress(self, current: int, total: int, desc: str) -> None:
            if self._progress_callback is not None:
                self._progress_callback(current, total, desc)

    return _Reporter()


def test_run_pipeline_job_emits_log_progress_and_result(tmp_path: Path) -> None:
    input_file = tmp_path / "input.mp4"
    output_file = tmp_path / "output.mp4"
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    input_file.write_bytes(b"")

    options = ProcessingOptions(
        input_file=input_file,
        output_file=output_file,
        temp_folder=temp_dir,
        small=False,
    )

    result = ProcessingResult(
        input_file=input_file,
        output_file=output_file,
        frame_rate=30.0,
        original_duration=120.0,
        output_duration=60.0,
        chunk_count=3,
        used_cuda=False,
        max_audio_volume=0.5,
        time_ratio=0.5,
        size_ratio=0.4,
    )

    def _speed_up(options: ProcessingOptions, reporter: server.SignalProgressReporter):
        reporter.log("Starting job")
        reporter.progress(5, 10, "Encoding")
        return result

    events = SimpleQueue()

    event_stream = server.run_pipeline_job(
        options,
        speed_up=_speed_up,
        reporter_factory=_stub_reporter_factory,
        events=events,
        enable_progress=True,
        start_in_thread=False,
    )

    emitted = list(event_stream)

    assert [kind for kind, _ in emitted] == [
        "log",
        "progress",
        "log",
        "result",
    ]
    assert emitted[0][1] == "Starting job"
    assert emitted[1][1] == (5, 10, "Encoding")
    assert emitted[-1][1] is result


def test_run_pipeline_job_wraps_exceptions_with_gradio_error(tmp_path: Path) -> None:
    input_file = tmp_path / "input.mp4"
    output_file = tmp_path / "output.mp4"
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    input_file.write_bytes(b"")

    options = ProcessingOptions(
        input_file=input_file,
        output_file=output_file,
        temp_folder=temp_dir,
        small=False,
    )

    def _speed_up(_options: ProcessingOptions, reporter: server.SignalProgressReporter):
        raise RuntimeError("pipeline exploded")

    events = SimpleQueue()

    event_stream = server.run_pipeline_job(
        options,
        speed_up=_speed_up,
        reporter_factory=_stub_reporter_factory,
        events=events,
        enable_progress=True,
        start_in_thread=False,
    )

    emitted = list(event_stream)

    assert [kind for kind, _ in emitted] == ["log", "error"]
    assert "pipeline exploded" in emitted[0][1]
    error = emitted[1][1]
    assert isinstance(error, gr.Error)
    assert "Failed to process the video" in str(error)


def test_describe_server_host_prefers_hostname_and_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server.socket, "gethostname", lambda: "talks-reducer-host")
    monkeypatch.setattr(server.socket, "gethostbyname", lambda _host: "192.0.2.15")

    assert server._describe_server_host() == "talks-reducer-host (192.0.2.15)"


def test_describe_server_host_handles_lookup_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server.socket, "gethostname", lambda: "")

    def _explode(_host: str) -> str:
        raise OSError("no network")

    monkeypatch.setattr(server.socket, "gethostbyname", _explode)

    assert server._describe_server_host() == "unknown"


def test_build_output_path_mirrors_cli_naming(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    output_path = server._build_output_path(Path("video.mp4"), workspace, small=False)
    small_output = server._build_output_path(Path("video.mp4"), workspace, small=True)

    assert output_path.name.endswith("_speedup.mp4")
    assert small_output.name.endswith("_speedup_small.mp4")


def test_build_output_path_includes_codec_suffix(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    output_path = server._build_output_path(
        Path("video.mp4"),
        workspace,
        small=False,
        add_codec_suffix=True,
        video_codec="AV1",
    )

    assert output_path.name == "video_speedup_av1.mp4"


def test_build_output_path_without_speedup_forces_codec(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    output_path = server._build_output_path(
        Path("video.mp4"),
        workspace,
        small=False,
        video_codec="h264",
        silent_speed=1.0,
        sounded_speed=1.0,
    )

    assert output_path.name == "video_h264.mp4"


def test_format_duration_handles_hours_minutes_seconds() -> None:
    assert server._format_duration(3665) == "1h 1m 5s"
    assert server._format_duration(0) == "0s"


def test_format_summary_includes_ratios() -> None:
    result = ProcessingResult(
        input_file=Path("input.mp4"),
        output_file=Path("output.mp4"),
        frame_rate=30.0,
        original_duration=120.0,
        output_duration=90.0,
        chunk_count=4,
        used_cuda=True,
        max_audio_volume=0.8,
        time_ratio=0.75,
        size_ratio=0.5,
    )

    summary = server._format_summary(result)

    assert "75.0%" in summary
    assert "50.0%" in summary
    assert "CUDA" in summary


def test_cleanup_workspaces_removes_temporary_directories(tmp_path: Path) -> None:
    workspaces = [tmp_path / "ws1", tmp_path / "ws2"]
    for workspace in workspaces:
        workspace.mkdir()
    server._WORKSPACES.extend(workspaces)

    server._cleanup_workspaces()

    for workspace in workspaces:
        assert not workspace.exists()
    assert server._WORKSPACES == []


def test_gradio_progress_reporter_updates_progress() -> None:
    progress = DummyProgress()
    reporter = server.GradioProgressReporter(
        progress_callback=lambda current, total, desc: progress(
            current, total=total, desc=desc
        )
    )

    with reporter.task(desc="Stage", total=10, unit="frames") as handle:
        handle.advance(3)
        handle.ensure_total(12)
        handle.advance(9)

    assert progress.calls[0] == (0, 10, "Stage")
    assert progress.calls[-1] == (12, 12, "Stage")


def test_process_video_streams_events_and_returns_result(tmp_path: Path) -> None:
    input_file = tmp_path / "clip.mp4"
    input_file.write_bytes(b"data")
    progress_widget = DummyProgressWidget()

    def _speed_up(options: ProcessingOptions, reporter: server.SignalProgressReporter):
        assert options.input_file == input_file
        assert options.silent_threshold == pytest.approx(0.2)
        assert options.sounded_speed == pytest.approx(1.5)
        assert options.silent_speed == pytest.approx(3.0)
        assert options.video_codec == "av1"
        assert options.add_codec_suffix is False
        assert options.prefer_global_ffmpeg is False
        assert options.prefer_global_ffmpeg is False

        with reporter.task(desc="Encode", total=10, unit="frames") as task:
            task.advance(5)

        reporter.log("Halfway done")

        return ProcessingResult(
            input_file=options.input_file,
            output_file=options.output_file or input_file,
            frame_rate=24.0,
            original_duration=120.0,
            output_duration=30.0,
            chunk_count=5,
            used_cuda=False,
            max_audio_volume=0.6,
            time_ratio=0.25,
            size_ratio=0.3,
        )

    dependencies = server.ProcessVideoDependencies(
        speed_up=_speed_up,
        reporter_factory=server._default_reporter_factory,
        queue_factory=SimpleQueue,
        run_pipeline_job_func=server.run_pipeline_job,
        start_in_thread=False,
    )

    try:
        outputs = list(
            server.process_video(
                str(input_file),
                small_video=False,
                video_codec="av1",
                silent_threshold=0.2,
                sounded_speed=1.5,
                silent_speed=3.0,
                progress=progress_widget,
                dependencies=dependencies,
            )
        )
    finally:
        server._cleanup_workspaces()

    assert len(outputs) >= 2
    final = outputs[-1]

    assert Path(final[0]).name.endswith("_speedup.mp4")
    assert "Halfway done" in final[1]
    assert "Processing complete." in final[1]
    assert "25.0%" in final[2]
    assert "30.0%" in final[2]
    assert final[3] == final[0]

    assert progress_widget.calls
    assert progress_widget.calls[0] == (0.0, 10, "Encode")
    assert progress_widget.calls[-1] == (1.0, 10, "Encode")


def test_process_video_honors_small_480_flag(tmp_path: Path) -> None:
    input_file = tmp_path / "clip.mp4"
    input_file.write_bytes(b"data")

    def _speed_up(options: ProcessingOptions, reporter: server.SignalProgressReporter):
        assert options.small is True
        assert options.small_target_height == 480
        assert options.video_codec == "hevc"
        assert options.add_codec_suffix is False
        assert options.prefer_global_ffmpeg is False
        return ProcessingResult(
            input_file=options.input_file,
            output_file=options.output_file or options.input_file,
            frame_rate=24.0,
            original_duration=120.0,
            output_duration=30.0,
            chunk_count=5,
            used_cuda=False,
            max_audio_volume=0.6,
            time_ratio=0.25,
            size_ratio=0.3,
        )

    dependencies = server.ProcessVideoDependencies(
        speed_up=_speed_up,
        reporter_factory=server._default_reporter_factory,
        queue_factory=SimpleQueue,
        run_pipeline_job_func=server.run_pipeline_job,
        start_in_thread=False,
    )

    try:
        outputs = list(
            server.process_video(
                str(input_file),
                small_video=True,
                small_480=True,
                progress=None,
                dependencies=dependencies,
            )
        )
    finally:
        server._cleanup_workspaces()

    assert outputs
    final = outputs[-1]
    assert Path(final[0]).name.endswith("_speedup_small_480.mp4")


def test_process_video_honors_add_codec_suffix(tmp_path: Path) -> None:
    input_file = tmp_path / "clip.mp4"
    input_file.write_bytes(b"data")

    def _speed_up(options: ProcessingOptions, reporter: server.SignalProgressReporter):
        assert options.add_codec_suffix is True
        assert options.video_codec == "h264"
        return ProcessingResult(
            input_file=options.input_file,
            output_file=options.output_file or options.input_file,
            frame_rate=24.0,
            original_duration=120.0,
            output_duration=30.0,
            chunk_count=5,
            used_cuda=False,
            max_audio_volume=0.6,
            time_ratio=0.25,
            size_ratio=0.3,
        )

    dependencies = server.ProcessVideoDependencies(
        speed_up=_speed_up,
        reporter_factory=server._default_reporter_factory,
        queue_factory=SimpleQueue,
        run_pipeline_job_func=server.run_pipeline_job,
        start_in_thread=False,
    )

    outputs = list(
        server.process_video(
            str(input_file),
            small_video=False,
            video_codec="h264",
            add_codec_suffix=True,
            dependencies=dependencies,
        )
    )

    assert outputs
    final = outputs[-1]
    assert Path(final[0]).name.endswith("_speedup_h264.mp4")


def test_process_video_without_speedup_forces_codec(tmp_path: Path) -> None:
    input_file = tmp_path / "clip.mp4"
    input_file.write_bytes(b"data")

    def _speed_up(options: ProcessingOptions, reporter: server.SignalProgressReporter):
        assert options.silent_speed == pytest.approx(1.0)
        assert options.sounded_speed == pytest.approx(1.0)
        assert options.video_codec == "av1"
        assert options.add_codec_suffix is False
        return ProcessingResult(
            input_file=options.input_file,
            output_file=options.output_file or options.input_file,
            frame_rate=24.0,
            original_duration=120.0,
            output_duration=30.0,
            chunk_count=5,
            used_cuda=False,
            max_audio_volume=0.6,
            time_ratio=0.25,
            size_ratio=0.3,
        )

    dependencies = server.ProcessVideoDependencies(
        speed_up=_speed_up,
        reporter_factory=server._default_reporter_factory,
        queue_factory=SimpleQueue,
        run_pipeline_job_func=server.run_pipeline_job,
        start_in_thread=False,
    )

    outputs = list(
        server.process_video(
            str(input_file),
            small_video=False,
            video_codec="av1",
            silent_speed=1.0,
            sounded_speed=1.0,
            dependencies=dependencies,
        )
    )

    assert outputs
    final = outputs[-1]
    assert Path(final[0]).name == "clip_av1.mp4"


def test_process_video_honors_use_global_ffmpeg(tmp_path: Path) -> None:
    input_file = tmp_path / "clip.mp4"
    input_file.write_bytes(b"data")

    def _speed_up(options: ProcessingOptions, reporter: server.SignalProgressReporter):
        assert options.prefer_global_ffmpeg is True
        assert options.add_codec_suffix is False
        return ProcessingResult(
            input_file=options.input_file,
            output_file=options.output_file or options.input_file,
            frame_rate=24.0,
            original_duration=120.0,
            output_duration=30.0,
            chunk_count=5,
            used_cuda=False,
            max_audio_volume=0.6,
            time_ratio=0.25,
            size_ratio=0.3,
        )

    dependencies = server.ProcessVideoDependencies(
        speed_up=_speed_up,
        reporter_factory=server._default_reporter_factory,
        queue_factory=SimpleQueue,
        run_pipeline_job_func=server.run_pipeline_job,
        start_in_thread=False,
    )

    outputs = list(
        server.process_video(
            str(input_file),
            small_video=False,
            use_global_ffmpeg=True,
            dependencies=dependencies,
        )
    )

    assert outputs[-1][0] is not None


def test_process_video_accepts_hevc_codec(tmp_path: Path) -> None:
    input_file = tmp_path / "clip.mp4"
    input_file.write_bytes(b"data")

    seen_codecs: list[str] = []

    def _speed_up(options: ProcessingOptions, reporter: server.SignalProgressReporter):
        seen_codecs.append(options.video_codec)
        return ProcessingResult(
            input_file=options.input_file,
            output_file=options.output_file or options.input_file,
            frame_rate=24.0,
            original_duration=120.0,
            output_duration=30.0,
            chunk_count=5,
            used_cuda=False,
            max_audio_volume=0.6,
            time_ratio=0.25,
            size_ratio=0.3,
        )

    dependencies = server.ProcessVideoDependencies(
        speed_up=_speed_up,
        reporter_factory=server._default_reporter_factory,
        queue_factory=SimpleQueue,
        run_pipeline_job_func=server.run_pipeline_job,
        start_in_thread=False,
    )

    try:
        outputs = list(
            server.process_video(
                str(input_file),
                small_video=False,
                video_codec="hevc",
                progress=None,
                dependencies=dependencies,
            )
        )
    finally:
        server._cleanup_workspaces()

    assert outputs[-1][0] is not None
    assert seen_codecs == ["hevc"]


def test_process_video_raises_when_pipeline_reports_error(
    tmp_path: Path,
) -> None:
    input_file = tmp_path / "clip.mp4"
    input_file.write_bytes(b"data")

    def _run_pipeline_job(**_kwargs: object) -> Iterator[server.PipelineEvent]:
        yield ("error", gr.Error("boom"))

    dependencies = server.ProcessVideoDependencies(
        run_pipeline_job_func=lambda *args, **kwargs: _run_pipeline_job(),
        queue_factory=SimpleQueue,
        start_in_thread=False,
    )

    try:
        with pytest.raises(gr.Error, match="boom"):
            list(
                server.process_video(
                    str(input_file),
                    small_video=False,
                    progress=None,
                    dependencies=dependencies,
                )
            )
    finally:
        server._cleanup_workspaces()


def test_process_video_raises_when_no_result_emitted(tmp_path: Path) -> None:
    input_file = tmp_path / "clip.mp4"
    input_file.write_bytes(b"data")

    dependencies = server.ProcessVideoDependencies(
        run_pipeline_job_func=lambda *args, **kwargs: iter(()),
        queue_factory=SimpleQueue,
        start_in_thread=False,
    )

    try:
        with pytest.raises(gr.Error, match="Failed to process the video"):
            list(
                server.process_video(
                    str(input_file),
                    small_video=False,
                    progress=None,
                    dependencies=dependencies,
                )
            )
    finally:
        server._cleanup_workspaces()


def test_process_video_validates_input_arguments(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.mp4"

    with pytest.raises(gr.Error, match="Please upload a video"):
        list(server.process_video(None, small_video=False))

    with pytest.raises(gr.Error, match="no longer available"):
        list(server.process_video(str(missing_path), small_video=False))


def test_favicon_filenames_prefer_available_png() -> None:
    """Ensure the web UI favicon search prefers bundled PNG assets."""

    assert "app-256.png" in server._FAVICON_FILENAMES
    if sys.platform.startswith("win"):
        assert server._FAVICON_FILENAMES[0] == "app.ico"
        assert server._FAVICON_FILENAMES[1] == "app-256.png"
    else:
        assert server._FAVICON_FILENAMES[0] == "app-256.png"


def test_guess_local_url_uses_loopback_for_wildcard() -> None:
    assert server_tray._guess_local_url("0.0.0.0", 8080) == "http://127.0.0.1:8080/"
    assert server_tray._guess_local_url(None, 9005) == "http://127.0.0.1:9005/"
    assert (
        server_tray._guess_local_url("example.com", 9005) == "http://example.com:9005/"
    )


def test_iter_icon_candidates_covers_packaged_roots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The icon discovery should probe project, frozen, and dist roots."""

    module_dir = tmp_path / "pkg" / "talks_reducer"
    module_dir.mkdir(parents=True)
    module_file = module_dir / "server_tray.py"
    module_file.write_text("# dummy module")

    project_docs_icon = module_dir.parent / "docs" / "assets" / "icon.png"
    project_docs_icon.parent.mkdir(parents=True)
    project_docs_icon.write_bytes(b"\x89PNG\r\n\x1a\n")

    frozen_root = tmp_path / "frozen"
    frozen_icon = frozen_root / "docs" / "assets" / "icon.png"
    frozen_icon.parent.mkdir(parents=True)
    frozen_icon.write_bytes(b"PNG")

    dist_root = tmp_path / "dist"
    dist_icon = dist_root / "docs" / "assets" / "icon.png"
    dist_icon.parent.mkdir(parents=True)
    dist_icon.write_bytes(b"PNG")

    internal_icon = dist_root / "_internal" / "docs" / "assets" / "icon.png"
    internal_icon.parent.mkdir(parents=True)
    internal_icon.write_bytes(b"PNG")

    monkeypatch.setattr(server_tray, "__file__", str(module_file))
    monkeypatch.setattr(server_tray.sys, "_MEIPASS", str(frozen_root), raising=False)
    monkeypatch.setattr(
        server_tray.sys,
        "executable",
        str(dist_root / "talks-reducer.exe"),
        raising=False,
    )
    monkeypatch.setattr(
        server_tray.sys,
        "argv",
        [str(dist_root / "talks-reducer.exe")],
        raising=False,
    )

    candidates = list(server_tray._iter_icon_candidates())

    assert project_docs_icon.resolve() in candidates
    assert frozen_icon.resolve() in candidates
    assert dist_icon.resolve() in candidates
    assert internal_icon.resolve() in candidates


def test_iter_icon_candidates_includes_package_resources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Package installations should discover bundled resources/icons assets."""

    package_root = tmp_path / "site-packages" / "talks_reducer"
    module_file = package_root / "server_tray.py"
    icon_path = package_root / "resources" / "icons" / "icon.png"

    module_file.parent.mkdir(parents=True)
    module_file.write_text("# dummy module")
    icon_path.parent.mkdir(parents=True)
    icon_path.write_bytes(b"PNG")

    monkeypatch.setattr(server_tray, "__file__", str(module_file))
    monkeypatch.setattr(server_tray.sys, "_MEIPASS", None, raising=False)
    monkeypatch.setattr(
        server_tray.sys,
        "executable",
        str(package_root / "talks-reducer.exe"),
        raising=False,
    )
    monkeypatch.setattr(
        server_tray.sys,
        "argv",
        [str(package_root / "talks-reducer.exe")],
        raising=False,
    )

    candidates = list(server_tray._iter_icon_candidates())

    assert icon_path.resolve() in candidates


def test_load_icon_uses_first_existing_candidate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The loader should return the first resolvable candidate image."""

    icon_path = tmp_path / "icon.png"
    Image.new("RGBA", (3, 5), color=(10, 20, 30, 255)).save(icon_path)

    monkeypatch.setattr(
        server_tray,
        "_iter_icon_candidates",
        lambda: iter([icon_path]),
    )

    icon = server_tray._load_icon()

    assert icon.size == (3, 5)


def test_load_icon_falls_back_to_embedded_asset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing filesystem icons should be handled by the embedded fallback."""

    monkeypatch.setattr(server_tray, "_iter_icon_candidates", lambda: iter(()))

    icon = server_tray._load_icon()

    assert icon.size == (64, 64)
    colors = icon.getcolors(maxcolors=256)
    assert colors is None or len(colors) > 1


def test_normalize_local_url_rewrites_wildcard_host() -> None:
    url = server_tray._normalize_local_url("http://0.0.0.0:9005/", "0.0.0.0", 9005)
    assert url == "http://127.0.0.1:9005/"

    unchanged = server_tray._normalize_local_url(
        "http://192.0.2.1:9005/", "192.0.2.1", 9005
    )
    assert unchanged == "http://192.0.2.1:9005/"
