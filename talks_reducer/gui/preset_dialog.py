"""Modal Save/Update dialog used to author a preset from the Advanced knobs.

The dialog mirrors the "Create lnk" modal pattern in
:mod:`talks_reducer.gui.shortcut` (``transient``/``grab_set``/
``WM_DELETE_WINDOW`` plus theme-matching and centering). Alongside the preset
name it exposes a checkbox per tunable param (resolution, silent speed, sounded
speed, silent threshold, codec) so the user picks exactly which settings the
preset controls — the checked subset becomes a **sparse** preset. Capture and
persistence happen in the ``on_submit`` callback so this module stays free of
preset-store logic. The Tk dialog is verified manually while the pure helpers it
reuses are unit-tested.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Mapping, Optional, Sequence, Set

from .shortcut import _apply_dialog_theme, _center_dialog_on_root

if TYPE_CHECKING:  # pragma: no cover - imported for type checking only
    from .app import TalksReducerGUI

# The tunable params a preset can carry, in dialog order, with display labels.
FIELD_SPECS: Sequence[tuple[str, str]] = (
    ("resolution", "Resolution"),
    ("silent_speed", "Silent speed"),
    ("sounded_speed", "Sounded speed"),
    ("silent_threshold", "Silent threshold"),
    ("video_codec", "Codec"),
)


def open_save_preset_dialog(
    gui: "TalksReducerGUI",
    on_submit: Callable[[str, Set[str]], None],
    *,
    initial: str = "",
    initial_fields: Optional[Set[str]] = None,
    field_values: Optional[Mapping[str, object]] = None,
    title: str = "Save preset as",
) -> None:
    """Open the Save/Update modal and call *on_submit* with ``(name, fields)``.

    *initial* seeds the name entry and *initial_fields* pre-checks the param
    checkboxes (defaults to all params). *field_values* supplies the live value
    shown beside each checkbox so the user sees what will be captured. A blank
    name or an empty checkbox selection is rejected with an error dialog and
    keeps the modal open; otherwise the dialog closes and forwards the trimmed
    name plus the set of checked field keys.
    """

    checked = (
        set(initial_fields)
        if initial_fields is not None
        else {key for key, _label in FIELD_SPECS}
    )
    values = dict(field_values or {})

    dialog = gui.tk.Toplevel(gui.root)
    dialog.title(title)
    dialog.transient(gui.root)
    _apply_dialog_theme(gui, dialog)
    dialog.grab_set()

    name_var = gui.tk.StringVar(value=initial)

    gui.ttk.Label(dialog, text="Preset name:").grid(
        row=0, column=0, columnspan=2, sticky="w", padx=gui.PADDING, pady=(12, 4)
    )
    entry = gui.ttk.Entry(dialog, textvariable=name_var, width=32)
    entry.grid(row=1, column=0, columnspan=2, sticky="ew", padx=gui.PADDING)

    gui.ttk.Label(dialog, text="Include these settings:").grid(
        row=2, column=0, columnspan=2, sticky="w", padx=gui.PADDING, pady=(12, 4)
    )

    field_vars: dict = {}
    row = 3
    for key, label in FIELD_SPECS:
        var = gui.tk.BooleanVar(value=key in checked)
        field_vars[key] = var
        if key in values:
            text = f"{label}: {values[key]}"
        else:
            text = label
        gui.ttk.Checkbutton(dialog, text=text, variable=var).grid(
            row=row, column=0, columnspan=2, sticky="w", padx=gui.PADDING
        )
        row += 1

    def create() -> None:
        name = name_var.get().strip()
        if not name:
            gui.messagebox.showerror("Save preset", "Please enter a preset name.")
            return
        selected = {key for key, var in field_vars.items() if bool(var.get())}
        if not selected:
            gui.messagebox.showerror(
                "Save preset", "Select at least one setting to include."
            )
            return
        dialog.grab_release()
        dialog.destroy()
        on_submit(name, selected)

    def cancel() -> None:
        dialog.grab_release()
        dialog.destroy()

    button_frame = gui.ttk.Frame(dialog)
    button_frame.grid(row=row, column=0, columnspan=2, pady=(12, 12))
    gui.ttk.Button(button_frame, text="Save", command=create).pack(
        side=gui.tk.LEFT, padx=(0, 8)
    )
    gui.ttk.Button(button_frame, text="Cancel", command=cancel).pack(side=gui.tk.LEFT)
    dialog.protocol("WM_DELETE_WINDOW", cancel)
    entry.bind("<Return>", lambda _e: create())

    try:
        entry.focus_set()
    except Exception:  # pragma: no cover - defensive on headless Tk
        pass
    _center_dialog_on_root(gui, dialog)
