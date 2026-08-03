"""Geometry checks that run against a real Tk, not the widget stubs.

The rest of the GUI suite drives hand-written widget stubs, which faithfully
record API calls but model no geometry at all: they accept ``grid`` on a packed
widget, ignore ``columnspan`` when deciding cell occupancy, and never raise the
``TclError`` that a bad ``pack(before=...)`` produces. Every layout defect found
by review on this feature lived in exactly that gap.

These tests are deliberately few and cheap. They skip themselves when no display
is available, so they add nothing on a headless runner.
"""

from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter")
ttk = pytest.importorskip("tkinter.ttk")

import talks_reducer.gui.layout as layout
from talks_reducer.gui.segmented import CustomSpec, Option, SegmentedChoice
from talks_reducer.gui.theme import LIGHT_THEME, apply_theme


@pytest.fixture(scope="module")
def root():
    """Yield one real Tk root for the module.

    Module-scoped on purpose: creating and destroying several ``tk.Tk()``
    instances in one process intermittently fails to re-locate ``tk.tcl``,
    which would surface as a random skip rather than a real result.
    """

    try:
        window = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - depends on the environment
        pytest.skip(f"no display available for Tk: {exc}")
    window.withdraw()
    try:
        yield window
    finally:
        window.destroy()


@pytest.fixture(scope="module")
def themed(root):
    """Apply the real stylesheet so style-driven metrics are the real ones."""

    style = ttk.Style()
    apply_theme(
        style,
        LIGHT_THEME,
        {
            "root": root,
            "drop_zone": tk.Label(root),
            "log_text": tk.Text(root),
            "activity_text": tk.Text(root),
            "status_label": tk.Label(root),
            "sliders": [],
            "tk": tk,
            "apply_status_style": lambda *_: None,
            "status_state": "idle",
        },
    )
    return style


def _make_mode_row(root):
    """Build the Mode row's packed children the way ``build_layout`` does."""

    mode_choice = ttk.Frame(root)
    gui = type("GuiStub", (), {})()
    gui.tk = tk
    gui.ttk = ttk
    gui.processing_mode_var = tk.StringVar(value="local")
    gui.server_url_var = tk.StringVar(value="http://192.168.1.5:9005")
    gui.remote_status_var = tk.StringVar(value="")
    gui.server_url_row = ttk.Frame(mode_choice)
    gui.server_url_row.pack(side=tk.LEFT, padx=(12, 0))
    gui.remote_status_label = ttk.Label(mode_choice, textvariable=gui.remote_status_var)
    gui.remote_status_label.pack(side=tk.LEFT, padx=(12, 0))
    return gui, mode_choice


def test_toggling_processing_mode_repeatedly_keeps_the_remote_group(root, themed):
    """Regression: Remote stopped showing its controls after two switches.

    ``pack(before=w)`` requires *w* to be packed. Local mode forgets the status
    label, so re-packing the address row before it raised ``TclError`` and left
    the whole remote group unmanaged — invisible to the stub suite, which
    records the call and moves on.
    """

    gui, mode_choice = _make_mode_row(root)

    for _ in range(3):
        gui.processing_mode_var.set("remote")
        layout.update_processing_mode_visibility(gui)
        slaves = [str(widget) for widget in mode_choice.pack_slaves()]
        assert str(gui.server_url_row) in slaves
        assert str(gui.remote_status_label) in slaves
        assert slaves.index(str(gui.server_url_row)) < slaves.index(
            str(gui.remote_status_label)
        )

        gui.processing_mode_var.set("local")
        layout.update_processing_mode_visibility(gui)
        assert str(gui.server_url_row) not in [
            str(widget) for widget in mode_choice.pack_slaves()
        ]


def test_custom_slot_button_and_entry_render_the_same_width(root, themed):
    """The swap must not resize the row, which needs real font metrics."""

    frame = ttk.Frame(root)
    control = SegmentedChoice(
        frame,
        [Option(1.0, "1"), Option(10.0, "10")],
        tk=tk,
        ttk=ttk,
        variable=tk.DoubleVar(value=1.0),
        custom=CustomSpec(minimum=1.0, maximum=10.0),
    )
    control.frame.pack()
    root.update_idletasks()

    assert (
        control.custom_entry.winfo_reqwidth() == control.custom_button.winfo_reqwidth()
    )


def test_a_committed_custom_value_keeps_its_entry_on_focus_out(root, themed):
    """The slot stays editable until a preset option is chosen.

    The handlers are called directly rather than through ``event_generate``:
    this root is withdrawn, and an unmapped window never delivers focus events.
    Delivering them is Tk's job — what is worth checking here is that the real
    pack state ends up right, which the widget stubs cannot tell us.
    """

    frame = ttk.Frame(root)
    frame.pack()
    variable = tk.DoubleVar(value=1.0)
    control = SegmentedChoice(
        frame,
        [Option(1.0, "1"), Option(10.0, "10")],
        tk=tk,
        ttk=ttk,
        variable=variable,
        custom=CustomSpec(minimum=1.0, maximum=10.0),
    )
    control.frame.pack()
    root.update()

    def slot_shows_entry() -> bool:
        packed = [str(widget) for widget in control.frame.pack_slaves()]
        return str(control.custom_entry) in packed

    control.custom_button.invoke()
    control.custom_var.set("3.5")
    control._commit_custom_edit()  # what <Return> is bound to
    root.update_idletasks()
    assert variable.get() == pytest.approx(3.5)
    assert slot_shows_entry()

    control._cancel_custom_edit()  # what <FocusOut> is bound to
    root.update_idletasks()
    assert slot_shows_entry(), "focus-out collapsed a committed custom value"
    assert variable.get() == pytest.approx(3.5)

    control.buttons[0].invoke()
    root.update()
    assert not slot_shows_entry()
    assert variable.get() == pytest.approx(1.0)


def test_help_link_is_sized_to_its_glyph(root, themed):
    """ttk's TButton carries ``width: -11``; the help link must opt out.

    Without ``width=0`` the one-character "?" was padded out to ~89px.
    """

    frame = ttk.Frame(root)
    help_button = ttk.Button(frame, text="?", style="HelpLink.TButton")
    help_button.pack()
    root.update_idletasks()

    assert help_button.winfo_reqwidth() < 30
