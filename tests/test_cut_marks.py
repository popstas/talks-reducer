"""Tests for remove-range marks: parsing, formatting and the sidecar file."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from talks_reducer import cut_marks


def test_normalize_ranges_sorts_merges_and_drops_invalid() -> None:
    ranges = [(30, 40), (10, 20), (15, 25), (50, 50), (60, 55), ("x", 1), (-5, 2)]

    assert cut_marks.normalize_ranges(ranges) == [
        (0.0, 2.0),
        (10.0, 25.0),
        (30.0, 40.0),
    ]


def test_normalize_ranges_merges_touching_ranges() -> None:
    assert cut_marks.normalize_ranges([(1, 2), (2, 3)]) == [(1.0, 3.0)]


def test_parse_ranges_text_accepts_clock_and_seconds() -> None:
    text = "1:20-1:45, 12:00 - 12:30.5,5–7"

    assert cut_marks.parse_ranges_text(text) == [
        (5.0, 7.0),
        (80.0, 105.0),
        (720.0, 750.5),
    ]


def test_parse_ranges_text_empty_is_empty_list() -> None:
    assert cut_marks.parse_ranges_text("  ") == []


@pytest.mark.parametrize("text", ["1:20", "a-b", "1:45-1:20", "1-2-3"])
def test_parse_ranges_text_rejects_bad_tokens(text: str) -> None:
    with pytest.raises(ValueError):
        cut_marks.parse_ranges_text(text)


def test_format_ranges_text_round_trips() -> None:
    ranges = [(80.0, 105.0), (720.0, 750.5)]

    text = cut_marks.format_ranges_text(ranges)

    assert text == "00:01:20-00:01:45, 00:12:00-00:12:30.500"
    assert cut_marks.parse_ranges_text(text) == ranges


def test_sidecar_path_appends_suffix() -> None:
    assert cut_marks.sidecar_path(Path("/v/lecture.mp4")) == Path(
        "/v/lecture.mp4.cuts.json"
    )


def test_save_and_load_marks(tmp_path: Path) -> None:
    video = tmp_path / "лекция.mp4"
    video.write_bytes(b"")

    cut_marks.save_marks(video, [(30, 40), (10, 20)])

    payload = json.loads(cut_marks.sidecar_path(video).read_text("utf-8"))
    assert payload == {
        "version": 1,
        "source": "лекция.mp4",
        "remove": [[10.0, 20.0], [30.0, 40.0]],
    }
    assert cut_marks.load_marks(video) == [(10.0, 20.0), (30.0, 40.0)]


def test_save_empty_marks_deletes_sidecar(tmp_path: Path) -> None:
    video = tmp_path / "a.mp4"
    cut_marks.save_marks(video, [(1, 2)])

    cut_marks.save_marks(video, [])

    assert not cut_marks.sidecar_path(video).exists()


def test_read_marks_file_tolerates_missing_and_bad_files(tmp_path: Path) -> None:
    assert cut_marks.read_marks_file(tmp_path / "missing.json") == []

    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert cut_marks.read_marks_file(bad) == []

    future = tmp_path / "future.json"
    future.write_text(json.dumps({"version": 2, "remove": [[1, 2]]}), "utf-8")
    assert cut_marks.read_marks_file(future) == []


def test_read_marks_file_accepts_empty_object_from_lua(tmp_path: Path) -> None:
    path = tmp_path / "m.json"
    path.write_text('{"version": 1, "source": "a.mp4", "remove": {}}', "utf-8")

    assert cut_marks.read_marks_file(path) == []
