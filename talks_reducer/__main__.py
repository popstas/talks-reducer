"""Module executed when running ``python -m talks_reducer``."""

from __future__ import annotations

try:
    from .cli import main
except ImportError:
    # Handle PyInstaller packaging where relative imports don't work
    from talks_reducer.cli import main

if __name__ == "__main__":
    main()
