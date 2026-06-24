"""Helpers for parsing and formatting trim timecodes.

Timecodes describe positions within a video and are accepted in several
forms by the CLI and GUIs: a bare number of seconds (``12.5``) or a
colon-separated clock string (``SS``, ``MM:SS`` or ``HH:MM:SS`` with an
optional fractional ``.ms`` suffix). All helpers operate on non-negative
values and reject malformed input with :class:`ValueError`.
"""

from __future__ import annotations

from numbers import Real

__all__ = ["parse_timecode", "format_timecode"]


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
        seconds = float(value)
        if seconds < 0:
            raise ValueError(f"Timecode cannot be negative: {value!r}")
        return seconds

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
        return seconds

    try:
        seconds = float(text)
    except ValueError as exc:
        raise ValueError(f"Invalid timecode: {value!r}") from exc
    if seconds < 0:
        raise ValueError(f"Timecode cannot be negative: {value!r}")
    return seconds


def format_timecode(seconds) -> str:
    """Return ``seconds`` formatted as a ``HH:MM:SS`` clock string."""

    if isinstance(seconds, bool) or not isinstance(seconds, Real):
        raise ValueError(f"Invalid seconds value: {seconds!r}")
    if seconds < 0:
        raise ValueError(f"Seconds cannot be negative: {seconds!r}")

    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"
