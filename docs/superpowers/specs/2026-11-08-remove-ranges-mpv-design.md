# Remove middle fragments via mpv.net — design

Date: 2026-11-08

## Goal

Let the user cut several fragments out of the middle of a video without
building a video-editor UI in Tk:

1. **Before conversion** — fragments marked on the source are dropped while the
   normal pipeline runs (speedup, resolution, codec as configured).
2. **After conversion** — fragments marked on a finished `_speedup` file are
   dropped in a separate fast pass that changes nothing else.

Marking happens in an external player (mpv.net on Windows, mpv elsewhere) driven
by a Lua script shipped with talks-reducer. The existing **Cut video** keep-range
(start/end sliders) stays and works together with the new ranges.

## Non-goals (v1)

- **Remote mode.** Remove ranges are local-only. With Mode=Remote and a
  non-empty list the run fails fast with `Remove ranges are local-only`.
  Passing them to the server (like `cut_start/cut_end` in `service_client`)
  is a later change.
- **Mapping marks between files.** Source and output timelines differ (silence
  is sped up), so a mark set belongs to the file it was made on. No chunk-map
  persistence, no translation of output marks back to the source.
- **Simple mode.** Ranges are ignored there, like the keep-range trim today.
- **Web UI / OBS dock.** Not exposed.

## 1. Mark file

Sidecar next to the video: `<video file name>.cuts.json`
(e.g. `lecture.mp4.cuts.json`, `lecture_speedup.mp4.cuts.json`).

```json
{"version": 1, "source": "lecture.mp4", "remove": [[80.3, 105.0], [720.0, 750.5]]}
```

- `remove` — list of `[start, end]` in seconds of **that** file, `start < end`.
- Readers normalise: drop invalid pairs, sort, merge overlapping/touching ranges.
- Unknown `version` or unparsable JSON → treated as no marks, logged at
  warning level.

## 2. Lua script — `talks_reducer/resources/talks_reducer_cuts.lua`

No dependencies beyond the mpv Lua API (works in mpv.net and mpv).

- `c` — first press stores a pending start at the current position; second
  press closes the range (start/end swapped if reversed), adds it, merges.
- `C` (Shift+c) — undo: clears the pending start if any, else removes the last
  added range.
- Both keys are registered with `mp.add_forced_key_binding`, so they win over
  whatever the user's `input.conf` (or mpv.net's defaults) binds to `c`/`C`,
  but only while this script is loaded via `--script=`.
- OSD line on every change (and on `c`/`C` with no change):
  `Cuts: 2 | 01:20.3–01:45.0, 12:00.0–12:30.5 | [mark 13:05.2…]`.
- **Which file it reads and writes.** When launched by talks-reducer the
  script gets `--script-opts=talks_reducer_cuts-file=<path>`: a JSON file in
  the system temp folder that the GUI pre-fills with the current marks. The
  script only ever touches that file; Python copies the result into the real
  sidecar. Reason: Lua's `io.open` inside mpv is not guaranteed to handle
  non-ASCII paths on Windows (Cyrillic file names are the common case here),
  while the temp path is under the user's temp folder. Run standalone (no
  `file` option), the script falls back to `<video path>.cuts.json`.
- On file load the script reads that file if it exists.
- The file is written after every change and on `shutdown`. An empty list
  writes `"remove": []` (the GUI then deletes the sidecar).
- Writing uses a temp file + rename so a crash never leaves half a JSON.

Shipped as package data: add `"*.lua"` to `[tool.setuptools.package-data]`
for `talks_reducer.resources` and an entry to `base_datas` in
`talks-reducer.spec`.

## 3. `talks_reducer/cut_marks.py`

Pure helpers plus the player launcher; no Tk imports.

- `RemoveRange = tuple[float, float]`
- `normalize_ranges(ranges) -> list[RemoveRange]` — validate, sort, merge.
- `sidecar_path(video: Path) -> Path`
- `load_marks(video: Path) -> list[RemoveRange]` / `save_marks(video, ranges)`
- `parse_ranges_text(text: str) -> list[RemoveRange]` — `"1:20-1:45, 12:00-12:30.5"`;
  each bound via `timecode.parse_timecode`; raises `ValueError` naming the bad
  token.
- `format_ranges_text(ranges) -> str` — `format_timecode` per bound, `", "`-joined.
- `find_player(preferred: str | None) -> Path | None` — order:
  1. `preferred` (the `mpv_path` setting) if it exists;
  2. `mpvnet`, then `mpv` on `PATH` (`shutil.which`);
  3. Windows: `%ProgramFiles%\mpv.net\mpvnet.exe`,
     `%LOCALAPPDATA%\Programs\mpv.net\mpvnet.exe`;
  4. macOS: `/opt/homebrew/bin/mpv`, `/usr/local/bin/mpv`.
- `script_path() -> Path` — resolved via `importlib.resources`, frozen-aware.
- `build_player_command(player, video, marks_file) -> list[str]` —
  `[player, "--script=<lua>", "--script-opts=talks_reducer_cuts-file=<marks_file>", video]`,
  plus `--process-instance=multi` when the player is mpv.net: its default
  single-instance mode hands the file to an already running window and exits
  at once, so the GUI would read the marks before the user made any (and the
  script would not be loaded).
- `open_player(player, video, marks_file) -> subprocess.Popen` — runs that
  command with `**hidden_subprocess_kwargs()`.
- `read_marks_file(path)` / `write_marks_file(path, ranges, source_name)` —
  the JSON (de)serialisers `load_marks`/`save_marks` delegate to.

## 4. Pipeline

### Options

`ProcessingOptions.remove_ranges: tuple[RemoveRange, ...] = ()` — seconds in
the input file's timeline.

### Mapping into the trimmed window

When the keep-range trim is active, ranges are shifted by `-cut_start` and
clipped to `[0, effective_duration]`; ranges that fall outside are dropped and
the count is logged.

### Chunk marking

New `chunks.apply_remove_ranges(chunks, ranges, frame_rate) -> list[list[int]]`:

- Converts each range to source frames `[round(start*fps), round(end*fps))`.
- Splits chunks at range boundaries and gives the pieces inside a range the
  speed index `REMOVED_SPEED_INDEX = 2`.
- Zero-length pieces are not emitted.

The pipeline calls it right after `build_chunks` and passes
`new_speeds = [silent_speed, sounded_speed, math.inf]`.

### Audio

`audio._render_chunk_list` and `_collect_vocoder_jobs` treat an infinite speed
as "emit zero samples": no vocoder, no pool job. The updated chunk then has
`start_output_frame == end_output_frame`, so `get_tree_expression` maps all of
its frames to one timestamp (`local_speedup = 0`) and the fps filter / CFR
muxing drops them — the same path silence-sped frames already take.

### Forcing the speed path

The pipeline currently skips `setpts` when both speeds are 1.0 (or there is no
audio). With non-empty `remove_ranges` it must take the speed path even at
1.0/1.0.

**Risk to verify first in the plan:** that collapsed frames are really dropped
(not muxed with duplicate timestamps) for both `fps` orig (no trailing `fps=`)
and a capped fps, on CPU and on a GPU encoder. If they are not, add an explicit
`select='not(between(n,a,b)+…)'` before the `fps=source` filter and offset the
chunk frames accordingly.

### No audio stream

Ranges are ignored with a warning (`Remove ranges need an audio stream`).

### Output name

A non-empty `remove_ranges` adds a `cut` token to the output name
(`lecture.mp4` → `lecture_speedup_cut.mp4`, `lecture_speedup.mp4` with
**Remove only** → `lecture_speedup_cut.mp4`). Because the name already differs
from the input, the token replaces the forced codec suffix that speeds 1/1
without `--small` otherwise add.

## 5. GUI (Advanced only)

Inside the existing Cut panel (`cut_panel`), below the sliders:

- **Mark cuts…** button — `find_player(prefs.mpv_path)`; if `None`, a
  messagebox explains how to install mpv.net with a link to its releases page.
  Otherwise the GUI writes the current marks to a temp marks file,
  `open_player`s the selected file with it, and a worker thread waits for the
  process; on exit it reads the temp file, deletes it, and schedules on the UI
  thread: `save_marks` (sidecar) → fill the field. Marking needs exactly one
  queued input that is a file.
- A run with remove ranges and more than one resolved input file stops with
  `Remove ranges apply to a single file`.
- **Remove:** `ttk.Entry` (`remove_ranges_text_var`) showing
  `format_ranges_text`; editable. Commit on Enter/focus-out via
  `parse_ranges_text`; on `ValueError` the field reverts and the status shows
  the error. A committed edit is also written back with `save_marks`, so the
  sidecar stays the single source of truth.
- Selecting a file loads its sidecar into the field (empty when absent).
- **Remove only** button next to **Convert**, visible when the field is
  non-empty. Runs the pipeline on the selected file with forced overrides:
  silent and sounded speed 1, resolution orig, fps orig, current codec, output
  suffix `_cut`, keep-range trim still applied. **Convert** keeps its meaning
  (current settings) and now also applies the ranges.
- Dropping a file does not auto-convert while ranges can apply: ranges only
  apply with **Cut video** on in Advanced mode, which is exactly when
  `InputController._cut_requires_manual_convert` already defers the run.
- `_collect_arguments` passes `remove_ranges` only in Advanced mode with
  **Cut video** on.

Preferences: only `mpv_path` (optional, default unset) is persisted. Ranges are
never stored in `settings.json`.

## 6. CLI

- `--remove RANGES` — `parse_ranges_text` syntax.
- `--remove-file PATH` — reads a `.cuts.json`.
- Both given → union, normalised.
- With multiple inputs the ranges apply to every input (documented; the GUI
  only ever passes them for one file).
- Post-conversion cut from the CLI is the plain combination
  `--silent-speed 1 --sounded-speed 1 --no-small --fps orig --remove …`;
  no extra flag.

## 7. Testing

- `apply_remove_ranges`: range inside one chunk, spanning chunks, at frame 0, at
  EOF, adjacent ranges, out-of-window ranges after trim shift.
- `cut_marks`: `normalize_ranges`, text parse/format round-trip, bad tokens,
  sidecar load/save/delete-on-empty, `find_player` order with patched
  `which`/paths.
- `audio`: infinite speed emits zero samples and is never sent to the pool.
- CLI: `--remove` / `--remove-file` reach `ProcessingOptions`.
- Integration (ffmpeg available): synthetic 10 s clip with tone, remove 3–5 s,
  speeds 1/1 → output duration ≈ 8 s (±1 frame) by ffprobe; same with fps cap.
- `test_no_console_windows.py` must keep passing (`open_player` uses the helper).
- GUI: stub tests for button visibility and the manual-convert gate; a real
  window check for layout per the GUI Layout Convention.

## 8. Docs

README: Cut video section gains "Mark cuts in mpv.net", the `.cuts.json`
format, **Remove only**, and the `--remove`/`--remove-file` flags. CLAUDE.md
Graphical Interface section updated for the new Cut panel controls.
