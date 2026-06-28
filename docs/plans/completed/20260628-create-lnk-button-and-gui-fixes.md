# GUI: Create lnk shortcut button and two layout fixes

## Overview

Add a Windows-only **Create lnk** button to the desktop GUI that writes a `.lnk`
shortcut to the user's Desktop, pre-seeded with the CLI flags selected in a
popup dialog. The shortcut acts as a drop-target: dragging a video onto it
launches the seeded GUI (the existing `_parse_seeded_launch` path) and
auto-converts the file with the chosen presets. Alongside this feature, fix two
GUI defects: seeded launch flags (e.g. `--silent-speed 10`) move the slider but
leave the value label showing the previous value, and the server URL field is
vertically misaligned with the **Discover** button.

## Context

- Impacted modules: `talks_reducer/gui/layout.py` (button + slider labels +
  server-row alignment), `talks_reducer/gui/app.py` (argument values, dialog
  handler, seeded-value application), a new `talks_reducer/gui/shortcut.py`
  module (dialog + pure arg/filename helpers + `.lnk` creation), and
  `README.md`.
- The dialog mirrors the existing modal pattern in `talks_reducer/gui/discovery.py`
  (`transient`, `grab_set`, `WM_DELETE_WINDOW`, `grab_release` + `destroy`).
- CLI flag names are defined in `talks_reducer/cli.py`: `--small`, `--480` /
  `--720` (mutually exclusive, both map to `small_480`), `--silent-speed`,
  `--sounded-speed`, `--silent-threshold`, `--video-codec h264|hevc|av1`
  (default `hevc`).
- No `.lnk`-writing dependency exists; `pywin32` is not used anywhere, so the
  shortcut is written via a one-shot PowerShell `WScript.Shell` call.
- The Create lnk feature is Windows-only and is developed on Linux: pure helpers
  get unit tests; the Tk dialog and PowerShell `.lnk` write are verified
  manually on Windows (see Post-Completion).
- Adopted from `docs/TODO.md`.

## Development Approach

- Testing approach: regular
- Complete each task fully before moving to the next
- Update this plan when scope changes during implementation

## Testing Strategy

- Unit tests required for the pure, platform-independent logic
  (`build_shortcut_args`, `shortcut_filename`)
- The Tk dialog and PowerShell `.lnk` creation are not unit-tested (consistent
  with the existing GUI test scope) and are checked manually on Windows
- Run project tests after each Task before proceeding

## Technical Details

- **Shortcut target resolution:** frozen build
  (`getattr(sys, "frozen", False)`) → `TargetPath = sys.executable`
  (talks-reducer.exe), `Arguments = <flags>`; dev run →
  `TargetPath = sys.executable` (pythonw), `Arguments = -m talks_reducer
  <flags>`. `WorkingDirectory` is the executable directory; `IconLocation` is the
  executable.
- **build_shortcut_args(selections, gui_values) -> list[str]:** maps checked
  options to flags using live GUI values — `--small`, `--720`/`--480` (only when
  Small is included), `--silent-speed`, `--sounded-speed`, `--silent-threshold`,
  `--video-codec <codec>`. Numeric values are trimmed of trailing zeros (`10`,
  not `10.0`). Checking 720 or 480 implies Small; 720 and 480 are mutually
  exclusive.
- **shortcut_filename(args) -> str:** derives a Desktop filename from the args
  (e.g. `Talks Reducer (small 720 silent-speed 10).lnk`), sanitized of illegal
  Windows filename characters, falling back to `Talks Reducer.lnk` when no args.
- **Dialog defaults:** a checkbox is pre-checked when its option is active in the
  current GUI — Small from `small_var`; 720/480 reflect `small_480_var` (relevant
  only when Small is on); speeds/threshold when the value differs from the
  pipeline default; Codec when `video_codec_var` is not `hevc`.
- **Seeded slider labels:** the value label beside each slider is refreshed by
  the slider's `command` callback, which does not fire when the value is set
  programmatically during seeding. After applying seeded values the formatting
  callback must be invoked for silent speed, sounded speed, and silent
  threshold.
- **Server row alignment:** the server URL entry and **Discover** button share a
  grid row; align them on the same center/baseline via consistent
  `sticky`/`pady`/`ipady`.

## Implementation Steps

### Task 1: Shortcut argument and filename helpers

- [x] Create `talks_reducer/gui/shortcut.py` with pure helper
  `build_shortcut_args(selections, gui_values)` mapping checked options to CLI
  flags using live GUI values, trimming trailing zeros from numeric values
- [x] Implement the 720/480-imply-Small rule and 720/480 mutual exclusivity in
  `build_shortcut_args`
- [x] Implement `shortcut_filename(args)` deriving a sanitized Desktop filename
  from the args, with `Talks Reducer.lnk` fallback when no args
- [x] write tests for `build_shortcut_args` (flag mapping, number formatting,
  720/480-imply-Small, mutual exclusivity, codec default handling) and
  `shortcut_filename` (sanitization, empty-args fallback)
- [x] run project tests - must pass before next task

### Task 2: Create lnk dialog, button, and shortcut writing

- [x] Add the dialog to `talks_reducer/gui/shortcut.py` as a `tk.Toplevel` modal
  mirroring `gui/discovery.py` (`transient`, `grab_set`,
  `WM_DELETE_WINDOW` -> `grab_release` + `destroy`), with seven checkboxes
  (Small, 720, 480, Silent speed, Sounded speed, Silent threshold, Codec)
- [x] Pre-check each checkbox from current GUI state and wire the
  720/480-imply-Small + mutual-exclusivity interaction in the dialog
- [x] Add a read-only args-preview label that updates live on every toggle (e.g.
  `talks-reducer.exe --small --720 --silent-speed 10`), plus Create and Cancel
  buttons
- [x] Resolve the shortcut target (frozen vs dev) and write the `.lnk` to the
  Desktop via a one-shot PowerShell `WScript.Shell.CreateShortcut` call; show an
  info messagebox on success and the error message on failure
- [x] Add `gui.lnk_button` ("Create lnk") to `button_frame` in
  `talks_reducer/gui/layout.py`, gridded only when `sys.platform == "win32"`, and
  wire it to a new `gui._open_create_lnk_dialog()` handler in `app.py`
- [x] write tests for any new platform-independent logic introduced in this task
  (`resolve_shortcut_target`, `build_powershell_script`,
  `_dialog_initial_selections`)
- [x] run project tests - must pass before next task

### Task 3: Fix seeded-launch slider value labels

- [x] After applying seeded values, trigger the slider label-formatting callback
  so the value label beside the slider reflects the seeded value for silent
  speed, sounded speed, and silent threshold
- [x] write tests verifying the slider label reflects a seeded value
- [x] run project tests - must pass before next task

### Task 4: Fix server URL / Discover button alignment

- [x] Align the server URL entry and the **Discover** button on the same
  center/baseline in `gui/layout.py` via consistent `sticky`/`pady`/`ipady`
- [x] write tests or update existing layout tests if the alignment is assertable;
  otherwise note manual verification
- [x] run project tests - must pass before next task

### Task 5: Document the Create lnk button

- [x] Update `README.md` (Graphical Interface section) to document the
  **Create lnk** button: Windows-only, Advanced-only, creates a desktop
  drop-target shortcut seeded with the selected preset flags
- [x] run project tests - must pass before next task

### Task 6: Verify acceptance criteria

- [x] verify all requirements from Overview are implemented
- [x] run full project test suite
- [x] run project linter (black, isort) - all issues must be fixed

## Post-Completion

*Items requiring manual intervention - no checkboxes, informational only*

- On a Windows machine: open the GUI in Advanced mode, click **Create lnk**,
  select options, confirm the args preview, create the shortcut, and verify the
  `.lnk` appears on the Desktop with the correct target and arguments.
- Drag a video onto the created shortcut and confirm the seeded GUI launches and
  auto-converts with the chosen presets.
