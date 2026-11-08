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
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

from .timecode import format_timecode, parse_timecode

RemoveRange = Tuple[float, float]

MARKS_VERSION = 1
SIDECAR_SUFFIX = ".cuts.json"

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


def read_marks_file(path: Path) -> List[RemoveRange]:
    """Return the ranges stored in a marks JSON file, or ``[]``.

    A missing file is silent; unreadable JSON or an unknown version is logged
    as a warning and treated as no marks.
    """

    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        _LOGGER.warning("Cannot read marks file %s: %s", path, exc)
        return []
    try:
        data = json.loads(text)
    except ValueError as exc:
        _LOGGER.warning("Ignoring malformed marks file %s: %s", path, exc)
        return []
    if not isinstance(data, dict) or data.get("version") != MARKS_VERSION:
        _LOGGER.warning("Ignoring marks file %s with unknown version", path)
        return []
    remove = data.get("remove") or []
    if not isinstance(remove, list):
        return []
    return normalize_ranges(remove)


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
