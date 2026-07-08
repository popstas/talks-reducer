from __future__ import annotations

from types import SimpleNamespace

from talks_reducer.gui.tooltips import add_tooltip


class FakeWidget:
    def __init__(self) -> None:
        self.bindings: dict[str, object] = {}
        self.after_calls: list[tuple[int, object]] = []
        self.cancelled: list[object] = []
        self._job_counter = 0

    def bind(self, sequence, callback):
        self.bindings[sequence] = callback

    def after(self, delay_ms, callback):
        self._job_counter += 1
        job_id = f"job-{self._job_counter}"
        self.after_calls.append((delay_ms, callback))
        return job_id

    def after_cancel(self, job_id):
        self.cancelled.append(job_id)

    def winfo_rootx(self) -> int:
        return 100

    def winfo_rooty(self) -> int:
        return 200

    def winfo_height(self) -> int:
        return 20


class FakeLabel:
    def __init__(self, master, **kwargs) -> None:
        self.master = master
        self.kwargs = kwargs
        self.packed = False

    def pack(self, *args, **kwargs):
        self.packed = True


class FakeToplevel:
    def __init__(self, master) -> None:
        self.master = master
        self.overrideredirect = None
        self.geometry = None
        self.destroyed = False

    def wm_overrideredirect(self, value):
        self.overrideredirect = value

    def wm_geometry(self, spec):
        self.geometry = spec

    def destroy(self):
        self.destroyed = True


def _make_tk():
    return SimpleNamespace(Toplevel=FakeToplevel, Label=FakeLabel)


def test_add_tooltip_binds_hover_events():
    widget = FakeWidget()

    add_tooltip(widget, "Larger size, but supports seeking", tk_module=_make_tk())

    assert "<Enter>" in widget.bindings
    assert "<Leave>" in widget.bindings


def test_hover_shows_tooltip_window_with_text():
    labels: list[FakeLabel] = []

    class RecordingLabel(FakeLabel):
        def __init__(self, master, **kwargs):
            super().__init__(master, **kwargs)
            labels.append(self)

    tk_module = SimpleNamespace(Toplevel=FakeToplevel, Label=RecordingLabel)
    widget = FakeWidget()
    add_tooltip(widget, "Larger size, but supports seeking", tk_module=tk_module)

    widget.bindings["<Enter>"](None)
    # The show is deferred via after(); invoke the scheduled callback.
    assert widget.after_calls, "entering should schedule the tooltip"
    _, show = widget.after_calls[-1]
    window = show()

    assert isinstance(window, FakeToplevel)
    assert window.overrideredirect is True
    assert (
        labels and labels[0].kwargs.get("text") == "Larger size, but supports seeking"
    )


def test_leave_destroys_tooltip_window():
    created = {}

    class RecordingToplevel(FakeToplevel):
        def __init__(self, master):
            super().__init__(master)
            created["window"] = self

    tk_module = SimpleNamespace(Toplevel=RecordingToplevel, Label=FakeLabel)
    widget = FakeWidget()
    add_tooltip(widget, "Larger size, but supports seeking", tk_module=tk_module)

    widget.bindings["<Enter>"](None)
    _, show = widget.after_calls[-1]
    show()
    widget.bindings["<Leave>"](None)

    assert created["window"].destroyed is True
