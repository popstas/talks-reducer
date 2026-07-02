# Design: Watch directory with dynamic Convert / Open-last button

Date: 2026-07-03

## Goal

Add a **watch directory** control to the GUI's **Advanced** settings. When
enabled, the GUI watches the chosen folder and drives a single **dynamic action
button** in the main button area (the slot currently used by **Open last**),
**visible in both Simple and Advanced modes**. The button reflects the
most-recently-modified *video* file in the watched folder:

- If that file's name contains **`_speedup`** (i.e. it is already a processed
  output), the button acts as **"Open last"** and reveals that file in the system
  file manager.
- Otherwise (a raw/unprocessed recording), the button acts as
  **"Convert `<filename>`"** and converts that file with the current GUI options.

This produces a natural loop: a raw file appears → button says **Convert** →
click → the processed `_speedup` file becomes the newest file → button flips to
**Open last**.

## Decisions

1. **Detection: polling timer**, not `watchdog`. A `root.after(...)` loop
   (~2s interval) rescans the folder. No new dependency, cross-platform, and the
   folder is small (a recordings dir), so polling cost is negligible.
2. **Candidate files: video only.** Reuse the extension set already used by the
   file picker in `gui/inputs.py`: `.mp4 .mkv .mov .avi .m4v` (case-insensitive).
3. **Processed-vs-raw marker: `_speedup` substring** (case-insensitive) in the
   filename. This matches the pipeline's default output suffix token (`speedup`,
   emitted as `_speedup[...]` by `_input_to_output_filename`). A file whose name
   contains `_speedup` is treated as an already-processed output → **Open last**;
   anything else → **Convert**.
4. **One dynamic button in the shared action slot, both modes.** The button lives
   in `status_frame` at the same grid cell as `stop_button` / `open_button` /
   `drop_hint_button` (row 2, columnspan 3) and is shown in Simple *and*
   Advanced. Only the **directory chooser + enable checkbox** live under
   Advanced and are hidden in Simple mode.

## User-facing behavior

**Advanced settings** gains a new group:

- **Watch directory** checkbox (`watch_enabled_var`) — enables/disables watching.
- **Directory entry + Browse…** — path field (`watch_directory_var`) with a
  folder picker (reuse the `browse_path` / `filedialog.askdirectory` pattern).

**Main action area** (both modes): the dynamic **watch button**
(`watch_button`), which:

- Is shown only when: watch is enabled AND the folder exists AND it contains at
  least one video file AND no run is currently active. (During a run the
  `stop_button` takes the slot, as today.)
- Chooses its variant from the newest video file (by `st_mtime`):
  - name contains `_speedup` → text **"Open last"**, command reveals that file.
  - otherwise → text **"Convert `<name>`"**, command converts that file. Long
    names are truncated for display; the full path is kept internally.
- While a conversion started from it is running, the slot shows `stop_button`
  (existing behavior), so double-submits are impossible.

When watch is disabled, the folder is missing, or it holds no video files, the
watch button is hidden and the existing button logic (`open_button` after a
session conversion, else `drop_hint_button`) is unchanged.

## Architecture / components

New module `talks_reducer/gui/watch.py` with a `WatchController` (mirrors the
`InputController` pattern in `gui/inputs.py`):

- `WatchController(gui)` — holds the GUI ref, the current watch dir, the last
  detected candidate `Path`, its variant (`open`/`convert`), and the pending
  `after` id.
- `start()` / `stop()` — begin/cancel the polling loop; idempotent. `start()` is
  a no-op when the directory is empty/invalid but keeps polling so the button
  reappears when the folder returns.
- `_poll()` — compute the newest video candidate, and if it changed, update the
  button variant/label/command + visibility, then reschedule via `root.after`.
- `_latest_video(directory) -> Optional[Path]` — pure helper: list files, filter
  by extension, return the greatest `st_mtime` (ties broken by name). Tk-free,
  unit-testable.
- `_is_processed(path) -> bool` — pure helper: `"_speedup" in name.lower()`.
- `refresh_button()` — apply the current candidate to `watch_button`
  (text/command/visibility); also called on enable-toggle and simple/advanced
  switches so state is consistent without waiting a poll tick.
- `open_latest()` / `convert_latest()` — the two button commands.

State/vars added to `TalksReducerGUI` (created next to `cut_enabled_var`, before
their `trace_add`):

- `watch_enabled_var: tk.BooleanVar`
- `watch_directory_var: tk.StringVar`
- `watch_button` widget (built in `layout.py` in `status_frame`, hidden by
  default like the other action buttons).
- `self.watch = WatchController(self)` and an `on_watch_*` toggle wiring similar
  to the input/cut controllers.

Layout wiring:

- `gui/layout.py` builds `watch_button` in `status_frame` at
  `row=2, column=0, columnspan=3` (same cell as stop/open/drop-hint), then
  `grid_remove()`.
- `gui/layout.py` builds the watch **checkbox + directory row** inside
  `advanced_frame`.
- `apply_simple_mode` hides only the Advanced chooser widgets in Simple mode
  (add to the existing hide/show list). The `watch_button` itself is **not**
  hidden by Simple mode — its visibility is owned by `WatchController`.

Button-slot coordination: the watch button shares the slot with
`stop_button`/`open_button`/`drop_hint_button`. `WatchController.refresh_button`
becomes the single authority for that slot when watch is active: it shows
`watch_button` and hides `open_button`/`drop_hint_button`; when watch is
inactive it hides `watch_button` and restores the legacy logic. `_hide_stop_button`
is extended to defer to the watch button (show it instead of the drop hint when
watch is active and has a candidate).

## Data flow

**Convert click** (`convert_latest`):

1. Re-check the tracked candidate still exists (refresh + abort quietly if not).
2. Set it as the **sole** input: clear `input_files`, then
   `InputController.extend_inputs([path], auto_run=True)`. Convert always
   processes exactly the named file; remote/local, small, cut, and every other
   option match a normal run.
3. The normal progress/summary/open-after-convert flow handles the rest. When it
   finishes and the `_speedup` output lands in the watched folder, the next poll
   flips the button to **Open last** automatically.

**Open-last click** (`open_latest`):

1. Reveal the tracked candidate via the existing `_open_in_file_manager(path)`
   helper.

No changes to the CLI or `ProcessingOptions` — watch is a GUI-only convenience
that feeds the existing input/run/reveal machinery.

## Persistence

Add two keys to `GUIPreferences`, following the `cut_enabled`/`cut_start`
pattern:

- `watch_enabled` (bool, default `False`)
- `watch_directory` (str, default `""`)

Seed the vars from preferences **before** installing their `trace_add`, so
seeding never fires the toggle. Toggling the checkbox or editing the path
persists via `preferences.update(...)`. On startup, if `watch_enabled` is `True`
and the directory is valid, start the poller (normal GUI only, after widgets
exist).

## Error handling / edge cases

- **Missing/deleted directory:** `_latest_video` → `None`; watch button hidden;
  poller keeps running so it reappears if the folder returns.
- **Permission / OS error during scan:** caught; treated as "no candidate" for
  that tick; logged at most once.
- **Empty folder / no video:** button hidden, legacy button logic restored.
- **File still being written** (recording in progress): out of scope for v1 — the
  user chooses when to click Convert. No mtime-stability debounce.
- **Conversion in progress:** slot shows `stop_button`; watch button re-appears
  after the run and reflects the (now `_speedup`) newest file.
- **Custom output path outside the watched folder:** after Convert the newest
  file in the watch dir may stay the raw file, so the button stays **Convert**.
  Acceptable — the button strictly reflects the watched folder.

## Testing

- **Unit (no Tk):** `_latest_video` — newest-by-mtime, extension filtering, empty
  dir → `None`, missing dir → `None`, tie-break by name (use `tmp_path` +
  `os.utime`). `_is_processed` — `_speedup`, `_speedup_small`, mixed case → True;
  raw name → False.
- **Preferences:** `watch_enabled`/`watch_directory` round-trip through
  `GUIPreferences` (defaults, update, failed-write rollback).
- **Controller logic (light, mocked GUI):** `refresh_button` picks the right
  variant/label from a candidate; `convert_latest` with no candidate is a no-op;
  with a raw candidate it clears inputs and runs that one file; `open_latest`
  calls `_open_in_file_manager` with the candidate.
- **Manual/E2E checklist** (for the PR): enable watch + pick a folder in
  Advanced; drop a raw video in → button shows **Convert `<name>`** in both
  Simple and Advanced; click → converts; when the `_speedup` output appears the
  button flips to **Open last** and reveals it; disabling watch restores the
  normal Open-last/drop-hint behavior; the setting persists across restart.

## Out of scope (YAGNI)

- Auto-conversion on new file (button is manual).
- Watching multiple directories or recursion into subfolders.
- Non-video file support.
- mtime-stability debounce for in-progress recordings.
