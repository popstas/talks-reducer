#!/usr/bin/env python
"""Launcher script for PyInstaller builds."""

import sys
import io

# On Windows, if built with --windowed, stdout/stderr might be None
# Ensure they always have a valid file-like object to prevent attribute errors
if sys.platform == "win32":
    if sys.stdout is None:
        sys.stdout = io.StringIO()
    if sys.stderr is None:
        sys.stderr = io.StringIO()
    if sys.stdin is None:
        sys.stdin = io.StringIO()

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
                if hasattr(sys.stdout, 'close'):
                    sys.stdout.close()
                if hasattr(sys.stderr, 'close'):
                    sys.stderr.close()
                if hasattr(sys.stdin, 'close'):
                    sys.stdin.close()
            except Exception:
                pass
            
            try:
                sys.stdout = open("CONOUT$", "w", encoding="utf-8")
                sys.stderr = open("CONOUT$", "w", encoding="utf-8")
                sys.stdin = open("CONIN$", "r", encoding="utf-8")
            except Exception:
                # If we can't open the console streams, revert to dummy streams
                sys.stdout = io.StringIO()
                sys.stderr = io.StringIO()
                sys.stdin = io.StringIO()
    except Exception:
        # If console attachment fails entirely, ensure we have dummy streams
        if sys.stdout is None:
            sys.stdout = io.StringIO()
        if sys.stderr is None:
            sys.stderr = io.StringIO()
        if sys.stdin is None:
            sys.stdin = io.StringIO()

from talks_reducer.cli import main

if __name__ == "__main__":
    main()
