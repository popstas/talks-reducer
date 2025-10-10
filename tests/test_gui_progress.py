import pytest

from talks_reducer.gui.progress import _GuiProgressHandle, _TkProgressReporter


def test_gui_progress_handle_context_manager_logs_completion(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logs: list[str] = []
    reporter = _TkProgressReporter(logs.append)

    with reporter.task(desc="Encoding") as handle:
        handle.ensure_total(5)
        handle.advance(2)

    assert logs == ["Encoding started", "Encoding completed"]
    assert handle.current == 5

    reporter.log("Finished")
    captured = capsys.readouterr()
    assert "Finished" in captured.out
    assert logs[-1] == "Finished"


def test_tk_progress_reporter_stop_requested() -> None:
    logs: list[str] = []
    stop_flag = {"value": False}

    reporter = _TkProgressReporter(
        logs.append, stop_callback=lambda: stop_flag["value"]
    )

    handle = reporter.task(desc="Processing")
    assert isinstance(handle, _GuiProgressHandle)
    assert reporter.stop_requested() is False

    stop_flag["value"] = True
    assert reporter.stop_requested() is True
