"""Tests for the timecode parsing and formatting helpers."""

import pytest

from talks_reducer.timecode import format_timecode, parse_timecode


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, 0.0),
        (12, 12.0),
        (12.5, 12.5),
        ("12.5", 12.5),
        ("0", 0.0),
        ("45", 45.0),
        ("01:45", 105.0),
        ("1:45", 105.0),
        ("00:01:45", 105.0),
        ("00:01:45.5", 105.5),
        ("01:00:00", 3600.0),
        ("1:02:03", 3723.0),
        ("  12.5  ", 12.5),
    ],
)
def test_parse_timecode_valid(value, expected):
    assert parse_timecode(value) == pytest.approx(expected)


@pytest.mark.parametrize(
    "value",
    [
        -1,
        -0.5,
        "-5",
        "aa:bb",
        "",
        "   ",
        "1:2:3:4",
        "1:aa",
        "12.5.5",
        None,
        "abc",
    ],
)
def test_parse_timecode_invalid(value):
    with pytest.raises(ValueError):
        parse_timecode(value)


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "00:00:00"),
        (0.0, "00:00:00"),
        (45, "00:00:45"),
        (105, "00:01:45"),
        (105.5, "00:01:45"),
        (3600, "01:00:00"),
        (3723, "01:02:03"),
    ],
)
def test_format_timecode(seconds, expected):
    assert format_timecode(seconds) == expected


def test_format_timecode_rejects_negative():
    with pytest.raises(ValueError):
        format_timecode(-1)
