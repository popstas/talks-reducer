"""Startup utilities for launching the Talks Reducer GUI."""

from __future__ import annotations

import argparse
import importlib
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence, Tuple

from ..cli import main as cli_main
from .app import TalksReducerGUI

_runtime_logged = False


def _log_python_runtime() -> None:
    """Emit the active Python runtime details once for troubleshooting."""

    global _runtime_logged
    if _runtime_logged:
        return

    _runtime_logged = True

    try:
        implementation = platform.python_implementation()
    except Exception:  # pragma: no cover - extremely defensive fallback
        implementation = "Python"

    try:
        version = platform.python_version()
    except Exception:  # pragma: no cover - platform module unavailable
        version = sys.version.split()[0]

    sys.stdout.write(
        f"[Talks Reducer] Runtime: {implementation} {version} (executable: {sys.executable})\n"
    )


def _check_tkinter_available() -> Tuple[bool, str]:
    """Check if tkinter can create windows without importing it globally."""

    # Test in a subprocess to avoid crashing the main process
    test_code = """
import json

def run_check():
    try:
        import tkinter as tk  # noqa: F401 - imported for side effect
    except Exception as exc:  # pragma: no cover - runs in subprocess
        return {
            "status": "import_error",
            "error": f"{exc.__class__.__name__}: {exc}",
        }

    try:
        import tkinter as tk

        root = tk.Tk()
        root.destroy()
    except Exception as exc:  # pragma: no cover - runs in subprocess
        return {
            "status": "init_error",
            "error": f"{exc.__class__.__name__}: {exc}",
        }

    return {"status": "ok"}


if __name__ == "__main__":
    print(json.dumps(run_check()))
"""

    try:
        result = subprocess.run(
            [sys.executable, "-c", test_code], capture_output=True, text=True, timeout=5
        )

        output = result.stdout.strip() or result.stderr.strip()

        if not output:
            return False, "Window creation failed"

        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            return False, output

        status = payload.get("status")

        if status == "ok":
            return True, ""

        if status == "import_error":
            return (
                False,
                f"tkinter is not installed ({payload.get('error', 'unknown error')})",
            )

        if status == "init_error":
            return (
                False,
                f"tkinter could not open a window ({payload.get('error', 'unknown error')})",
            )

        return False, output
    except Exception as e:  # pragma: no cover - defensive fallback
        return False, f"Error testing tkinter: {e}"


def main(argv: Optional[Sequence[str]] = None) -> bool:
    """Launch the GUI when run without arguments, otherwise defer to the CLI."""

    _log_python_runtime()

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--server",
        action="store_true",
        help="Launch the Talks Reducer server tray instead of the desktop GUI.",
    )
    parser.add_argument(
        "--no-tray",
        action="store_true",
        help="Deprecated: the GUI no longer starts the server tray automatically.",
    )

    parsed_args, remaining = parser.parse_known_args(argv)
    if parsed_args.server:
        package_name = __package__ or "talks_reducer"
        module_name = f"{package_name}.server_tray"
        try:
            tray_module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name != module_name:
                raise
            root_package = package_name.split(".")[0] or "talks_reducer"
            tray_module = importlib.import_module(f"{root_package}.server_tray")
        tray_main = getattr(tray_module, "main")
        tray_main(remaining)
        return False
    if parsed_args.no_tray:
        sys.stderr.write(
            "Warning: --no-tray is deprecated; the GUI no longer starts the server tray automatically.\n"
        )
    argv = remaining

    if sys.platform == "darwin":
        argv = [arg for arg in argv if not arg.startswith("-psn_")]

    if argv:
        launch_gui = False
        if sys.platform == "win32" and not any(arg.startswith("-") for arg in argv):
            if any(Path(arg).exists() for arg in argv if arg):
                launch_gui = True

        if launch_gui:
            try:
                app = TalksReducerGUI(argv, auto_run=True)
                app.run()
                return True
            except Exception:
                # Fall back to the CLI if the GUI cannot be started.
                pass

        cli_main(argv)
        return False

    is_frozen = getattr(sys, "frozen", False)

    if not is_frozen:
        tkinter_available, error_msg = _check_tkinter_available()

        if not tkinter_available:
            try:
                print("Talks Reducer GUI")
                print("=" * 50)
                print("X GUI not available on this system")
                print(f"Error: {error_msg}")
                print()
                print("! Alternative: Use the command-line interface")
                print()
                print("The CLI provides all the same functionality:")
                print("  python3 -m talks_reducer <input_file> [options]")
                print()
                print("Examples:")
                print("  python3 -m talks_reducer video.mp4")
                print("  python3 -m talks_reducer video.mp4 --small")
                print("  python3 -m talks_reducer video.mp4 -o output.mp4")
                print()
                print("Run 'python3 -m talks_reducer --help' for all options.")
                print()
                print("Troubleshooting tips:")
                if sys.platform == "darwin":
                    print(
                        "  - On macOS, install Python from python.org or ensure "
                        "Homebrew's python-tk package is present."
                    )
                elif sys.platform.startswith("linux"):
                    print(
                        "  - On Linux, install the Tk bindings for Python (for example, "
                        "python3-tk)."
                    )
                else:
                    print("  - Ensure your Python installation includes Tk support.")
                print("  - You can always fall back to the CLI workflow below.")
                print()
                print("The CLI interface works perfectly and is recommended.")
            except UnicodeEncodeError:
                sys.stderr.write("GUI not available. Use CLI mode instead.\n")
            return False

    try:
        app = TalksReducerGUI()
        app.run()
        return True
    except Exception as e:
        import traceback

        sys.stderr.write(f"Error starting GUI: {e}\n")
        sys.stderr.write(traceback.format_exc())
        sys.stderr.write("\nPlease use the CLI mode instead:\n")
        sys.stderr.write("  python3 -m talks_reducer <input_file> [options]\n")
        sys.exit(1)


__all__ = ["_check_tkinter_available", "main"]
