from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from talks_reducer import server, server_tray
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


def test_guess_local_url_uses_loopback_for_wildcard() -> None:
    assert server_tray._guess_local_url("0.0.0.0", 8080) == "http://127.0.0.1:8080/"
    assert server_tray._guess_local_url(None, 9005) == "http://127.0.0.1:9005/"
    assert (
        server_tray._guess_local_url("example.com", 9005) == "http://example.com:9005/"
    )


def test_normalize_local_url_rewrites_wildcard_host() -> None:
    url = server_tray._normalize_local_url("http://0.0.0.0:9005/", "0.0.0.0", 9005)
    assert url == "http://127.0.0.1:9005/"

    unchanged = server_tray._normalize_local_url(
        "http://192.0.2.1:9005/", "192.0.2.1", 9005
    )
    assert unchanged == "http://192.0.2.1:9005/"
