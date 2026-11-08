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


def test_find_player_prefers_configured_path() -> None:
    found = cut_marks.find_player(
        "D:/tools/mpvnet.exe",
        platform="win32",
        which=lambda _n: None,
        environ={},
        exists=lambda p: p == "D:/tools/mpvnet.exe",
    )

    assert found == Path("D:/tools/mpvnet.exe")


def test_find_player_uses_path_before_install_dirs() -> None:
    found = cut_marks.find_player(
        None,
        platform="win32",
        which=lambda n: "C:/bin/mpv.exe" if n == "mpv" else None,
        environ={"ProgramFiles": "C:/Program Files"},
        exists=lambda _p: True,
    )

    assert found == Path("C:/bin/mpv.exe")


def test_find_player_falls_back_to_program_files() -> None:
    expected = str(Path("C:/Program Files") / "mpv.net" / "mpvnet.exe")

    found = cut_marks.find_player(
        None,
        platform="win32",
        which=lambda _n: None,
        environ={"ProgramFiles": "C:/Program Files"},
        exists=lambda p: p == expected,
    )

    assert found == Path(expected)


def test_find_player_returns_none_when_missing() -> None:
    assert (
        cut_marks.find_player(
            None,
            platform="linux",
            which=lambda _n: None,
            environ={},
            exists=lambda _p: False,
        )
        is None
    )


def test_build_player_command_for_mpvnet_forces_new_instance() -> None:
    command = cut_marks.build_player_command(
        Path("C:/mpv.net/mpvnet.exe"), Path("v.mp4"), Path("m.json"), Path("s.lua")
    )

    assert command == [
        str(Path("C:/mpv.net/mpvnet.exe")),
        "--process-instance=multi",
        f"--script={Path('s.lua')}",
        f"--script-opts=talks_reducer_cuts-file={Path('m.json')}",
        str(Path("v.mp4")),
    ]


def test_build_player_command_for_mpv_has_no_instance_flag() -> None:
    command = cut_marks.build_player_command(
        Path("/usr/bin/mpv"), Path("v.mp4"), Path("m.json"), Path("s.lua")
    )

    assert "--process-instance=multi" not in command


def test_lua_script_is_bundled() -> None:
    path = cut_marks.script_path()

    assert path is not None and path.name == "talks_reducer_cuts.lua"
    text = path.read_text(encoding="utf-8")
    assert 'read_options(opts, "talks_reducer_cuts")' in text
    assert "add_forced_key_binding" in text


def test_lua_script_is_packaged() -> None:
    root = Path(__file__).resolve().parents[1]

    assert '"*.lua"' in (root / "pyproject.toml").read_text(encoding="utf-8")
    assert "talks_reducer_cuts.lua" in (root / "talks-reducer.spec").read_text(
        encoding="utf-8"
    )
