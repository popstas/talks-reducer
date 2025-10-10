"""Compatibility layer for the Talks Reducer GUI package."""

from __future__ import annotations

from .app import (
    TalksReducerGUI,
    _default_remote_destination,
    _parse_ratios_from_summary,
)
from .progress import _GuiProgressHandle, _TkProgressReporter
from .startup import _check_tkinter_available, main

__all__ = [
    "TalksReducerGUI",
    "_GuiProgressHandle",
    "_TkProgressReporter",
    "_check_tkinter_available",
    "_default_remote_destination",
    "_parse_ratios_from_summary",
    "main",
]
