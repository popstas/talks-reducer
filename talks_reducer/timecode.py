"""Helpers for parsing and formatting trim timecodes.

Timecodes describe positions within a video and are accepted in several
forms by the CLI and GUIs: a bare number of seconds (``12.5``) or a
colon-separated clock string (``SS``, ``MM:SS`` or ``HH:MM:SS`` with an
optional fractional ``.ms`` suffix). All helpers operate on non-negative
values and reject malformed input with :class:`ValueError`.
"""

from __future__ import annotations

import math
from numbers import Real

__all__ = ["parse_timecode", "format_timecode"]


def _validate_seconds(seconds: float, value) -> float:
    """Return ``seconds`` after rejecting negative or non-finite values."""

    if not math.isfinite(seconds):
        raise ValueError(f"Invalid timecode: {value!r}")
    if seconds < 0:
        raise ValueError(f"Timecode cannot be negative: {value!r}")
    return seconds


def parse_timecode(value) -> float:
    """Return the number of seconds described by ``value``.

    ``value`` may be a numeric seconds value (``int``/``float``) or a string
    holding either a decimal number of seconds or a ``SS`` / ``MM:SS`` /
    ``HH:MM:SS`` clock with an optional ``.ms`` fractional part. Negative or
    malformed values raise :class:`ValueError`.
    """

    if isinstance(value, bool):  # bool is a subclass of int; reject explicitly
        raise ValueError(f"Invalid timecode: {value!r}")

    if isinstance(value, Real):
        return _validate_seconds(float(value), value)

    if not isinstance(value, str):
        raise ValueError(f"Invalid timecode: {value!r}")

    text = value.strip()
    if not text:
        raise ValueError("Timecode cannot be empty")

    if ":" in text:
        parts = text.split(":")
        if len(parts) > 3:
            raise ValueError(f"Invalid timecode: {value!r}")
        try:
            numbers = [float(part) for part in parts]
        except ValueError as exc:
            raise ValueError(f"Invalid timecode: {value!r}") from exc
        if any(number < 0 for number in numbers):
            raise ValueError(f"Timecode cannot be negative: {value!r}")
        seconds = 0.0
        for number in numbers:
            seconds = seconds * 60 + number
        return _validate_seconds(seconds, value)

    try:
        seconds = float(text)
    except ValueError as exc:
        raise ValueError(f"Invalid timecode: {value!r}") from exc
    return _validate_seconds(seconds, value)


def format_timecode(seconds, *, milliseconds: bool = False) -> str:
    """Return ``seconds`` formatted as a ``HH:MM:SS`` clock string.

    When ``milliseconds`` is true the fractional part is appended as a
    three-digit ``.mmm`` suffix (``HH:MM:SS.mmm``) so the value can round-trip
    through :func:`parse_timecode` without losing sub-second precision.
    """

    if isinstance(seconds, bool) or not isinstance(seconds, Real):
        raise ValueError(f"Invalid seconds value: {seconds!r}")
    if seconds < 0:
        raise ValueError(f"Seconds cannot be negative: {seconds!r}")

    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    clock = f"{hours:02d}:{minutes:02d}:{secs:02d}"
    if not milliseconds:
        return clock
    millis = int(round((float(seconds) - total) * 1000))
    if millis >= 1000:  # rounding can spill into the next second
        millis = 999
    return f"{clock}.{millis:03d}"
