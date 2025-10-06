"""Tests for the command line interface entry point."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import List

import pytest

from talks_reducer import cli


class _DummyParser:
    """Small helper parser used to assert CLI flow without argparse."""

    def __init__(self) -> None:
        self.help_called = False
        self.parsed_args: List[str] | None = None

    def print_help(self) -> None:
        self.help_called = True

    def parse_args(self, args: List[str]):  # pragma: no cover - not used in help test
        self.parsed_args = list(args)
        return SimpleNamespace(
            input_file=args,
            output_file=None,
            temp_folder=None,
            silent_threshold=None,
            silent_speed=None,
            sounded_speed=None,
            frame_spreadage=None,
            sample_rate=None,
            small=False,
        )


def test_main_launches_gui_when_no_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure the GUI branch is exercised when no CLI args are provided."""

    captured: dict[str, List[str]] = {}

    def fake_launch(argv: List[str]) -> bool:
        captured["argv"] = list(argv)
        return True

    monkeypatch.setattr(cli, "_attempt_gui_launch", fake_launch)

    build_called = False

    def fake_build_parser() -> _DummyParser:
        nonlocal build_called
        build_called = True
        return _DummyParser()

    monkeypatch.setattr(cli, "_build_parser", fake_build_parser)

    cli.main([])

    assert captured["argv"] == []
    assert build_called is False


def test_main_prints_help_when_gui_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the CLI gracefully falls back to help output when GUI fails."""

    monkeypatch.setattr(cli, "_attempt_gui_launch", lambda argv: False)

    parser = _DummyParser()
    monkeypatch.setattr(cli, "_build_parser", lambda: parser)

    cli.main([])

    assert parser.help_called is True


def test_main_processes_cli_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    """Confirm the standard CLI execution path still runs the pipeline."""

    parsed: dict[str, object] = {}

    def fake_build_parser() -> _DummyParser:
        class Parser(_DummyParser):
            def parse_args(self, args: List[str]):
                parsed["parse_args"] = list(args)
                return SimpleNamespace(
                    input_file=args,
                    output_file="output.mp4",
                    temp_folder="TEMP",
                    silent_threshold=0.05,
                    silent_speed=3.0,
                    sounded_speed=1.0,
                    frame_spreadage=3,
                    sample_rate=48000,
                    small=True,
                )

        return Parser()

    monkeypatch.setattr(cli, "_build_parser", fake_build_parser)
    monkeypatch.setattr(cli, "gather_input_files", lambda paths: paths)

    class DummyReporter:
        def log(self, message: str) -> None:  # pragma: no cover - simple stub
            parsed.setdefault("logs", []).append(message)

    monkeypatch.setattr(cli, "TqdmProgressReporter", lambda: DummyReporter())

    class DummyResult:
        def __init__(self, output_file: str) -> None:
            self.output_file = Path(output_file)

    def fake_speed(options, reporter) -> DummyResult:
        parsed["options"] = options
        return DummyResult("final.mp4")

    monkeypatch.setattr(cli, "speed_up_video", fake_speed)
    monkeypatch.setattr(cli, "ProcessingOptions", lambda **kwargs: kwargs)

    cli.main(["input.mp4"])

    assert parsed["parse_args"] == ["input.mp4"]
    assert parsed["options"]["input_file"] == Path("input.mp4")
    assert parsed["options"]["output_file"] == Path("output.mp4")
    assert parsed["options"]["temp_folder"] == Path("TEMP")
    assert parsed["options"]["silent_threshold"] == 0.05
    assert parsed["options"]["silent_speed"] == 3.0
    assert parsed["options"]["sounded_speed"] == 1.0
    assert parsed["options"]["frame_spreadage"] == 3
    assert parsed["options"]["sample_rate"] == 48000
    assert parsed["options"]["small"] is True
    assert parsed["logs"] == ["Completed: final.mp4"]
