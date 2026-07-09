"""Startup utilities for launching the Talks Reducer GUI."""

from __future__ import annotations

import argparse
import importlib
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from ..cli import _build_parser
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


def _build_seed_parser() -> argparse.ArgumentParser:
    """Return a CLI parser whose defaults are suppressed for GUI seeding.

    The standard CLI parser fills every option with a default value, which makes
    it impossible to tell which flags the user actually passed. Suppressing the
    defaults means the parsed namespace only contains the options that appeared
    on the command line, so the GUI applies just the settings the launch
    requested instead of clobbering stored preferences with parser defaults.
    """

    parser = _build_parser()
    # ``set_defaults`` stores values (such as ``optimize=True``) outside the
    # per-action defaults, so clear them too to keep the parsed namespace limited
    # to the options the launch actually provided.
    parser._defaults.clear()
    for action in parser._actions:
        if action.dest in {"help", "version"}:
            continue
        action.default = argparse.SUPPRESS
        # Allow an args-only launch (settings, no file) to parse successfully so
        # a shortcut such as ``talks-reducer.exe --small --silent-speed 5`` opens
        # the GUI with those settings instead of erroring on the missing file.
        if action.dest == "input_file":
            action.nargs = "*"
    return parser


def _gui_settings_from_namespace(parsed: argparse.Namespace) -> Dict[str, object]:
    """Translate explicitly-provided CLI options into GUI control settings."""

    provided = vars(parsed)
    settings: Dict[str, object] = {}
    for key in (
        "small",
        "small_480",
        "silent_speed",
        "sounded_speed",
        "silent_threshold",
        "frame_spreadage",
        "sample_rate",
        "keyframe_interval_seconds",
        "video_codec",
        "add_codec_suffix",
        "prefer_global_ffmpeg",
        "optimize",
        "output_file",
        "temp_folder",
        "open_location",
        "auto_close",
    ):
        if key in provided:
            settings[key] = provided[key]

    host = provided.get("host")
    if host:
        settings["server_url"] = f"http://{host}:9005"
    elif provided.get("server_url"):
        settings["server_url"] = provided["server_url"]

    return settings


def _expand_seeded_preset(parsed: argparse.Namespace) -> None:
    """Fan a ``--preset NAME`` seed onto the namespace's per-field attributes.

    The seed parser leaves ``--preset`` as a bare name, but
    :func:`_gui_settings_from_namespace` only understands concrete fields
    (``small``, ``silent_speed``, ``video_codec`` …). Without this expansion a
    launch such as ``talks-reducer.exe <file> --preset Smallest`` (used by the
    OBS dock) would silently drop the preset. Reuse the CLI's
    :func:`_apply_preset_to_args` so preset fields flow through with the same
    explicit-flag precedence, then clear ``preset`` so it does not leak further.
    """

    preset_name = getattr(parsed, "preset", None)
    if not preset_name:
        return

    from .. import presets as presets_module
    from ..cli import _apply_preset_to_args

    explicit = set(vars(parsed).keys())
    preset = presets_module.find_preset(preset_name, presets_module.load_presets())
    if preset is not None:
        _apply_preset_to_args(parsed, preset, explicit)

    if hasattr(parsed, "preset"):
        delattr(parsed, "preset")


def _parse_seeded_launch(
    argv: Sequence[str],
) -> Optional[Tuple[List[str], Dict[str, object]]]:
    """Return seeded input files and GUI settings when *argv* carries a file path.

    Detects the file-association launch pattern where the executable is invoked
    with CLI flags plus one or more existing positional file paths (for example
    a Windows shortcut to ``talks-reducer.exe --small --silent-speed 5`` that
    receives a dropped video). Also detects an args-only launch (recognized GUI
    settings with no file at all), so a shortcut that only carries preset flags
    opens the GUI with those settings applied. Returns ``None`` when ``argv``
    cannot be parsed, or when a positional path was given but does not exist, so
    the caller can fall back to the regular CLI pipeline.
    """

    parser = _build_seed_parser()
    try:
        parsed = parser.parse_args(list(argv))
    except SystemExit:
        return None

    _expand_seeded_preset(parsed)

    input_paths = getattr(parsed, "input_file", None) or []
    input_files = [path for path in input_paths if path and Path(path).exists()]
    if input_files:
        return input_files, _gui_settings_from_namespace(parsed)

    # No usable file. Only treat this as a GUI launch when no positional path was
    # supplied at all and at least one GUI setting was provided; if a path was
    # given but is missing, fall back to the CLI so it can report the error.
    if not input_paths:
        settings = _gui_settings_from_namespace(parsed)
        if settings:
            return [], settings

    return None


def _import_server_tray():
    """Import and return the ``server_tray`` module relative to this package."""

    package_name = __package__ or "talks_reducer"
    module_name = f"{package_name}.server_tray"
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name != module_name:
            raise
        root_package = package_name.split(".")[0] or "talks_reducer"
        return importlib.import_module(f"{root_package}.server_tray")


def _should_start_in_server_tray() -> bool:
    """Return the persisted ``start_in_server_tray`` preference, defaulting to False.

    Reads the preference via the standard :class:`GUIPreferences` loader, which
    already treats a missing or corrupt config file as an empty mapping, so a
    broken settings file simply yields ``False`` here.
    """

    try:
        from .preferences import GUIPreferences, determine_config_path

        preferences = GUIPreferences(determine_config_path())
        return bool(preferences.get("start_in_server_tray", False))
    except Exception:  # pragma: no cover - defensive: never block launch
        return False


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
    parser.add_argument(
        "--server-managed",
        action="store_true",
        help=(
            "Internal flag set by the server tray to mark the GUI as running "
            "under a tray-managed server."
        ),
    )
    parser.add_argument(
        "--server-url",
        dest="server_url",
        default=None,
        help=(
            "Local server URL passed by the tray when the GUI runs in "
            "server-managed mode."
        ),
    )

    parsed_args, remaining = parser.parse_known_args(argv)

    server_managed = bool(parsed_args.server_managed)
    local_server_url: Optional[str] = parsed_args.server_url
    if not server_managed and local_server_url is not None:
        # ``--server-url`` outside managed mode belongs to the CLI/seeded launch;
        # restore it so the downstream parser still receives it unchanged.
        remaining = ["--server-url", local_server_url, *remaining]
        local_server_url = None

    if parsed_args.server:
        tray_module = _import_server_tray()
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
        seeded: Optional[Tuple[List[str], Dict[str, object]]] = None
        if sys.platform == "win32":
            seeded = _parse_seeded_launch(argv)

        if seeded is not None:
            input_files, cli_settings = seeded
            try:
                app = TalksReducerGUI(
                    input_files,
                    auto_run=bool(input_files),
                    cli_settings=cli_settings,
                    server_managed=server_managed,
                    local_server_url=local_server_url,
                )
                app.run()
                return True
            except Exception:
                # Fall back to the CLI if the GUI cannot be started.
                pass

        cli_main(argv)
        return False

    # No explicit flags, no positional inputs, and not a tray-managed child:
    # honor the persisted ``start_in_server_tray`` preference and boot straight
    # into the server-tray experience. Managed children always run the plain GUI
    # so enabling the preference never spawns a tray loop.
    #
    # The server-tray module pulls in optional dependencies (``pystray`` and the
    # server stack) that may be absent from a frozen bundle. A persisted
    # preference must never be able to brick the launcher, so any import or
    # startup failure here falls through to the normal GUI instead of crashing —
    # otherwise the user could not even open the window to disable the toggle.
    if not server_managed and _should_start_in_server_tray():
        try:
            tray_module = _import_server_tray()
            tray_main = getattr(tray_module, "main")
        except Exception:  # pragma: no cover - exercised on bundles lacking deps
            import traceback

            sys.stderr.write(
                "Warning: could not start in server tray; falling back to the GUI.\n"
            )
            sys.stderr.write(traceback.format_exc())
        else:
            tray_main(["--with-gui"])
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
        app = TalksReducerGUI(
            server_managed=server_managed,
            local_server_url=local_server_url,
        )
        app.run()
        return True
    except Exception as e:
        import traceback

        sys.stderr.write(f"Error starting GUI: {e}\n")
        sys.stderr.write(traceback.format_exc())
        sys.stderr.write("\nPlease use the CLI mode instead:\n")
        sys.stderr.write("  python3 -m talks_reducer <input_file> [options]\n")
        sys.exit(1)


__all__ = [
    "_check_tkinter_available",
    "_parse_seeded_launch",
    "_should_start_in_server_tray",
    "main",
]
