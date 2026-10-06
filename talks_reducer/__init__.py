"""talks_reducer exposes a CLI for speeding up videos with silent sections."""

from __future__ import annotations

from typing import Any

from .__about__ import __version__

__all__ = ["main", "__version__"]


def __getattr__(name: str) -> Any:
    """Resolve ``talks_reducer.main`` lazily.

    Importing ``cli`` eagerly pulled numpy and OpenBLAS into every process
    that touched any submodule, including the OBS dock server, which never
    processes media itself. Deferring the import keeps
    ``import talks_reducer.dock_server`` cheap.
    """

    if name == "main":
        from .cli import main

        return main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
