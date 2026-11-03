"""Modal dialog that sets the order in which queued parts are glued.

Dropped files arrive in whatever order the file manager hands them over and
folders expand in ``os.listdir`` order, so neither says anything about the order
the recordings were made in. After the user agrees to glue, this dialog lists
the parts sorted by file name and lets them reorder the list (↑/↓ buttons,
Alt+↑/Alt+↓, or dragging a row) before the concat runs. The first entry also
names the output. The pure helpers are unit-tested; the Tk dialog itself is
verified manually, like :mod:`talks_reducer.gui.preset_dialog`.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Callable, List, Optional, Sequence, Tuple

from .shortcut import _apply_dialog_theme, _center_dialog_on_root

if TYPE_CHECKING:  # pragma: no cover - imported for type checking only
    from .app import TalksReducerGUI

_DIGITS = re.compile(r"(\d+)")
_MAX_VISIBLE_ROWS = 12
_ACCENT = "#2563eb"  # theme.py uses this accent in both palettes


def natural_name_key(path: str) -> Tuple[object, ...]:
    """Return a sort key for *path*'s file name that orders digit runs as numbers.

    ``part2.mp4`` therefore sorts before ``part10.mp4``. Text runs compare
    case-insensitively; each run is tagged so text and numbers never compare
    directly.
    """

    name = os.path.basename(path)
    key: List[object] = []
    for index, chunk in enumerate(_DIGITS.split(name)):
        if index % 2:
            key.append((0, int(chunk), ""))
        elif chunk:
            key.append((1, 0, chunk.casefold()))
    return tuple(key)


def sort_glue_inputs(files: Sequence[str]) -> List[str]:
    """Return *files* sorted by file name, the dialog's initial order.

    The full path breaks ties so parts with the same name in different folders
    still come out in a stable order.
    """

    return sorted(files, key=lambda item: (natural_name_key(item), str(item)))


def move_item(items: Sequence[str], index: int, delta: int) -> Tuple[List[str], int]:
    """Move ``items[index]`` by *delta* places and return ``(items, new_index)``.

    The target is clamped to the list bounds, so moving the first entry up or
    the last one down leaves the list unchanged.
    """

    result = list(items)
    if not 0 <= index < len(result):
        return result, index
    target = max(0, min(len(result) - 1, index + delta))
    result.insert(target, result.pop(index))
    return result, target


def display_names(files: Sequence[str]) -> List[str]:
    """Return the label shown for each file: its name, or its path when ambiguous."""

    names = [os.path.basename(item) for item in files]
    return [
        name if names.count(name) == 1 else str(path)
        for name, path in zip(names, files)
    ]


def open_glue_order_dialog(
    gui: "TalksReducerGUI",
    files: Sequence[str],
    on_done: Callable[[Optional[List[str]]], None],
) -> None:
    """Show the order dialog and call *on_done* once with the result.

    *on_done* receives the reordered file list on **Glue**, or ``None`` when the
    dialog is cancelled or closed.
    """

    order = sort_glue_inputs(files)
    finished = {"done": False}

    dialog = gui.tk.Toplevel(gui.root)
    dialog.title("Glue order")
    dialog.transient(gui.root)
    _apply_dialog_theme(gui, dialog)
    dialog.grab_set()

    gui.ttk.Label(
        dialog,
        text="Parts are glued top to bottom. The first one names the output.",
    ).grid(row=0, column=0, columnspan=2, sticky="w", padx=gui.PADDING, pady=(12, 6))

    labels = display_names(order)
    list_frame = gui.ttk.Frame(dialog)
    list_frame.grid(row=1, column=0, sticky="nsew", padx=(gui.PADDING, 6))
    listbox = gui.tk.Listbox(
        list_frame,
        height=min(len(order), _MAX_VISIBLE_ROWS),
        width=min(max(len(label) for label in labels) + 4, 80),
        activestyle="none",
        exportselection=False,
        highlightthickness=1,
        borderwidth=0,
    )
    _style_listbox(gui, listbox)
    listbox.pack(side=gui.tk.LEFT, fill="both", expand=True)
    if len(order) > _MAX_VISIBLE_ROWS:
        scrollbar = gui.ttk.Scrollbar(
            list_frame, orient="vertical", command=listbox.yview
        )
        listbox.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=gui.tk.LEFT, fill="y")

    def refresh(selected: int) -> None:
        listbox.delete(0, gui.tk.END)
        for label in display_names(order):
            listbox.insert(gui.tk.END, label)
        listbox.selection_clear(0, gui.tk.END)
        listbox.selection_set(selected)
        listbox.activate(selected)
        listbox.see(selected)

    def selected_index() -> int:
        selection = listbox.curselection()
        return int(selection[0]) if selection else 0

    def move(delta: int) -> str:
        nonlocal order
        order, target = move_item(order, selected_index(), delta)
        refresh(target)
        return "break"

    def drag(event: object) -> None:
        nonlocal order
        target = listbox.nearest(event.y)  # type: ignore[attr-defined]
        current = selected_index()
        if target != current:
            order, target = move_item(order, current, target - current)
            refresh(target)

    def finish(result: Optional[List[str]]) -> None:
        if finished["done"]:
            return
        finished["done"] = True
        dialog.grab_release()
        dialog.destroy()
        on_done(result)

    side = gui.ttk.Frame(dialog)
    side.grid(row=1, column=1, sticky="n", padx=(0, gui.PADDING))
    gui.ttk.Button(side, text="↑ Up", command=lambda: move(-1)).pack(fill="x")
    gui.ttk.Button(side, text="↓ Down", command=lambda: move(1)).pack(
        fill="x", pady=(6, 0)
    )

    buttons = gui.ttk.Frame(dialog)
    buttons.grid(row=2, column=0, columnspan=2, pady=(12, 12))
    gui.ttk.Button(buttons, text="Glue", command=lambda: finish(list(order))).pack(
        side=gui.tk.LEFT, padx=(0, 8)
    )
    gui.ttk.Button(buttons, text="Cancel", command=lambda: finish(None)).pack(
        side=gui.tk.LEFT
    )

    listbox.bind("<B1-Motion>", drag)
    for widget in (dialog, listbox):
        widget.bind("<Alt-Up>", lambda _e: move(-1))
        widget.bind("<Alt-Down>", lambda _e: move(1))
    dialog.bind("<Return>", lambda _e: finish(list(order)))
    dialog.bind("<Escape>", lambda _e: finish(None))
    dialog.protocol("WM_DELETE_WINDOW", lambda: finish(None))

    refresh(0)
    _center_dialog_on_root(gui, dialog)
    try:
        dialog.lift()
        listbox.focus_set()
    except Exception:  # pragma: no cover - defensive on headless Tk
        pass


def _style_listbox(gui: "TalksReducerGUI", listbox: object) -> None:
    """Colour the plain-Tk Listbox from the active ttk theme.

    ``_apply_dialog_theme`` only paints the Toplevel, so without this the list
    stays white in dark mode.
    """

    try:
        background = gui.style.lookup("TEntry", "fieldbackground") or ""
        foreground = gui.style.lookup("TLabel", "foreground") or ""
        border = gui.style.lookup("TFrame", "background") or ""
    except Exception:  # pragma: no cover - style is always present
        return
    options = {"selectbackground": _ACCENT, "selectforeground": "#ffffff"}
    if background:
        options["bg"] = background
    if foreground:
        options["fg"] = foreground
    if border:
        options["highlightbackground"] = border
    listbox.configure(**options)  # type: ignore[attr-defined]
