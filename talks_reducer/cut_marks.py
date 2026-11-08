"""Remove-range marks: parsing, the ``.cuts.json`` sidecar and the mpv launcher.

A *remove range* is a ``(start, end)`` pair in seconds of one specific file.
Marks made on a source and on its processed output are different files with
different timelines, so each video keeps its own sidecar next to it.
"""

from __future__ import annotations

import json
import logging
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterable, List, Mapping, Optional, Sequence, Tuple

from .icons import find_icon_path
from .subprocess_utils import hidden_subprocess_kwargs
from .timecode import format_timecode, parse_timecode

RemoveRange = Tuple[float, float]

MARKS_VERSION = 1
SIDECAR_SUFFIX = ".cuts.json"

LUA_SCRIPT_NAME = "talks_reducer_cuts.lua"
MPV_NET_RELEASES_URL = "https://github.com/mpvnet-player/mpv.net/releases"

_SCRIPT_RELATIVE_PATHS = (
    Path("resources"),
    Path("talks_reducer") / "resources",
)

_LOGGER = logging.getLogger(__name__)


def normalize_ranges(ranges: Iterable[Sequence[float]]) -> List[RemoveRange]:
    """Return *ranges* validated, sorted and with overlapping ranges merged.

    Pairs that are not two finite numbers, or whose end is not after the start,
    are dropped. Negative starts are clamped to zero. Touching ranges merge.
    """

    cleaned: List[RemoveRange] = []
    for item in ranges:
        try:
            start, end = float(item[0]), float(item[1])
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        if not (math.isfinite(start) and math.isfinite(end)):
            continue
        start = max(0.0, start)
        if end <= start:
            continue
        cleaned.append((start, end))

    cleaned.sort()
    merged: List[RemoveRange] = []
    for start, end in cleaned:
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def parse_ranges_text(text: str) -> List[RemoveRange]:
    """Parse ``"1:20-1:45, 12:00-12:30.5"`` into normalised ranges.

    Each bound accepts anything :func:`talks_reducer.timecode.parse_timecode`
    does. An en dash is accepted as the separator because the player's OSD
    shows one. Raises :class:`ValueError` naming the offending token.
    """

    ranges: List[RemoveRange] = []
    for token in str(text or "").replace("–", "-").split(","):
        token = token.strip()
        if not token:
            continue
        bounds = token.split("-")
        if len(bounds) != 2:
            raise ValueError(f"Invalid range {token!r}: use START-END")
        try:
            start = parse_timecode(bounds[0].strip())
            end = parse_timecode(bounds[1].strip())
        except ValueError as exc:
            raise ValueError(f"Invalid range {token!r}: {exc}") from exc
        if end <= start:
            raise ValueError(f"Invalid range {token!r}: end must be after start")
        ranges.append((start, end))
    return normalize_ranges(ranges)


def _format_bound(seconds: float) -> str:
    """Format one bound, adding milliseconds only when the value has them."""

    if abs(seconds - round(seconds)) < 0.0005:
        return format_timecode(int(round(seconds)))
    return format_timecode(seconds, milliseconds=True)


def format_ranges_text(ranges: Iterable[Sequence[float]]) -> str:
    """Return the editable ``START-END, START-END`` text for *ranges*."""

    return ", ".join(
        f"{_format_bound(start)}-{_format_bound(end)}"
        for start, end in normalize_ranges(ranges)
    )


def sidecar_path(video: Path) -> Path:
    """Return the ``<video name>.cuts.json`` path next to *video*."""

    video = Path(video)
    return video.with_name(video.name + SIDECAR_SUFFIX)


def try_read_marks_file(path: Path) -> Optional[List[RemoveRange]]:
    """Return the ranges in a marks JSON file, or ``None`` when it is unusable.

    ``None`` means the file is missing, unreadable, malformed or of an unknown
    version; a valid file with no ranges yields ``[]``. Missing files are
    silent, other failures are logged as warnings.
    """

    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        _LOGGER.warning("Cannot read marks file %s: %s", path, exc)
        return None
    try:
        data = json.loads(text)
    except ValueError as exc:
        _LOGGER.warning("Ignoring malformed marks file %s: %s", path, exc)
        return None
    if not isinstance(data, dict) or data.get("version") != MARKS_VERSION:
        _LOGGER.warning("Ignoring marks file %s with unknown version", path)
        return None
    remove = data.get("remove") or []
    if not isinstance(remove, list):
        return []
    return normalize_ranges(remove)


def read_marks_file(path: Path) -> List[RemoveRange]:
    """Return the ranges stored in a marks JSON file, or ``[]``.

    A missing file is silent; unreadable JSON or an unknown version is logged
    as a warning and treated as no marks.
    """

    ranges = try_read_marks_file(path)
    return [] if ranges is None else ranges


def write_marks_file(
    path: Path, ranges: Iterable[Sequence[float]], source_name: str
) -> None:
    """Atomically write *ranges* to *path* in the marks JSON format."""

    path = Path(path)
    payload = {
        "version": MARKS_VERSION,
        "source": source_name,
        "remove": [[start, end] for start, end in normalize_ranges(ranges)],
    }
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def load_marks(video: Path) -> List[RemoveRange]:
    """Return the marks saved next to *video*."""

    return read_marks_file(sidecar_path(video))


def save_marks(video: Path, ranges: Iterable[Sequence[float]]) -> None:
    """Save *ranges* next to *video*; an empty list deletes the sidecar."""

    video = Path(video)
    normalized = normalize_ranges(ranges)
    target = sidecar_path(video)
    if not normalized:
        target.unlink(missing_ok=True)
        return
    write_marks_file(target, normalized, video.name)


def find_player(
    preferred: Optional[str] = None,
    *,
    platform: str = sys.platform,
    which: Callable[[str], Optional[str]] = shutil.which,
    environ: Mapping[str, str] = os.environ,
    exists: Callable[[str], bool] = os.path.isfile,
) -> Optional[Path]:
    """Return the player to mark cuts with, or ``None`` when none is installed.

    Order: the configured *preferred* path, ``mpvnet``/``mpv`` on ``PATH``,
    mpv.net's Windows install folders, then Homebrew's ``mpv`` on macOS. The
    keyword arguments exist so tests can describe a machine without touching
    the real one.
    """

    if preferred and exists(preferred):
        return Path(preferred)

    for name in ("mpvnet", "mpv"):
        found = which(name)
        if found:
            return Path(found)

    candidates: list[str] = []
    if platform == "win32":
        program_files = environ.get("ProgramFiles")
        local_app_data = environ.get("LOCALAPPDATA")
        if program_files:
            candidates.append(str(Path(program_files) / "mpv.net" / "mpvnet.exe"))
        if local_app_data:
            candidates.append(
                str(Path(local_app_data) / "Programs" / "mpv.net" / "mpvnet.exe")
            )
    elif platform == "darwin":
        candidates.extend(["/opt/homebrew/bin/mpv", "/usr/local/bin/mpv"])

    for candidate in candidates:
        if exists(candidate):
            return Path(candidate)
    return None


def script_path() -> Optional[Path]:
    """Return the bundled Lua marking script, or ``None`` when it is missing."""

    return find_icon_path(
        filenames=[LUA_SCRIPT_NAME], relative_paths=_SCRIPT_RELATIVE_PATHS
    )


def build_player_command(
    player: Path, video: Path, marks_file: Path, script: Path
) -> list[str]:
    """Return the command line that opens *video* with the marking script.

    mpv.net defaults to a single instance: a second launch hands the file to
    the running window and exits at once, which would make the caller read the
    marks before any were made. ``--process-instance=multi`` keeps the new
    process alive until its window closes.
    """

    command = [str(player)]
    if Path(player).stem.lower() == "mpvnet":
        command.append("--process-instance=multi")
    command.append(f"--script={script}")
    command.append(f"--script-opts=talks_reducer_cuts-file={marks_file}")
    command.append(str(video))
    return command


def open_player(player: Path, video: Path, marks_file: Path) -> subprocess.Popen:
    """Launch *player* on *video*, writing marks to *marks_file*."""

    script = script_path()
    if script is None:
        raise FileNotFoundError(f"Bundled {LUA_SCRIPT_NAME} is missing")
    return subprocess.Popen(
        build_player_command(player, video, marks_file, script),
        **hidden_subprocess_kwargs(),
    )
