"""GUI glue for marking remove ranges in mpv.net and editing them by hand.

Every helper takes the ``TalksReducerGUI`` instance so ``app.py`` only wires
callbacks. The sidecar next to the video is the source of truth: the field is
filled from it on input change and every committed edit is written back.
"""

from __future__ import annotations

import os
import tempfile
import threading
import webbrowser
from pathlib import Path
from typing import Iterable, Optional, Sequence

from .. import cut_marks

_OVERRIDDEN_KEYS = ("small", "small_target_height", "max_frame_rate")


def current_input_video(gui) -> Optional[Path]:
    """Return the single queued input file, or ``None`` for zero, many or a folder."""

    files = list(getattr(gui, "input_files", []) or [])
    if len(files) != 1:
        return None
    path = Path(files[0])
    return path if path.is_file() else None


def set_ranges(gui, ranges: Iterable[Sequence[float]]) -> None:
    """Store *ranges* on the GUI, mirror them into the field, refresh buttons."""

    gui.remove_ranges = cut_marks.normalize_ranges(ranges)
    gui.remove_ranges_text_var.set(cut_marks.format_ranges_text(gui.remove_ranges))
    gui._update_cut_convert_button()


def load_for_current_input(gui) -> None:
    """Fill the field from the current input's sidecar (empty when absent)."""

    video = current_input_video(gui)
    set_ranges(gui, cut_marks.load_marks(video) if video else [])


def commit_text(gui) -> None:
    """Parse the field; save valid ranges to the sidecar, revert invalid text."""

    try:
        ranges = cut_marks.parse_ranges_text(gui.remove_ranges_text_var.get())
    except ValueError as exc:
        gui._append_log(f"Invalid remove ranges: {exc}")
        set_ranges(gui, gui.remove_ranges)
        return
    set_ranges(gui, ranges)
    video = current_input_video(gui)
    if video is not None:
        cut_marks.save_marks(video, ranges)


def remove_only_overrides(args: dict) -> dict:
    """Return *args* for a pass that only drops fragments from a finished file.

    Speeds go to 1 so remaining silence is not sped up a second time, and
    scaling and the fps cap are removed so the picture is left as it is. The
    codec stays as selected.
    """

    result = {key: value for key, value in args.items() if key not in _OVERRIDDEN_KEYS}
    result["silent_speed"] = 1.0
    result["sounded_speed"] = 1.0
    return result


def open_marker(gui) -> None:
    """Open the current input in mpv.net with the marking script.

    The marks travel through a temp file (see the Lua script for why). When the
    player exits, the result is saved to the sidecar and shown in the field.
    """

    video = current_input_video(gui)
    if video is None:
        gui.messagebox.showwarning("Mark cuts", "Add exactly one video file first.")
        return

    preferred = gui.preferences.get("mpv_path", None) or None
    player = cut_marks.find_player(preferred)
    if player is None:
        if gui.messagebox.askyesno(
            "Mark cuts",
            "Marking cuts needs mpv.net (or mpv).\n\nOpen the mpv.net download page?",
        ):
            webbrowser.open(cut_marks.MPV_NET_RELEASES_URL)
        return

    handle, name = tempfile.mkstemp(prefix="talks-reducer-cuts-", suffix=".json")
    os.close(handle)
    marks_file = Path(name)
    cut_marks.write_marks_file(marks_file, gui.remove_ranges, video.name)

    try:
        process = cut_marks.open_player(player, video, marks_file)
    except (OSError, FileNotFoundError) as exc:
        marks_file.unlink(missing_ok=True)
        gui.messagebox.showerror("Mark cuts", f"Could not start {player.name}: {exc}")
        return

    def wait_for_player() -> None:
        process.wait()
        ranges = cut_marks.read_marks_file(marks_file)
        marks_file.unlink(missing_ok=True)

        def apply() -> None:
            cut_marks.save_marks(video, ranges)
            if current_input_video(gui) == video:
                set_ranges(gui, ranges)

        gui._schedule_on_ui_thread(apply)

    threading.Thread(target=wait_for_player, daemon=True).start()
