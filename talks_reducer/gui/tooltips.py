"""Lightweight hover tooltips for Tkinter widgets.

The desktop GUI does not ship with a tooltip widget, so this module provides a
small reusable helper that shows a borderless label near a widget while the
pointer hovers over it.
"""

from __future__ import annotations

from typing import Any, Optional


class _Tooltip:
    """Show a text bubble near ``widget`` while the pointer hovers over it."""

    def __init__(
        self,
        widget: Any,
        text: str,
        *,
        tk_module: Any,
        delay_ms: int = 500,
        wraplength: int = 260,
    ) -> None:
        self._widget = widget
        self._text = text
        self._tk = tk_module
        self._delay_ms = delay_ms
        self._wraplength = wraplength
        self._after_id: Optional[Any] = None
        self._window: Optional[Any] = None

        widget.bind("<Enter>", self._on_enter)
        widget.bind("<Leave>", self._on_leave)
        widget.bind("<ButtonPress>", self._on_leave)

    def _on_enter(self, _event: Any = None) -> None:
        """Schedule the tooltip to appear after a short delay."""

        self._cancel_pending()
        self._after_id = self._widget.after(self._delay_ms, self._show)

    def _on_leave(self, _event: Any = None) -> None:
        """Hide the tooltip and cancel any pending show."""

        self._cancel_pending()
        self._hide()

    def _cancel_pending(self) -> None:
        """Cancel a scheduled show, if one is pending."""

        if self._after_id is not None:
            self._widget.after_cancel(self._after_id)
            self._after_id = None

    def _show(self) -> Optional[Any]:
        """Create and position the tooltip window."""

        self._after_id = None
        if self._window is not None or not self._text:
            return self._window

        x = self._widget.winfo_rootx() + 12
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4

        window = self._tk.Toplevel(self._widget)
        window.wm_overrideredirect(True)
        window.wm_geometry(f"+{x}+{y}")

        label = self._tk.Label(
            window,
            text=self._text,
            justify="left",
            background="#ffffe0",
            foreground="#000000",
            relief="solid",
            borderwidth=1,
            padx=6,
            pady=3,
            wraplength=self._wraplength,
        )
        label.pack()

        self._window = window
        return window

    def _hide(self) -> None:
        """Destroy the tooltip window if it is visible."""

        if self._window is not None:
            self._window.destroy()
            self._window = None


def add_tooltip(
    widget: Any,
    text: str,
    *,
    tk_module: Any,
    delay_ms: int = 500,
) -> _Tooltip:
    """Attach a hover tooltip displaying ``text`` to ``widget``.

    ``tk_module`` supplies the ``Toplevel`` and ``Label`` classes used to render
    the bubble, so callers pass the ``tkinter``/``tk`` module already available
    on the GUI namespace.
    """

    return _Tooltip(widget, text, tk_module=tk_module, delay_ms=delay_ms)
