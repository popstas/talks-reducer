from __future__ import annotations

import json
from pathlib import Path

import pytest

from talks_reducer import presets
from talks_reducer.presets import (
    DEFAULT_PRESETS,
    Preset,
    add_preset,
    delete_preset,
    find_preset,
    get_selected_preset,
    load_presets,
    match_preset,
    preset_to_cli_args,
    save_presets,
    set_selected_preset,
    update_preset,
)


def _preset(name: str, resolution: str = "720p", codec: str = "h264") -> Preset:
    return Preset(
        name=name,
        resolution=resolution,
        silent_speed=5.0,
        sounded_speed=1.0,
        silent_threshold=0.01,
        video_codec=codec,
    )


def _config_path(tmp_path: Path) -> Path:
    return tmp_path / "talks-reducer" / "settings.json"


def _read(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def test_load_presets_seeds_defaults_on_first_run(tmp_path):
    path = _config_path(tmp_path)
    assert not path.exists()

    result = load_presets(config_path=path)

    assert result == DEFAULT_PRESETS
    # The defaults are persisted so every other surface sees the same list.
    stored = _read(path)
    assert [entry["name"] for entry in stored["presets"]] == [
        preset.name for preset in DEFAULT_PRESETS
    ]


def test_load_presets_preserves_empty_list(tmp_path):
    path = _config_path(tmp_path)
    save_presets([], config_path=path)

    # The user emptied the list; it must not be re-seeded.
    assert load_presets(config_path=path) == []


def test_load_presets_skips_malformed_entries(tmp_path):
    path = _config_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "presets": [
                    {
                        "name": "Good",
                        "resolution": "720p",
                        "silent_speed": 10.0,
                        "sounded_speed": 1.0,
                        "silent_threshold": 0.01,
                        "video_codec": "h264",
                    },
                    # A non-numeric speed must not take down every surface.
                    {"name": "Broken", "silent_speed": "fast"},
                    "not-a-mapping",
                ]
            },
            handle,
        )

    result = load_presets(config_path=path)

    assert [preset.name for preset in result] == ["Good"]


def test_save_and_load_round_trip(tmp_path):
    path = _config_path(tmp_path)
    custom = [
        Preset(
            name="My preset",
            resolution="1080p",
            silent_speed=7.5,
            sounded_speed=1.25,
            silent_threshold=0.02,
            video_codec="av1",
        )
    ]

    assert save_presets(custom, config_path=path) is True
    assert load_presets(config_path=path) == custom


def test_save_presets_preserves_other_settings(tmp_path):
    path = _config_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump({"theme": "dark"}, handle)

    save_presets([DEFAULT_PRESETS[0]], config_path=path)

    stored = _read(path)
    assert stored["theme"] == "dark"
    assert stored["presets"][0]["name"] == DEFAULT_PRESETS[0].name


def test_load_presets_ignores_non_mapping_entries(tmp_path):
    path = _config_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(
            {"presets": ["bogus", {"name": "Good", "resolution": "720p"}]}, handle
        )

    result = load_presets(config_path=path)

    assert [preset.name for preset in result] == ["Good"]


def test_load_presets_non_list_value_returns_empty(tmp_path):
    path = _config_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump({"presets": "nope"}, handle)

    assert load_presets(config_path=path) == []


@pytest.mark.parametrize(
    "resolution, expected_prefix",
    [
        ("1080p", ["--no-small"]),
        ("720p", ["--small", "--720"]),
        ("480p", ["--small", "--480"]),
    ],
)
def test_preset_to_cli_args_resolution_tri_state(resolution, expected_prefix):
    preset = Preset(
        name="p",
        resolution=resolution,
        silent_speed=10.0,
        sounded_speed=1.0,
        silent_threshold=0.01,
        video_codec="h264",
    )

    args = preset_to_cli_args(preset)

    assert args[: len(expected_prefix)] == expected_prefix
    assert args[len(expected_prefix) :] == [
        "--silent-speed",
        "10",
        "--sounded-speed",
        "1",
        "--silent-threshold",
        "0.01",
        "--video-codec",
        "h264",
    ]


def test_preset_to_cli_args_trims_trailing_zeros():
    preset = Preset(
        name="p",
        resolution="720p",
        silent_speed=7.50,
        sounded_speed=1.0,
        silent_threshold=0.005,
        video_codec="hevc",
    )

    args = preset_to_cli_args(preset)

    assert "--silent-speed" in args
    assert args[args.index("--silent-speed") + 1] == "7.5"
    assert args[args.index("--silent-threshold") + 1] == "0.005"


def test_match_preset_exact_match_within_tolerance():
    values = {
        "resolution": "480p",
        "silent_speed": 10.0 + 1e-12,
        "sounded_speed": 1.0,
        "silent_threshold": 0.01,
        "video_codec": "hevc",
    }

    assert match_preset(values, DEFAULT_PRESETS) == "480p 10x speedup H.265"


def test_match_preset_returns_none_when_custom():
    values = {
        "resolution": "720p",
        "silent_speed": 3.0,
        "sounded_speed": 1.0,
        "silent_threshold": 0.01,
        "video_codec": "h264",
    }

    assert match_preset(values, DEFAULT_PRESETS) is None


def test_match_preset_resolution_and_codec_must_match():
    base = DEFAULT_PRESETS[0]  # 720p ... h264
    wrong_codec = {
        "resolution": base.resolution,
        "silent_speed": base.silent_speed,
        "sounded_speed": base.sounded_speed,
        "silent_threshold": base.silent_threshold,
        "video_codec": "av1",
    }
    assert match_preset(wrong_codec, DEFAULT_PRESETS) is None


def test_match_preset_invalid_number_returns_none():
    values = {
        "resolution": "720p",
        "silent_speed": "not-a-number",
        "sounded_speed": 1.0,
        "silent_threshold": 0.01,
        "video_codec": "h264",
    }

    assert match_preset(values, DEFAULT_PRESETS) is None


def test_find_preset():
    assert find_preset("720p no speedup H.264", DEFAULT_PRESETS).resolution == "720p"
    assert find_preset("missing", DEFAULT_PRESETS) is None


def test_selected_preset_round_trip(tmp_path):
    path = _config_path(tmp_path)

    assert get_selected_preset(config_path=path) is None

    assert set_selected_preset("My preset", config_path=path) is True
    assert get_selected_preset(config_path=path) == "My preset"

    # Clearing removes the key entirely ("Custom").
    assert set_selected_preset(None, config_path=path) is True
    assert get_selected_preset(config_path=path) is None


def test_set_selected_preset_preserves_other_settings(tmp_path):
    path = _config_path(tmp_path)
    save_presets([DEFAULT_PRESETS[0]], config_path=path)

    set_selected_preset(DEFAULT_PRESETS[0].name, config_path=path)

    stored = _read(path)
    assert stored["selected_preset"] == DEFAULT_PRESETS[0].name
    assert stored["presets"][0]["name"] == DEFAULT_PRESETS[0].name


def test_add_preset_appends_and_leaves_source_untouched():
    original = [_preset("A"), _preset("B")]
    result = add_preset(original, _preset("C"))

    assert [p.name for p in result] == ["A", "B", "C"]
    # The helper is pure: the source list is not mutated in place.
    assert [p.name for p in original] == ["A", "B"]


def test_add_preset_overwrites_same_name():
    original = [_preset("A", codec="h264"), _preset("B")]
    result = add_preset(original, _preset("A", codec="hevc"))

    assert [p.name for p in result] == ["B", "A"]
    assert find_preset("A", result).video_codec == "hevc"


def test_update_preset_replaces_named_entry():
    original = [_preset("A"), _preset("B", codec="h264")]
    replacement = _preset("B", codec="av1")
    result = update_preset(original, "B", replacement)

    assert [p.name for p in result] == ["A", "B"]
    assert find_preset("B", result).video_codec == "av1"
    # Source is not mutated.
    assert find_preset("B", original).video_codec == "h264"


def test_update_preset_can_rename():
    original = [_preset("A"), _preset("B")]
    result = update_preset(original, "B", _preset("B renamed"))

    assert [p.name for p in result] == ["A", "B renamed"]


def test_update_preset_appends_when_name_absent():
    original = [_preset("A")]
    result = update_preset(original, "missing", _preset("New"))

    assert [p.name for p in result] == ["A", "New"]


def test_delete_preset_removes_named_entry():
    original = [_preset("A"), _preset("B"), _preset("C")]
    result = delete_preset(original, "B")

    assert [p.name for p in result] == ["A", "C"]
    # Source is not mutated.
    assert [p.name for p in original] == ["A", "B", "C"]


def test_delete_preset_absent_name_is_noop():
    original = [_preset("A")]
    assert [p.name for p in delete_preset(original, "missing")] == ["A"]


def test_preset_from_dict_coerces_types():
    preset = Preset.from_dict(
        {
            "name": "x",
            "resolution": "480p",
            "silent_speed": "10",
            "sounded_speed": "1",
            "silent_threshold": "0.02",
            "video_codec": "av1",
        }
    )

    assert preset.silent_speed == 10.0
    assert preset.silent_threshold == 0.02


# --- Sparse presets --------------------------------------------------------


def test_sparse_to_dict_stores_only_present_fields():
    preset = Preset(name="codec only", video_codec="hevc")

    assert preset.to_dict() == {"name": "codec only", "video_codec": "hevc"}


def test_from_dict_missing_fields_load_as_none():
    preset = Preset.from_dict({"name": "codec only", "video_codec": "hevc"})

    assert preset.video_codec == "hevc"
    assert preset.resolution is None
    assert preset.silent_speed is None
    assert preset.sounded_speed is None
    assert preset.silent_threshold is None


def test_from_dict_explicit_null_loads_as_none():
    preset = Preset.from_dict({"name": "x", "silent_speed": None})

    assert preset.silent_speed is None


def test_sparse_round_trip(tmp_path):
    path = _config_path(tmp_path)
    sparse = [Preset(name="speed swap", silent_speed=10.0, video_codec="h264")]

    assert save_presets(sparse, config_path=path) is True
    # Only the defined fields are persisted on disk.
    stored = _read(path)["presets"]
    assert stored == [
        {"name": "speed swap", "silent_speed": 10.0, "video_codec": "h264"}
    ]
    assert load_presets(config_path=path) == sparse


def test_present_fields_reports_defined_fields():
    preset = Preset(name="x", resolution="480p", video_codec="av1")

    assert preset.present_fields() == {"resolution", "video_codec"}
    assert Preset(name="empty").present_fields() == set()


def test_preset_to_cli_args_sparse_emits_only_present_flags():
    preset = Preset(name="codec only", video_codec="hevc")

    assert preset_to_cli_args(preset) == ["--video-codec", "hevc"]


def test_preset_to_cli_args_sparse_resolution_only():
    preset = Preset(name="res only", resolution="1080p")

    assert preset_to_cli_args(preset) == ["--no-small"]


def test_match_preset_sparse_ignores_undefined_fields():
    preset = Preset(name="codec only", video_codec="hevc")
    values = {
        "resolution": "480p",
        "silent_speed": 3.0,
        "sounded_speed": 2.0,
        "silent_threshold": 0.5,
        "video_codec": "hevc",
    }

    # The preset only constrains the codec, so any resolution/speed still matches.
    assert match_preset(values, [preset]) == "codec only"


def test_match_preset_sparse_requires_defined_field_to_match():
    preset = Preset(name="codec only", video_codec="hevc")
    values = {"video_codec": "h264"}

    assert match_preset(values, [preset]) is None


def test_match_preset_empty_preset_never_matches():
    preset = Preset(name="empty")
    values = {"video_codec": "h264", "resolution": "720p"}

    assert match_preset(values, [preset]) is None


# --- Reordering ------------------------------------------------------------


def test_move_preset_up_and_down():
    original = [_preset("A"), _preset("B"), _preset("C")]

    up = presets.move_preset(original, "C", -1)
    assert [p.name for p in up] == ["A", "C", "B"]

    down = presets.move_preset(original, "A", 1)
    assert [p.name for p in down] == ["B", "A", "C"]


def test_move_preset_clamps_at_bounds():
    original = [_preset("A"), _preset("B")]

    assert [p.name for p in presets.move_preset(original, "A", -1)] == ["A", "B"]
    assert [p.name for p in presets.move_preset(original, "B", 1)] == ["A", "B"]


def test_move_preset_absent_name_is_noop():
    original = [_preset("A"), _preset("B")]

    assert [p.name for p in presets.move_preset(original, "missing", 1)] == ["A", "B"]


def test_move_preset_does_not_mutate_source():
    original = [_preset("A"), _preset("B")]
    presets.move_preset(original, "A", 1)

    assert [p.name for p in original] == ["A", "B"]
