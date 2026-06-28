"""Helpers for creating a Windows ``.lnk`` desktop shortcut for the GUI.

The pure helpers in this module (:func:`build_shortcut_args` and
:func:`shortcut_filename`) are platform-independent and unit-tested. The Tk
dialog and the PowerShell ``.lnk`` write are added on top of these helpers and
are verified manually on Windows.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING, Iterable, List, Mapping

if TYPE_CHECKING:  # pragma: no cover - imported for type checking only
    from .app import TalksReducerGUI

# Defaults the seeded GUI falls back to when a flag is omitted from the shortcut.
# These mirror the GUI control defaults (``talks_reducer/gui/layout.py`` and
# ``talks_reducer/gui/app.py``), NOT the CLI/pipeline defaults: a dropped-on
# shortcut re-enters the GUI seeding path (``_parse_seeded_launch``), so an option
# left off the command line resolves to the GUI default rather than the pipeline
# default. A checkbox is therefore pre-checked only when the current value differs
# from these, so the shortcut captures exactly what an unflagged launch would not
# reproduce.
DEFAULT_SILENT_SPEED = 5.0
DEFAULT_SOUNDED_SPEED = 1.0
DEFAULT_SILENT_THRESHOLD = 0.01
DEFAULT_VIDEO_CODEC = "h264"

# Characters that are illegal in Windows filenames.
_ILLEGAL_FILENAME_CHARS = '<>:"/\\|?*'


def _format_number(value: float) -> str:
    """Render *value* without a trailing ``.0`` (e.g. ``10`` instead of ``10.0``)."""

    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return text or "0"


def build_shortcut_args(
    selections: Mapping[str, bool], gui_values: Mapping[str, object]
) -> List[str]:
    """Map the checked dialog options to CLI flags using live GUI values.

    ``selections`` keys: ``small``, ``small_720``, ``small_480``,
    ``silent_speed``, ``sounded_speed``, ``silent_threshold`` and ``codec``.
    ``gui_values`` supplies the live values: ``silent_speed``,
    ``sounded_speed``, ``silent_threshold`` (numbers) and ``video_codec`` (str).

    Checking ``small_720`` or ``small_480`` implies ``--small``; the two are
    mutually exclusive with ``small_480`` taking precedence when both are set.
    Numeric values are trimmed of trailing zeros.
    """

    args: List[str] = []

    want_480 = bool(selections.get("small_480"))
    want_720 = bool(selections.get("small_720"))
    want_small = bool(selections.get("small")) or want_480 or want_720

    if want_small:
        args.append("--small")
        if want_480:
            args.append("--480")
        elif want_720:
            args.append("--720")

    if selections.get("silent_speed"):
        args.extend(
            [
                "--silent-speed",
                _format_number(gui_values.get("silent_speed", DEFAULT_SILENT_SPEED)),
            ]
        )
    if selections.get("sounded_speed"):
        args.extend(
            [
                "--sounded-speed",
                _format_number(gui_values.get("sounded_speed", DEFAULT_SOUNDED_SPEED)),
            ]
        )
    if selections.get("silent_threshold"):
        args.extend(
            [
                "--silent-threshold",
                _format_number(
                    gui_values.get("silent_threshold", DEFAULT_SILENT_THRESHOLD)
                ),
            ]
        )

    if selections.get("codec"):
        codec = str(gui_values.get("video_codec", DEFAULT_VIDEO_CODEC))
        args.extend(["--video-codec", codec])

    return args


def shortcut_filename(args: Iterable[str]) -> str:
    """Derive a sanitized Desktop ``.lnk`` filename from *args*.

    Strips the leading dashes from flags and joins the tokens, e.g.
    ``Talks Reducer (small 720 silent-speed 10).lnk``. Illegal Windows
    filename characters are removed. Falls back to ``Talks Reducer.lnk`` when
    no arguments are supplied.
    """

    tokens = [str(token).lstrip("-") for token in args]
    tokens = [token for token in tokens if token]
    if not tokens:
        return "Talks Reducer.lnk"

    summary = " ".join(tokens)
    sanitized = "".join(
        char for char in summary if char not in _ILLEGAL_FILENAME_CHARS
    ).strip()
    if not sanitized:
        return "Talks Reducer.lnk"

    return f"Talks Reducer ({sanitized}).lnk"


def resolve_shortcut_target(
    args: Iterable[str],
    *,
    executable: str | None = None,
    frozen: bool | None = None,
) -> dict[str, str]:
    """Resolve the ``.lnk`` target/arguments for the current runtime.

    In a frozen build (``sys.frozen``) the shortcut points at the bundled
    ``talks-reducer.exe`` with the seeded flags as ``Arguments``. In a dev run it
    points at the Python interpreter (``pythonw``) and prefixes
    ``-m talks_reducer.gui`` so the GUI entry point (``startup.main`` ->
    ``_parse_seeded_launch``) launches the seeded drop-target flow, mirroring the
    frozen launcher (``launcher.py`` -> ``talks_reducer.gui.main``). Targeting
    ``-m talks_reducer`` would instead reach the CLI, which processes a dropped
    file through the pipeline rather than seeding the GUI. ``WorkingDirectory`` is
    the executable directory and ``IconLocation`` is the executable itself.

    ``executable`` and ``frozen`` may be supplied to make the resolution testable
    without depending on the live interpreter.
    """

    if executable is None:
        executable = sys.executable
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))

    flags = " ".join(str(arg) for arg in args)
    if frozen:
        arguments = flags
    else:
        arguments = " ".join(filter(None, ["-m talks_reducer.gui", flags]))

    return {
        "target_path": executable,
        "arguments": arguments,
        "working_directory": os.path.dirname(executable),
        "icon_location": executable,
    }


def _escape_ps_single_quote(value: str) -> str:
    """Escape *value* for a single-quoted PowerShell string (doubling ``'``)."""

    return value.replace("'", "''")


def build_powershell_script(shortcut_path: str, target: Mapping[str, str]) -> str:
    """Build a one-shot PowerShell script that writes the ``.lnk`` via WScript.Shell."""

    def quote(value: str) -> str:
        return f"'{_escape_ps_single_quote(value)}'"

    return (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut({quote(shortcut_path)}); "
        f"$s.TargetPath = {quote(target['target_path'])}; "
        f"$s.Arguments = {quote(target['arguments'])}; "
        f"$s.WorkingDirectory = {quote(target['working_directory'])}; "
        f"$s.IconLocation = {quote(target['icon_location'])}; "
        "$s.Save()"
    )


def write_shortcut(shortcut_path: str, target: Mapping[str, str]) -> None:
    """Create the ``.lnk`` at *shortcut_path* by invoking PowerShell.

    Raises :class:`subprocess.CalledProcessError` (or :class:`OSError`) when the
    PowerShell invocation fails so callers can surface the error to the user.
    """

    script = build_powershell_script(shortcut_path, dict(target))
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _dialog_initial_selections(gui: "TalksReducerGUI") -> dict[str, bool]:
    """Compute the pre-checked dialog options from the current GUI state."""

    small_on = bool(gui.small_var.get())
    is_480 = bool(gui.small_480_var.get())
    return {
        "small": small_on,
        "small_720": small_on and not is_480,
        "small_480": small_on and is_480,
        "silent_speed": abs(float(gui.silent_speed_var.get()) - DEFAULT_SILENT_SPEED)
        > 1e-9,
        "sounded_speed": abs(float(gui.sounded_speed_var.get()) - DEFAULT_SOUNDED_SPEED)
        > 1e-9,
        "silent_threshold": abs(
            float(gui.silent_threshold_var.get()) - DEFAULT_SILENT_THRESHOLD
        )
        > 1e-9,
        # Codec defaults to unchecked: the seeded GUI already restores the user's
        # codec preference, so the shortcut omits it unless explicitly added.
        "codec": False,
    }


def _dialog_gui_values(gui: "TalksReducerGUI") -> dict[str, object]:
    """Snapshot the live GUI values consumed by :func:`build_shortcut_args`."""

    return {
        "silent_speed": gui.silent_speed_var.get(),
        "sounded_speed": gui.sounded_speed_var.get(),
        "silent_threshold": gui.silent_threshold_var.get(),
        "video_codec": gui.video_codec_var.get(),
    }


def compute_centered_geometry(
    parent: tuple[int, int, int, int], dialog: tuple[int, int]
) -> tuple[int, int]:
    """Return the ``(x, y)`` that centers a *dialog* over its *parent*.

    ``parent`` is ``(root_x, root_y, width, height)`` and ``dialog`` is
    ``(width, height)``. The result is clamped to non-negative coordinates so the
    dialog never lands off the top-left of the screen.
    """

    px, py, pw, ph = parent
    dw, dh = dialog
    x = px + (pw - dw) // 2
    y = py + (ph - dh) // 2
    return max(0, x), max(0, y)


def _apply_dialog_theme(gui: "TalksReducerGUI", dialog: object) -> None:
    """Match the Toplevel background to the active ttk theme.

    A ``tk.Toplevel`` is a plain Tk widget, so it does not inherit the ttk theme
    and would otherwise render with the default light background even in dark
    mode. Looking the background up from the current style keeps the dialog in
    sync with whichever theme is applied.
    """

    try:
        background = gui.style.lookup("TFrame", "background")
    except Exception:  # pragma: no cover - defensive, style is always present
        background = ""
    if background:
        dialog.configure(bg=background)


def _center_dialog_on_root(gui: "TalksReducerGUI", dialog: object) -> None:
    """Position *dialog* centered over the main window."""

    dialog.update_idletasks()
    x, y = compute_centered_geometry(
        (
            gui.root.winfo_rootx(),
            gui.root.winfo_rooty(),
            gui.root.winfo_width(),
            gui.root.winfo_height(),
        ),
        (dialog.winfo_width(), dialog.winfo_height()),
    )
    dialog.geometry(f"+{x}+{y}")


def open_create_lnk_dialog(gui: "TalksReducerGUI") -> None:
    """Open the **Create lnk** modal dialog and write the chosen shortcut.

    Mirrors the modal pattern in :mod:`talks_reducer.gui.discovery`
    (``transient``/``grab_set``/``WM_DELETE_WINDOW``). Seven checkboxes seed the
    CLI flags; a live preview label echoes the resulting command line; **Create**
    writes the ``.lnk`` to the Desktop via :func:`write_shortcut`.
    """

    selections = _dialog_initial_selections(gui)

    dialog = gui.tk.Toplevel(gui.root)
    dialog.title("Create lnk")
    dialog.transient(gui.root)
    _apply_dialog_theme(gui, dialog)
    dialog.grab_set()

    vars_by_key: dict[str, object] = {
        key: gui.tk.BooleanVar(value=selections[key])
        for key in (
            "small",
            "small_720",
            "small_480",
            "silent_speed",
            "sounded_speed",
            "silent_threshold",
            "codec",
        )
    }

    preview_var = gui.tk.StringVar()

    def current_selections() -> dict[str, bool]:
        return {key: bool(var.get()) for key, var in vars_by_key.items()}

    def refresh_preview() -> None:
        args = build_shortcut_args(current_selections(), _dialog_gui_values(gui))
        target = (
            "talks-reducer.exe" if getattr(sys, "frozen", False) else "talks-reducer"
        )
        preview_var.set(" ".join([target, *args]).strip())

    _updating = {"busy": False}

    def on_small_variant(changed: str) -> None:
        if _updating["busy"]:
            return
        _updating["busy"] = True
        try:
            if changed in ("small_720", "small_480") and vars_by_key[changed].get():
                # 720/480 imply Small and are mutually exclusive.
                vars_by_key["small"].set(True)
                other = "small_480" if changed == "small_720" else "small_720"
                vars_by_key[other].set(False)
            if changed == "small" and not vars_by_key["small"].get():
                vars_by_key["small_720"].set(False)
                vars_by_key["small_480"].set(False)
        finally:
            _updating["busy"] = False
        refresh_preview()

    row = 0
    gui.ttk.Label(dialog, text="Seed the shortcut with these options:").grid(
        row=row, column=0, columnspan=2, sticky="w", padx=gui.PADDING, pady=(12, 4)
    )
    row += 1

    checkbox_specs = [
        ("small", "Small video"),
        ("small_720", "720p"),
        ("small_480", "480p"),
        ("silent_speed", "Silent speed"),
        ("sounded_speed", "Sounded speed"),
        ("silent_threshold", "Silent threshold"),
        ("codec", "Codec"),
    ]
    for key, label in checkbox_specs:
        gui.ttk.Checkbutton(
            dialog,
            text=label,
            variable=vars_by_key[key],
            command=lambda key=key: on_small_variant(key),
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=gui.PADDING)
        row += 1

    gui.ttk.Label(dialog, textvariable=preview_var, foreground="gray").grid(
        row=row, column=0, columnspan=2, sticky="w", padx=gui.PADDING, pady=(8, 4)
    )
    row += 1

    def create() -> None:
        args = build_shortcut_args(current_selections(), _dialog_gui_values(gui))
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        shortcut_path = os.path.join(desktop, shortcut_filename(args))
        target = resolve_shortcut_target(args)
        try:
            write_shortcut(shortcut_path, target)
        except Exception as exc:  # pragma: no cover - surfaced to the user
            message = getattr(exc, "stderr", None) or str(exc)
            gui.messagebox.showerror("Create lnk failed", str(message))
            return
        gui.messagebox.showinfo(
            "Shortcut created",
            f"Created shortcut:\n{shortcut_path}",
        )
        dialog.grab_release()
        dialog.destroy()

    def cancel() -> None:
        dialog.grab_release()
        dialog.destroy()

    button_frame = gui.ttk.Frame(dialog)
    button_frame.grid(row=row, column=0, columnspan=2, pady=(8, 12))
    gui.ttk.Button(button_frame, text="Create", command=create).pack(
        side=gui.tk.LEFT, padx=(0, 8)
    )
    gui.ttk.Button(button_frame, text="Cancel", command=cancel).pack(side=gui.tk.LEFT)
    dialog.protocol("WM_DELETE_WINDOW", cancel)

    refresh_preview()
    _center_dialog_on_root(gui, dialog)
