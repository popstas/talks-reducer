import pytest

from talks_reducer.gui.progress import (
    _GuiProgressHandle,
    _TkProgressReporter,
    map_stage_progress,
)


@pytest.mark.parametrize(
    "desc, current, total, expected",
    [
        ("Uploading:", 0, 100, 0.0),
        ("Uploading:", 50, 100, 2.5),
        ("Uploading:", 100, 100, 5.0),
        ("Extracting audio:", 0, 100, 5.0),
        ("Extracting audio:", 100, 100, 20.0),
        ("Audio processing:", 0, 100, 20.0),
        ("Audio processing:", 100, 100, 35.0),
        ("Generating final:", 0, 100, 35.0),
        ("Generating final:", 100, 100, 100.0),
        ("Generating final (fallback):", 50, 100, 67.5),
        ("Mystery task", 50, 100, 50.0),
        ("Mystery task", 100, 100, 100.0),
    ],
)
def test_map_stage_progress_maps_known_and_unknown_stages(
    desc: str, current: int, total: int, expected: float
) -> None:
    assert map_stage_progress(desc, current, total) == pytest.approx(expected)


def test_map_stage_progress_requires_positive_total() -> None:
    assert map_stage_progress("Uploading:", 5, 0) is None
    assert map_stage_progress("Uploading:", 5, None) is None


def test_map_stage_progress_clamps_overshoot_and_negative() -> None:
    assert map_stage_progress("Audio processing:", 200, 100) == pytest.approx(35.0)
    assert map_stage_progress("Audio processing:", -10, 100) == pytest.approx(20.0)


def test_map_stage_progress_is_case_insensitive() -> None:
    assert map_stage_progress("AUDIO PROCESSING:", 100, 100) == pytest.approx(35.0)


def test_gui_progress_handle_uses_stage_mapper() -> None:
    logs: list[str] = []
    values: list[float] = []
    reporter = _TkProgressReporter(logs.append, progress_callback=values.append)

    with reporter.task(desc="Generating final:", total=100) as handle:
        handle.advance(50)

    assert values[0] == pytest.approx(67.5)
    assert values[-1] == pytest.approx(100.0)


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
