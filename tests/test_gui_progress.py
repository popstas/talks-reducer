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
        ("Extracting audio:", 100, 100, 10.0),
        ("Audio processing:", 0, 100, 10.0),
        ("Audio processing:", 100, 100, 20.0),
        ("Generating final:", 0, 100, 20.0),
        ("Generating final:", 100, 100, 100.0),
        ("Generating final (fallback):", 50, 100, 60.0),
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
    assert map_stage_progress("Audio processing:", 200, 100) == pytest.approx(20.0)
    assert map_stage_progress("Audio processing:", -10, 100) == pytest.approx(10.0)


def test_map_stage_progress_is_case_insensitive() -> None:
    assert map_stage_progress("AUDIO PROCESSING:", 100, 100) == pytest.approx(20.0)


def test_gui_progress_handle_uses_stage_mapper() -> None:
    logs: list[str] = []
    values: list[float] = []
    reporter = _TkProgressReporter(logs.append, progress_callback=values.append)

    with reporter.task(desc="Generating final:", total=100) as handle:
        handle.advance(50)

    assert values[0] == pytest.approx(60.0)
    assert values[-1] == pytest.approx(100.0)


def test_gui_progress_handle_invokes_stage_callback_on_start() -> None:
    logs: list[str] = []
    stages: list[str] = []
    reporter = _TkProgressReporter(
        logs.append,
        progress_callback=lambda _value: None,
        stage_callback=stages.append,
    )

    with reporter.task(desc="Audio processing:", total=100) as handle:
        handle.advance(50)

    # The structured stage opens once, before any progress is reported, so the
    # GUI can cancel the synthetic audio fallback timer immediately.
    assert stages == ["Audio processing:"]


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


def test_gui_progress_handle_reports_stage_percentages_to_the_status_line() -> None:
    """Real stage progress must keep the status text counting.

    Opening the structured ``Audio processing:`` stage cancels the synthetic
    fallback timer, which was the only writer of the ``Audio processing: NN%``
    status text. Without a status callback the text froze at whatever
    percentage the timer had reached while the bar kept moving.
    """

    statuses: list[tuple[str, float]] = []
    reporter = _TkProgressReporter(
        lambda _message: None,
        progress_callback=lambda _value: None,
        status_callback=lambda desc, percent: statuses.append((desc, percent)),
    )

    with reporter.task(desc="Audio processing:", total=200) as handle:
        handle.advance(50)
        handle.advance(50)

    assert statuses[0] == ("Audio processing:", pytest.approx(25.0))
    assert statuses[1] == ("Audio processing:", pytest.approx(50.0))
    assert statuses[-1] == ("Audio processing:", pytest.approx(100.0))


def test_gui_progress_handle_coalesces_status_updates_to_whole_percents() -> None:
    """One status update per displayed percent, not one per chunk.

    The audio stage advances once per chunk — thousands of times on a long
    recording — while the status text only renders whole percents.
    """

    statuses: list[float] = []
    reporter = _TkProgressReporter(
        lambda _message: None,
        progress_callback=lambda _value: None,
        status_callback=lambda _desc, percent: statuses.append(percent),
    )

    with reporter.task(desc="Audio processing:", total=1000) as handle:
        for _ in range(5):
            handle.advance(1)

    assert statuses == [pytest.approx(0.1), pytest.approx(100.0)]


def test_gui_progress_handle_skips_status_without_a_total() -> None:
    """A task with no total cannot report a percentage, so the fallback stands."""

    statuses: list[tuple[str, float]] = []
    reporter = _TkProgressReporter(
        lambda _message: None,
        progress_callback=lambda _value: None,
        status_callback=lambda desc, percent: statuses.append((desc, percent)),
    )

    handle = reporter.task(desc="Extracting audio:", total=None)
    handle.advance(10)

    assert statuses == []
