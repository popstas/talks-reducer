# Segmented Settings Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace every small-choice slider and radio row in the Talks Reducer desktop GUI with a reusable button group that supports a default value and a `...` slot for arbitrary input, and regroup the Advanced settings panel so related settings sit together one per line.

**Architecture:** A new `talks_reducer/gui/segmented.py` splits into a pure, Tk-free core (value↔option matching, custom-value parsing) and a thin `SegmentedChoice` widget that renders one `ttk.Button` per option. The widget both writes and traces its bound `tk` variable, so preset application keeps working unchanged. `layout.py` swaps `add_slider()` for `add_segmented()` while preserving the `_slider_updaters` / `_basic_defaults` / `_basic_variables` bookkeeping that `apply_preset_to_gui` depends on.

**Tech Stack:** Python 3, Tkinter/ttk, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-03-segmented-settings-design.md`

## Global Constraints

- Run `black` and `isort` (configured via `pyproject.toml`) before every commit.
- New logic gets function-level docstrings, not inline comments.
- No new dependencies. `segmented.py` receives `tk` and `ttk` as injected arguments — it must never `import tkinter` at module scope, so tests can pass stubs.
- Commit messages use angular format. `feat:` and `fix:` feed `CHANGELOG.md` and are reserved for user-facing changes; use `refactor:`, `test:`, `docs:`, `style:` for everything else.
- Tests must not instantiate real Tk. Follow the existing stub harness in `tests/test_gui_layout.py` (`WidgetFactory`, `WidgetStub`, `StringVarStub`, `DoubleVarStub`).
- `talks_reducer/gui/tooltips.py` must not be modified by this plan.
- Float comparison tolerance throughout is `1e-9`, matching `BASIC_PRESET_TOLERANCE` in `layout.py`.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `talks_reducer/gui/segmented.py` (new) | `Option`, `CustomSpec`, pure helpers `resolve_selection` / `parse_custom`, and the `SegmentedChoice` widget |
| `talks_reducer/gui/theme.py` (modify) | Two new ttk styles for selected/unselected segment buttons |
| `talks_reducer/gui/layout.py` (modify) | `add_segmented()` replaces `add_slider()`; panel regrouping; keyframe interval migration; threshold `?` link; server-status label |
| `talks_reducer/gui/app.py` (modify) | `remote_status_var` + `_set_remote_status`; processing-mode visibility |
| `talks_reducer/gui/remote.py` (modify) | Feed the remote status label from the existing ping status callback |
| `tests/test_gui_segmented.py` (new) | Pure helpers and widget behavior |
| `tests/test_gui_layout.py` (modify) | Preset contract still holds after the slider removal |
| `tests/test_gui_theme.py` (modify) | The new segment and heading styles are configured |
| `tests/test_gui_remote.py` (modify) | Ping status reaches the remote status label |
| `docs/gui.md` (modify) | User-facing description of the new controls |

---

### Task 1: Pure core of the segmented module

**Files:**
- Create: `talks_reducer/gui/segmented.py`
- Test: `tests/test_gui_segmented.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Option(value, label, tooltip=None)`, `CustomSpec(minimum, maximum, display_format)`, `resolve_selection(value, options) -> int | None`, `parse_custom(text, spec) -> float`, `format_custom_label(value, spec) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_gui_segmented.py`:

```python
from __future__ import annotations

import pytest

from talks_reducer.gui.segmented import (
    CustomSpec,
    Option,
    format_custom_label,
    parse_custom,
    resolve_selection,
)

SPEED_OPTIONS = [
    Option(1.0, "1"),
    Option(2.0, "2"),
    Option(5.0, "5"),
    Option(10.0, "10"),
]
CODEC_OPTIONS = [Option("h264", "h.264"), Option("hevc", "h.265")]
SPEED_CUSTOM = CustomSpec(minimum=1.0, maximum=10.0, display_format="{:g}")


def test_resolve_selection_matches_float_option():
    assert resolve_selection(5.0, SPEED_OPTIONS) == 2


def test_resolve_selection_tolerates_float_noise():
    assert resolve_selection(5.0 + 1e-12, SPEED_OPTIONS) == 2


def test_resolve_selection_returns_none_for_unlisted_value():
    assert resolve_selection(3.5, SPEED_OPTIONS) is None


def test_resolve_selection_matches_string_option():
    assert resolve_selection("hevc", CODEC_OPTIONS) == 1


def test_resolve_selection_handles_non_numeric_value_against_float_options():
    assert resolve_selection("nonsense", SPEED_OPTIONS) is None


def test_parse_custom_reads_a_plain_number():
    assert parse_custom("3.5", SPEED_CUSTOM) == pytest.approx(3.5)


def test_parse_custom_strips_whitespace():
    assert parse_custom("  7 ", SPEED_CUSTOM) == pytest.approx(7.0)


def test_parse_custom_clamps_above_maximum():
    assert parse_custom("99", SPEED_CUSTOM) == pytest.approx(10.0)


def test_parse_custom_clamps_below_minimum():
    assert parse_custom("0.1", SPEED_CUSTOM) == pytest.approx(1.0)


def test_parse_custom_rejects_garbage():
    with pytest.raises(ValueError):
        parse_custom("abc", SPEED_CUSTOM)


def test_parse_custom_rejects_empty_text():
    with pytest.raises(ValueError):
        parse_custom("   ", SPEED_CUSTOM)


def test_format_custom_label_drops_trailing_zeros():
    assert format_custom_label(3.5, SPEED_CUSTOM) == "3.5"
    assert format_custom_label(7.0, SPEED_CUSTOM) == "7"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_gui_segmented.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'talks_reducer.gui.segmented'`

- [ ] **Step 3: Write the module core**

Create `talks_reducer/gui/segmented.py`:

```python
"""A button-based choice control for settings with a handful of values.

The module is deliberately split in two: the dataclasses and helpers below are
pure Python and carry the value semantics, while :class:`SegmentedChoice` is a
thin Tk shell over them. ``tk``/``ttk`` are injected rather than imported so the
control can be exercised with widget stubs in tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Union

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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_gui_segmented.py -v`
Expected: PASS — 12 tests.

- [ ] **Step 5: Format and commit**

```bash
black talks_reducer/gui/segmented.py tests/test_gui_segmented.py
isort talks_reducer/gui/segmented.py tests/test_gui_segmented.py
git add talks_reducer/gui/segmented.py tests/test_gui_segmented.py
git commit -m "refactor: Add pure core for the segmented choice control"
```

---

### Task 2: The `SegmentedChoice` widget

**Files:**
- Modify: `talks_reducer/gui/segmented.py`
- Test: `tests/test_gui_segmented.py`

**Interfaces:**
- Consumes: `Option`, `CustomSpec`, `resolve_selection`, `parse_custom`, `format_custom_label` from Task 1.
- Produces: `SegmentedChoice(parent, options, *, tk, ttk, variable=None, default_value=None, custom=None, tooltip=None, on_change=None)` with public attribute `frame` and methods `set_value(value) -> None`, `set_selected(value) -> None`, `get_value() -> Value | None`. Style names `"Segment.TButton"` and `"SelectedSegment.TButton"`.

Behavior contract:

- Buttons pack left-to-right in option order; the `...` slot packs last when `custom` is given.
- Clicking an option writes `variable` (when bound), restyles, and calls `on_change(value)`.
- Clicking `...` hides the slot button and packs an `Entry` in its place. `Return` commits, `Escape` and `<FocusOut>` cancel.
- A committed custom value re-labels the slot button and selects it.
- `set_value` is the programmatic entry point registered into `gui._slider_updaters`; it accepts a string or a number.
- `set_selected` only restyles and is for groups built with `variable=None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gui_segmented.py`:

```python
from types import SimpleNamespace
from unittest.mock import Mock

from talks_reducer.gui.segmented import SegmentedChoice


class _Widget:
    """Minimal stand-in for a ttk widget used by SegmentedChoice."""

    def __init__(self, kind, **kwargs):
        self.kind = kind
        self.kwargs = dict(kwargs)
        self.style_history = []
        self.packed = False
        self.bindings = {}
        self.focused = False
        if "style" in kwargs:
            self.style_history.append(kwargs["style"])

    def pack(self, **kwargs):
        self.packed = True
        return self

    def pack_forget(self):
        self.packed = False

    def configure(self, **kwargs):
        self.kwargs.update(kwargs)
        if "style" in kwargs:
            self.style_history.append(kwargs["style"])

    def bind(self, sequence, callback):
        self.bindings[sequence] = callback

    def focus_set(self):
        self.focused = True

    def selection_range(self, *_args):
        return None

    @property
    def style(self):
        return self.kwargs.get("style")

    @property
    def text(self):
        return self.kwargs.get("text")


def _factory(kind):
    created = []

    def build(parent, **kwargs):
        widget = _Widget(kind, **kwargs)
        created.append(widget)
        return widget

    build.created = created
    return build


class _Var:
    def __init__(self, value):
        self._value = value
        self.traces = []

    def get(self):
        return self._value

    def set(self, value):
        self._value = value
        for callback in list(self.traces):
            callback()

    def trace_add(self, _mode, callback):
        self.traces.append(lambda *a: callback())


def _make_modules():
    ttk = SimpleNamespace(
        Frame=_factory("Frame"),
        Button=_factory("Button"),
        Entry=_factory("Entry"),
    )
    tk = SimpleNamespace(LEFT="left", StringVar=lambda value="": _Var(value))
    return tk, ttk


def _build(variable=None, custom=None, on_change=None, default_value=None):
    tk, ttk = _make_modules()
    control = SegmentedChoice(
        object(),
        SPEED_OPTIONS,
        tk=tk,
        ttk=ttk,
        variable=variable,
        custom=custom,
        on_change=on_change,
        default_value=default_value,
    )
    return control, ttk


def test_creates_one_button_per_option():
    control, ttk = _build()
    assert len(control.buttons) == 4
    assert [button.text for button in control.buttons] == ["1", "2", "5", "10"]


def test_bound_variable_value_is_selected_on_build():
    control, _ = _build(variable=_Var(5.0))
    assert control.buttons[2].style == "SelectedSegment.TButton"
    assert control.buttons[0].style == "Segment.TButton"


def test_clicking_an_option_writes_the_variable():
    variable = _Var(5.0)
    control, _ = _build(variable=variable)
    control.buttons[3].kwargs["command"]()
    assert variable.get() == 10.0
    assert control.buttons[3].style == "SelectedSegment.TButton"


def test_clicking_an_option_invokes_on_change():
    on_change = Mock()
    control, _ = _build(variable=_Var(1.0), on_change=on_change)
    control.buttons[1].kwargs["command"]()
    on_change.assert_called_once_with(2.0)


def test_external_variable_write_restyles_buttons():
    variable = _Var(1.0)
    control, _ = _build(variable=variable)
    variable.set(10.0)
    assert control.buttons[3].style == "SelectedSegment.TButton"


def test_set_value_accepts_a_string():
    variable = _Var(1.0)
    control, _ = _build(variable=variable)
    control.set_value("5")
    assert variable.get() == 5.0
    assert control.buttons[2].style == "SelectedSegment.TButton"


def test_custom_slot_is_absent_without_a_spec():
    control, _ = _build()
    assert control.custom_button is None


def test_custom_slot_renders_ellipsis_when_value_matches_an_option():
    control, _ = _build(variable=_Var(5.0), custom=SPEED_CUSTOM)
    assert control.custom_button.text == "…"
    assert control.custom_button.style == "Segment.TButton"


def test_unlisted_initial_value_lands_in_the_custom_slot():
    control, _ = _build(variable=_Var(3.5), custom=SPEED_CUSTOM)
    assert control.custom_button.text == "3.5"
    assert control.custom_button.style == "SelectedSegment.TButton"


def test_clicking_custom_swaps_in_an_entry():
    control, _ = _build(variable=_Var(5.0), custom=SPEED_CUSTOM)
    control.custom_button.kwargs["command"]()
    assert control.custom_button.packed is False
    assert control.custom_entry.packed is True
    assert control.custom_entry.focused is True


def test_committing_a_custom_value_updates_variable_and_label():
    variable = _Var(5.0)
    control, _ = _build(variable=variable, custom=SPEED_CUSTOM)
    control.custom_button.kwargs["command"]()
    control.custom_var.set("3.5")
    control.custom_entry.bindings["<Return>"](None)
    assert variable.get() == 3.5
    assert control.custom_button.text == "3.5"
    assert control.custom_button.style == "SelectedSegment.TButton"
    assert control.custom_entry.packed is False


def test_committing_an_out_of_range_custom_value_clamps_it():
    variable = _Var(5.0)
    control, _ = _build(variable=variable, custom=SPEED_CUSTOM)
    control.custom_button.kwargs["command"]()
    control.custom_var.set("99")
    control.custom_entry.bindings["<Return>"](None)
    assert variable.get() == 10.0


def test_committing_garbage_cancels_the_edit():
    variable = _Var(5.0)
    control, _ = _build(variable=variable, custom=SPEED_CUSTOM)
    control.custom_button.kwargs["command"]()
    control.custom_var.set("abc")
    control.custom_entry.bindings["<Return>"](None)
    assert variable.get() == 5.0
    assert control.custom_button.text == "…"
    assert control.custom_entry.packed is False


def test_escape_cancels_the_edit():
    variable = _Var(5.0)
    control, _ = _build(variable=variable, custom=SPEED_CUSTOM)
    control.custom_button.kwargs["command"]()
    control.custom_var.set("3.5")
    control.custom_entry.bindings["<Escape>"](None)
    assert variable.get() == 5.0
    assert control.custom_entry.packed is False


def test_selecting_an_option_resets_the_custom_slot():
    variable = _Var(3.5)
    control, _ = _build(variable=variable, custom=SPEED_CUSTOM)
    assert control.custom_button.text == "3.5"
    control.buttons[0].kwargs["command"]()
    assert control.custom_button.text == "…"
    assert control.custom_button.style == "Segment.TButton"


def test_unbound_group_highlights_via_set_selected():
    control, _ = _build()
    control.set_selected(2.0)
    assert control.buttons[1].style == "SelectedSegment.TButton"
    control.set_selected(None)
    assert all(b.style == "Segment.TButton" for b in control.buttons)


def test_unparseable_variable_falls_back_to_default_value():
    control, _ = _build(variable=_Var("nonsense"), default_value=5.0)
    assert control.buttons[2].style == "SelectedSegment.TButton"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_gui_segmented.py -v -k "not resolve and not parse and not format"`
Expected: FAIL — `ImportError: cannot import name 'SegmentedChoice'`

- [ ] **Step 3: Implement the widget**

First extend the imports at the top of `talks_reducer/gui/segmented.py` — Task 1 deliberately imported only what its pure helpers used, so the names the widget needs are not there yet:

```python
from typing import Any, Callable, Optional, Sequence, Union

from .tooltips import add_tooltip
```

Then append to `talks_reducer/gui/segmented.py`:

```python
SEGMENT_STYLE = "Segment.TButton"
SELECTED_SEGMENT_STYLE = "SelectedSegment.TButton"
CUSTOM_PLACEHOLDER = "…"


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
        for index, option in enumerate(self._options):
            button = ttk.Button(
                self.frame,
                text=option.label,
                style=SEGMENT_STYLE,
                command=lambda i=index: self._on_option_click(i),
            )
            button.pack(side=tk.LEFT)
            self.buttons.append(button)

        self.custom_button = None
        self.custom_entry = None
        self.custom_var = None
        if custom is not None:
            self.custom_var = tk.StringVar(value="")
            self.custom_button = ttk.Button(
                self.frame,
                text=CUSTOM_PLACEHOLDER,
                style=SEGMENT_STYLE,
                command=self._begin_custom_edit,
            )
            self.custom_button.pack(side=tk.LEFT)
            self.custom_entry = ttk.Entry(
                self.frame, textvariable=self.custom_var, width=6
            )
            self.custom_entry.bind("<Return>", self._commit_custom_edit)
            self.custom_entry.bind("<Escape>", self._cancel_custom_edit)
            self.custom_entry.bind("<FocusOut>", self._cancel_custom_edit)

        for option, button in zip(self._options, self.buttons):
            if option.tooltip:
                add_tooltip(button, option.tooltip, tk_module=tk)
        if tooltip:
            add_tooltip(self.frame, tooltip, tk_module=tk)

        if variable is not None:
            variable.trace_add("write", self._on_variable_write)
            self._sync_from_variable()

    def get_value(self) -> Optional[Value]:
        """Return the currently selected value, or ``None`` when unbound."""

        if self._variable is None:
            return None
        return self._variable.get()

    def set_value(self, value: Value) -> None:
        """Write *value* into the bound variable and restyle the buttons.

        Registered into ``gui._slider_updaters`` so ``apply_preset_to_gui`` keeps
        applying stored presets exactly as it did with the sliders it replaces.
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
        """Return *value* as a float when the options are numeric."""

        if self._options and isinstance(self._options[0].value, str):
            return str(value)
        try:
            return float(value)
        except (TypeError, ValueError):
            if self._default_value is not None:
                return self._default_value
            return value

    def _on_variable_write(self, *_args: Any) -> None:
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
                text=CUSTOM_PLACEHOLDER, style=SEGMENT_STYLE
            )
        else:
            self.custom_button.configure(
                text=format_custom_label(self._custom_value, self._custom),
                style=SELECTED_SEGMENT_STYLE,
            )

    def _on_option_click(self, index: int) -> None:
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_gui_segmented.py -v`
Expected: PASS — all Task 1 and Task 2 tests.

- [ ] **Step 5: Format and commit**

```bash
black talks_reducer/gui/segmented.py tests/test_gui_segmented.py
isort talks_reducer/gui/segmented.py tests/test_gui_segmented.py
git add talks_reducer/gui/segmented.py tests/test_gui_segmented.py
git commit -m "refactor: Add SegmentedChoice widget with custom-value slot"
```

---

### Task 3: Theme styles for segment buttons

**Files:**
- Modify: `talks_reducer/gui/theme.py` (insert after the `SelectedLink.TButton` block that ends around line 270)
- Test: `tests/test_gui_theme.py`

**Interfaces:**
- Consumes: `SEGMENT_STYLE` / `SELECTED_SEGMENT_STYLE` names from Task 2.
- Produces: ttk styles `Segment.TButton` and `SelectedSegment.TButton`.

- [ ] **Step 1: Write the failing test**

`tests/test_gui_theme.py` passes a plain `Mock()` as the style object (see `test_apply_theme_updates_widgets`), so the assertions read the recorded calls. Add:

```python
def _configured_styles(style: Mock) -> dict[str, dict]:
    """Map style name to kwargs for every ``style.configure(name, **kwargs)`` call."""

    return {
        call.args[0]: call.kwargs
        for call in style.configure.call_args_list
        if call.args
    }


def test_segment_styles_are_configured():
    style = Mock()
    apply_theme(
        style,
        LIGHT_THEME,
        {
            "root": Mock(),
            "drop_zone": Mock(),
            "log_text": Mock(),
            "activity_text": Mock(),
            "status_label": Mock(),
            "sliders": [Mock()],
            "tk": SimpleNamespace(FLAT="flat"),
            "apply_status_style": Mock(),
            "status_state": "idle",
        },
    )

    configured = _configured_styles(style)
    assert "Segment.TButton" in configured
    assert "SelectedSegment.TButton" in configured
    assert (
        configured["SelectedSegment.TButton"]["background"]
        != configured["Segment.TButton"]["background"]
    )
```

`Heading.TLabel` arrives in Task 6, which adds its own assertion to this same test. Do not reference it here.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_gui_theme.py -k segment -v`
Expected: FAIL — `Segment.TButton` missing from the configured styles.

- [ ] **Step 3: Add the styles**

In `talks_reducer/gui/theme.py`, directly after the `style.map("SelectedLink.TButton", ...)` call, insert:

```python
    style.configure(
        "Segment.TButton",
        background=palette["surface"],
        foreground=palette["foreground"],
        borderwidth=1,
        relief="solid",
        padding=(9, 2),
        font=("TkDefaultFont", 8),
    )
    style.map(
        "Segment.TButton",
        background=[
            ("active", palette.get("hover", palette["surface"])),
            ("disabled", palette["surface"]),
        ],
        foreground=[
            ("active", palette.get("hover_text", palette["foreground"])),
            ("disabled", palette["foreground"]),
        ],
    )
    style.configure(
        "SelectedSegment.TButton",
        background=selected_background,
        foreground=selected_foreground,
        borderwidth=1,
        relief="solid",
        padding=(9, 2),
        font=("TkDefaultFont", 8),
    )
    style.map(
        "SelectedSegment.TButton",
        background=[
            ("active", selected_background),
            ("disabled", selected_background),
        ],
        foreground=[
            ("active", selected_foreground),
            ("disabled", selected_foreground),
        ],
    )
```

`selected_background` and `selected_foreground` are already defined just above for `SelectedLink.TButton` — reuse them, do not recompute.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_gui_theme.py -v`
Expected: PASS

- [ ] **Step 5: Format and commit**

```bash
black talks_reducer/gui/theme.py tests/test_gui_theme.py
isort talks_reducer/gui/theme.py tests/test_gui_theme.py
git add talks_reducer/gui/theme.py tests/test_gui_theme.py
git commit -m "refactor: Add ttk styles for segmented choice buttons"
```

---

### Task 4: `add_segmented()` replaces `add_slider()` for the three numeric knobs

**Files:**
- Modify: `talks_reducer/gui/layout.py` — delete `add_slider` (lines 1258-1311), add `add_segmented`, rewrite the three `add_slider(...)` call sites (lines 736-786)
- Test: `tests/test_gui_layout.py`

**Interfaces:**
- Consumes: `SegmentedChoice`, `Option`, `CustomSpec` from Tasks 1-2.
- Produces: `add_segmented(gui, parent, label, variable, *, row, setting_key, options, default_value, custom=None, tooltip=None, pady=4) -> SegmentedChoice`. Registers `gui._slider_updaters[setting_key] = control.set_value`, `gui._basic_defaults[setting_key] = default_value`, `gui._basic_variables[setting_key] = variable`, and stores the control on `gui._segmented_controls[setting_key]`.

**Why the registration matters:** `apply_preset_to_gui` (layout.py:109) calls `updaters.get(key)` and invokes it with `str(value)`. If `_slider_updaters` loses these three keys, every stored preset silently stops applying speeds and thresholds.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_gui_layout.py`:

```python
def test_build_layout_registers_segmented_updaters():
    gui = _make_layout_gui()
    layout.build_layout(gui)
    for key in ("silent_speed", "sounded_speed", "silent_threshold"):
        assert key in gui._slider_updaters
        assert key in gui._basic_variables
    assert gui._basic_defaults["silent_speed"] == 5.0
    assert gui._basic_defaults["sounded_speed"] == 1.0
    assert gui._basic_defaults["silent_threshold"] == 0.01


def test_build_layout_no_longer_creates_sliders_for_basic_options():
    gui = _make_layout_gui()
    layout.build_layout(gui)
    # Keyframe interval (removed in Task 8) plus the two Cut video sliders.
    assert len(gui._sliders) == 3


def test_apply_preset_to_gui_still_lands_values_through_segmented_updaters():
    gui = _make_layout_gui()
    layout.build_layout(gui)
    layout.apply_preset_to_gui(gui, _TEST_PRESETS[0])
    assert gui.silent_speed_var.get() == pytest.approx(10.0)
    assert gui.sounded_speed_var.get() == pytest.approx(1.0)
    assert gui.silent_threshold_var.get() == pytest.approx(0.01)
```

Note: `_make_layout_gui` currently seeds `_sliders`, `_slider_updaters`, `_basic_defaults`, `_basic_variables`. Read the tail of `_make_layout_gui` and confirm; if `_segmented_controls` is needed as a seeded dict, add it there.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_gui_layout.py -k "segmented or sliders" -v`
Expected: FAIL — before this task `_sliders` holds 6 entries (3 basic + keyframe + 2 cut), so the `== 3` assertion fails. After this task it holds 3; Task 8 removes the keyframe slider and tightens the assertion to 2.

- [ ] **Step 3: Add `add_segmented` and delete `add_slider`**

In `talks_reducer/gui/layout.py`, add the import at the top:

```python
from .segmented import CustomSpec, Option, SegmentedChoice
```

Replace the whole `add_slider` function with:

```python
def add_segmented(
    gui: "TalksReducerGUI",
    parent: "tk.Misc",
    label: str,
    variable: "tk.DoubleVar",
    *,
    row: int,
    setting_key: str,
    options: list,
    default_value: float,
    custom: "CustomSpec | None" = None,
    tooltip: str | None = None,
    pady: int | tuple[int, int] = 4,
) -> "SegmentedChoice":
    """Add a labeled row of choice buttons to *parent* and wire it into presets.

    The control is registered under *setting_key* in ``_slider_updaters``,
    ``_basic_defaults`` and ``_basic_variables`` so preset application, the
    reset-state bookkeeping and the reverse preset match keep working exactly as
    they did with the slider this replaces.
    """

    gui.ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=pady)

    def persist(value: float) -> None:
        gui.preferences.update(setting_key, float(f"{float(value):.6f}"))
        update_basic_reset_state(gui)

    control = SegmentedChoice(
        parent,
        options,
        tk=gui.tk,
        ttk=gui.ttk,
        variable=variable,
        default_value=default_value,
        custom=custom,
        tooltip=tooltip,
        on_change=persist,
    )
    control.frame.grid(row=row, column=1, columnspan=2, sticky="w", pady=pady)

    def apply_and_persist(value) -> None:
        """Set the control and persist, for callers that drive it programmatically.

        ``reset_basic_defaults`` and ``apply_preset_to_gui`` reach the knobs only
        through ``_slider_updaters`` and rely on that call to write the new value
        to ``settings.json`` — the slider's own ``update()`` used to do both.
        ``SegmentedChoice.set_value`` deliberately does not fire ``on_change``, so
        the persistence half is restored here rather than in the widget.
        """

        control.set_value(value)
        persist(value)

    gui._slider_updaters[setting_key] = apply_and_persist
    gui._basic_defaults[setting_key] = default_value
    gui._basic_variables[setting_key] = variable
    gui._segmented_controls[setting_key] = control
    variable.trace_add("write", lambda *_: update_basic_reset_state(gui))
    return control
```

Then replace the three call sites (currently `add_slider(...)` at layout.py:739, 756, 770):

```python
    gui.silent_speed_var = gui.tk.DoubleVar(
        value=min(max(gui.preferences.get_float("silent_speed", 5.0), 1.0), 10.0)
    )
    add_segmented(
        gui,
        gui.basic_options_frame,
        "Silent",
        gui.silent_speed_var,
        row=1,
        setting_key="silent_speed",
        options=[
            Option(1.0, "1"),
            Option(2.0, "2"),
            Option(5.0, "5"),
            Option(10.0, "10"),
        ],
        default_value=5.0,
        custom=CustomSpec(minimum=1.0, maximum=10.0),
    )

    gui.sounded_speed_var = gui.tk.DoubleVar(
        value=min(max(gui.preferences.get_float("sounded_speed", 1.0), 0.75), 2.0)
    )
    add_segmented(
        gui,
        gui.basic_options_frame,
        "Sounded",
        gui.sounded_speed_var,
        row=2,
        setting_key="sounded_speed",
        options=[
            Option(1.0, "1"),
            Option(1.3, "1.3"),
            Option(1.5, "1.5"),
            Option(2.0, "2"),
        ],
        default_value=1.0,
        custom=CustomSpec(minimum=0.75, maximum=2.0),
    )

    gui.silent_threshold_var = gui.tk.DoubleVar(
        value=min(max(gui.preferences.get_float("silent_threshold", 0.01), 0.0), 1.0)
    )
    add_segmented(
        gui,
        gui.basic_options_frame,
        "Threshold",
        gui.silent_threshold_var,
        row=3,
        setting_key="silent_threshold",
        options=[
            Option(0.01, "0.01"),
            Option(0.03, "0.03"),
            Option(0.05, "0.05"),
            Option(0.10, "0.10"),
        ],
        default_value=0.01,
        custom=CustomSpec(minimum=0.0, maximum=1.0, display_format="{:.2f}"),
    )
```

**Use Task 6's final row numbers now**, leaving rows 0, 4 and 6 empty for the headings that task inserts — an empty `grid` row collapses to zero height, so the panel looks right in the meantime and Task 6 only has to add headings rather than renumber everything. That means every row below the three knobs must move down too, in the same commit:

| Row | Content | Was |
| --- | --- | --- |
| 1 / 2 / 3 | Silent / Sounded / Threshold | 0 / 1 / 2 |
| 5 | Video codec label + `codec_choice` | 3 |
| 7 | Processing mode label + `mode_choice` + `local_server_url_label` | 4 |
| 8 | Server URL label + entry + Discover | 5 |
| 9 | Theme label + `theme_choice` | 6 |

Leaving the codec row at 3 while Threshold moves to 3 puts two controls in the same grid cell and visibly breaks the panel.

Also add `gui._segmented_controls = {}` next to wherever `gui._slider_updaters = {}` is initialized in `app.py`.

- [ ] **Step 4: Run the full test suite**

Run: `python -m pytest tests/ -v`
Expected: PASS. If `test_gui_app.py` references `layout.add_slider`, update those references — `add_slider` no longer exists.

- [ ] **Step 5: Format and commit**

```bash
black talks_reducer/gui/layout.py talks_reducer/gui/app.py tests/test_gui_layout.py
isort talks_reducer/gui/layout.py talks_reducer/gui/app.py tests/test_gui_layout.py
git add talks_reducer/gui/layout.py talks_reducer/gui/app.py tests/test_gui_layout.py
git commit -m "feat: Replace Basic options sliders with choice buttons"
```

---

### Task 5: Migrate codec, mode, theme and the Basic options macro row

**Files:**
- Modify: `talks_reducer/gui/layout.py` — codec block (lines 788-814), mode block (816-835), theme block (866-878), macro buttons (700-726), `update_basic_reset_state` (1314-1337), `update_basic_preset_highlight` (1340-1376)
- Test: `tests/test_gui_layout.py`

**Interfaces:**
- Consumes: `add_segmented`, `SegmentedChoice`, `Option` from Task 4.
- Produces: `gui.video_codec_control`, `gui.processing_mode_control`, `gui.theme_control`, `gui.basic_preset_control` — all `SegmentedChoice`. The macro group is built with `variable=None` and highlighted through `set_selected`.

**Behavior change (agreed in the spec):** `update_basic_reset_state` stops calling `reset_basic_button.configure(state=...)`. A button that shows "selected" must not simultaneously be disabled. Remove the `state` handling and keep only the highlight call.

- [ ] **Step 1: Write the failing tests**

```python
def test_basic_macro_group_is_highlighted_by_matching_values():
    gui = _make_layout_gui()
    layout.build_layout(gui)
    gui.silent_speed_var.set(10.0)
    gui.sounded_speed_var.set(1.0)
    gui.silent_threshold_var.set(0.01)
    layout.update_basic_preset_highlight(gui)
    assert gui._active_basic_preset == "silence_x10"


def test_update_basic_reset_state_no_longer_disables_the_default_macro():
    gui = _make_layout_gui()
    layout.build_layout(gui)
    gui.silent_speed_var.set(5.0)
    gui.sounded_speed_var.set(1.0)
    gui.silent_threshold_var.set(0.01)
    layout.update_basic_reset_state(gui)
    states = [
        kwargs.get("state")
        for _args, kwargs in gui.reset_basic_button.configure_calls
        if "state" in kwargs
    ]
    assert states == []


def test_clicking_a_theme_button_applies_the_theme():
    gui = _make_layout_gui()
    layout.build_layout(gui)
    gui._refresh_theme.reset_mock()
    gui.theme_control.buttons[2].kwargs["command"]()  # "Dark"
    assert gui.theme_var.get() == "dark"
    gui._refresh_theme.assert_called_once()


def test_clicking_a_codec_button_writes_the_codec_var():
    gui = _make_layout_gui()
    layout.build_layout(gui)
    gui.video_codec_control.buttons[0].kwargs["command"]()  # "h.264"
    assert gui.video_codec_var.get() == "h264"


def test_remote_mode_button_is_still_exposed_for_state_updates():
    gui = _make_layout_gui()
    layout.build_layout(gui)
    assert gui.remote_mode_button is gui.processing_mode_control.buttons[1]
```

`WidgetStub` records constructor kwargs in `.kwargs`, so `buttons[i].kwargs["command"]` is the click handler. Confirm this when writing the test; if `SegmentedChoice` ends up passing `command` positionally, adjust the accessor rather than the widget.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_gui_layout.py -k "macro or reset_state or theme_group" -v`
Expected: FAIL — `gui.theme_control` does not exist; `states` is non-empty.

- [ ] **Step 3: Replace the radio rows and macro links**

Codec (replaces the `ttk.Radiobutton` loop and keeps `add_codec_suffix_check` to the right):

```python
    gui.ttk.Label(gui.basic_options_frame, text="Codec").grid(
        row=5, column=0, sticky="w", pady=(8, 0)
    )
    codec_choice = gui.ttk.Frame(gui.basic_options_frame)
    codec_choice.grid(row=5, column=1, columnspan=2, sticky="w", pady=(8, 0))
    gui.video_codec_control = SegmentedChoice(
        codec_choice,
        [
            Option("h264", "h.264", tooltip="Faster"),
            Option("hevc", "h.265", tooltip="25% smaller"),
            Option("av1", "av1", tooltip="No advantages"),
            Option("mp3", "mp3", tooltip="Audio only"),
        ],
        tk=gui.tk,
        ttk=gui.ttk,
        variable=gui.video_codec_var,
        default_value="h264",
    )
    gui.video_codec_control.frame.pack(side=gui.tk.LEFT)
    gui.add_codec_suffix_check = gui.ttk.Checkbutton(
        codec_choice,
        text="Add codec suffix",
        variable=gui.add_codec_suffix_var,
    )
    gui.add_codec_suffix_check.pack(side=gui.tk.LEFT, padx=(12, 0))
```

Per-button tooltips need no extra wiring here — `SegmentedChoice.__init__` (Task 2) already attaches `Option.tooltip` to each button.

Processing mode:

```python
    gui.ttk.Label(gui.basic_options_frame, text="Mode").grid(
        row=7, column=0, sticky="w", pady=(8, 0)
    )
    mode_choice = gui.ttk.Frame(gui.basic_options_frame)
    mode_choice.grid(row=7, column=1, sticky="w", pady=(8, 0))
    gui.processing_mode_control = SegmentedChoice(
        mode_choice,
        [Option("local", "Local"), Option("remote", "Remote")],
        tk=gui.tk,
        ttk=gui.ttk,
        variable=gui.processing_mode_var,
        default_value="local",
        on_change=lambda _value: gui._update_processing_mode_state(),
    )
    gui.processing_mode_control.frame.pack(side=gui.tk.LEFT)
    gui.remote_mode_button = gui.processing_mode_control.buttons[1]
```

`gui.remote_mode_button` must keep existing: `_update_processing_mode_state` (app.py:668) calls `.configure(state=...)` on it.

Theme:

```python
    gui.ttk.Label(gui.basic_options_frame, text="Theme").grid(
        row=9, column=0, sticky="w", pady=(8, 0)
    )
    theme_choice = gui.ttk.Frame(gui.basic_options_frame)
    theme_choice.grid(row=9, column=1, columnspan=2, sticky="w", pady=(8, 0))
    gui.theme_control = SegmentedChoice(
        theme_choice,
        [Option("os", "OS"), Option("light", "Light"), Option("dark", "Dark")],
        tk=gui.tk,
        ttk=gui.ttk,
        variable=gui.theme_var,
        default_value="os",
        on_change=lambda _value: gui._refresh_theme(),
    )
    gui.theme_control.frame.pack(side=gui.tk.LEFT)
```

Basic options macro row (replaces the three `Link.TButton` widgets):

```python
    gui.basic_preset_control = SegmentedChoice(
        gui.basic_presets_frame,
        [
            Option("compress_only", "No speedup"),
            Option("defaults", "Silence ×5"),
            Option("silence_x10", "Silence ×10"),
        ],
        tk=gui.tk,
        ttk=gui.ttk,
        variable=None,
        on_change=lambda value: gui._apply_basic_preset(value),
    )
    gui.basic_preset_control.frame.pack(side=gui.tk.LEFT)
    gui.reset_basic_button = gui.basic_preset_control.buttons[1]
    gui.basic_preset_buttons = {
        "compress_only": gui.basic_preset_control.buttons[0],
        "defaults": gui.basic_preset_control.buttons[1],
        "silence_x10": gui.basic_preset_control.buttons[2],
    }
```

Then in `update_basic_preset_highlight`, replace the per-button `configure(style=...)` loop with a single call:

```python
    gui._active_basic_preset = active
    control = getattr(gui, "basic_preset_control", None)
    if control is not None:
        control.set_selected(active)
```

and in `update_basic_reset_state`, delete these two lines:

```python
    state = gui.tk.NORMAL if should_enable else gui.tk.DISABLED
    gui.reset_basic_button.configure(state=state)
```

keeping the `should_enable` computation only if something else uses it — if nothing does, delete that loop too and have the function call `update_basic_preset_highlight(gui)` and `refresh_advanced_preset_selection(gui)` directly.

- [ ] **Step 4: Run the full test suite**

Run: `python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 5: Format and commit**

```bash
black talks_reducer/gui/layout.py talks_reducer/gui/segmented.py tests/test_gui_layout.py
isort talks_reducer/gui/layout.py talks_reducer/gui/segmented.py tests/test_gui_layout.py
git add talks_reducer/gui/layout.py talks_reducer/gui/segmented.py tests/test_gui_layout.py
git commit -m "feat: Move codec, mode, theme and basic presets onto choice buttons"
```

---

### Task 6: Group headings and the threshold guidance link

**Files:**
- Modify: `talks_reducer/gui/layout.py`
- Test: `tests/test_gui_layout.py`

**Interfaces:**
- Consumes: everything from Tasks 4-5.
- Produces: module constants `THRESHOLD_TOOLTIP: str` and `THRESHOLD_ARTICLE_URL: str`; `gui.threshold_help_button`.

- [ ] **Step 1: Write the failing tests**

```python
def test_threshold_tooltip_lists_every_documented_value():
    for value in ("0.01", "0.03", "0.05", "0.10"):
        assert value in layout.THRESHOLD_TOOLTIP


def test_threshold_help_button_opens_the_article(monkeypatch):
    opened = []
    monkeypatch.setattr(layout.webbrowser, "open", lambda url: opened.append(url))
    gui = _make_layout_gui()
    layout.build_layout(gui)
    gui.threshold_help_button.kwargs["command"]()
    assert opened == [layout.THRESHOLD_ARTICLE_URL]


def test_threshold_article_url_points_at_the_telegraph_post():
    assert layout.THRESHOLD_ARTICLE_URL == (
        "https://telegra.ph/"
        "How-hard-can-you-trim-silence-before-speech-to-text-breaks-08-03"
    )
```

`_make_layout_gui` builds buttons via `WidgetFactory`, whose stubs expose `.kwargs` — confirm `ttk.Button` stubs record `command` in `kwargs` and adjust the accessor if they do not.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_gui_layout.py -k threshold -v`
Expected: FAIL — `module 'talks_reducer.gui.layout' has no attribute 'THRESHOLD_TOOLTIP'`

- [ ] **Step 3: Add the constants, headings and help link**

At the top of `layout.py` add `import webbrowser` and, next to `BASIC_PRESETS`:

```python
THRESHOLD_ARTICLE_URL = (
    "https://telegra.ph/"
    "How-hard-can-you-trim-silence-before-speech-to-text-breaks-08-03"
)

THRESHOLD_TOOLTIP = (
    "0.01 — never cuts speech; only mutes silence on a good microphone\n"
    "0.03 — fits most cases and phone video, but may cut quiet speech\n"
    "0.05 — cuts aggressively\n"
    "0.10 — the last sane limit for painless silence removal"
)
```

Add a small helper for the group headings:

```python
def add_group_heading(gui: "TalksReducerGUI", parent: "tk.Misc", text: str, *, row: int):
    """Add a quiet section heading above a run of related settings rows."""

    heading = gui.ttk.Label(parent, text=text.upper(), style="Heading.TLabel")
    heading.grid(row=row, column=0, columnspan=3, sticky="w", pady=(10, 2))
    return heading
```

and add `assert "Heading.TLabel" in configured` to `test_segment_styles_are_configured` in `tests/test_gui_theme.py`, then register `Heading.TLabel` in `theme.py` next to the segment styles:

```python
    style.configure(
        "Heading.TLabel",
        background=palette["background"],
        foreground=palette["foreground"],
        font=("TkDefaultFont", 7),
    )
```

Then lay out `basic_options_frame` in this final row order:

| Row | Content |
| --- | --- |
| 0 | heading `SPEED & SILENCE` |
| 1 | Silent |
| 2 | Sounded |
| 3 | Threshold + `?` |
| 4 | heading `OUTPUT` |
| 5 | Codec + Add codec suffix |
| 6 | heading `PROCESSING & APPEARANCE` |
| 7 | Mode + status label |
| 8 | Server URL + Discover |
| 9 | Theme |

Attach the tooltip and the help link to the threshold row by passing `tooltip=THRESHOLD_TOOLTIP` to its `add_segmented` call and adding, right after it:

```python
    gui.threshold_help_button = gui.ttk.Button(
        gui.basic_options_frame,
        text="?",
        style="Link.TButton",
        command=lambda: webbrowser.open(THRESHOLD_ARTICLE_URL),
    )
    gui.threshold_help_button.grid(row=3, column=2, sticky="w", padx=(8, 0))
```

- [ ] **Step 4: Run the full test suite**

Run: `python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 5: Format and commit**

```bash
black talks_reducer/gui/layout.py talks_reducer/gui/theme.py tests/test_gui_layout.py
isort talks_reducer/gui/layout.py talks_reducer/gui/theme.py tests/test_gui_layout.py
git add talks_reducer/gui/layout.py talks_reducer/gui/theme.py tests/test_gui_layout.py
git commit -m "feat: Group Advanced settings and link the threshold guide"
```

---

### Task 7: Remote status label and conditional Server URL row

**Files:**
- Modify: `talks_reducer/gui/layout.py`, `talks_reducer/gui/app.py`, `talks_reducer/gui/remote.py`
- Test: `tests/test_gui_remote.py`, `tests/test_gui_layout.py`

**Interfaces:**
- Consumes: `gui.processing_mode_control` from Task 5.
- Produces: `gui.remote_status_var` (`StringVar`), `gui.remote_status_label`, `gui.server_url_row` (a `Frame` holding the entry and Discover button), and `TalksReducerGUI._set_remote_status(message: str) -> None`. `check_remote_server_for_gui` gains an `on_remote_status` path that mirrors each status message into that var.

`check_remote_server` already formats `f"Server {host_label} is ready"` and `f"Server {host_label} is unreachable"` (remote.py:106, 111) — reuse those strings, do not build new ones.

- [ ] **Step 1: Write the failing tests**

`tests/test_gui_remote.py` already defines `StubGUI`, whose `_schedule_on_ui_thread` invokes its callback immediately. It lacks `_ping_server` and `_set_remote_status`, so the test supplies both. Add `check_remote_server_for_gui` to that module's imports from `talks_reducer.gui.remote`, then:

```python
def test_check_remote_server_for_gui_mirrors_status_into_remote_status() -> None:
    gui = StubGUI()
    messages: list[str] = []
    gui._ping_server = lambda url, timeout=5.0: True
    gui._set_remote_status = messages.append

    success = check_remote_server_for_gui(
        gui,
        "http://192.168.1.5:9005",
        success_status="Idle",
        waiting_status="Error",
        failure_status="Error",
        max_attempts=1,
    )

    assert success is True
    assert messages
    assert messages[-1].endswith("is ready")


def test_check_remote_server_for_gui_mirrors_failure_into_remote_status() -> None:
    gui = StubGUI()
    messages: list[str] = []
    gui._ping_server = lambda url, timeout=5.0: False
    gui._set_remote_status = messages.append

    success = check_remote_server_for_gui(
        gui,
        "http://192.168.1.5:9005",
        success_status="Idle",
        waiting_status="Error",
        failure_status="Error",
        max_attempts=1,
    )

    assert success is False
    assert messages[-1].endswith("is unreachable")
```

The exact host label comes from `format_server_host`, so assert on the suffix rather than hardcoding the full string.

```python
def test_server_url_row_is_hidden_in_local_mode():
    gui = _make_layout_gui()
    layout.build_layout(gui)
    layout.update_processing_mode_visibility(gui)
    assert gui.server_url_row.grid_remove_calls


def test_server_url_row_is_shown_in_remote_mode():
    gui = _make_layout_gui(processing_mode_var=StringVarStub(value="remote"))
    layout.build_layout(gui)
    layout.update_processing_mode_visibility(gui)
    assert gui.server_url_row.grid_calls
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_gui_remote.py tests/test_gui_layout.py -k "remote_status or server_url_row" -v`
Expected: FAIL — `gui.server_url_row` does not exist.

- [ ] **Step 3: Implement**

In `layout.py`, wrap the Server URL entry and Discover button in one frame so they hide together:

```python
    gui.server_url_row = gui.ttk.Frame(gui.basic_options_frame)
    gui.server_url_row.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(8, 0))
    gui.ttk.Label(gui.server_url_row, text="Server URL").pack(side=gui.tk.LEFT)
    gui.server_entry = gui.ttk.Entry(
        gui.server_url_row, textvariable=gui.server_url_var, width=40
    )
    gui.server_entry.pack(side=gui.tk.LEFT, padx=(8, 0))
    gui.server_discover_button = gui.ttk.Button(
        gui.server_url_row, text="Discover", command=gui._start_discovery
    )
    gui.server_discover_button.pack(side=gui.tk.LEFT, padx=(8, 0))
```

Add the status label next to the mode buttons:

```python
    gui.remote_status_label = gui.ttk.Label(
        mode_choice, textvariable=gui.remote_status_var
    )
    gui.remote_status_label.pack(side=gui.tk.LEFT, padx=(12, 0))
```

Add the visibility helper:

```python
def update_processing_mode_visibility(gui: "TalksReducerGUI") -> None:
    """Show the Server URL row and connection status only in remote mode.

    Local processing has no server to address, so both the address field and the
    readiness text are removed from the grid rather than left blank.
    """

    remote = gui.processing_mode_var.get() == "remote"
    row = getattr(gui, "server_url_row", None)
    if row is not None:
        row.grid() if remote else row.grid_remove()
    label = getattr(gui, "remote_status_label", None)
    if label is not None:
        label.grid() if remote else label.grid_remove()
    if not remote and hasattr(gui, "remote_status_var"):
        gui.remote_status_var.set("")
```

Call it at the end of `build_layout` (next to the existing `gui._update_processing_mode_state()`) and from `TalksReducerGUI._update_processing_mode_state`.

In `app.py`, create the variable wherever the other `StringVar`s are created:

```python
        self.remote_status_var = self.tk.StringVar(value="")
```

and add:

```python
    def _set_remote_status(self, message: str) -> None:
        """Show *message* beside the processing-mode buttons."""

        if hasattr(self, "remote_status_var"):
            self.remote_status_var.set(message)
```

In `remote.py`, extend `status_callback` inside `check_remote_server_for_gui`:

```python
    def status_callback(status: str, message: str) -> None:
        gui._schedule_on_ui_thread(lambda s=status, m=message: gui._set_status(s, m))
        gui._schedule_on_ui_thread(lambda m=message: gui._set_remote_status(m))
```

`_schedule_on_ui_thread` is required here because these callbacks run on the ping worker thread, not the Tk main thread.

- [ ] **Step 4: Run the full test suite**

Run: `python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 5: Format and commit**

```bash
black talks_reducer/gui/layout.py talks_reducer/gui/app.py talks_reducer/gui/remote.py tests/
isort talks_reducer/gui/layout.py talks_reducer/gui/app.py talks_reducer/gui/remote.py tests/
git add talks_reducer/gui/layout.py talks_reducer/gui/app.py talks_reducer/gui/remote.py tests/
git commit -m "feat: Show server readiness and hide the URL row in local mode"
```

---

### Task 8: Keyframe interval on buttons

**Files:**
- Modify: `talks_reducer/gui/layout.py` — lift `estimate_keyframe_overhead` and `format_percent` out of `build_layout` (currently nested at lines 1035-1063) to module scope, replace the slider (1018-1095)
- Test: `tests/test_gui_layout.py`

**Interfaces:**
- Consumes: `add_segmented` from Task 4.
- Produces: module-level `estimate_keyframe_overhead(interval_seconds: float) -> float`, `format_percent(delta_percent: float) -> str`, `KEYFRAME_INTERVAL_SAMPLES`, and `gui.keyframe_interval_control` / `gui.keyframe_interval_value_label`.

The estimate stays a visible label (`+1.4%`) beside the buttons — the spec is explicit that it must not move into tooltips.

- [ ] **Step 1: Write the failing tests**

```python
def test_estimate_keyframe_overhead_matches_known_samples():
    assert layout.estimate_keyframe_overhead(60.0) == pytest.approx(0.5)
    assert layout.estimate_keyframe_overhead(30.0) == pytest.approx(1.4)
    assert layout.estimate_keyframe_overhead(1.0) == pytest.approx(44.0)


def test_estimate_keyframe_overhead_clamps_out_of_range_input():
    assert layout.estimate_keyframe_overhead(999.0) == pytest.approx(0.5)
    assert layout.estimate_keyframe_overhead(0.0) == pytest.approx(44.0)


def test_estimate_keyframe_overhead_interpolates_between_samples():
    value = layout.estimate_keyframe_overhead(20.0)
    assert 1.4 < value < 4.7


def test_format_percent_switches_precision_at_ten():
    assert layout.format_percent(1.4) == "+1.4%"
    assert layout.format_percent(44.0) == "+44%"


def test_keyframe_interval_label_tracks_the_selected_value():
    gui = _make_layout_gui()
    layout.build_layout(gui)
    gui.keyframe_interval_control.set_value(60.0)
    texts = [
        kwargs.get("text")
        for _args, kwargs in gui.keyframe_interval_value_label.configure_calls
        if "text" in kwargs
    ]
    assert texts[-1] == "+0.5%"


def test_keyframe_interval_persists_the_selected_value():
    gui = _make_layout_gui()
    layout.build_layout(gui)
    gui.preferences.update.reset_mock()
    gui.keyframe_interval_control._on_option_click(0)  # 5 sec
    gui.preferences.update.assert_any_call("keyframe_interval_seconds", 5.0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_gui_layout.py -k keyframe -v`
Expected: FAIL — `module 'talks_reducer.gui.layout' has no attribute 'estimate_keyframe_overhead'`

- [ ] **Step 3: Lift the helpers and swap the control**

Move to module scope in `layout.py`, unchanged in behavior:

```python
KEYFRAME_INTERVAL_MIN = 1.0
KEYFRAME_INTERVAL_MAX = 60.0
KEYFRAME_INTERVAL_DEFAULT = 30.0
KEYFRAME_INTERVAL_SAMPLES = [
    (60.0, 0.5),
    (30.0, 1.4),
    (10.0, 4.7),
    (5.0, 9.6),
    (1.0, 44.0),
]


def estimate_keyframe_overhead(interval_seconds: float) -> float:
    """Estimate percent size increase vs. encoding with no extra keyframes.

    Values between the measured samples are interpolated in log space, which
    matches how the overhead actually scales with the interval.
    """

    bounded = max(
        KEYFRAME_INTERVAL_MIN, min(KEYFRAME_INTERVAL_MAX, interval_seconds)
    )
    samples = KEYFRAME_INTERVAL_SAMPLES
    if bounded >= samples[0][0]:
        return samples[0][1]
    if bounded <= samples[-1][0]:
        return samples[-1][1]

    for upper_idx in range(len(samples) - 1):
        upper_interval, upper_percent = samples[upper_idx]
        lower_interval, lower_percent = samples[upper_idx + 1]
        if lower_interval <= bounded <= upper_interval:
            ratio = (math.log(bounded) - math.log(upper_interval)) / (
                math.log(lower_interval) - math.log(upper_interval)
            )
            return math.exp(
                math.log(upper_percent)
                + ratio * (math.log(lower_percent) - math.log(upper_percent))
            )

    return samples[-1][1]


def format_percent(delta_percent: float) -> str:
    """Format an overhead estimate, dropping the decimal above ten percent."""

    if abs(delta_percent) >= 10.0:
        return f"{delta_percent:+.0f}%"
    return f"{delta_percent:+.1f}%"
```

Replace the slider block in `advanced_frame` with:

```python
    keyframe_setting = gui.preferences.get_float(
        "keyframe_interval_seconds", KEYFRAME_INTERVAL_DEFAULT
    )
    try:
        validated_interval = float(keyframe_setting)
    except (TypeError, ValueError):
        validated_interval = KEYFRAME_INTERVAL_DEFAULT
    validated_interval = max(
        KEYFRAME_INTERVAL_MIN, min(KEYFRAME_INTERVAL_MAX, validated_interval)
    )

    gui.keyframe_interval_var = gui.tk.DoubleVar(value=validated_interval)

    gui.ttk.Label(gui.advanced_frame, text="Keyframe interval").grid(
        row=7, column=0, sticky="w", pady=4
    )
    keyframe_row = gui.ttk.Frame(gui.advanced_frame)
    keyframe_row.grid(row=7, column=1, columnspan=2, sticky="w", pady=4)

    gui.keyframe_interval_value_label = gui.ttk.Label(keyframe_row)

    def update_keyframe_interval(value) -> None:
        """Persist the chosen interval and refresh the size-overhead label."""

        numeric = max(
            KEYFRAME_INTERVAL_MIN, min(KEYFRAME_INTERVAL_MAX, float(value))
        )
        gui.keyframe_interval_value_label.configure(
            text=format_percent(estimate_keyframe_overhead(numeric))
        )
        gui.preferences.update("keyframe_interval_seconds", float(f"{numeric:.6f}"))

    gui.keyframe_interval_control = SegmentedChoice(
        keyframe_row,
        [
            Option(5.0, "5 sec"),
            Option(10.0, "10 sec"),
            Option(30.0, "30 sec"),
            Option(60.0, "60 sec"),
        ],
        tk=gui.tk,
        ttk=gui.ttk,
        variable=gui.keyframe_interval_var,
        default_value=KEYFRAME_INTERVAL_DEFAULT,
        custom=CustomSpec(
            minimum=KEYFRAME_INTERVAL_MIN,
            maximum=KEYFRAME_INTERVAL_MAX,
            display_format="{:g} sec",
        ),
        on_change=update_keyframe_interval,
    )
    gui.keyframe_interval_control.frame.pack(side=gui.tk.LEFT)
    gui.keyframe_interval_value_label.pack(side=gui.tk.LEFT, padx=(12, 0))

    update_keyframe_interval(validated_interval)
```

`set_value` does not call `on_change` (only clicks and custom commits do), so `test_keyframe_interval_label_tracks_the_selected_value` requires the label to also update on a variable write. Add a trace next to the control:

```python
    gui.keyframe_interval_var.trace_add(
        "write", lambda *_: update_keyframe_interval(gui.keyframe_interval_var.get())
    )
```

Delete the now-unused `gui.keyframe_interval_slider` and its `gui._sliders.append(...)`. Confirm `_sliders` now holds exactly the two Cut video sliders and update the count asserted in Task 4's `test_build_layout_no_longer_creates_sliders_for_basic_options` to `2`.

- [ ] **Step 4: Run the full test suite**

Run: `python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 5: Format and commit**

```bash
black talks_reducer/gui/layout.py tests/test_gui_layout.py
isort talks_reducer/gui/layout.py tests/test_gui_layout.py
git add talks_reducer/gui/layout.py tests/test_gui_layout.py
git commit -m "feat: Move keyframe interval onto choice buttons"
```

---

### Task 9: Documentation and TODO cleanup

**Files:**
- Modify: `README.md`, `CLAUDE.md`, `AGENTS.md`, `docs/TODO.md`

**Interfaces:**
- Consumes: the finished behavior from Tasks 1-8.
- Produces: nothing code-facing.

- [ ] **Step 1: Update `docs/gui.md`**

This is the real GUI reference — `README.md` only links to it and mentions the GUI in passing, so it needs no change. Edit these lines:

- **Line 26** — "and the timing/audio sliders" is now wrong. Describe the button groups for silent speed, sounded speed and silent threshold, and note that any other value is typed through the `...` slot.
- **Line 29** — **Keyframe interval (s)** is no longer a slider. Document the 5 / 10 / 30 / 60 sec buttons, the `...` slot for 1–60, and the size-overhead percentage shown beside them.
- **Line 66-72 (Processing mode and Discover)** — record that the Server URL field and Discover button appear only in Remote mode, and that the connection status reads `Server <host> is ready` once the ping succeeds.
- Add a short paragraph covering the threshold guidance tooltip and the `?` link to the article.
- **Line 80-82 (Cut video)** — leave alone; those range sliders are unchanged.

- [ ] **Step 2: Update `CLAUDE.md` and `AGENTS.md`**

Both files describe the GUI in detail and both are now stale. Edit the **Graphical Interface** section in each:

- Replace any mention of the Basic options sliders with `SegmentedChoice` (`talks_reducer/gui/segmented.py`), noting that it registers into `_slider_updaters` so presets keep applying.
- Record that `Segment.TButton` / `SelectedSegment.TButton` / `Heading.TLabel` live in `theme.py`.
- Record the behavior change: the `Silence ×5` macro button is no longer disabled at defaults.
- Add `segmented.py` to the Repository Structure list in both files.
- In `CLAUDE.md`, note that `gui._sliders` now holds only the two Cut video sliders.

- [ ] **Step 3: Check off the TODO items**

In `docs/TODO.md`, mark the three implemented items `[x]`. Verify each against the code before ticking it — the control, its `defaultValue`/`customValue` support, every migrated setting, the compaction, and the article link.

- [ ] **Step 4: Run the full test suite one final time**

Run: `python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 5: Manual verification**

Launch the GUI and confirm by eye — automated tests use widget stubs and cannot catch a layout that renders wrong:

```bash
python -m talks_reducer.gui
```

- Advanced panel shows three group headings with one setting per line.
- Clicking each button in every group selects it and deselects its siblings.
- `...` opens an inline entry; Enter commits and re-labels the slot; Escape cancels.
- Typing `99` into the Silent speed `...` clamps to `10`.
- Hovering the Threshold group shows all four guidance lines; `?` opens the article in a browser.
- Hovering each codec button shows its own tooltip.
- Switching to Remote reveals the Server URL row and shows `Server <ip> is ready` after the ping; switching to Local hides both.
- Keyframe interval shows `+1.4%` at 30 sec and `+0.5%` at 60 sec.
- Selecting a preset in Simple mode, then reopening Advanced, moves the buttons to that preset's values.
- Toggle the theme to Dark and confirm the selected/unselected buttons stay readable.

- [ ] **Step 6: Commit**

```bash
git add docs/gui.md CLAUDE.md AGENTS.md docs/TODO.md
git commit -m "docs: Document the segmented settings controls"
```

---

## Notes for the implementer

- **The riskiest edit is Task 4's registration block.** If `_slider_updaters` loses `silent_speed`, `sounded_speed` or `silent_threshold`, presets stop applying with no error — `apply_preset_to_gui` just falls through to `variables.get(key)`. The test in Task 4 Step 1 guards this; do not delete it.
- **`gui.remote_mode_button` and `gui.reset_basic_button` must keep existing** after Task 5. `_update_processing_mode_state` (app.py:668) and `update_basic_reset_state` reference them by name; both are reassigned to buttons owned by a `SegmentedChoice`.
- **Row numbers in `basic_options_frame` shift twice** — once in Task 4 and again in Task 6 when headings are inserted. Task 6's table is the final authority.
- **`tests/test_gui_layout.py` stubs may need new factory entries** as widgets change. Extend `_make_layout_gui` rather than building a parallel harness.
