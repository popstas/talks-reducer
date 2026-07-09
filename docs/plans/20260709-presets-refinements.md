# Presets refinements (post-review iteration)

## Overview

Second iteration on the cross-surface presets feature (PR #152, branch
`presets-cross-surface`), from hands-on review of the running build. Covers one
data-model change (**sparse presets** — a preset stores only selected params)
and six UX refinements across the desktop GUI Simple mode and the OBS dock.

Builds directly on `docs/plans/completed/20260709-presets-cross-surface.md` and
the design spec `docs/superpowers/specs/2026-07-09-presets-design.md`.

**Refinements requested:**

1. Remember the last-selected preset in the GUI, Web UI, and OBS dock.
2. Default to the first preset when nothing is selected.
3. Move the "Open output" checkbox to line 1 (right of the preset dropdown).
4. Save/Update opens a dialog with per-param checkboxes like "Create link";
   a preset stores **only the checked params** (sparse presets).
5. OBS dock: reduce corner rounding to match OBS's native controls (the "Fade"
   Scene Transitions dropdown).
6. OBS dock: replace the "Settings" text with a ⚙️ gear.
7. OBS dock: cap the preset dropdown width so the select + "Process" button +
   settings gear fit on one line.

## Context (from discovery)

- `talks_reducer/presets.py` — `Preset` dataclass (currently all fields
  required), `load_presets`/`save_presets`, `match_preset`, `preset_to_cli_args`,
  `find_preset`, `add_preset`/`update_preset`/`delete_preset`,
  `get_selected_preset`/`set_selected_preset`.
- `talks_reducer/gui/preset_dialog.py` — name-only Save dialog (mirrors the
  "Create lnk" modal); the create-link checkbox pattern lives in
  `gui/shortcut.py` (`build_shortcut_args`, `_dialog_initial_selections`).
- `talks_reducer/gui/layout.py` — `apply_preset_to_gui` (L76), Simple-mode preset
  frame (`simple_preset_frame`, `simple_preset_combo` around L449), the
  checkbox_frame rows, `preset_from_gui`, `_refresh_preset_widgets`,
  save/update/delete handlers (L288/L304/L319), `match_preset` "Custom" wiring
  (L191).
- `talks_reducer/server.py` — Gradio preset dropdown + change handler.
- `talks_reducer/resources/dock.html` — `#presetControls` (select L308 +
  `presetProcessBtn` L309), `<summary>Settings</summary>` (L331),
  `manualSettingsSlot` (L332), `border-radius` at L61 (99px) / L80/181/210 (10px)
  / L191 (3px), `obsDock.preset` persistence, `PRESETS_URL` fetch (L384).
- Tests: `test_presets.py`, `test_gui_layout.py`, `test_server.py`,
  `test_dock_server.py`. Dock HTML/JS is verified manually.

## Development Approach

- **Testing approach**: Regular (implement, then unit tests in the same task).
- Small, focused changes; complete each task fully before the next.
- **CRITICAL: every task with code changes MUST add/update tests** (success +
  error/edge), listed as separate checklist items.
- **CRITICAL: all tests pass before the next task.** Run `black` + `isort`.
- **CRITICAL: update this plan if scope changes.**
- Maintain backward compatibility: existing full presets in `settings.json` must
  keep loading and applying unchanged.

## Testing Strategy

- **Unit tests** required per task: sparse-preset serialize/apply/match/CLI in
  `test_presets.py`; GUI default-first/remember + layout in `test_gui_layout.py`;
  Web dropdown default/persist in `test_server.py`; dock `/presets` + `build_args`
  in `test_dock_server.py`.
- **Manual only** (no e2e harness): the Tk dialogs, Gradio dropdown behavior, and
  the dock HTML/CSS (rounding, gear, single-line width). Captured in
  Post-Completion.

## Progress Tracking

- Mark items `[x]` immediately. New tasks `➕`, blockers `⚠️`. Keep in sync.

## What Goes Where

- **Implementation Steps** (`[ ]`): code, unit tests, docs in this repo.
- **Post-Completion** (no checkboxes): manual GUI/Web/dock verification.

## Implementation Steps

### Task 1: Sparse preset data model (`talks_reducer/presets.py`)
- [ ] make `Preset` value fields optional (`resolution`, `silent_speed`,
      `sounded_speed`, `silent_threshold`, `video_codec` default `None`); `name`
      stays required
- [ ] serialize only non-`None` fields in `save_presets`; `load_presets` tolerates
      missing keys (absent → `None`); keep the three seeded defaults fully
      populated
- [ ] update `preset_to_cli_args` to emit flags only for present fields (and
      resolution only when set)
- [ ] update `match_preset` so a preset matches when **every present field** equals
      the current value (fields it doesn't define are ignored)
- [ ] add a `preset_fields_present(preset) -> set[str]` helper for the dialog/apply
- [ ] update `test_presets.py`: sparse round-trip (only checked fields stored),
      apply/CLI/match with partial presets, full-preset backward compatibility
- [ ] run `black`, `isort`, tests — must pass before Task 2

### Task 2: Param-selection Save/Update dialog (sparse capture)
- [ ] extend `gui/preset_dialog.py` (or add a helper) to show a name entry **plus**
      per-param checkboxes (resolution, silent speed, sounded speed, threshold,
      codec) mirroring the "Create link" dialog, returning `(name, selected_fields)`
- [ ] add a pure builder `preset_from_gui_selection(gui, name, selected_fields)`
      in `layout.py`/`presets.py` that captures only the checked fields into a
      sparse `Preset`
- [ ] wire **Save as…** and **Update** (layout.py L288/L304) to open the dialog;
      Update pre-fills the name and pre-checks the fields the existing preset
      defines
- [ ] apply-side: confirm `apply_preset_to_gui` only sets present fields (leaves
      others untouched)
- [ ] tests for `preset_from_gui_selection` (checked subset only) and the
      apply-only-present behavior; keep the pure builder Tk-free for unit testing
- [ ] run `black`, `isort`, tests — must pass before Task 3

### Task 3: GUI — default first preset + remember last selection
- [ ] on GUI init, restore `get_selected_preset()`; if unset or not found, select
      and apply the **first** preset in the list (when the list is non-empty)
- [ ] ensure both Simple and Advanced dropdowns seed from that value and persist
      changes via `set_selected_preset`
- [ ] tests in `test_gui_layout.py`: default-to-first when no saved selection;
      restore a saved selection; empty list still hides the selector
- [ ] run `black`, `isort`, tests — must pass before Task 4

### Task 4: Simple-mode layout — Open output on line 1 right
- [ ] rearrange the Simple-mode rows in `layout.py`: line 1 = preset dropdown
      (left) + "Open output" checkbox (right); line 2 = "Simple mode" checkbox
- [ ] keep the empty-preset case tidy (checkbox still placed when the selector is
      hidden)
- [ ] tests/assertions for the widget arrangement where feasible (grid row/column),
      otherwise note manual verification
- [ ] run `black`, `isort`, tests — must pass before Task 5

### Task 5: Web UI — default first preset + remember last
- [ ] `server.py`: the preset dropdown defaults to `get_selected_preset()`, else
      the first preset; the change handler persists the choice via
      `set_selected_preset`
- [ ] tests in `test_server.py`: default value resolution (saved → first → none)
      and that selecting persists
- [ ] run `black`, `isort`, tests — must pass before Task 6

### Task 6: OBS dock — remember last + default first
- [ ] `dock.html`: on load, restore `obsDock.preset`; if unset/invalid, default to
      the first preset from `/presets`; persist on change; keep the Process button
      enabled state correct
- [ ] tests in `test_dock_server.py` for any server-side support needed (e.g.
      `/presets` ordering); JS default/persist verified manually
- [ ] run `black`, `isort`, tests — must pass before Task 7

### Task 7: OBS dock — restyle to match OBS + single-line layout
- [ ] reduce corner rounding on the dock controls to match OBS native widgets
      (square-ish, ~2–4px; drop the 99px/10px radii on `#presetControls`,
      select, and buttons)
- [ ] replace the `<summary>Settings</summary>` text with a ⚙️ gear (accessible
      label retained)
- [ ] cap the preset `<select>` width (flex layout / `max-width`) so
      select + "Process" + gear fit on one line without wrapping
- [ ] manual verification note (HTML/CSS; no unit test) — see Post-Completion
- [ ] run `black`, `isort`, and the suite — must pass before Task 8

### Task 8: Verify acceptance criteria
- [ ] verify sparse presets end-to-end (GUI apply leaves unset fields alone; CLI
      `--preset` emits only present flags; Web/dock apply only present fields)
- [ ] verify default-first + remember-last on all three surfaces
- [ ] verify backward compatibility with pre-existing full presets in settings.json
- [ ] run the full unit suite; `black --check`, `isort --check-only`; fix all
- [ ] verify coverage of changed `presets.py` logic

### Task 9: [Final] Update documentation
- [ ] update `docs/gui.md` (Simple-mode line-1 Open output, Save/Update param
      dialog, default-first/remember), `docs/obs-dock.md` (restyle, gear,
      remember/default), `README.md` if needed
- [ ] update `CLAUDE.md` GUI section for sparse presets + layout changes

## Technical Details

- **Sparse preset dict**: only set fields are persisted; absent keys mean "don't
  touch". Apply/CLI/match all skip absent fields. Seeded defaults remain full.
- **Selection precedence** (all surfaces): saved `selected_preset` → first preset
  → none (selector hidden when list empty).
- **Dock single-line**: `#presetControls` as a flex row; the select gets
  `flex: 1 1 auto; min-width: 0` and a `max-width`; Process + ⚙️ are
  `flex: 0 0 auto`.

## Post-Completion
*Manual verification — no checkboxes.*

- GUI: last preset restored on relaunch; first preset auto-selected on a fresh
  profile; Open output sits on line 1 right; Save/Update dialog shows param
  checkboxes and stores only checked ones; applying a sparse preset leaves other
  knobs untouched.
- Web UI: dropdown reopens on the last-used preset; selecting persists.
- OBS dock: rounding matches OBS "Fade" controls; ⚙️ replaces "Settings"; the
  select + Process + gear sit on one line at typical dock widths; last preset
  restored, first preset defaulted on first use.
