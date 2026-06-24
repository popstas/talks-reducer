from __future__ import annotations

import json
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
    monkeypatch.setattr(server, "_resolve_host_ip", lambda: "192.0.2.15")

    assert server._describe_server_host() == "talks-reducer-host (192.0.2.15)"


def test_describe_server_host_handles_lookup_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server.socket, "gethostname", lambda: "")
    monkeypatch.setattr(server, "_resolve_host_ip", lambda: "")

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


def test_process_video_logs_upload_receipt(tmp_path: Path) -> None:
    """The first streamed update should announce the received upload."""

    input_file = tmp_path / "clip.mp4"
    input_file.write_bytes(b"0123456789")

    def _speed_up(options: ProcessingOptions, reporter: server.SignalProgressReporter):
        with reporter.task(desc="Encode", total=10, unit="frames") as task:
            task.advance(10)
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
                progress=None,
                dependencies=dependencies,
            )
        )
    finally:
        server._cleanup_workspaces()

    first_log = outputs[0][1]
    assert "Upload received" in first_log
    assert "clip.mp4" in first_log
    assert "10 B" in first_log

    final_log = outputs[-1][1]
    assert "Upload received" in final_log


def test_format_file_size_uses_human_readable_units() -> None:
    assert server._format_file_size(0) == "0 B"
    assert server._format_file_size(512) == "512 B"
    assert server._format_file_size(1536) == "1.5 KB"
    assert server._format_file_size(5 * 1024 * 1024) == "5.0 MB"


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

    try:
        outputs = list(
            server.process_video(
                str(input_file),
                small_video=False,
                video_codec="h264",
                add_codec_suffix=True,
                dependencies=dependencies,
            )
        )
    finally:
        server._cleanup_workspaces()

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

    try:
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
    finally:
        server._cleanup_workspaces()

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

    try:
        outputs = list(
            server.process_video(
                str(input_file),
                small_video=False,
                use_global_ffmpeg=True,
                dependencies=dependencies,
            )
        )
    finally:
        server._cleanup_workspaces()

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


def _trim_capturing_dependencies(
    captured: dict,
) -> "server.ProcessVideoDependencies":
    def _speed_up(options: ProcessingOptions, reporter: server.SignalProgressReporter):
        captured["cut_start_seconds"] = options.cut_start_seconds
        captured["cut_end_seconds"] = options.cut_end_seconds
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

    return server.ProcessVideoDependencies(
        speed_up=_speed_up,
        reporter_factory=server._default_reporter_factory,
        queue_factory=SimpleQueue,
        run_pipeline_job_func=server.run_pipeline_job,
        start_in_thread=False,
    )


def test_process_video_honors_trim_when_enabled(tmp_path: Path) -> None:
    input_file = tmp_path / "clip.mp4"
    input_file.write_bytes(b"data")

    captured: dict = {}
    dependencies = _trim_capturing_dependencies(captured)

    try:
        outputs = list(
            server.process_video(
                str(input_file),
                small_video=False,
                cut_enabled=True,
                cut_start_seconds=10.0,
                cut_end_seconds=60.0,
                progress=None,
                dependencies=dependencies,
            )
        )
    finally:
        server._cleanup_workspaces()

    assert outputs
    assert captured["cut_start_seconds"] == pytest.approx(10.0)
    assert captured["cut_end_seconds"] == pytest.approx(60.0)


def test_process_video_ignores_trim_when_disabled(tmp_path: Path) -> None:
    input_file = tmp_path / "clip.mp4"
    input_file.write_bytes(b"data")

    captured: dict = {}
    dependencies = _trim_capturing_dependencies(captured)

    try:
        outputs = list(
            server.process_video(
                str(input_file),
                small_video=False,
                cut_enabled=False,
                cut_start_seconds=10.0,
                cut_end_seconds=60.0,
                progress=None,
                dependencies=dependencies,
            )
        )
    finally:
        server._cleanup_workspaces()

    assert outputs
    assert captured["cut_start_seconds"] == pytest.approx(0.0)
    assert captured["cut_end_seconds"] == pytest.approx(0.0)


def test_build_interface_exposes_cut_video_components() -> None:
    """The web UI should expose the Cut video checkbox and start/end inputs."""

    demo = server.build_interface()
    process_fns = [
        fn for fn in demo.fns.values() if getattr(fn, "name", "") == "process_video"
    ]
    assert process_fns, "process_video handler not registered on demo"
    registered_inputs = list(process_fns[0].inputs or [])
    labels = [getattr(component, "label", None) for component in registered_inputs]

    assert "Cut video" in labels
    assert "Cut start (seconds)" in labels
    assert "Cut end (seconds)" in labels


def test_build_interface_inputs_align_with_process_video_signature() -> None:
    """Guard against positional mismatch between the Gradio inputs list and
    ``process_video``'s signature. A missing component would shift every
    subsequent argument by one slot and cause values to be validated against
    the wrong component's constraints (e.g. silent_threshold=0.01 rejected by
    sounded_speed slider with minimum=0.5)."""

    import inspect

    sig = inspect.signature(server.process_video)
    expected_params = [
        name
        for name, param in sig.parameters.items()
        if param.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
        and name != "progress"
    ]

    demo = server.build_interface()
    process_fns = [
        fn for fn in demo.fns.values() if getattr(fn, "name", "") == "process_video"
    ]
    assert process_fns, "process_video handler not registered on demo"
    handler = process_fns[0]
    registered_inputs = list(handler.inputs or [])

    assert len(registered_inputs) == len(expected_params), (
        f"Gradio inputs list has {len(registered_inputs)} components but "
        f"process_video expects {len(expected_params)} positional parameters "
        f"({expected_params})."
    )

    sounded_speed_index = expected_params.index("sounded_speed")
    sounded_slider = registered_inputs[sounded_speed_index]
    assert getattr(sounded_slider, "label", None) == "Sounded speed", (
        "Positional mismatch: the component at the sounded_speed slot does "
        "not have the expected 'Sounded speed' label."
    )

    silent_threshold_index = expected_params.index("silent_threshold")
    silent_slider = registered_inputs[silent_threshold_index]
    assert getattr(silent_slider, "label", None) == "Silent threshold", (
        "Positional mismatch: the component at the silent_threshold slot "
        "does not have the expected 'Silent threshold' label."
    )


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


def _run_asgi(app, scope, messages):
    """Drive an ASGI *app* with queued receive *messages*; capture sent events."""

    import asyncio

    sent: list[dict] = []
    queue = list(messages)

    async def receive() -> dict:
        return queue.pop(0)

    async def send(message: dict) -> None:
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    return sent


def test_transfer_middleware_logs_upload_progress() -> None:
    logs: list[str] = []

    async def downstream(scope, receive, send):
        # Drain the request body the way gradio's upload route would.
        more = True
        while more:
            message = await receive()
            more = message.get("more_body", False)

    middleware = server.TransferProgressMiddleware(
        downstream, log=logs.append, step_percent=50
    )

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/gradio_api/upload",
        "headers": [(b"content-length", b"10")],
    }
    messages = [
        {"type": "http.request", "body": b"01234", "more_body": True},
        {"type": "http.request", "body": b"56789", "more_body": False},
    ]

    _run_asgi(middleware, scope, messages)

    assert any("Receiving upload" in line for line in logs)
    assert any("100%" in line for line in logs)


def test_transfer_middleware_logs_download_progress() -> None:
    logs: list[str] = []

    async def downstream(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-length", b"8")],
            }
        )
        await send({"type": "http.response.body", "body": b"abcd", "more_body": True})
        await send({"type": "http.response.body", "body": b"efgh", "more_body": False})

    middleware = server.TransferProgressMiddleware(
        downstream, log=logs.append, step_percent=50
    )

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/gradio_api/file=/tmp/output.mp4",
        "headers": [],
    }

    _run_asgi(middleware, scope, [])

    assert any("Sending download output.mp4" in line for line in logs)
    assert any("100%" in line for line in logs)


def test_transfer_middleware_ignores_other_routes() -> None:
    logs: list[str] = []
    seen: list[str] = []

    async def downstream(scope, receive, send):
        seen.append(scope["path"])

    middleware = server.TransferProgressMiddleware(downstream, log=logs.append)

    scope = {"type": "http", "method": "GET", "path": "/", "headers": []}
    _run_asgi(middleware, scope, [])

    assert seen == ["/"]
    assert logs == []


def test_build_launch_app_kwargs_registers_middleware() -> None:
    kwargs = server.build_launch_app_kwargs()

    middleware = kwargs.get("middleware")
    assert middleware, "expected middleware to be registered"
    assert any(
        getattr(entry, "cls", None) is server.TransferProgressMiddleware
        for entry in middleware
    )
    assert any(
        getattr(entry, "cls", None) is server.ActivityMiddleware for entry in middleware
    )


def test_activity_recorder_records_and_respects_maxlen() -> None:
    recorder = server.ActivityRecorder(maxlen=3)

    for index in range(5):
        recorder.record(f"10.0.0.{index}", "upload", timestamp=float(index))

    entries = recorder.snapshot()
    assert len(entries) == 3
    assert [entry.client_ip for entry in entries] == [
        "10.0.0.2",
        "10.0.0.3",
        "10.0.0.4",
    ]
    assert all(entry.action == "upload" for entry in entries)
    assert entries[-1].timestamp == 4.0


def test_activity_recorder_clear_empties_entries() -> None:
    recorder = server.ActivityRecorder(maxlen=5)
    recorder.record("10.0.0.1", "download")

    recorder.clear()

    assert recorder.snapshot() == []


def test_activity_middleware_records_upload_with_client_ip() -> None:
    recorder = server.ActivityRecorder(maxlen=10)
    seen: list[str] = []

    async def downstream(scope, receive, send):
        seen.append(scope["path"])

    middleware = server.ActivityMiddleware(downstream, recorder=recorder)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/gradio_api/upload",
        "headers": [],
        "client": ("203.0.113.7", 51234),
    }

    _run_asgi(middleware, scope, [])

    assert seen == ["/gradio_api/upload"]
    entries = recorder.snapshot()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.client_ip == "203.0.113.7"
    assert entry.action == "upload"
    assert isinstance(entry.timestamp, float)
    assert entry.timestamp > 0


def test_activity_middleware_records_download_and_uses_forwarded_for() -> None:
    recorder = server.ActivityRecorder(maxlen=10)

    async def downstream(scope, receive, send):
        return None

    middleware = server.ActivityMiddleware(downstream, recorder=recorder)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/gradio_api/file=/tmp/output.mp4",
        "headers": [(b"x-forwarded-for", b"198.51.100.9, 10.0.0.1")],
        "client": ("10.0.0.1", 6000),
    }

    _run_asgi(middleware, scope, [])

    entries = recorder.snapshot()
    assert len(entries) == 1
    assert entries[0].client_ip == "198.51.100.9"
    assert entries[0].action == "download"


def test_activity_middleware_ignores_unrelated_routes() -> None:
    recorder = server.ActivityRecorder(maxlen=10)
    seen: list[str] = []

    async def downstream(scope, receive, send):
        seen.append(scope["path"])

    middleware = server.ActivityMiddleware(downstream, recorder=recorder)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "client": ("10.0.0.1", 7000),
    }

    _run_asgi(middleware, scope, [])

    assert seen == ["/"]
    assert recorder.snapshot() == []


def test_classify_activity_maps_known_requests() -> None:
    assert server._classify_activity("POST", "/gradio_api/upload") == "upload"
    assert server._classify_activity("POST", "/gradio_api/upload/") == "upload"
    assert (
        server._classify_activity("GET", "/gradio_api/file=/tmp/out.mp4") == "download"
    )
    assert (
        server._classify_activity("POST", "/gradio_api/call/process_video") == "process"
    )
    assert server._classify_activity("POST", "/gradio_api/queue/join") == "process"
    assert server._classify_activity("POST", "/gradio_api/queue/join/") == "process"
    assert server._classify_activity("GET", "/gradio_api/queue/data") is None
    assert server._classify_activity("GET", "/") is None
    assert server._classify_activity("POST", "/gradio_api/other") is None


def test_activity_middleware_records_process() -> None:
    recorder = server.ActivityRecorder(maxlen=10)

    async def downstream(scope, receive, send):
        return None

    middleware = server.ActivityMiddleware(downstream, recorder=recorder)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/gradio_api/call/process_video",
        "headers": [],
        "client": ("203.0.113.7", 51234),
    }

    _run_asgi(middleware, scope, [])

    entries = recorder.snapshot()
    assert len(entries) == 1
    assert entries[0].action == "process"
    assert entries[0].client_ip == "203.0.113.7"


def test_activity_middleware_records_queued_process() -> None:
    """Queued submissions hit ``queue/join`` and must record a ``process``."""

    recorder = server.ActivityRecorder(maxlen=10)

    async def downstream(scope, receive, send):
        return None

    middleware = server.ActivityMiddleware(downstream, recorder=recorder)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/gradio_api/queue/join",
        "headers": [],
        "client": ("203.0.113.9", 51200),
    }

    _run_asgi(middleware, scope, [])

    entries = recorder.snapshot()
    assert len(entries) == 1
    assert entries[0].action == "process"
    assert entries[0].client_ip == "203.0.113.9"


def test_activity_middleware_passes_through_non_http() -> None:
    recorder = server.ActivityRecorder(maxlen=10)
    seen: list[str] = []

    async def downstream(scope, receive, send):
        seen.append(scope["type"])

    middleware = server.ActivityMiddleware(downstream, recorder=recorder)

    _run_asgi(middleware, {"type": "lifespan"}, [])

    assert seen == ["lifespan"]
    assert recorder.snapshot() == []


def test_activity_middleware_client_ip_unknown_without_client() -> None:
    recorder = server.ActivityRecorder(maxlen=10)

    async def downstream(scope, receive, send):
        return None

    middleware = server.ActivityMiddleware(downstream, recorder=recorder)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/gradio_api/upload",
        "headers": [],
    }

    _run_asgi(middleware, scope, [])

    entries = recorder.snapshot()
    assert len(entries) == 1
    assert entries[0].client_ip == "unknown"


def test_resolve_host_ip_skips_loopback(monkeypatch) -> None:
    class _Probe:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def connect(self, address):
            return None

        def getsockname(self):
            return ("10.20.30.40", 12345)

    monkeypatch.setattr(server, "_preferred_lan_ip", lambda: "")
    monkeypatch.setattr(server.socket, "socket", lambda *a, **k: _Probe())

    assert server._resolve_host_ip() == "10.20.30.40"


def test_resolve_host_ip_falls_back_when_probe_loopback(monkeypatch) -> None:
    class _Probe:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def connect(self, address):
            return None

        def getsockname(self):
            return ("127.0.0.1", 12345)

    monkeypatch.setattr(server, "_preferred_lan_ip", lambda: "")
    monkeypatch.setattr(server.socket, "socket", lambda *a, **k: _Probe())
    monkeypatch.setattr(server.socket, "gethostname", lambda: "host")
    monkeypatch.setattr(server.socket, "gethostbyname", lambda name: "127.0.1.1")

    assert server._resolve_host_ip() == ""


def test_preferred_lan_ip_prefers_192_168_over_vpn_and_docker() -> None:
    addresses = [
        "127.0.0.1",
        "10.8.1.28",  # VPN tunnel
        "172.18.0.1",  # docker bridge
        "192.168.1.14",  # LAN
    ]
    assert server._preferred_lan_ip(lambda: iter(addresses)) == "192.168.1.14"


def test_preferred_lan_ip_returns_empty_without_192_168() -> None:
    addresses = ["127.0.0.1", "10.8.1.28", "172.18.0.1"]
    assert server._preferred_lan_ip(lambda: iter(addresses)) == ""


def test_resolve_host_ip_prefers_lan_over_probe(monkeypatch) -> None:
    """A 192.168 interface address wins over the VPN default-route probe."""

    class _Probe:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def connect(self, address):
            return None

        def getsockname(self):
            return ("10.8.1.28", 12345)  # VPN tunnel

    monkeypatch.setattr(server, "_preferred_lan_ip", lambda: "192.168.1.14")
    monkeypatch.setattr(server.socket, "socket", lambda *a, **k: _Probe())

    assert server._resolve_host_ip() == "192.168.1.14"


def test_activity_endpoint_returns_entries_and_identity(monkeypatch) -> None:
    recorder = server.ActivityRecorder(maxlen=10)
    recorder.record("203.0.113.7", "upload", timestamp=1.0)
    recorder.record("203.0.113.8", "download", timestamp=2.0)
    # Pin the resolved LAN IP so the asserted URL does not depend on the host's
    # network configuration.
    monkeypatch.setattr(server, "_resolve_host_ip", lambda: "192.0.2.5")

    middleware = server.ActivityMiddleware(
        lambda scope, receive, send: None,
        recorder=recorder,
        identity_factory=lambda: "talks-host (192.0.2.5)",
    )

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/activity",
        "headers": [],
        "client": ("203.0.113.9", 8000),
        "server": ("0.0.0.0", 9005),
    }

    sent = _run_asgi(middleware, scope, [])

    start = next(msg for msg in sent if msg["type"] == "http.response.start")
    assert start["status"] == 200
    assert any(
        key == b"content-type" and value == b"application/json"
        for key, value in start["headers"]
    )

    body = next(msg for msg in sent if msg["type"] == "http.response.body")["body"]
    payload = json.loads(body.decode("utf-8"))

    assert payload["server"]["identity"] == "talks-host (192.0.2.5)"
    assert payload["server"]["url"] == "http://192.0.2.5:9005/"
    assert [entry["action"] for entry in payload["entries"]] == ["upload", "download"]
    assert payload["entries"][0]["client_ip"] == "203.0.113.7"
    assert payload["entries"][0]["timestamp"] == 1.0


def test_activity_endpoint_handles_empty_recorder() -> None:
    recorder = server.ActivityRecorder(maxlen=10)

    middleware = server.ActivityMiddleware(
        lambda scope, receive, send: None,
        recorder=recorder,
        identity_factory=lambda: "talks-host",
    )

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/activity",
        "headers": [],
        "client": ("203.0.113.9", 8000),
    }

    sent = _run_asgi(middleware, scope, [])

    body = next(msg for msg in sent if msg["type"] == "http.response.body")["body"]
    payload = json.loads(body.decode("utf-8"))

    assert payload["entries"] == []
    assert payload["server"]["identity"] == "talks-host"
    # No scope["server"] → URL is omitted rather than guessed incorrectly.
    assert payload["server"]["url"] is None
