# Presets across Simple mode, Web UI, OBS dock, and CLI

**Date:** 2026-07-09
**Status:** Approved design, ready for implementation planning
**TODO item:** "Add presets across Simple mode, Web UI, OBS dock, and CLI (e.g. create a preset like a shortcut/LNK)"

## Summary

Add **user-named presets**: saved bundles of processing settings that a user
creates once and applies on every surface. A preset is authored **only in the
desktop GUI (Advanced mode)** and consumed (apply-only) in Simple mode, the Web
UI, the OBS dock, and the CLI. Presets are stored in the shared `settings.json`
so a single list appears everywhere the config file is reachable.

This generalizes the existing `.lnk` "Create link" mechanism (which serializes a
config as CLI flags) into a persistent, named, cross-surface store.

## Goals

- One canonical list of named presets, stored once, applied everywhere.
- Free-text preset names.
- Ship three seeded defaults that a user can edit or remove.
- Keep Simple mode minimal: a preset dropdown plus two checkboxes.
- No new processing path — a selected preset just fans its fields onto each
  surface's existing controls / CLI flags, which still funnel through
  `ProcessingOptions`.

## Non-goals

- Authoring presets outside the desktop GUI (Web UI / OBS dock / CLI are
  apply-only).
- Storing per-run values in a preset (input/output paths, temp folder, cut
  start/end, transport/URL).
- Exposing rarely-touched machine knobs (`optimize`, `keyframe_interval`,
  `sample_rate`, `frame_margin`) in a preset — they keep their current defaults.

## Data model

A preset stores exactly the fields the existing "Create link" dialog captures,
with resolution promoted to an explicit tri-state so a 1080p preset can force
`--no-small`:

| Field | Type | Notes |
|---|---|---|
| `name` | str | Free-text, unique (the dropdown label and CLI key). |
| `resolution` | enum `"1080p" \| "720p" \| "480p"` | Explicit — includes the `no_small` (1080p) case. |
| `silent_speed` | float | The "speedup". |
| `sounded_speed` | float | |
| `silent_threshold` | float | |
| `video_codec` | str | One of `h264 / hevc / av1 / mp3`. |

**Resolution mapping** (applied explicitly on every surface, never omitted):

| `resolution` | GUI vars | CLI flags |
|---|---|---|
| `1080p` | `small=False` | `--no-small` |
| `720p` | `small=True`, `small_480=False` | `--small --720` |
| `480p` | `small=True`, `small_480=True` | `--small --480` |

Applying a preset always emits the resolution flags explicitly so the preset
wins over a persisted `--small`/`--no-small` GUI default (the seeded-GUI flag
resolution described in `gui/shortcut.py`).

### Seeded defaults

Written to `settings.json` the first time the `presets` key is absent. Fully
editable/removable afterward — they are ordinary presets, not immutable
built-ins.

1. **720p 10x speedup H.264** — `resolution=720p, silent_speed=10, sounded_speed=1, silent_threshold=0.01, video_codec=h264`
2. **480p 10x speedup H.265** — `resolution=480p, silent_speed=10, sounded_speed=1, silent_threshold=0.01, video_codec=hevc`
3. **720p no speedup H.264** — `resolution=720p, silent_speed=1, sounded_speed=1, silent_threshold=0.01, video_codec=h264`

## Architecture

### New module: `talks_reducer/presets.py`

The canonical, UI-agnostic store and the single source of truth:

- `Preset` dataclass (the fields above).
- `DEFAULT_PRESETS: list[Preset]` (the three seeded defaults).
- `load_presets() -> list[Preset]` — reads the `presets` key; **seeds and
  persists `DEFAULT_PRESETS` when the key is absent**; returns `[]` only if the
  user has deleted them all.
- `save_presets(presets: list[Preset]) -> bool`.
- Mapping helpers:
  - `preset_to_options(preset, base) -> ProcessingOptions` (or field overrides).
  - `preset_to_cli_args(preset) -> list[str]`.
  - `apply_preset_to_gui(preset, gui)` — sets the Tk vars.
  - `match_preset(values, presets) -> str | None` — reverse-match current
    values to a preset name, else `None` ("Custom"), with the existing
    `1e-9` float tolerance from `layout.get_current_preset()`.

### Shared config module: `talks_reducer/config.py`

To let non-GUI callers (CLI, servers) read/write the same `settings.json`
without importing `gui/`, extract from `gui/preferences.py`:

- `determine_config_path()`
- `load_settings()`
- `save_settings(data)`

`gui/preferences.py` re-imports these (no behavior change); `presets.py` uses
them. One settings file, one path-resolution rule.

Storage keys added to `settings.json`:

- `presets` — list of preset dicts.
- `selected_preset` — name of the currently selected preset (persists the
  dropdown selection), or absent/`null` for "Custom".

## Surface behavior

### Simple mode (GUI) — replaces today's speed + codec dropdowns

Layout:

- **Line 1:** `Preset` dropdown.
- **Line 2:** `Simple mode` + `Open after convert` checkboxes.
- Plus the drop zone and Convert button. Nothing else.

Behavior:

- Selecting a preset applies its fields to the underlying GUI vars via
  `apply_preset_to_gui`.
- **No presets → the selector is hidden entirely**; Convert uses the last-used
  settings.
- Removes the current `simple_speedup_frame` / `simple_codec_frame` dropdowns
  and the hardcoded `BASIC_PRESETS` table from `layout.py`.

### Advanced mode (GUI) — the only authoring surface

An inline strip above the existing knobs:

- `Preset` dropdown + **Save as… / Update / Delete** buttons.
- Editing any knob flips the dropdown to **"Custom"** (via `match_preset`).
- **Save as…** prompts for a name and captures the current knobs into a new
  preset (dialog mirrors the existing "Create link" modal pattern).
- **Update** overwrites the selected preset with the current knobs.
- **Delete** removes the selected preset.
- All three persist through `presets.save_presets` and refresh every dropdown.

### CLI

- `--preset NAME` loads the named preset as the base config; **explicit flags
  override it**. Precedence: explicit flag > preset > default.
- `--list-presets` prints the available preset names and exits.
- Unknown `--preset NAME` is a clear error listing valid names.

### Web UI (Gradio) — apply-only

- A `Preset` dropdown near the top of `build_interface`, populated from
  `load_presets()` at build time.
- A change handler sets the resolution / speedup / codec / threshold controls to
  the preset's values.
- The server reads `settings.json` on the host machine (presets are whatever the
  host has).

### OBS dock — apply-only

- New `GET /presets` endpoint on `dock_server.py` returns the preset list.
- **When presets exist:** the `Preset` dropdown becomes the primary control, and
  the existing resolution / speed / codec selects **move into the dock's
  settings panel** (next to OBS URL / password / exe). Selecting a preset sends
  its **name** in the `POST /process` payload; `build_args` emits
  `--preset NAME`, so full-fidelity settings (including custom thresholds) apply
  rather than being flattened to the dock's three radios.
- **When no presets exist:** the resolution / speed / codec selects stay in the
  main dock UI exactly as today, and `build_args` behaves as it does now.
- Preset choice persists in `localStorage` alongside the existing `obsDock.*`
  keys.

## Data flow

```
                 settings.json  (presets, selected_preset)
                        ▲  ▲
        author/apply    │  │   read
   ┌────────────────────┘  └───────────────┬──────────────┬───────────┐
   │                                        │              │           │
Desktop GUI                               CLI          Gradio       dock_server
(Simple: apply)                        --preset       server        GET /presets
(Advanced: author + apply)                                            │
                                                                 dock.html
                                                              POST /process
                                                              (--preset NAME)
```

Every surface applies a preset by fanning its fields onto that surface's
existing controls or CLI flags; the actual processing still flows through
`ProcessingOptions` / the current pipeline. No new execution path.

## Testing

Unit tests (pure helpers, matching the repo's existing `build_shortcut_args`
style):

- `load_presets` seeds `DEFAULT_PRESETS` on first run and round-trips through
  `save_presets`.
- `preset_to_cli_args` emits the correct resolution flags for each tri-state,
  including `--no-small` for 1080p.
- `--preset` precedence: explicit CLI flags override preset values; preset
  overrides defaults.
- `match_preset` returns the preset name on an exact match (within tolerance)
  and `None` ("Custom") otherwise.

Manual verification:

- GUI Simple dropdown apply + empty-state hiding; Advanced Save as… / Update /
  Delete and the "Custom" flip.
- Web UI dropdown applies to the controls.
- OBS dock preset fetch, the settings-panel move when presets are present, and
  the `--preset NAME` pass-through.

## Open decisions resolved during design

- Preset concept: **user-named saved configs** (not fixed built-ins, not
  per-launcher).
- Fields: **the "Create link" dialog set**, with resolution as an explicit
  tri-state (`no_small` storable).
- Naming: **free-text**.
- Authoring: **desktop GUI only**; all other surfaces apply-only.
- Simple mode: **preset dropdown + two checkboxes**, selector hidden when empty.
- Advanced management: **inline strip** (dropdown + Save as… / Update / Delete).
- OBS dock: **manual selects move to settings when presets are present.**
