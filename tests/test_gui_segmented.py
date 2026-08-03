from __future__ import annotations

import pytest

from talks_reducer.gui.segmented import (
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
