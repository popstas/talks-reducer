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


_MAX_LABEL_CHARS = 40


class WatchController:
    """Poll a folder and drive the dynamic Convert/Open-last action button."""

    def __init__(self, gui: "TalksReducerGUI") -> None:
        self.gui = gui
        self._after_id: Optional[str] = None
        self._candidate: Optional[Path] = None
        self._processed: bool = False

    def start(self) -> None:
        """Begin (or restart) the polling loop; safe to call repeatedly."""

        self.stop()
        self._tick()

    def stop(self) -> None:
        """Cancel any scheduled poll; safe to call when not running."""

        if self._after_id is not None:
            try:
                self.gui.root.after_cancel(self._after_id)
            except Exception:  # pragma: no cover - defensive
                pass
            self._after_id = None

    def _tick(self) -> None:
        self.refresh_candidate()
        self._after_id = self.gui.root.after(POLL_INTERVAL_MS, self._tick)

    def _watch_directory(self) -> Optional[Path]:
        if not self.gui.watch_enabled_var.get():
            return None
        raw = str(self.gui.watch_directory_var.get()).strip()
        if not raw:
            return None
        folder = Path(raw)
        return folder if folder.is_dir() else None

    def refresh_candidate(self) -> None:
        """Recompute the newest video and update the button."""

        directory = self._watch_directory()
        candidate = latest_video(directory) if directory is not None else None
        self._candidate = candidate
        self._processed = is_processed(candidate) if candidate is not None else False
        self.refresh_button()

    @staticmethod
    def _display_name(name: str) -> str:
        if len(name) <= _MAX_LABEL_CHARS:
            return name
        return "…" + name[-(_MAX_LABEL_CHARS - 1) :]

    def refresh_button(self) -> None:
        """Apply the current candidate to the shared action-button slot."""

        button = getattr(self.gui, "watch_button", None)
        if button is None:
            return

        if self._candidate is None:
            button.grid_remove()
            self.gui._restore_default_action_button()
            return

        if self.gui.stop_button.winfo_viewable():
            button.grid_remove()
            return

        self.gui.open_button.grid_remove()
        drop_hint = getattr(self.gui, "drop_hint_button", None)
        if drop_hint is not None:
            drop_hint.grid_remove()

        if self._processed:
            button.configure(text="Open last", command=self.open_latest)
        else:
            label = self._display_name(self._candidate.name)
            button.configure(text=f"Convert {label}", command=self.convert_latest)
        button.grid()

    def convert_latest(self) -> None:
        """Convert exactly the tracked candidate with the current options."""

        candidate = self._candidate
        if candidate is None or not candidate.exists():
            self.refresh_candidate()
            return
        self.gui.inputs.clear_input_files()
        self.gui.inputs.extend_inputs([str(candidate)])
        self.gui._start_run()

    def open_latest(self) -> None:
        """Reveal the tracked processed output in the system file manager."""

        if self._candidate is not None:
            self.gui._open_in_file_manager(self._candidate)
