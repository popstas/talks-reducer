from __future__ import annotations

from pathlib import Path

from talks_reducer import icons


def test_iter_icon_candidates_skips_duplicate_roots(
    monkeypatch, tmp_path: Path
) -> None:
    """Duplicate base roots should not yield repeated icon candidates."""

    base_root = tmp_path / "base"
    base_root.mkdir()
    assets_dir = base_root / "assets"
    assets_dir.mkdir()
    icon_path = assets_dir / "app.ico"
    icon_path.write_bytes(b"ico")

    missing_root = tmp_path / "missing"
    missing_root.mkdir()

    def fake_iter_base_roots(module_file=None):
        yield base_root
        yield base_root  # Duplicate to exercise deduplication logic.
        yield missing_root

    monkeypatch.setattr(icons, "_iter_base_roots", fake_iter_base_roots)

    results = list(
        icons.iter_icon_candidates(
            filenames=("app.ico",),
            relative_paths=(Path("assets"),),
        )
    )

    assert results == [icon_path.resolve()]
