"""talks_reducer exposes a CLI for speeding up videos with silent sections."""

from __future__ import annotations

from .__about__ import __version__
from .cli import main

__all__ = ["main", "__version__"]
