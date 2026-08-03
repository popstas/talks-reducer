"""A button-based choice control for settings with a handful of values.

The module is deliberately split in two: the dataclasses and helpers below are
pure Python and carry the value semantics, while :class:`SegmentedChoice` is a
thin Tk shell over them. ``tk``/``ttk`` are injected rather than imported so the
control can be exercised with widget stubs in tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence, Union

from .tooltips import add_tooltip

TOLERANCE = 1e-9

Value = Union[float, str]


@dataclass(frozen=True)
class Option:
    """A single selectable value with its button label and optional tooltip."""

    value: Value
    label: str
    tooltip: Optional[str] = None


@dataclass(frozen=True)
class CustomSpec:
    """Bounds and formatting for values typed into the ``...`` slot."""

    minimum: float
    maximum: float
    display_format: str = "{:g}"


def resolve_selection(value: Value, options: Sequence[Option]) -> Optional[int]:
    """Return the index of the option matching *value*, or ``None``.

    Numeric options compare within :data:`TOLERANCE` so a float that survived a
    round-trip through ``settings.json`` still matches its button. ``None`` means
    the value belongs in the custom slot rather than on a preset button.
    """

    for index, option in enumerate(options):
        if isinstance(option.value, str):
            if str(value) == option.value:
                return index
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if abs(numeric - float(option.value)) <= TOLERANCE:
            return index
    return None


def parse_custom(text: str, spec: CustomSpec) -> float:
    """Parse *text* into a value clamped to *spec*'s bounds.

    Raises ``ValueError`` when the text is blank or not a number, letting the
    caller cancel the edit rather than write nonsense into the bound variable.
    """

    stripped = str(text).strip()
    if not stripped:
        raise ValueError("empty custom value")
    numeric = float(stripped)
    return max(spec.minimum, min(spec.maximum, numeric))


def format_custom_label(value: float, spec: CustomSpec) -> str:
    """Return the button label for a committed custom *value*."""

    return spec.display_format.format(value)


SEGMENT_STYLE = "Segment.TButton"
SELECTED_SEGMENT_STYLE = "SelectedSegment.TButton"
# The "…" slot is styled apart from the option buttons: it has to line up with
# the entry that replaces it, and a segment's horizontal padding would make it
# noticeably wider than that entry.
CUSTOM_SEGMENT_STYLE = "CustomSegment.TButton"
SELECTED_CUSTOM_SEGMENT_STYLE = "SelectedCustomSegment.TButton"
CUSTOM_PLACEHOLDER = "…"

# The ``…`` slot's button and its inline entry share this width (in text units)
# so swapping one for the other never reflows the row mid-edit. It also has to
# fit the widest committed label a control can show, e.g. ``60 sec``.
CUSTOM_SLOT_WIDTH = 6


class SegmentedChoice:
    """Render *options* as a row of buttons acting like radio buttons.

    When *variable* is given the control both writes it on click and traces it,
    so a preset applied elsewhere restyles the buttons without the caller doing
    anything. Passing ``variable=None`` yields a display-only group whose
    highlight is driven externally through :meth:`set_selected` — used by the
    "Basic options" macro row, where the selected entry is derived from several
    other variables at once.

    *custom* enables a trailing ``…`` slot that swaps itself for an entry so any
    value inside the spec's bounds can be typed. *default_value* is the fallback
    used when the bound variable holds something unparseable.
    """

    def __init__(
        self,
        parent: Any,
        options: Sequence[Option],
        *,
        tk: Any,
        ttk: Any,
        variable: Any = None,
        default_value: Optional[Value] = None,
        custom: Optional[CustomSpec] = None,
        tooltip: Optional[str] = None,
        on_change: Optional[Callable[[Value], None]] = None,
    ) -> None:
        self._tk = tk
        self._ttk = ttk
        self._options = list(options)
        self._variable = variable
        self._default_value = default_value
        self._custom = custom
        self._on_change = on_change
        self._custom_value: Optional[float] = None
        self._selected_index: Optional[int] = None
        self._editing = False

        self.frame = ttk.Frame(parent)
        self.buttons = []
        self._build_buttons()

        self.custom_button = None
        self.custom_entry = None
        self.custom_var = None
        if custom is not None:
            self.custom_var = tk.StringVar(value="")
            self.custom_button = ttk.Button(
                self.frame,
                text=CUSTOM_PLACEHOLDER,
                style=CUSTOM_SEGMENT_STYLE,
                width=CUSTOM_SLOT_WIDTH,
                command=self._begin_custom_edit,
            )
            self.custom_button.pack(side=tk.LEFT)
            self.custom_entry = ttk.Entry(
                self.frame,
                textvariable=self.custom_var,
                width=CUSTOM_SLOT_WIDTH,
                justify="center",
            )
            self.custom_entry.bind("<Return>", self._commit_custom_edit)
            self.custom_entry.bind("<Escape>", self._cancel_custom_edit)
            self.custom_entry.bind("<FocusOut>", self._cancel_custom_edit)

        if tooltip:
            add_tooltip(self.frame, tooltip, tk_module=tk)

        if variable is not None:
            variable.trace_add("write", self._on_variable_write)
            self._sync_from_variable()

    def _build_buttons(self) -> None:
        """Create one button per option, packed left to right in option order.

        Split out of ``__init__`` so :meth:`set_options` can rebuild the row.
        """

        for index, option in enumerate(self._options):
            button = self._ttk.Button(
                self.frame,
                text=option.label,
                style=SEGMENT_STYLE,
                command=lambda i=index: self._on_option_click(i),
            )
            button.pack(side=self._tk.LEFT)
            if option.tooltip:
                add_tooltip(button, option.tooltip, tk_module=self._tk)
            self.buttons.append(button)

    def set_options(self, options: Sequence[Option]) -> None:
        """Replace the option list and rebuild the buttons.

        Controls whose options are user-authored — the preset row, whose entries
        can be added, renamed, reordered or deleted while the window is open —
        need the row rebuilt rather than merely restyled. The custom slot is
        repacked afterwards so it stays last, and the selection is re-derived
        from the bound variable so a surviving option stays highlighted.
        """

        for button in self.buttons:
            button.destroy()
        self.buttons = []
        self._options = list(options)
        self._build_buttons()

        if self.custom_button is not None:
            self.custom_button.pack_forget()
            self.custom_button.pack(side=self._tk.LEFT)

        if self._variable is not None:
            self._sync_from_variable()
        else:
            self._selected_index = None
            self._apply_styles()

    def get_value(self) -> Optional[Value]:
        """Return the currently selected value, or ``None`` when unbound."""

        if self._variable is None:
            return None
        return self._variable.get()

    def set_value(self, value: Value) -> None:
        """Write *value* into the bound variable and restyle the buttons.

        ``layout.add_segmented`` wraps this in an ``apply_and_persist`` helper
        and registers *that* wrapper into ``gui._slider_updaters`` — not this
        method directly — because ``set_value`` deliberately never persists or
        fires ``on_change``. Out-of-range values are clamped to the custom
        slot's bounds (when one is configured) so the bound variable never
        diverges from what the buttons/custom slot display.
        """

        coerced = self._coerce(value)
        if self._variable is not None:
            self._variable.set(coerced)
        else:
            self.set_selected(coerced)

    def set_selected(self, value: Optional[Value]) -> None:
        """Highlight the button matching *value* without writing any variable."""

        index = None if value is None else resolve_selection(value, self._options)
        self._selected_index = index
        self._apply_styles()

    def _coerce(self, value: Value) -> Value:
        """Return *value* as a float when the options are numeric, clamped to range.

        When a :class:`CustomSpec` is configured the numeric result is clamped
        to its ``minimum``/``maximum`` so ``set_value`` can never write
        something out of range: ``_sync_from_variable`` already clamps for
        *display* purposes via :func:`parse_custom`, but it never writes the
        clamped value back, so without this the bound variable (and anything
        persisting it, e.g. ``settings.json``) could silently diverge from
        what the control shows. Values already inside the bounds — including
        every button's own value — pass through unchanged.
        """

        if self._options and isinstance(self._options[0].value, str):
            return str(value)
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            if self._default_value is not None:
                return self._default_value
            return value
        if self._custom is not None:
            numeric = max(self._custom.minimum, min(self._custom.maximum, numeric))
        return numeric

    def _on_variable_write(self, *_args: Any) -> None:
        """Resync the selection whenever something else writes the bound variable."""

        self._sync_from_variable()

    def _sync_from_variable(self) -> None:
        """Recompute the selection and custom slot from the bound variable."""

        raw = self._variable.get()
        index = resolve_selection(raw, self._options)
        if index is None and self._custom is not None:
            try:
                self._custom_value = parse_custom(str(raw), self._custom)
            except ValueError:
                self._custom_value = None
                if self._default_value is not None:
                    index = resolve_selection(self._default_value, self._options)
        elif index is None and self._default_value is not None:
            index = resolve_selection(self._default_value, self._options)
        else:
            self._custom_value = None
        self._selected_index = index
        self._apply_styles()

    def _apply_styles(self) -> None:
        """Repaint every button so exactly one carries the selected style."""

        for position, button in enumerate(self.buttons):
            style = (
                SELECTED_SEGMENT_STYLE
                if position == self._selected_index
                else SEGMENT_STYLE
            )
            button.configure(style=style)
        if self.custom_button is None:
            return
        if self._custom_value is None:
            self.custom_button.configure(
                text=CUSTOM_PLACEHOLDER, style=CUSTOM_SEGMENT_STYLE
            )
        else:
            self.custom_button.configure(
                text=format_custom_label(self._custom_value, self._custom),
                style=SELECTED_CUSTOM_SEGMENT_STYLE,
            )

    def _on_option_click(self, index: int) -> None:
        """Select the button at *index*, write its value, and notify ``on_change``."""

        value = self._options[index].value
        self._custom_value = None
        self._selected_index = index
        if self._variable is not None:
            self._variable.set(value)
        self._apply_styles()
        if self._on_change is not None:
            self._on_change(value)

    def _begin_custom_edit(self) -> None:
        """Swap the custom slot button for an entry and focus it."""

        if self._editing:
            return
        self._editing = True
        initial = (
            format_custom_label(self._custom_value, self._custom)
            if self._custom_value is not None
            else ""
        )
        self.custom_var.set(initial)
        self.custom_button.pack_forget()
        self.custom_entry.pack(side=self._tk.LEFT)
        self.custom_entry.focus_set()

    def _end_custom_edit(self) -> None:
        """Swap the entry back out for the custom slot button and repaint styles."""

        self._editing = False
        self.custom_entry.pack_forget()
        self.custom_button.pack(side=self._tk.LEFT)
        self._apply_styles()

    def _commit_custom_edit(self, _event: Any = None) -> None:
        """Validate the typed value and adopt it, or cancel on bad input."""

        if not self._editing:
            return
        try:
            value = parse_custom(self.custom_var.get(), self._custom)
        except ValueError:
            self._end_custom_edit()
            return
        self._custom_value = value
        self._selected_index = None
        if self._variable is not None:
            self._variable.set(value)
        self._end_custom_edit()
        if self._on_change is not None:
            self._on_change(value)

    def _cancel_custom_edit(self, _event: Any = None) -> None:
        """Abandon the edit and restore the slot to its previous state."""

        if not self._editing:
            return
        self._end_custom_edit()
