from __future__ import annotations

from pathlib import Path

from talks_reducer import server
from talks_reducer.models import ProcessingResult


class DummyProgress:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int, str]] = []

    def __call__(self, current: int, *, total: int, desc: str) -> None:
        self.calls.append((current, total, desc))


def test_build_output_path_mirrors_cli_naming(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    output_path = server._build_output_path(Path("video.mp4"), workspace, small=False)
    small_output = server._build_output_path(Path("video.mp4"), workspace, small=True)

    assert output_path.name.endswith("_speedup.mp4")
    assert small_output.name.endswith("_speedup_small.mp4")


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
