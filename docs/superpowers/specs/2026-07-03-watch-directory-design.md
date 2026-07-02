# Design: Watch directory with "Convert <filename>" button

Date: 2026-07-03

## Goal

Add a **watch directory** control to the GUI's **Advanced** settings. When
enabled, the GUI watches the chosen folder and shows a **"Convert `<filename>`"**
button, where `<filename>` is the most-recently-modified *video* file in that
folder. Clicking the button converts that file with the current GUI options.

## Decisions (from brainstorming — defaults chosen while user was away)

1. **Detection: polling timer**, not `watchdog`. A `root.after(...)` loop
   (~2s interval) rescans the folder. No new dependency, cross-platform, and the
   folder is small (a recordings dir), so polling cost is negligible.
2. **Candidate files: video only.** Reuse the extension set already used by the
   file picker in `gui/inputs.py`: `.mp4 .mkv .mov .avi .m4v` (case-insensitive).
   Non-video files never surface a button.
3. **Action: manual button only.** New/changed files update the button label but
   do **not** auto-convert. The user reviews and clicks. (Matches the task
   wording "выводить кнопку".)
4. **Availability: Advanced only.** Both the directory chooser and the Convert
   button live under Advanced and are hidden in Simple mode, mirroring the
   **Cut video** feature (`apply_simple_mode`).

These are recommended defaults; the user can override any of them at the review
gate.

## User-facing behavior

Under **Advanced settings**, a new group:

- **Watch directory** checkbox (`watch_enabled_var`) — enables/disables watching.
- **Directory entry + Browse…** — path field (`watch_directory_var`) with a
  folder picker (reuse the `browse_path`/`filedialog.askdirectory` pattern).
- A **"Convert `<name>`"** button that:
  - Is shown only when: Advanced is visible AND watch is enabled AND the folder
    exists AND it contains at least one video file.
  - Labels itself with the basename of the most-recently-modified video file
    (by `st_mtime`). Long names are truncated for display; the full name is kept
    internally.
  - On click: converts that single file with the current options via the
    existing run path (see Data flow). While a conversion is running the button
    is disabled to avoid double-submits.

When watch is disabled, the folder is missing, or it holds no video files, the
button is hidden and no polling work is scheduled.

## Architecture / components

New small module `talks_reducer/gui/watch.py` holding a `WatchController`
(mirrors the `InputController` pattern in `gui/inputs.py`):

- `WatchController(gui)` — holds a reference to the GUI, the current watch dir,
  the last-detected candidate path, and the pending `after` id.
- `start()` / `stop()` — begin/cancel the polling loop; idempotent.
- `_poll()` — scan the directory for the newest video file, update the tracked
  candidate + button label if it changed, then reschedule via `root.after`.
- `_latest_video(directory) -> Optional[Path]` — pure helper: list files, filter
  by extension, return the one with the greatest `st_mtime` (ties broken by
  name). Unit-testable without Tk.
- `convert_latest()` — the button command; forwards the candidate to the run
  path.

State/vars added to `TalksReducerGUI` (created in the same place as
`cut_enabled_var` etc.):

- `watch_enabled_var: tk.BooleanVar`
- `watch_directory_var: tk.StringVar`
- `watch_convert_button` widget + a `watch_frame`/row in `advanced_frame`.

Layout wiring in `gui/layout.py`:

- Build the watch row(s) inside `advanced_frame` next to the other Advanced
  controls.
- `apply_simple_mode` hides the watch widgets in Simple mode (add to the existing
  hide/show list alongside `cut_check`/`cut_panel`).

## Data flow (Convert click)

`convert_latest()`:

1. Resolve the tracked candidate path (re-check it still exists; if not, refresh
   and abort quietly).
2. Set it as the **sole** input and start the run: clear `input_files`, then
   `InputController.extend_inputs([path], auto_run=True)` so Convert always
   processes exactly the named file (never appends to a stale queue). This keeps
   remote/local, small, cut, and all other options identical to a normal run.
3. The normal progress/summary/open-after-convert flow handles the rest.

No changes to the CLI or `ProcessingOptions` — watch is a GUI-only convenience
that feeds the existing input/run machinery.

## Persistence

Add two keys to `GUIPreferences`, following the `cut_enabled`/`cut_start`
pattern:

- `watch_enabled` (bool, default `False`)
- `watch_directory` (str, default `""`)

Seed the vars from preferences on startup **before** installing their
`trace_add`, so seeding never fires the toggle (same guard the tray var uses).
Toggling the checkbox or editing the path persists via `preferences.update(...)`.
On startup, if `watch_enabled` is `True` and the directory is valid, start the
poller (only in a normal GUI, and only once Advanced widgets exist).

## Error handling / edge cases

- **Missing/deleted directory:** `_latest_video` returns `None`; button hidden;
  poller keeps running (cheap) so the button reappears if the folder returns.
- **Permission / OS error during scan:** caught; treated as "no candidate" for
  that tick; logged at most once to avoid spam.
- **File still being written** (recording in progress): out of scope for v1 —
  the user decides when to click Convert, which naturally avoids half-written
  files. (No mtime-stability debounce in v1.)
- **Simple mode:** widgets hidden and, like cut, watch never triggers a run
  there.
- **Conversion in progress:** button disabled until the run finishes.

## Testing

- **Unit (no Tk):** `_latest_video` — newest-by-mtime selection, extension
  filtering, empty dir → `None`, missing dir → `None`, tie-break by name. Use
  `tmp_path` and `os.utime` to set mtimes.
- **Preferences:** `watch_enabled`/`watch_directory` round-trip through
  `GUIPreferences` (default values, update, rollback on failed write consistent
  with existing helpers).
- **Controller logic (light):** `convert_latest` with no candidate is a no-op;
  with a candidate it calls the run path with that single file (mock the GUI run
  method).
- **Manual/E2E checklist** (for the PR): enable watch, pick a folder, drop/record
  a video, confirm the button labels with the newest file and converts it;
  confirm Simple mode hides the controls; confirm the setting persists across
  restart.

## Out of scope (YAGNI)

- Auto-conversion on new file (explicitly a manual button).
- Watching multiple directories or recursion into subfolders.
- Non-video file support.
- mtime-stability debounce for in-progress recordings.
