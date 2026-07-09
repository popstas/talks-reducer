# Presets across Simple mode, Web UI, OBS dock, and CLI

## Overview

Add **user-named presets**: saved bundles of processing settings a user creates
once (in the desktop GUI, Advanced mode) and applies read-only everywhere else —
Simple mode, the Web UI, the OBS dock, and the CLI. Presets live in the shared
`settings.json` so one list appears on every surface the config file reaches.

This generalizes the existing `.lnk` "Create link" mechanism into a persistent,
named, cross-surface store. Full design:
`docs/superpowers/specs/2026-07-09-presets-design.md`.

**Key benefits:** one canonical preset list; minimal Simple mode (preset
dropdown + two checkboxes); no new processing path — a selected preset just fans
its fields onto each surface's existing controls / CLI flags, still funneling
through `ProcessingOptions`.

## Context (from discovery)

Files/components involved:

- `talks_reducer/gui/preferences.py` — `GUIPreferences`, `determine_config_path()`,
  `load_settings()`; owns `settings.json` at
  `<config-base>/talks-reducer/settings.json`.
- `talks_reducer/models.py` — `ProcessingOptions` (canonical 1:1 knob set).
- `talks_reducer/cli.py` — `_build_parser()`, `main()` dispatch.
- `talks_reducer/gui/layout.py` — `BASIC_PRESETS`, `PRESET_LABELS`,
  `CODEC_LABELS`, `get_current_preset()`, `apply_basic_preset()`,
  `apply_simple_mode()`, `simple_speedup_frame`/`simple_codec_frame`.
- `talks_reducer/gui/app.py` — `simple_preset_var`, `simple_codec_var`,
  var/trace wiring, `_sync_simple_preset`/`_sync_simple_codec`.
- `talks_reducer/gui/shortcut.py` — `build_shortcut_args()` (the field set and
  flag spellings a preset mirrors), the "Create lnk" modal pattern to reuse.
- `talks_reducer/server.py` — `build_interface()` Gradio Blocks (Web UI).
- `talks_reducer/dock_server.py` — `build_args()`, `handle_process()`, HTTP
  routes; `talks_reducer/resources/dock.html` — OBS dock UI + `localStorage`.

Related patterns found:

- Pure helpers are unit-tested (`build_shortcut_args`); Tk dialogs / HTML
  verified manually.
- Preferences: keys created on first use via `get`/`update`; no schema.
- Per-module test files exist: `test_cli.py`, `test_dock_server.py`,
  `test_gui_layout.py`, `test_gui_preferences.py`, `test_server.py`,
  `test_models.py`.

Dependencies identified: `argparse`, Tk/ttk, Gradio, stdlib `http.server`.

## Development Approach

- **Testing approach**: Regular (implement, then unit tests in the same task).
- Complete each task fully before the next; small, focused changes.
- **CRITICAL: every task MUST include new/updated tests** for its code changes
  (success + error/edge cases), listed as separate checklist items.
- **CRITICAL: all tests must pass before starting the next task.**
- **CRITICAL: update this plan file if scope changes during implementation.**
- Run `black` + `isort` and the test suite after each change. Maintain backward
  compatibility (existing `settings.json` files must keep working).

## Testing Strategy

- **Unit tests**: required every task. New `tests/test_presets.py` for the store;
  extend `test_cli.py`, `test_dock_server.py`, `test_gui_layout.py`,
  `test_server.py`, `test_gui_preferences.py` for surface wiring.
- **E2E tests**: repo has no browser-based e2e harness. GUI Tk dialogs, the
  Gradio dropdown behavior, and the OBS dock HTML are verified manually (see
  Post-Completion); pure logic (mapping, precedence, seeding, endpoint payloads)
  is unit-tested.

## Progress Tracking

- Mark completed items `[x]` immediately.
- New tasks: `➕` prefix. Blockers: `⚠️` prefix.
- Keep the plan in sync with actual work.

## What Goes Where

- **Implementation Steps** (`[ ]`): code, unit tests, doc updates in this repo.
- **Post-Completion** (no checkboxes): manual GUI/Web/dock verification.

## Implementation Steps

### Task 1: Extract shared config module
- [x] create `talks_reducer/config.py` with `determine_config_path()`,
      `load_settings()`, and a new `save_settings(data)` moved/lifted from
      `gui/preferences.py` (no behavior change to path resolution)
- [x] update `gui/preferences.py` to import these from `talks_reducer.config`
      (re-export for any existing importers to preserve backward compatibility)
- [x] write tests in `tests/test_config.py` for config path resolution per
      platform-base and load/save round-trip (success + malformed-JSON returns
      `{}`)
- [x] confirm `tests/test_gui_preferences.py` still passes unchanged
- [x] run `black`, `isort`, and the test suite — must pass before Task 2

### Task 2: Preset store and model (`talks_reducer/presets.py`)
- [x] add `Preset` dataclass: `name: str`, `resolution: str`
      (`"1080p"|"720p"|"480p"`), `silent_speed`, `sounded_speed`,
      `silent_threshold`, `video_codec`
- [x] add `DEFAULT_PRESETS`: "720p 10x speedup H.264", "480p 10x speedup H.265",
      "720p no speedup H.264" (values per the design spec)
- [x] implement `load_presets()` (reads the `presets` key via
      `talks_reducer.config`; **seeds and persists `DEFAULT_PRESETS` when the key
      is absent**; returns `[]` only when the user emptied the list) and
      `save_presets(presets)`
- [x] implement `preset_to_cli_args(preset) -> list[str]` with the resolution
      tri-state mapping (`1080p → --no-small`, `720p → --small --720`,
      `480p → --small --480`) plus speed/threshold/codec flags, reusing the flag
      spellings from `gui/shortcut.build_shortcut_args`
- [x] implement `match_preset(values, presets) -> str | None` (reverse-match with
      the `1e-9` float tolerance from `layout.get_current_preset`)
- [x] add `get_selected_preset()` / `set_selected_preset(name)` for the
      `selected_preset` key
- [x] write `tests/test_presets.py`: first-run seeding, save/load round-trip,
      `preset_to_cli_args` per resolution (incl. `--no-small`), `match_preset`
      exact-match + `None` ("Custom"), empty-list persistence
- [x] run `black`, `isort`, tests — must pass before Task 3

### Task 3: CLI `--preset` / `--list-presets`
- [x] add `--preset NAME` and `--list-presets` to `cli._build_parser()`
- [x] in `main()`: `--list-presets` prints names and exits; `--preset NAME`
      loads the preset and applies its fields as the base config **before**
      explicit flags are applied, so explicit flags override (precedence:
      explicit flag > preset > default)
- [x] unknown `--preset NAME` errors clearly, listing valid names
- [x] write `tests/test_cli.py` cases: `--preset` sets each field; explicit flag
      overrides a preset value; `--list-presets` output; unknown-preset error
- [x] run `black`, `isort`, tests — must pass before Task 4

### Task 4: Simple mode preset dropdown (GUI)
- [x] replace `simple_speedup_frame` + `simple_codec_frame` with a single
      `Preset` dropdown (line 1) in `gui/layout.py`; keep `Simple mode` +
      `Open after convert` checkboxes (line 2)
- [x] on selection, apply the preset to the underlying GUI vars (resolution →
      `small_var`/`small_480_var`, speeds, threshold, codec) via
      `apply_preset_to_gui`
- [x] hide the preset selector entirely when `load_presets()` returns `[]`
- [x] remove the hardcoded `PRESET_LABELS`/`CODEC_LABELS` simple-mode tables and
      the `app.py` sync wiring (`_sync_simple_preset`/`_sync_simple_codec` +
      traces); persist the chosen preset via `selected_preset`
      (`get_selected_preset` seeds `simple_preset_var`, `set_selected_preset` on
      selection). `BASIC_PRESETS` is retained because the Advanced-mode "Basic
      options" quick-preset link buttons still use it (out of scope for removal).
- [x] write `tests/test_gui_layout.py` cases: applying a preset sets the vars
      (720p/480p/1080p + slider-updater path); empty-preset list hides the
      selector; selection persists via `set_selected_preset`
- [x] run `black`, `isort`, tests — must pass before Task 5

### Task 5: Advanced mode preset management strip (GUI)
- [x] add an inline strip above the Advanced knobs: `Preset` dropdown +
      **Save as… / Update / Delete** buttons
- [x] wire the dropdown to `match_preset` so editing any knob flips it to
      **"Custom"**
- [x] **Save as…** opens a name-entry modal (reuse the `gui/shortcut.py`
      "Create lnk" modal pattern) and appends a preset from the current knobs;
      **Update** overwrites the selected preset; **Delete** removes it — all via
      `presets.save_presets`, refreshing every dropdown (Simple + Advanced)
- [x] extract the pure preset-mutation helpers (add/update/delete a preset in a
      list) so they are unit-testable without Tk
- [x] write tests: `tests/test_presets.py` for the mutation helpers;
      `tests/test_gui_layout.py` (or `test_gui_app.py`) for the "Custom" flip and
      dropdown refresh
- [x] run `black`, `isort`, tests — must pass before Task 6

### Task 6: Web UI preset dropdown (Gradio)
- [x] add a `Preset` dropdown near the top of `server.build_interface`,
      populated from `load_presets()` at build time
- [x] add a change handler that sets the resolution / speedup / codec / threshold
      controls to the selected preset's values
- [x] write `tests/test_server.py` cases: dropdown is populated from the store;
      the change handler maps a preset to the expected control values (incl. the
      1080p/no-small case)
- [x] run `black`, `isort`, tests — must pass before Task 7

### Task 7: OBS dock presets
- [ ] add `GET /presets` to `dock_server.py` returning the preset list from
      `load_presets()` (JSON)
- [ ] in `build_args()`: when the `POST /process` payload carries a `preset`
      name, emit `--preset NAME` (full-fidelity) instead of the
      resolution/speed/codec flags; keep the current mapping when no preset is
      sent
- [ ] update `resources/dock.html`: fetch `/presets`; when presets exist, show a
      `Preset` dropdown as the primary control and **move** the
      resolution/speed/codec selects into the settings panel; when none exist,
      keep those selects in the main UI as today; persist the choice in a new
      `obsDock.preset` `localStorage` key
- [ ] write `tests/test_dock_server.py` cases: `GET /presets` payload; `build_args`
      emits `--preset NAME` for a preset payload and the legacy flags otherwise
- [ ] run `black`, `isort`, tests — must pass before Task 8

### Task 8: Verify acceptance criteria
- [ ] verify each surface applies a preset and the resolution tri-state
      (incl. 1080p `--no-small`) end-to-end against `ProcessingOptions`
- [ ] verify CLI precedence (explicit flag > preset > default) and backward
      compatibility with a pre-existing `settings.json` (no `presets` key → seeds)
- [ ] run the full unit-test suite
- [ ] run `black --check`, `isort --check`, and any repo linter — fix all issues
- [ ] verify coverage of the new `presets.py` / `config.py` meets project
      standard

### Task 9: [Final] Update documentation
- [ ] update `README.md` (preset feature + `--preset`/`--list-presets` CLI)
- [ ] update `docs/cli.md`, `docs/gui.md`, `docs/server.md`, `docs/obs-dock.md`
      for the new preset controls per surface
- [ ] update the GUI section of `CLAUDE.md` (Simple mode dropdown replacement,
      Advanced management strip, OBS dock settings-panel move)

## Technical Details

- **Storage keys** (`settings.json`): `presets` (list of preset dicts),
  `selected_preset` (name or absent).
- **Preset dict shape:** `{name, resolution, silent_speed, sounded_speed,
  silent_threshold, video_codec}`.
- **Resolution mapping:** `1080p` → `small=False` / `--no-small`; `720p` →
  `small=True, small_480=False` / `--small --720`; `480p` → `small=True,
  small_480=True` / `--small --480`. Always applied explicitly so a preset wins
  over a persisted default.
- **Precedence (CLI):** explicit flag > preset > default.
- **Layering:** `config.py` holds the settings-file path/load/save so `cli.py`,
  `server.py`, and `dock_server.py` never import from `gui/`.

## Post-Completion
*Items requiring manual intervention — no checkboxes, informational only.*

**Manual verification:**
- Desktop GUI: Simple mode preset dropdown apply + empty-state hiding; Advanced
  Save as… / Update / Delete and the "Custom" flip; selection persists across
  relaunch.
- Web UI: selecting a preset updates the resolution/speed/codec/threshold
  controls; a run uses those values.
- OBS dock: `/presets` populates the dropdown; the resolution/speed/codec selects
  move into the settings panel when presets exist and return to the main UI when
  the list is emptied; a preset run passes `--preset NAME` through to the CLI.
- Cross-machine: a preset authored on the host GUI appears in the Web UI / dock
  served from that host.
