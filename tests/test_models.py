"""Tests for the :mod:`talks_reducer.models` dataclasses."""

from pathlib import Path

from talks_reducer.models import ProcessingOptions


def test_cut_fields_default_to_zero() -> None:
    """The trim fields default to ``0.0`` (no trim) when omitted."""

    options = ProcessingOptions(input_file=Path("input.mp4"))

    assert options.cut_start_seconds == 0.0
    assert options.cut_end_seconds == 0.0


def test_cut_fields_carry_supplied_values() -> None:
    """Constructed options retain the supplied keep-range timestamps."""

    options = ProcessingOptions(
        input_file=Path("input.mp4"),
        cut_start_seconds=10.0,
        cut_end_seconds=60.5,
    )

    assert options.cut_start_seconds == 10.0
    assert options.cut_end_seconds == 60.5
