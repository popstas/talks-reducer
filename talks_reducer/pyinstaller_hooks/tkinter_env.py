"""PyInstaller runtime hook ensuring Tcl/Tk uses bundled resources."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _select_latest(directory: Path, prefix: str) -> Path | None:
    """Pick the newest matching child directory within *directory*."""

    if not directory.exists() or not directory.is_dir():
        return None

    candidates = [child for child in directory.iterdir() if child.is_dir() and child.name.lower().startswith(prefix)]
    if not candidates:
        return None

    def sort_key(item: Path) -> float:
        try:
            return item.stat().st_mtime
        except OSError:
            return 0.0

    candidates.sort(key=sort_key, reverse=True)
    return candidates[0]


def configure_tk_paths() -> None:
    """Set Tcl/Tk environment variables when running from a PyInstaller bundle."""

    if not getattr(sys, "frozen", False):
        return

    base = getattr(sys, "_MEIPASS", None)
    if not base:
        return

    bundle_root = Path(base)

    tcl_dir = _select_latest(bundle_root / "tcl", "tcl")
    tk_dir = _select_latest(bundle_root / "tk", "tk")

    if tcl_dir and "TCL_LIBRARY" not in os.environ:
        os.environ["TCL_LIBRARY"] = str(tcl_dir)

    if tk_dir and "TK_LIBRARY" not in os.environ:
        os.environ["TK_LIBRARY"] = str(tk_dir)


configure_tk_paths()
