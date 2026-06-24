"""Input selection and drop-zone helpers for the Talks Reducer GUI."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Sequence

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from tkinter import Misc

    from .app import TalksReducerGUI


class InputController:
    """Manage file selection, drop zone interactions, and related input state."""

    def __init__(self, gui: "TalksReducerGUI") -> None:
        self.gui = gui

    def configure_drop_targets(self, widget: "Misc") -> None:
        if not self.gui._dnd_available:
            return
        widget.drop_target_register(self.gui.DND_FILES)  # type: ignore[attr-defined]
        widget.dnd_bind("<<Drop>>", self.gui._on_drop)  # type: ignore[attr-defined]

    def ask_for_input_files(self) -> tuple[str, ...]:
        """Prompt the user to select input files for processing."""

        return self.gui.filedialog.askopenfilenames(
            title="Select input files",
            filetypes=[
                ("Video files", "*.mp4 *.mkv *.mov *.avi *.m4v"),
                ("All", "*.*"),
            ],
        )

    def add_files(self) -> None:
        files = self.ask_for_input_files()
        self.extend_inputs(files)

    def add_directory(self) -> None:
        directory = self.gui.filedialog.askdirectory(title="Select input folder")
        if directory:
            self.extend_inputs([directory])

    def extend_inputs(self, paths: Iterable[str], *, auto_run: bool = False) -> None:
        added = False
        for path in paths:
            if path and path not in self.gui.input_files:
                self.gui.input_files.append(path)
                added = True
        if added:
            notify = getattr(self.gui, "_on_inputs_updated", None)
            if callable(notify):
                notify()
        if auto_run and added and self.gui.run_after_drop_var.get():
            if self._cut_requires_manual_convert():
                return
            self.gui._start_run()

    def _cut_requires_manual_convert(self) -> bool:
        """Return ``True`` when an active Cut + Advanced layout defers the run.

        With Cut video enabled outside Simple mode the user reviews the trim and
        starts processing with the panel's **Convert** button, so dropping a file
        must not kick off the conversion automatically.
        """

        cut_var = getattr(self.gui, "cut_enabled_var", None)
        simple_var = getattr(self.gui, "simple_mode_var", None)
        if cut_var is None or simple_var is None:
            return False
        return bool(cut_var.get()) and not bool(simple_var.get())

    def clear_input_files(self) -> None:
        """Clear all queued input files."""

        self.gui.input_files.clear()

    def on_drop(self, event: object) -> None:
        data = getattr(event, "data", "")
        if not data:
            return
        paths = self.gui.root.tk.splitlist(data)
        cleaned = [path.strip("{}") for path in paths]
        # Clear existing files before adding dropped files
        self.gui.input_files.clear()
        self.extend_inputs(cleaned, auto_run=True)

    def on_drop_zone_click(self, event: object) -> str | None:
        """Open a file selection dialog when the drop zone is activated."""

        files = self.ask_for_input_files()
        if not files:
            return "break"
        self.clear_input_files()
        self.extend_inputs(files, auto_run=True)
        return "break"

    def browse_path(self, variable, label: str) -> None:  # type: (object, str) -> None
        if "folder" in label.lower():
            result = self.gui.filedialog.askdirectory()
        else:
            initial = variable.get() or Path.cwd()
            result = self.gui.filedialog.asksaveasfilename(
                initialfile=Path(initial).name
            )
        if result:
            variable.set(result)
