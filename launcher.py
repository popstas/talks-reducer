#!/usr/bin/env python
"""Launcher script for PyInstaller builds."""

import sys

# On Windows, if built with --windowed, we need to handle console attachment
# when CLI arguments are provided (e.g., --help)
if sys.platform == "win32" and len(sys.argv) > 1:
    try:
        import ctypes
        
        kernel32 = ctypes.windll.kernel32
        
        # Try to attach to parent console (only works when launched from cmd/terminal)
        # AttachConsole returns 0 on failure
        if kernel32.AttachConsole(ctypes.c_ulong(-1)):  # ATTACH_PARENT_PROCESS = -1
            # Reopen stdout and stderr to the console
            try:
                sys.stdout.close()
                sys.stderr.close()
                sys.stdin.close()
            except Exception:
                pass
            
            try:
                sys.stdout = open("CONOUT$", "w", encoding="utf-8")
                sys.stderr = open("CONOUT$", "w", encoding="utf-8")
                sys.stdin = open("CONIN$", "r", encoding="utf-8")
            except Exception:
                # If we can't open the console streams, continue anyway
                pass
    except Exception:
        # If console attachment fails entirely, continue anyway
        # The program will still work, just without console output
        pass

from talks_reducer.cli import main

if __name__ == "__main__":
    main()
