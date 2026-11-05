"""User-named preset store shared across the GUI, Web UI, OBS dock, and CLI.

A preset is a saved bundle of processing settings authored in the desktop GUI
and applied read-only everywhere else. Presets live in the shared
``settings.json`` (see :mod:`talks_reducer.config`) under the ``presets`` key so
one canonical list appears on every surface the config file reaches.

The helpers here are UI-agnostic and unit-tested. The seeded defaults are
persisted the first time the ``presets`` key is absent; afterward they are
ordinary, fully editable presets rather than immutable built-ins.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import List, Mapping, Optional, Sequence

from . import config

# Storage keys within ``settings.json``.
PRESETS_KEY = "presets"
SELECTED_PRESET_KEY = "selected_preset"

# Valid resolution values. ``"orig"`` leaves the source resolution alone; the
# others downscale (never upscale) to that height.
RESOLUTIONS = ("orig", "1080p", "720p", "480p")

# Valid frame-rate values. ``"orig"`` keeps the source frame rate; a number caps it.
FPS_VALUES = ("30", "60", "orig")

# Schema marker. Version 1 files used ``"1080p"`` for "no scaling"; version 2
# gives ``"1080p"`` its literal meaning and spells "no scaling" as ``"orig"``.
PRESETS_VERSION_KEY = "presets_version"
PRESETS_VERSION = 2

# Label shown in an authoring dropdown when the live knobs match no stored
# preset. Mirrors :func:`match_preset` returning ``None``.
CUSTOM_LABEL = "Custom"

# Float tolerance for reverse-matching current values back to a preset. Mirrors
# ``layout.BASIC_PRESET_TOLERANCE`` so both surfaces agree on "unchanged".
MATCH_TOLERANCE = 1e-9


# The tunable value fields a preset can carry. ``name`` is excluded because it
# is the identity, not an applied value.
PRESET_VALUE_FIELDS = (
    "resolution",
    "fps",
    "silent_speed",
    "sounded_speed",
    "silent_threshold",
    "video_codec",
)

# Human-readable names for the value fields, shared by the Save/Update dialog's
# checkboxes and the preset summaries shown as tooltips.
PRESET_FIELD_LABELS = {
    "resolution": "Resolution",
    "fps": "FPS",
    "silent_speed": "Silent speed",
    "sounded_speed": "Sounded speed",
    "silent_threshold": "Silent threshold",
    "video_codec": "Codec",
}

# Display names for the codec identifiers stored in a preset, matching the
# labels on the GUI's Codec buttons.
CODEC_LABELS = {
    "h264": "h.264",
    "hevc": "h.265",
    "av1": "av1",
    "mp3": "mp3",
}


@dataclass(frozen=True)
class Preset:
    """A named bundle of processing settings applied across every surface.

    Presets are **sparse**: every value field is optional and a field left as
    ``None`` is not stored, not applied, and ignored when reverse-matching, so a
    preset controls only the params it was saved with. ``resolution`` is one
    of :data:`RESOLUTIONS` (``"orig"`` forces ``--no-small`` rather than
    inheriting a persisted ``--small`` default) and ``fps`` is one of
    :data:`FPS_VALUES`.
    """

    name: str
    resolution: Optional[str] = None
    fps: Optional[str] = None
    silent_speed: Optional[float] = None
    sounded_speed: Optional[float] = None
    silent_threshold: Optional[float] = None
    video_codec: Optional[str] = None

    def to_dict(self) -> dict[str, object]:
        """Return the JSON dict stored in ``settings.json``.

        Only fields the preset actually defines are serialized, so a sparse
        preset round-trips without inventing values for the params it omits.
        """

        data: dict[str, object] = {"name": self.name}
        for field in PRESET_VALUE_FIELDS:
            value = getattr(self, field)
            if value is not None:
                data[field] = value
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "Preset":
        """Build a :class:`Preset` from a stored dict, coercing present fields.

        A missing (or explicitly ``null``) field loads as ``None`` so both the
        new sparse presets and the fully populated presets written by the first
        release round-trip unchanged.
        """

        def _opt_str(key: str) -> Optional[str]:
            value = data.get(key)
            return str(value) if value is not None else None

        def _opt_float(key: str) -> Optional[float]:
            value = data.get(key)
            return float(value) if value is not None else None

        return cls(
            name=str(data.get("name", "")),
            resolution=_opt_str("resolution"),
            fps=_opt_str("fps"),
            silent_speed=_opt_float("silent_speed"),
            sounded_speed=_opt_float("sounded_speed"),
            silent_threshold=_opt_float("silent_threshold"),
            video_codec=_opt_str("video_codec"),
        )

    def present_fields(self) -> set:
        """Return the set of value fields this preset defines (non-``None``)."""

        return {
            field for field in PRESET_VALUE_FIELDS if getattr(self, field) is not None
        }


# The seeded defaults written on first run when ``presets`` is absent. Named for
# the outcome rather than the settings ("Compatible", not "720p 10x speedup
# H.264") — the values are one hover away in the GUI (:func:`describe_preset`),
# so the name is free to say what the preset is *for*. "Compatible" leads
# because it is the first-run default on every surface and h.264 plays
# everywhere. "mp3" is deliberately sparse: it carries no resolution, so
# extracting audio leaves the video settings alone. "Compress" keeps 1080p (a
# real downscale for 4K sources) at 30 fps; "Smallest" also caps at 30 fps.
# "Compatible" and "Optimal" say ``fps="orig"`` explicitly: a sparse preset with
# no fps would keep whatever cap the previously selected preset left behind.
DEFAULT_PRESETS: List[Preset] = [
    Preset(
        name="Compatible",
        resolution="720p",
        fps="orig",
        silent_speed=10.0,
        sounded_speed=1.0,
        silent_threshold=0.01,
        video_codec="h264",
    ),
    Preset(
        name="Optimal",
        resolution="720p",
        fps="orig",
        silent_speed=10.0,
        sounded_speed=1.0,
        silent_threshold=0.01,
        video_codec="hevc",
    ),
    Preset(
        name="Smallest",
        resolution="480p",
        fps="30",
        silent_speed=10.0,
        sounded_speed=1.0,
        silent_threshold=0.01,
        video_codec="hevc",
    ),
    Preset(
        name="Compress",
        resolution="1080p",
        fps="30",
        silent_speed=1.0,
        sounded_speed=1.0,
        silent_threshold=0.01,
        video_codec="h264",
    ),
    Preset(
        name="mp3",
        silent_speed=10.0,
        sounded_speed=1.0,
        silent_threshold=0.01,
        video_codec="mp3",
    ),
]


def _resolve_config_path(config_path: Optional[Path]) -> Path:
    """Return *config_path* or the platform default settings-file path."""

    return config_path if config_path is not None else config.determine_config_path()


def _format_number(value: float) -> str:
    """Render *value* without a trailing ``.0`` (e.g. ``10`` instead of ``10.0``).

    Matches the CLI-flag rendering used by
    :func:`talks_reducer.gui.shortcut.build_shortcut_args` so preset flags read
    the same as a "Create link" command line, without importing the GUI package.
    """

    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return text or "0"


def resolution_to_small(resolution: str) -> tuple[bool, Optional[int]]:
    """Map a resolution value to ``(small, target_height)``.

    ``"orig"`` disables scaling and returns no height; ``"1080p"``/``"480p"``
    return their height; ``"720p"`` and any unexpected value fall back to the
    720p small preset, matching how unknown values were always treated.
    """

    if resolution == "orig":
        return False, None
    if resolution == "1080p":
        return True, 1080
    if resolution == "480p":
        return True, 480
    return True, 720


def parse_fps_token(token: object) -> float:
    """Return the frame-rate cap for *token*: ``0.0`` for ``"orig"``.

    Any other value must be a positive finite number; anything else raises
    :class:`ValueError` so callers can reject it (CLI) or skip it (presets).
    """

    text = str(token).strip().lower()
    if text == "orig":
        return 0.0
    value = float(text)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"fps must be positive or 'orig', got {token!r}")
    return value


def format_fps_token(max_frame_rate: Optional[float]) -> str:
    """Render a frame-rate cap as a token: ``"orig"`` when unset or non-positive."""

    if not max_frame_rate or max_frame_rate <= 0:
        return "orig"
    return _format_number(max_frame_rate)


def _stored_presets_version(settings: Mapping[str, object]) -> int:
    """Return the ``presets_version`` marker, treating absent/garbage as 1."""

    try:
        return int(settings.get(PRESETS_VERSION_KEY, 1))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1


def _migrate_v1_entry(entry: object) -> object:
    """Rewrite a version-1 preset dict into the version-2 schema.

    ``"1080p"`` meant "orig" in version 1, and a preset with a resolution but
    no ``fps`` implicitly kept the source frame rate, so it gains
    ``fps: "orig"`` to stop inheriting the cap of a previously selected preset.
    Presets without a resolution (e.g. audio-only) are left alone.
    """

    if not isinstance(entry, Mapping) or entry.get("resolution") is None:
        return entry
    migrated = dict(entry)
    if migrated["resolution"] == "1080p":
        migrated["resolution"] = "orig"
    if migrated.get("fps") is None:
        migrated["fps"] = "orig"
    return migrated


def load_presets(config_path: Optional[Path] = None) -> List[Preset]:
    """Return the stored presets, seeding :data:`DEFAULT_PRESETS` on first run.

    When the ``presets`` key is absent the defaults are persisted to
    ``settings.json`` and returned. An explicitly empty list (the user deleted
    every preset) is preserved and returned as ``[]``. A version-1 file (no
    ``presets_version`` marker) has its ``"1080p"`` presets rewritten to
    ``"orig"`` once, gains ``fps: "orig"`` where it has a resolution but no fps,
    and is re-saved with the marker.
    """

    path = _resolve_config_path(config_path)
    try:
        settings = config.read_settings_strict(path)
    except config.SettingsReadError:
        # A locked or partially written file must not be mistaken for a missing
        # ``presets`` key: re-seeding on top of a ``{}`` produced by a read
        # failure would clobber every other setting. Return the defaults without
        # persisting so the transient failure leaves the file untouched.
        return list(DEFAULT_PRESETS)

    if PRESETS_KEY not in settings:
        save_presets(DEFAULT_PRESETS, config_path=path)
        return list(DEFAULT_PRESETS)

    raw = settings.get(PRESETS_KEY)
    if not isinstance(raw, list):
        return []

    if _stored_presets_version(settings) < PRESETS_VERSION:
        raw = [_migrate_v1_entry(entry) for entry in raw]
        settings[PRESETS_KEY] = raw
        settings[PRESETS_VERSION_KEY] = PRESETS_VERSION
        # Best-effort: a failed write migrates again on the next load, which
        # is safe because only a version-1 file is ever rewritten.
        config.save_settings(path, settings)

    presets: List[Preset] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        try:
            presets.append(Preset.from_dict(entry))
        except (TypeError, ValueError):
            # A partially edited or corrupt preset entry (e.g. a non-numeric
            # ``silent_speed``) must not take down every surface that loads the
            # store; skip it rather than propagating the conversion error.
            continue
    return presets


def save_presets(presets: Sequence[Preset], config_path: Optional[Path] = None) -> bool:
    """Persist *presets* to the ``presets`` key, preserving other settings."""

    path = _resolve_config_path(config_path)
    try:
        settings = config.read_settings_strict(path)
    except config.SettingsReadError:
        # Abort rather than rewrite the file from a ``{}`` produced by a read
        # failure, which would delete every non-preset setting. Mirrors
        # ``GUIPreferences.save()`` hardening for the shared ``settings.json``.
        return False
    settings[PRESETS_KEY] = [preset.to_dict() for preset in presets]
    settings[PRESETS_VERSION_KEY] = PRESETS_VERSION
    return config.save_settings(path, settings)


def find_preset(name: str, presets: Sequence[Preset]) -> Optional[Preset]:
    """Return the preset named *name* from *presets*, or ``None`` when absent."""

    for preset in presets:
        if preset.name == name:
            return preset
    return None


def add_preset(presets: Sequence[Preset], preset: Preset) -> List[Preset]:
    """Return a new list with *preset* appended.

    Any existing preset that shares *preset*'s name is dropped first so a
    "Save as…" reusing a name overwrites in place rather than creating a
    duplicate the dropdown could not disambiguate.
    """

    result = [existing for existing in presets if existing.name != preset.name]
    result.append(preset)
    return result


def update_preset(presets: Sequence[Preset], name: str, preset: Preset) -> List[Preset]:
    """Return a new list with the preset named *name* replaced by *preset*.

    When *name* is absent the *preset* is appended so an "Update" on a stale
    selection still persists the current knobs rather than silently dropping
    them.
    """

    result = list(presets)
    for index, existing in enumerate(result):
        if existing.name == name:
            result[index] = preset
            return result
    result.append(preset)
    return result


def delete_preset(presets: Sequence[Preset], name: str) -> List[Preset]:
    """Return a new list with the preset named *name* removed."""

    return [existing for existing in presets if existing.name != name]


def move_preset(presets: Sequence[Preset], name: str, delta: int) -> List[Preset]:
    """Return a new list with the preset named *name* shifted by *delta* slots.

    A negative *delta* moves the preset earlier (up), a positive one later (down);
    the target index is clamped to the list bounds so moving the first preset up or
    the last one down is a no-op. An absent *name* returns the list unchanged. The
    order is shared across every surface via ``settings.json`` and also decides
    which preset is the "first" default.
    """

    result = list(presets)
    index = next((i for i, p in enumerate(result) if p.name == name), None)
    if index is None:
        return result
    new_index = max(0, min(len(result) - 1, index + delta))
    if new_index == index:
        return result
    item = result.pop(index)
    result.insert(new_index, item)
    return result


def preset_to_cli_args(preset: Preset) -> List[str]:
    """Map *preset* to the CLI flags a run should apply.

    Only the fields the (sparse) preset defines are emitted, so a preset that
    stores just a codec leaves resolution and speeds untouched. When present,
    resolution is emitted explicitly (``--no-small`` / ``--small --1080`` /
    ``--small --720`` / ``--small --480``) so the preset wins over a persisted
    ``--small`` default, followed by ``--fps``. Speeds, threshold, and codec follow using the same flag spellings as
    :func:`talks_reducer.gui.shortcut.build_shortcut_args`.
    """

    args: List[str] = []

    if preset.resolution is not None:
        small, height = resolution_to_small(preset.resolution)
        if not small:
            args.append("--no-small")
        else:
            args.extend(["--small", f"--{height}"])
    if preset.fps is not None:
        args.extend(["--fps", str(preset.fps)])

    if preset.silent_speed is not None:
        args.extend(["--silent-speed", _format_number(preset.silent_speed)])
    if preset.sounded_speed is not None:
        args.extend(["--sounded-speed", _format_number(preset.sounded_speed)])
    if preset.silent_threshold is not None:
        args.extend(["--silent-threshold", _format_number(preset.silent_threshold)])
    if preset.video_codec is not None:
        args.extend(["--video-codec", str(preset.video_codec)])

    return args


def describe_preset_fields(preset: Preset) -> List[str]:
    """Return one ``"Label: value"`` line per field *preset* actually applies.

    Sparse presets list only their present fields, so the summary doubles as a
    statement of what the preset leaves untouched. Speeds are rendered as
    ``10×`` and the codec identifier is mapped to its GUI label (``hevc`` reads
    as ``h.265``), matching the human-readable style of the Save-preset dialog
    rather than raw CLI flags.
    """

    lines: List[str] = []
    for field in PRESET_VALUE_FIELDS:
        value = getattr(preset, field)
        if value is None:
            continue
        if field in ("silent_speed", "sounded_speed"):
            rendered = f"{_format_number(value)}×"
        elif field == "silent_threshold":
            rendered = _format_number(value)
        elif field == "video_codec":
            rendered = CODEC_LABELS.get(str(value), str(value))
        else:
            rendered = str(value)
        lines.append(f"{PRESET_FIELD_LABELS[field]}: {rendered}")
    return lines


def describe_preset(preset: Preset) -> str:
    """Return the multi-line summary of *preset* shown as a hover tooltip.

    A preset with no value fields yields an explicit note rather than an empty
    string, so the tooltip never renders as a blank bubble.
    """

    lines = describe_preset_fields(preset)
    if not lines:
        return "Applies no settings"
    return "\n".join(lines)


def match_preset(
    values: Mapping[str, object], presets: Sequence[Preset]
) -> Optional[str]:
    """Reverse-match live *values* to a preset name, or ``None`` for "Custom".

    ``values`` supplies ``resolution``, ``fps`` and ``video_codec`` (compared exactly)
    plus ``silent_speed``, ``sounded_speed``, and ``silent_threshold`` (compared
    within :data:`MATCH_TOLERANCE`). A sparse preset matches when **every field
    it defines** equals the live value; the params it omits are ignored. A preset
    with no value fields never matches so it cannot hijack the "Custom" state.
    """

    for preset in presets:
        present = preset.present_fields()
        if not present:
            continue
        if "resolution" in present and preset.resolution != str(
            values.get("resolution", "")
        ):
            continue
        if "video_codec" in present and preset.video_codec != str(
            values.get("video_codec", "")
        ):
            continue
        if "fps" in present and preset.fps != str(values.get("fps", "")):
            continue

        matched = True
        for field in ("silent_speed", "sounded_speed", "silent_threshold"):
            if field not in present:
                continue
            try:
                live = float(values.get(field))
            except (TypeError, ValueError):
                matched = False
                break
            if abs(getattr(preset, field) - live) >= MATCH_TOLERANCE:
                matched = False
                break
        if matched:
            return preset.name
    return None


def get_selected_preset(config_path: Optional[Path] = None) -> Optional[str]:
    """Return the persisted ``selected_preset`` name, or ``None`` when absent."""

    path = _resolve_config_path(config_path)
    settings = config.load_settings(path)
    value = settings.get(SELECTED_PRESET_KEY)
    if isinstance(value, str) and value:
        return value
    return None


def set_selected_preset(
    name: Optional[str], config_path: Optional[Path] = None
) -> bool:
    """Persist the selected preset *name* (``None`` clears it for "Custom")."""

    path = _resolve_config_path(config_path)
    try:
        settings = config.read_settings_strict(path)
    except config.SettingsReadError:
        # Abort rather than collapse the shared ``settings.json`` to just the
        # ``selected_preset`` key when the file is transiently unreadable.
        return False
    if name:
        settings[SELECTED_PRESET_KEY] = name
    else:
        settings.pop(SELECTED_PRESET_KEY, None)
    return config.save_settings(path, settings)
