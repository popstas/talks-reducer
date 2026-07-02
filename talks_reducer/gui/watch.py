"""Watch-directory polling and the dynamic Convert/Open-last button."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from .app import TalksReducerGUI

VIDEO_EXTENSIONS: tuple[str, ...] = (".mp4", ".mkv", ".mov", ".avi", ".m4v")
PROCESSED_MARKERS: tuple[str, ...] = ("_speedup", "_small")
POLL_INTERVAL_MS: int = 2000


def latest_video(directory) -> Optional[Path]:
    """Return the most-recently-modified video file in *directory*.

    Files are filtered to :data:`VIDEO_EXTENSIONS`; the newest by ``st_mtime``
    wins with ties broken by the greatest filename. Missing, empty, or
    unreadable directories yield ``None``.
    """

    folder = Path(directory)
    try:
        entries = list(folder.iterdir())
    except (OSError, ValueError):
        return None

    candidates: list[tuple[float, str, Path]] = []
    for entry in entries:
        if entry.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        try:
            if not entry.is_file():
                continue
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        candidates.append((mtime, entry.name, entry))

    if not candidates:
        return None
    return max(candidates)[2]


def is_processed(path) -> bool:
    """Return ``True`` when *path*'s name carries a processed-output marker."""

    name = Path(path).name.lower()
    return any(marker in name for marker in PROCESSED_MARKERS)
