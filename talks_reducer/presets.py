"""User-named preset store shared across the GUI, Web UI, OBS dock, and CLI.

A preset is a saved bundle of processing settings authored in the desktop GUI
and applied read-only everywhere else. Presets live in the shared
``settings.json`` (see :mod:`talks_reducer.config`) under the ``presets`` key so
one canonical list appears on every surface the config file reaches.

The helpers here are UI-agnostic and unit-tested. The three seeded defaults are
persisted the first time the ``presets`` key is absent; afterward they are
ordinary, fully editable presets rather than immutable built-ins.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Mapping, Optional, Sequence

from . import config

# Storage keys within ``settings.json``.
PRESETS_KEY = "presets"
SELECTED_PRESET_KEY = "selected_preset"

# Valid resolution tri-state values.
RESOLUTIONS = ("1080p", "720p", "480p")

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
    "silent_speed",
    "sounded_speed",
    "silent_threshold",
    "video_codec",
)


@dataclass(frozen=True)
class Preset:
    """A named bundle of processing settings applied across every surface.

    Presets are **sparse**: every value field is optional and a field left as
    ``None`` is not stored, not applied, and ignored when reverse-matching, so a
    preset controls only the params it was saved with. ``resolution`` is an
    explicit tri-state (``"1080p"``, ``"720p"``, or ``"480p"``) so a 1080p preset
    can force ``--no-small`` rather than inheriting a persisted ``--small``
    default.
    """

    name: str
    resolution: Optional[str] = None
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


# The three seeded defaults written on first run when ``presets`` is absent.
DEFAULT_PRESETS: List[Preset] = [
    Preset(
        name="720p 10x speedup H.264",
        resolution="720p",
        silent_speed=10.0,
        sounded_speed=1.0,
        silent_threshold=0.01,
        video_codec="h264",
    ),
    Preset(
        name="480p 10x speedup H.265",
        resolution="480p",
        silent_speed=10.0,
        sounded_speed=1.0,
        silent_threshold=0.01,
        video_codec="hevc",
    ),
    Preset(
        name="720p no speedup H.264",
        resolution="720p",
        silent_speed=1.0,
        sounded_speed=1.0,
        silent_threshold=0.01,
        video_codec="h264",
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


def load_presets(config_path: Optional[Path] = None) -> List[Preset]:
    """Return the stored presets, seeding :data:`DEFAULT_PRESETS` on first run.

    When the ``presets`` key is absent the defaults are persisted to
    ``settings.json`` and returned. An explicitly empty list (the user deleted
    every preset) is preserved and returned as ``[]``.
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


def preset_to_cli_args(preset: Preset) -> List[str]:
    """Map *preset* to the CLI flags a run should apply.

    Only the fields the (sparse) preset defines are emitted, so a preset that
    stores just a codec leaves resolution and speeds untouched. When present,
    resolution is emitted explicitly (``--no-small`` / ``--small --720`` /
    ``--small --480``) so the preset wins over a persisted ``--small`` default.
    Speeds, threshold, and codec follow using the same flag spellings as
    :func:`talks_reducer.gui.shortcut.build_shortcut_args`.
    """

    args: List[str] = []

    if preset.resolution is not None:
        if preset.resolution == "1080p":
            args.append("--no-small")
        elif preset.resolution == "480p":
            args.extend(["--small", "--480"])
        else:  # "720p" (and any unexpected value) map to the 720p small preset.
            args.extend(["--small", "--720"])

    if preset.silent_speed is not None:
        args.extend(["--silent-speed", _format_number(preset.silent_speed)])
    if preset.sounded_speed is not None:
        args.extend(["--sounded-speed", _format_number(preset.sounded_speed)])
    if preset.silent_threshold is not None:
        args.extend(["--silent-threshold", _format_number(preset.silent_threshold)])
    if preset.video_codec is not None:
        args.extend(["--video-codec", str(preset.video_codec)])

    return args


def match_preset(
    values: Mapping[str, object], presets: Sequence[Preset]
) -> Optional[str]:
    """Reverse-match live *values* to a preset name, or ``None`` for "Custom".

    ``values`` supplies ``resolution`` and ``video_codec`` (compared exactly)
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
