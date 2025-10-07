"""Tests for the CLI entry point behaviour."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from talks_reducer import cli


def test_main_launches_gui_when_no_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """The GUI should be launched when no CLI arguments are provided."""

    launch_calls: list[list[str]] = []

    def fake_launch(argv: list[str]) -> bool:
        launch_calls.append(list(argv))
        return True

    def fail_build_parser() -> None:
        raise AssertionError("Parser should not be built when GUI launches")

    monkeypatch.setattr(cli, "_launch_gui", fake_launch)
    monkeypatch.setattr(cli, "_build_parser", fail_build_parser)

    cli.main([])

    assert launch_calls == [[]]


def test_main_runs_cli_with_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    """Providing CLI arguments should bypass the GUI and run the pipeline."""

    parsed_args = SimpleNamespace(
        input_file=["input.mp4"],
        output_file=None,
        temp_folder=None,
        silent_threshold=None,
        silent_speed=None,
        sounded_speed=None,
        frame_spreadage=None,
        sample_rate=None,
        small=False,
    )

    parser_mock = mock.Mock()
    parser_mock.parse_args.return_value = parsed_args

    outputs: list[cli.ProcessingOptions] = []

    class DummyReporter:
        def log(self, _message: str) -> None:  # pragma: no cover - simple stub
            pass

    def fake_speed_up_video(options: cli.ProcessingOptions, reporter: object):
        outputs.append(options)
        return SimpleNamespace(output_file=Path("/tmp/output.mp4"))

    def fake_gather_input_files(_paths: list[str]) -> list[str]:
        return ["/tmp/input.mp4"]

    def fail_launch(_argv: list[str]) -> bool:
        raise AssertionError("GUI should not be launched when arguments exist")

    monkeypatch.setattr(cli, "_build_parser", lambda: parser_mock)
    monkeypatch.setattr(cli, "gather_input_files", fake_gather_input_files)
    monkeypatch.setattr(cli, "speed_up_video", fake_speed_up_video)
    monkeypatch.setattr(cli, "TqdmProgressReporter", lambda: DummyReporter())
    monkeypatch.setattr(cli, "_launch_gui", fail_launch)

    cli.main(["input.mp4"])

    parser_mock.parse_args.assert_called_once_with(["input.mp4"])
    assert len(outputs) == 1
    assert outputs[0].input_file == Path("/tmp/input.mp4")


def test_main_launches_server_when_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    """The server subcommand should dispatch to the Gradio launcher."""

    server_calls: list[list[str]] = []

    def fake_server(argv: list[str]) -> bool:
        server_calls.append(list(argv))
        return True

    monkeypatch.setattr(cli, "_launch_server", fake_server)
    monkeypatch.setattr(cli, "_launch_gui", lambda argv: False)

    cli.main(["server", "--share"])

    assert server_calls == [["--share"]]


def test_main_exits_when_server_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing Gradio server should raise SystemExit to mimic CLI failures."""

    monkeypatch.setattr(cli, "_launch_server", lambda argv: False)
    monkeypatch.setattr(cli, "_launch_gui", lambda argv: False)

    with pytest.raises(SystemExit):
        cli.main(["server"])
