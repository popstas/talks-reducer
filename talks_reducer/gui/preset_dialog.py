"""Modal name-entry dialog used to author a new preset from the Advanced knobs.

The dialog mirrors the "Create lnk" modal pattern in
:mod:`talks_reducer.gui.shortcut` (``transient``/``grab_set``/
``WM_DELETE_WINDOW`` plus theme-matching and centering). It only collects a
preset name; the actual capture and persistence happen in the ``on_submit``
callback so this module stays free of preset-store logic. The Tk dialog is
verified manually while the pure helpers it reuses are unit-tested.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from .shortcut import _apply_dialog_theme, _center_dialog_on_root

if TYPE_CHECKING:  # pragma: no cover - imported for type checking only
    from .app import TalksReducerGUI


def open_save_preset_dialog(
    gui: "TalksReducerGUI",
    on_submit: Callable[[str], None],
    *,
    initial: str = "",
) -> None:
    """Open the **Save preset as…** modal and call *on_submit* with the name.

    A blank name is rejected with an error dialog and keeps the modal open so
    the user can correct it; a valid name closes the dialog and forwards the
    trimmed value to *on_submit*.
    """

    dialog = gui.tk.Toplevel(gui.root)
    dialog.title("Save preset as")
    dialog.transient(gui.root)
    _apply_dialog_theme(gui, dialog)
    dialog.grab_set()

    name_var = gui.tk.StringVar(value=initial)

    gui.ttk.Label(dialog, text="Preset name:").grid(
        row=0, column=0, sticky="w", padx=gui.PADDING, pady=(12, 4)
    )
    entry = gui.ttk.Entry(dialog, textvariable=name_var, width=32)
    entry.grid(row=1, column=0, sticky="ew", padx=gui.PADDING)

    def create() -> None:
        name = name_var.get().strip()
        if not name:
            gui.messagebox.showerror("Save preset", "Please enter a preset name.")
            return
        dialog.grab_release()
        dialog.destroy()
        on_submit(name)

    def cancel() -> None:
        dialog.grab_release()
        dialog.destroy()

    button_frame = gui.ttk.Frame(dialog)
    button_frame.grid(row=2, column=0, pady=(12, 12))
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
