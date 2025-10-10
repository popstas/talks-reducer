"""Discovery helpers for the Talks Reducer GUI."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, List

from ..discovery import discover_servers as core_discover_servers

if TYPE_CHECKING:  # pragma: no cover - imported for type checking only
    from .app import TalksReducerGUI


def start_discovery(gui: "TalksReducerGUI") -> None:
    """Search the local network for running Talks Reducer servers."""

    if gui._discovery_thread and gui._discovery_thread.is_alive():
        return

    gui.server_discover_button.configure(state=gui.tk.DISABLED, text="Discovering…")
    gui._append_log("Discovering Talks Reducer servers on port 9005…")

    def worker() -> None:
        try:
            urls = core_discover_servers(
                progress_callback=lambda current, total: gui._schedule_on_ui_thread(
                    lambda c=current, t=total: on_discovery_progress(gui, c, t)
                )
            )
        except Exception as exc:  # pragma: no cover - network failure safeguard
            gui._schedule_on_ui_thread(lambda: on_discovery_failed(gui, exc))
            return
        gui._schedule_on_ui_thread(lambda: on_discovery_complete(gui, urls))

    gui._discovery_thread = threading.Thread(target=worker, daemon=True)
    gui._discovery_thread.start()


def on_discovery_failed(gui: "TalksReducerGUI", exc: Exception) -> None:
    gui.server_discover_button.configure(state=gui.tk.NORMAL, text="Discover")
    message = f"Discovery failed: {exc}"
    gui._append_log(message)
    gui.messagebox.showerror("Discovery failed", message)


def on_discovery_progress(gui: "TalksReducerGUI", current: int, total: int) -> None:
    if total > 0:
        bounded = max(0, min(current, total))
        label = f"{bounded} / {total}"
    else:
        label = "Discovering…"
    gui.server_discover_button.configure(text=label)


def on_discovery_complete(gui: "TalksReducerGUI", urls: List[str]) -> None:
    gui.server_discover_button.configure(state=gui.tk.NORMAL, text="Discover")
    if not urls:
        gui._append_log("No Talks Reducer servers were found.")
        gui.messagebox.showinfo(
            "No servers found",
            "No Talks Reducer servers responded on port 9005.",
        )
        return

    gui._append_log(f"Discovered {len(urls)} server{'s' if len(urls) != 1 else ''}.")

    if len(urls) == 1:
        gui.server_url_var.set(urls[0])
        return

    show_discovery_results(gui, urls)


def show_discovery_results(gui: "TalksReducerGUI", urls: List[str]) -> None:
    dialog = gui.tk.Toplevel(gui.root)
    dialog.title("Select server")
    dialog.transient(gui.root)
    dialog.grab_set()

    gui.ttk.Label(dialog, text="Select a Talks Reducer server:").grid(
        row=0, column=0, columnspan=2, sticky="w", padx=gui.PADDING, pady=(12, 4)
    )

    listbox = gui.tk.Listbox(
        dialog,
        height=min(10, len(urls)),
        selectmode=gui.tk.SINGLE,
    )
    listbox.grid(
        row=1,
        column=0,
        columnspan=2,
        padx=gui.PADDING,
        sticky="nsew",
    )
    dialog.columnconfigure(0, weight=1)
    dialog.columnconfigure(1, weight=1)
    dialog.rowconfigure(1, weight=1)

    for url in urls:
        listbox.insert(gui.tk.END, url)
    listbox.select_set(0)

    def choose(_: object | None = None) -> None:
        selection = listbox.curselection()
        if not selection:
            return
        index = selection[0]
        gui.server_url_var.set(urls[index])
        dialog.grab_release()
        dialog.destroy()

    def cancel() -> None:
        dialog.grab_release()
        dialog.destroy()

    listbox.bind("<Double-Button-1>", choose)
    listbox.bind("<Return>", choose)

    button_frame = gui.ttk.Frame(dialog)
    button_frame.grid(row=2, column=0, columnspan=2, pady=(8, 12))
    gui.ttk.Button(button_frame, text="Use server", command=choose).pack(
        side=gui.tk.LEFT, padx=(0, 8)
    )
    gui.ttk.Button(button_frame, text="Cancel", command=cancel).pack(side=gui.tk.LEFT)
    dialog.protocol("WM_DELETE_WINDOW", cancel)
