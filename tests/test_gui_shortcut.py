"""Tests for the pure helpers in :mod:`talks_reducer.gui.shortcut`."""

from __future__ import annotations

import os

from talks_reducer.gui import shortcut


def _gui_values(**overrides):
    values = {
        "silent_speed": 5.0,
        "sounded_speed": 1.0,
        "silent_threshold": 0.01,
        "video_codec": "h264",
    }
    values.update(overrides)
    return values


def test_build_shortcut_args_empty_selection():
    assert shortcut.build_shortcut_args({}, _gui_values()) == []


def test_build_shortcut_args_small_only():
    args = shortcut.build_shortcut_args({"small": True}, _gui_values())
    assert args == ["--small"]


def test_build_shortcut_args_720_implies_small():
    args = shortcut.build_shortcut_args({"small_720": True}, _gui_values())
    assert args == ["--small", "--720"]


def test_build_shortcut_args_480_implies_small():
    args = shortcut.build_shortcut_args({"small_480": True}, _gui_values())
    assert args == ["--small", "--480"]


def test_build_shortcut_args_480_takes_precedence_when_both_set():
    args = shortcut.build_shortcut_args(
        {"small": True, "small_720": True, "small_480": True}, _gui_values()
    )
    assert args == ["--small", "--480"]


def test_build_shortcut_args_numbers_trim_trailing_zeros():
    args = shortcut.build_shortcut_args(
        {"silent_speed": True, "sounded_speed": True},
        _gui_values(silent_speed=10.0, sounded_speed=1.5),
    )
    assert args == ["--silent-speed", "10", "--sounded-speed", "1.5"]


def test_build_shortcut_args_silent_threshold_preserves_decimals():
    args = shortcut.build_shortcut_args(
        {"silent_threshold": True}, _gui_values(silent_threshold=0.05)
    )
    assert args == ["--silent-threshold", "0.05"]


def test_build_shortcut_args_codec():
    args = shortcut.build_shortcut_args({"codec": True}, _gui_values(video_codec="av1"))
    assert args == ["--video-codec", "av1"]


def test_build_shortcut_args_codec_default_still_emitted_when_selected():
    args = shortcut.build_shortcut_args({"codec": True}, _gui_values())
    assert args == ["--video-codec", "h264"]


def test_build_shortcut_args_full_combination_order():
    args = shortcut.build_shortcut_args(
        {
            "small_720": True,
            "silent_speed": True,
            "sounded_speed": True,
            "silent_threshold": True,
            "codec": True,
        },
        _gui_values(
            silent_speed=10.0,
            sounded_speed=2.0,
            silent_threshold=0.02,
            video_codec="h264",
        ),
    )
    assert args == [
        "--small",
        "--720",
        "--silent-speed",
        "10",
        "--sounded-speed",
        "2",
        "--silent-threshold",
        "0.02",
        "--video-codec",
        "h264",
    ]


def test_shortcut_filename_empty_args_fallback():
    assert shortcut.shortcut_filename([]) == "Talks Reducer.lnk"


def test_shortcut_filename_derives_from_args():
    name = shortcut.shortcut_filename(["--small", "--720", "--silent-speed", "10"])
    assert name == "Talks Reducer (small 720 silent-speed 10).lnk"


def test_shortcut_filename_falls_back_when_sanitization_empties_name():
    assert shortcut.shortcut_filename(["--", "////"]) == "Talks Reducer.lnk"


def test_shortcut_filename_sanitizes_illegal_characters():
    name = shortcut.shortcut_filename(["--video-codec", "h2/64:?"])
    assert "/" not in name
    assert ":" not in name
    assert "?" not in name
    assert name == "Talks Reducer (video-codec h264).lnk"


def test_compute_centered_geometry_centers_over_parent():
    # Parent at (100, 200), 400x300; dialog 200x100 -> centered offset.
    assert shortcut.compute_centered_geometry((100, 200, 400, 300), (200, 100)) == (
        200,
        300,
    )


def test_compute_centered_geometry_clamps_to_non_negative():
    # A dialog larger than the parent would compute a negative origin; clamp it.
    assert shortcut.compute_centered_geometry((0, 0, 100, 100), (400, 400)) == (0, 0)


def test_resolve_shortcut_target_frozen_uses_executable_directly():
    executable = os.path.join("Apps", "talks-reducer.exe")
    target = shortcut.resolve_shortcut_target(
        ["--small", "--720"],
        executable=executable,
        frozen=True,
    )
    assert target["target_path"] == executable
    assert target["arguments"] == "--small --720"
    assert target["icon_location"] == executable
    assert target["working_directory"] == "Apps"


def test_resolve_shortcut_target_dev_prefixes_module():
    target = shortcut.resolve_shortcut_target(
        ["--small"],
        executable=r"C:\\Python\\pythonw.exe",
        frozen=False,
    )
    assert target["target_path"] == r"C:\\Python\\pythonw.exe"
    assert target["arguments"] == "-m talks_reducer.gui --small"


def test_resolve_shortcut_target_dev_no_args_still_runs_module():
    target = shortcut.resolve_shortcut_target(
        [],
        executable=r"C:\\Python\\pythonw.exe",
        frozen=False,
    )
    assert target["arguments"] == "-m talks_reducer.gui"


class _FakeVar:
    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value


class _FakeGUI:
    def __init__(self, **values):
        self.small_var = _FakeVar(values.get("small", False))
        self.small_480_var = _FakeVar(values.get("small_480", False))
        self.silent_speed_var = _FakeVar(values.get("silent_speed", 5.0))
        self.sounded_speed_var = _FakeVar(values.get("sounded_speed", 1.0))
        self.silent_threshold_var = _FakeVar(values.get("silent_threshold", 0.01))
        self.video_codec_var = _FakeVar(values.get("video_codec", "h264"))


def test_dialog_initial_selections_defaults_all_unchecked():
    selections = shortcut._dialog_initial_selections(_FakeGUI())
    assert selections == {
        "small": False,
        "small_720": False,
        "small_480": False,
        "silent_speed": False,
        "sounded_speed": False,
        "silent_threshold": False,
        "codec": False,
    }


def test_dialog_initial_selections_small_720_when_small_on():
    selections = shortcut._dialog_initial_selections(_FakeGUI(small=True))
    assert selections["small"] is True
    assert selections["small_720"] is True
    assert selections["small_480"] is False


def test_dialog_initial_selections_small_480_when_variant_on():
    selections = shortcut._dialog_initial_selections(
        _FakeGUI(small=True, small_480=True)
    )
    assert selections["small_720"] is False
    assert selections["small_480"] is True


def test_dialog_initial_selections_checks_changed_numeric_values():
    selections = shortcut._dialog_initial_selections(
        _FakeGUI(silent_speed=10.0, video_codec="av1")
    )
    assert selections["silent_speed"] is True
    assert selections["sounded_speed"] is False


def test_dialog_initial_selections_codec_always_unchecked():
    """Codec defaults to unchecked regardless of the current codec value."""

    for codec in ("h264", "hevc", "av1"):
        selections = shortcut._dialog_initial_selections(_FakeGUI(video_codec=codec))
        assert selections["codec"] is False


def test_dialog_initial_selections_captures_pipeline_default_values():
    """A value equal to the pipeline default but not the GUI default must be
    pre-checked, otherwise an unflagged shortcut would fall back to the GUI
    default and silently reproduce a different setting."""

    selections = shortcut._dialog_initial_selections(_FakeGUI(silent_speed=4.0))
    assert selections["silent_speed"] is True


def test_build_powershell_script_sets_all_fields_and_escapes_quotes():
    target = {
        "target_path": r"C:\\It's\\talks-reducer.exe",
        "arguments": "--small",
        "working_directory": r"C:\\It's",
        "icon_location": r"C:\\It's\\talks-reducer.exe",
    }
    script = shortcut.build_powershell_script(r"C:\\Desktop\\Talks.lnk", target)
    assert "CreateShortcut('C:\\\\Desktop\\\\Talks.lnk')" in script
    assert "$s.Arguments = '--small'" in script
    assert "$s.Save()" in script
    # Single quotes in paths are doubled for PowerShell single-quoted strings.
    assert "It''s" in script
