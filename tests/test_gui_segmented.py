from __future__ import annotations

import pytest

from talks_reducer.gui.segmented import (
    CUSTOM_SLOT_WIDTH,
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
    assert control.custom_button.style == "CustomSegment.TButton"


def test_unlisted_initial_value_lands_in_the_custom_slot():
    """A value matching no button shows as an editable entry, not a button.

    The slot stays an entry for as long as a custom value is in play, so the
    number can be adjusted in place.
    """

    control, _ = _build(variable=_Var(3.5), custom=SPEED_CUSTOM)
    assert control.custom_entry.packed is True
    assert control.custom_button.packed is False
    assert control.custom_var.get() == "3.5"


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
    # The entry survives the commit instead of collapsing back to a button.
    assert control.custom_entry.packed is True
    assert control.custom_button.packed is False
    assert control.custom_var.get() == "3.5"


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
    assert control.custom_entry.packed is True
    control.buttons[0].kwargs["command"]()
    assert control.custom_entry.packed is False
    assert control.custom_button.packed is True
    assert control.custom_button.text == "…"
    assert control.custom_button.style == "CustomSegment.TButton"


def test_unbound_group_highlights_via_set_selected():
    control, _ = _build()
    control.set_selected(2.0)
    assert control.buttons[1].style == "SelectedSegment.TButton"
    control.set_selected(None)
    assert all(b.style == "Segment.TButton" for b in control.buttons)


def test_unparseable_variable_falls_back_to_default_value():
    control, _ = _build(variable=_Var("nonsense"), default_value=5.0)
    assert control.buttons[2].style == "SelectedSegment.TButton"


def test_set_value_clamps_above_the_custom_maximum():
    """Regression: ``set_value`` used to skip clamping entirely.

    ``control.set_value(15.0)`` on a 1-10 control used to leave the bound
    variable holding the raw ``15.0`` while the display (correctly) clamped to
    ``10`` via ``parse_custom`` in ``_sync_from_variable`` — a persisted preset
    or hand-edited ``settings.json`` value outside the range would silently
    diverge from what the control showed. ``15`` clamped to ``10`` lands
    exactly on the "10" button (a real option), so the fix is visible as the
    variable now also reading ``10`` rather than the unclamped ``15``.
    """

    variable = _Var(5.0)
    control, _ = _build(variable=variable, custom=SPEED_CUSTOM)
    control.set_value(15.0)
    assert variable.get() == 10.0
    assert control.buttons[3].style == "SelectedSegment.TButton"


def test_set_value_clamps_below_the_custom_minimum():
    variable = _Var(5.0)
    control, _ = _build(variable=variable, custom=SPEED_CUSTOM)
    control.set_value(-5.0)
    assert variable.get() == 1.0
    assert control.buttons[0].style == "SelectedSegment.TButton"


def test_set_value_leaves_an_in_range_custom_value_unchanged():
    """An in-range, unlisted value must still reach the custom slot unchanged.

    Clamping in ``_coerce`` must not tighten the range or otherwise disturb a
    value that already fits inside ``minimum``/``maximum``.
    """

    variable = _Var(5.0)
    control, _ = _build(variable=variable, custom=SPEED_CUSTOM)
    control.set_value(3.5)
    assert variable.get() == 3.5
    assert control.custom_entry.packed is True
    assert control.custom_var.get() == "3.5"


def test_custom_slot_button_and_entry_share_a_width():
    """The inline entry must not resize the row when it replaces the button.

    Both are given ``CUSTOM_SLOT_WIDTH`` so swapping one for the other during an
    edit leaves the row's geometry untouched.
    """

    control, _ = _build(variable=_Var(5.0), custom=SPEED_CUSTOM)
    assert control.custom_button.kwargs["width"] == CUSTOM_SLOT_WIDTH
    assert control.custom_entry.kwargs["width"] == CUSTOM_SLOT_WIDTH


def test_focus_out_commits_the_typed_value_like_enter():
    """Leaving the field must not silently discard what was typed."""

    variable = _Var(5.0)
    control, _ = _build(variable=variable, custom=SPEED_CUSTOM)
    control.custom_button.kwargs["command"]()
    control.custom_var.set("3.5")

    control.custom_entry.bindings["<FocusOut>"](None)

    assert variable.get() == 3.5
    assert control.custom_entry.packed is True


def test_escape_still_discards_the_edit():
    variable = _Var(5.0)
    control, _ = _build(variable=variable, custom=SPEED_CUSTOM)
    control.custom_button.kwargs["command"]()
    control.custom_var.set("3.5")

    control.custom_entry.bindings["<Escape>"](None)

    assert variable.get() == 5.0
    assert control.custom_button.packed is True


def test_retyping_in_a_persistent_entry_commits_without_reopening():
    """A committed value keeps its entry, so edits skip ``_begin_custom_edit``.

    Guarding the commit on ``_editing`` would drop those keystrokes entirely.
    """

    variable = _Var(3.5)
    control, _ = _build(variable=variable, custom=SPEED_CUSTOM)
    assert control.custom_entry.packed is True  # no button click involved

    control.custom_var.set("7.25")
    control.custom_entry.bindings["<Return>"](None)

    assert variable.get() == 7.25
