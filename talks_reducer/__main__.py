"""Module executed when running ``python -m talks_reducer``."""

from __future__ import annotations

import sys


def _run() -> None:
    """Dispatch the dock server before the CLI pulls in the processing stack.

    ``cli`` imports ``audio`` and ``pipeline`` at module level, and with them
    numpy and OpenBLAS; the dock server only spawns child processes and needs
    none of it.
    """

    from talks_reducer.dock_server import DOCK_SERVER_COMMANDS

    if sys.argv[1:2] and sys.argv[1] in DOCK_SERVER_COMMANDS:
        from talks_reducer.dock_server import main as dock_main

        dock_main(sys.argv[2:])
        return

    from talks_reducer.cli import main

    main()


if __name__ == "__main__":
    _run()
