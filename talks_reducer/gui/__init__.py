"""Compatibility layer for the Talks Reducer GUI package."""

from __future__ import annotations

from .app import TalksReducerGUI
from .progress import _GuiProgressHandle, _TkProgressReporter
from .summaries import default_remote_destination, parse_ratios_from_summary
from .startup import _check_tkinter_available, main

__all__ = [
    "TalksReducerGUI",
    "_GuiProgressHandle",
    "_TkProgressReporter",
    "_check_tkinter_available",
    "default_remote_destination",
    "parse_ratios_from_summary",
    "main",
]
