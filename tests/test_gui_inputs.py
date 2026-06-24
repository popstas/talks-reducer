"""Tests for :class:`talks_reducer.gui.inputs.InputController`."""

from __future__ import annotations

from types import SimpleNamespace

from talks_reducer.gui.inputs import InputController


def _make_gui(*, cut_enabled: bool, simple_mode: bool) -> SimpleNamespace:
    return SimpleNamespace(
        input_files=[],
        run_after_drop_var=SimpleNamespace(get=lambda: True),
        cut_enabled_var=SimpleNamespace(get=lambda: cut_enabled),
        simple_mode_var=SimpleNamespace(get=lambda: simple_mode),
        _on_inputs_updated=lambda: None,
        _start_run=lambda: started.append(True),
    )


def test_extend_inputs_auto_runs_in_simple_mode():
    global started
    started = []
    gui = _make_gui(cut_enabled=True, simple_mode=True)
    controller = InputController(gui)

    controller.extend_inputs(["video.mp4"], auto_run=True)

    # Simple mode auto-converts even with Cut enabled.
    assert started == [True]


def test_extend_inputs_defers_run_for_advanced_cut():
    global started
    started = []
    gui = _make_gui(cut_enabled=True, simple_mode=False)
    controller = InputController(gui)

    controller.extend_inputs(["video.mp4"], auto_run=True)

    # Advanced + Cut waits for the explicit Convert button.
    assert started == []
    assert gui.input_files == ["video.mp4"]


def test_extend_inputs_auto_runs_without_cut():
    global started
    started = []
    gui = _make_gui(cut_enabled=False, simple_mode=False)
    controller = InputController(gui)

    controller.extend_inputs(["video.mp4"], auto_run=True)

    assert started == [True]
