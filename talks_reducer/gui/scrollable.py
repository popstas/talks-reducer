"""A vertically scrollable frame whose height is set from outside.

Used for the Advanced block, which is taller than the full layout can show. The
caller decides how much height is left (``fit``); the area shows its content at
that height and adds a scrollbar only when the content does not fit, so a short
block looks exactly like the plain frame it replaces.

As in :mod:`.segmented`, ``tk``/``ttk`` are injected so the pure sizing rule can
be tested without a display.
"""

from __future__ import annotations

from typing import Any


def fit_height(*, available: int, content: int, minimum: int) -> tuple[int, bool]:
    """Return ``(height, needs_scrollbar)`` for *content* in *available* pixels.

    Content that fits keeps its own height. Taller content is cut to the space
    left, but never below *minimum*, so a cramped window still shows a few rows
    to scroll through instead of collapsing the block to nothing.
    """

    if content <= max(available, minimum):
        return content, False
    return max(available, minimum), True


class ScrollableFrame:
    """A ``Canvas`` + ``Scrollbar`` pair hosting :attr:`inner`.

    Children go into :attr:`inner`; :attr:`container` is what the caller
    grids, shows and hides. The inner frame always spans the canvas width, and
    the canvas asks for the inner frame's width so the window still makes room
    for the widest row.
    """

    def __init__(
        self, parent: Any, *, tk: Any, ttk: Any, scroll_step: int = 30
    ) -> None:
        """Build the area; one wheel notch scrolls *scroll_step* pixels."""

        self.container = ttk.Frame(parent)
        self.container.columnconfigure(0, weight=1)
        self.container.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(
            self.container,
            highlightthickness=0,
            borderwidth=0,
            height=1,
            yscrollincrement=scroll_step,
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar = ttk.Scrollbar(
            self.container, orient=tk.VERTICAL, command=self.canvas.yview
        )
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.scrollbar.grid_remove()
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.inner = ttk.Frame(self.canvas)
        self._window = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.scrolling = False
        self.canvas.bind("<Configure>", self._on_canvas_configure, add="+")

    def _on_canvas_configure(self, event: Any) -> None:
        """Stretch the inner frame across the canvas."""

        self.canvas.itemconfigure(self._window, width=event.width)

    def fit(self, *, available: int, minimum: int) -> None:
        """Size the area for *available* pixels of height (see :func:`fit_height`)."""

        content = self.inner.winfo_reqheight()
        width = self.inner.winfo_reqwidth()
        height, scrolling = fit_height(
            available=available, content=content, minimum=minimum
        )
        if int(self.canvas.cget("height")) != height:
            self.canvas.configure(height=height)
        if int(self.canvas.cget("width")) != width:
            self.canvas.configure(width=width)
        self.canvas.configure(scrollregion=(0, 0, width, content))
        if scrolling != self.scrolling:
            self.scrolling = scrolling
            if scrolling:
                self.scrollbar.grid()
            else:
                self.scrollbar.grid_remove()
                self.canvas.yview_moveto(0)

    def contains(self, widget: Any) -> bool:
        """Return whether *widget* is the area or one of its descendants."""

        if widget is None:
            return False
        own = str(self.container)
        name = str(widget)
        return name == own or name.startswith(own + ".")

    def scroll_by_wheel(self, *, delta: int, widget: Any) -> bool:
        """Scroll for a wheel turn over *widget*; return whether it was handled.

        Only turns over the area itself count, and only while it scrolls: the
        rest of the window (the log above all) keeps its own wheel behaviour.
        """

        if not self.scrolling or not self.contains(widget):
            return False
        steps = -int(delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
        self.canvas.yview_scroll(steps, "units")
        return True
