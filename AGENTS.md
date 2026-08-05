# Repository Guidelines

- Keep the documentation in `README.md` in sync with recent feature changes and CLI options.
- When modifying the Python code, favor clear function-level docstrings over inline comments for new logic.
- Run available linters or sanity checks when adding dependencies; document any skipped checks in your PR description.
- For documentation-only changes, describe the rationale behind updates so future contributors understand the context.
- Keep Python formatting consistent by running `black` and `isort` (configured via `pyproject.toml`) before committing code changes.

# Pull request naming
Create name using angular commit message format.
`feat:` and `fix:` are using in CHANGELOG.md. It's a release notes for users. Name your PRs in a way that it's easy to understand what was changed. Forbidden to use `feat:` and `fix:` prefixes for chore tasks that don't add new features or fix bugs.

Name examples:
- feat: Add 480p small preset option
- fix: Switch to static-ffmpeg for bundled ffprobe
Look at the commit history to get more examples.



### Graphical Interface

- **Simple mode** — the default experience shrinks the window to a large drop
  zone, hides the manual run controls and log, and automatically processes new
  files as soon as you drop them. Uncheck the box to return to the full layout
  with file pickers, the Run button, and detailed logging.
- **Input drop zone** — drag files or folders from your desktop, click to open
  the system file picker, or add them via the Explorer/Finder dialog; duplicates
  are ignored.
- **Basic options** — the panel (`layout.py`, inside `options_frame`) is a flat run of labelled
  rows with no group captions: every row is already labelled, so the headings only spent vertical
  space. Row spacing carries the grouping instead — `layout.SETTING_ROW_PADY` above every option
  row, the wider `layout.PRESET_ROW_PADY` around the Preset strip so it reads as its own band.
  The panel renders its choice-style
  settings as `SegmentedChoice` (`talks_reducer/gui/segmented.py`) — one `ttk.Button` per option,
  styled `Segment.TButton`/`SelectedSegment.TButton` (added in `theme.py`)
  — instead of the `tk.Scale` sliders it used to use. **Codec** leads the rows, directly under
  **Resolution**: the two together describe the output file, so they read as a pair before the
  timing knobs. It offers h.264/h.265/av1/mp3, each with its own tooltip ("Faster", "25%
  smaller", "No advantages", "Audio only" — text that used to sit in parentheses in the label);
  **Add codec suffix** sits to its right. **Silent**
  speed offers 10/5/2/1 (custom 1–10, default 10 — every row leads with its
  strongest option and opens on it); **Sounded** speed offers 1/1.3/1.5/2 (custom
  0.75–10, default 1 — 1.3 and 1.5 are newly reachable now that the old slider's 0.25 quantization
  is gone); **Threshold** offers 0.01/0.03/0.05/0.10 (custom 0–`THRESHOLD_MAXIMUM`, which is 0.9 —
  past that the detector calls almost the whole track silence — default 0.01), the group carries
  one tooltip listing what each value trims, and a narrow `?` link (`HelpLink.TButton`,
  `webbrowser.open` on
  `THRESHOLD_ARTICLE_URL`, the telegra.ph write-up on trimming silence before speech-to-text
  breaks) sits in the setting's **label**, not in the value row — `add_segmented`'s `help_url`
  builds the label as a frame holding the text plus the link and exposes it as
  `control.help_button`. **Mode** offers Local/Remote and carries the whole
  remote group on its own line — the address `ttk.Entry` (`SERVER_URL_WIDTH`), **Discover**, then
  the readiness text, in that order. **Discover** is styled `Segment.TButton` so it matches the
  height and inset of the mode buttons beside it (a plain `ttk.Button` inherits ttk's
  eleven-character minimum width and a taller padding), and the entry hugs both neighbours with
  the shared `SERVER_URL_GAP` (4px) instead of the row's wider spacing, so mode buttons + entry +
  Discover read as one control group. `server_url_row` and `remote_status_label` are both packed
  into the Mode row's frame, so `update_processing_mode_visibility` hides them with
  `pack_forget` and re-packs the row `before=remote_status_label` to keep that order. **Theme**
  offers OS/Light/Dark. A trailing `…` slot on the custom-range controls swaps itself for an
  inline `ttk.Entry` — Enter **and focus-out** both commit (clamped to the control's bounds), so
  clicking away never discards a typed value; only Escape cancels, and a non-number falls back to
  the last committed value. Once a value is committed the slot **stays** an entry so it can be edited
  in place; only clicking a preset option clears it back to `…`. Button and entry are sized to
  match (`CUSTOM_SLOT_WIDTH` plus the near-padless `CustomSegment.TButton`/`SegmentEntry.TEntry`
  styles) so the swap never reflows the row. Every bound control traces its variable and is registered into
  `gui._slider_updaters` through `layout.add_segmented`'s `apply_and_persist` wrapper, so
  `apply_preset_to_gui` and presets applied on other surfaces keep moving the buttons exactly as
  they moved the sliders they replaced. The **Silence speedup** macro row (**Silence ×10** /
  **Silence ×5** / **No speedup**) is also a `SegmentedChoice` (`gui.basic_preset_control`,
  `variable=None`); **Silence ×5** (`gui.reset_basic_button`) used to disable itself when the
  sliders already matched the defaults, but a button rendered as "selected" must not
  simultaneously be disabled, so it no longer does — clicking it always re-applies the defaults.
- **Resolution** — a `SegmentedChoice` (**720p** / **480p** / **orig**) in the basic options
  panel, replacing the old **Small video** + **480p** checkboxes. `orig` leaves the source
  resolution untouched and corresponds to the CLI's `--no-small`. The control is a *projection*:
  `small_var`/`small_480_var` remain the source of truth that presets, the seeded-launch CLI
  flags and `_collect_arguments` read, so clicking a button fans onto them
  (`layout.apply_resolution_choice`) and a trace on both booleans writes `resolution_var` back
  (`layout.resolution_from_small`) — that is what makes an applied preset move the buttons.
  Because the control lives inside `basic_options_frame`, which Simple mode hides, a Simple-mode
  session with **zero** presets now has no resolution control at all (the checkboxes used to
  cover that case).
- **Open after convert** — controls whether the exported file is revealed in
  your system file manager as soon as each job finishes.
- **Cut video** — an **Advanced-only** checkbox (`apply_simple_mode` hides it and
  its panel in Simple mode) that reveals a collapsible trim panel with two linked
  range sliders (start ≤ end, range `0..duration`), each paired with an editable
  time entry (`cut_start_text_var`/`cut_end_text_var`) and a tall **Convert**
  button that spans both rows. On file-select the slider range is seeded from
  `get_video_duration` (ffprobe). Entries mirror the handles as `HH:MM:SS.mmm`
  (`format_timecode(..., milliseconds=True)`) and accept manual edits parsed by
  `parse_timecode` (`_on_cut_entry_commit`), allowing millisecond input. With Cut
  on, dropping a file does not auto-convert
  (`InputController._cut_requires_manual_convert`); the user clicks **Convert**
  (revealed by `_update_cut_convert_button`). `_collect_arguments` ignores the
  trim while Simple mode is on, so a persisted flag never trims there. When
  applied, the GUI emits the same keep-range used by the `--cut-start`/`--cut-end`
  CLI flags as `cut_start_seconds`/`cut_end_seconds` (in/out timestamps, end
  `0` = EOF) into `ProcessingOptions` locally or into `service_client.send_video`
  for the remote path; when off the trim args are omitted. The enabled flag plus
  the last start/end values persist via `GUIPreferences` (`cut_enabled`,
  `cut_start`, `cut_end`).
- **Watch directory** — an **Advanced** setting (`watch_check`,
  `watch_directory_entry`, `watch_browse_button` in `advanced_frame`,
  auto-hidden in Simple mode) that lets you pick a folder for `WatchController`
  (`talks_reducer/gui/watch.py`) to poll (~2s) for its most-recently-modified
  video. The controller owns a dynamic `watch_button` in `status_frame`,
  sharing that slot with the Stop/Open/Drop button via `refresh_button`: it
  reads **"Convert `<filename>`"** for a raw recording, or **"Open last"** when
  the newest file's name already contains a processed marker (`_speedup` or
  `_small`). The button itself is visible in both Simple and Advanced modes
  even though the folder chooser is Advanced-only. The enabled flag and chosen
  path persist via `GUIPreferences` (`watch_enabled`, `watch_directory`).
- **Advanced** — reveals optional controls for the output path, temp folder,
  timing/audio knobs mirrored from the command line, and an appearance picker
  that can force dark or light mode or follow your operating system.
- **Server mode (`--server-managed`)** — when the tray launches the GUI it passes
  `--server-managed` and `--server-url <local url>`. The window then shows a
  **Server:** label near **Mode** with the LAN-reachable address and a
  **Connected clients** panel that polls the server's `GET /activity` endpoint
  (~5s) and renders recent client requests as `HH:MM:SS  <ip>  <action>`. Both
  are hidden in the standalone GUI. While downloading a remote result the GUI
  shows a refreshing **Waiting for download…** status during the
  processing→download gap, and the download bar advances to 100% only once.

Progress updates stream into the 10-line log panel while the processing runs in
a background thread. Once every queued job succeeds an **Open last output**
button appears so you can jump straight to the exported file in your system
file manager.

The GUI stores your last-used Simple mode, Small video, Open after convert, and
theme preferences in a cross-platform configuration file so they persist across
launches.

## Repository Structure
- `talks_reducer/` — Python package that exposes the CLI and reusable pipeline:
  - `cli.py` parses arguments and dispatches to the pipeline.
  - `pipeline.py` orchestrates FFmpeg, audio processing, and temporary assets.
  - `audio.py` handles audio validation, volume analysis, and phase vocoder processing.
  - `chunks.py` builds timing metadata and FFmpeg expressions for frame selection.
  - `ffmpeg.py` discovers the FFmpeg binary, checks GPU encoder availability (`check_cuda_available` for NVENC, `check_videotoolbox_available` for Apple VideoToolbox), and assembles command strings.
  - `gui/segmented.py` defines `SegmentedChoice`, the button-row control (with an optional custom-value `…` slot) used throughout the Advanced "Basic options" panel in place of `tk.Scale` sliders.
- `requirements.txt` — Python dependencies for local development.
- `default.nix` — reproducible environment definition for Nix users.
- `CONTRIBUTION.md` — development workflow, formatting expectations, and release checklist.
- `AGENTS.md` — maintainer tips and coding conventions for this repository.

## Highlights
- Builds on gegell's classic jumpcutter workflow with more efficient frame and audio processing
- Generates FFmpeg filter graphs instead of writing temporary frames to disk
- Streams audio transformations in memory to avoid slow intermediate files
- Accepts multiple inputs or directories of recordings in a single run
- Provides progress feedback via `tqdm`
- Automatically detects GPU encoders — NVENC on NVIDIA hardware, VideoToolbox for HEVC on macOS — so you no longer need to pass `--cuda`

## Processing Pipeline
1. Validate that each input file contains an audio stream using `ffprobe`.
2. Extract audio and calculate loudness to identify silent regions.
3. Stretch the non-silent segments with `audiotsm` to maintain speech clarity.
4. Stitch the processed audio and video together with FFmpeg, using NVENC if the GPU encoders are detected, or VideoToolbox on macOS for HEVC only (H.264 is faster on `libx264` there, and Apple ships no AV1 encoder).

## GUI Layout Convention
- **The GUI test suite runs against hand-written widget stubs (`WidgetStub`/`WidgetFactory` in `tests/test_gui_layout.py`), never real Tk, and those stubs model widget *API calls* but not *geometry*.** Cell occupancy under `columnspan`, slack distribution from `columnconfigure(weight=...)`, and the `TclError` from calling `grid()` on a `pack`-managed widget are invisible to them. Every layout defect that reached review on the segmented-settings branch was in that class: two controls on one grid row, a `?` button drifting ~680px right because a `columnspan=2` neighbour absorbed the row's slack, and a status label hidden with the wrong geometry manager. A green suite says nothing about layout — check a real window, and prefer extending `test_basic_options_frame_grid_positions_do_not_collide` (which expands `columnspan`/`rowspan` into per-cell occupancy) over another stub assertion.
- **ttk's `TButton` style carries `width: -11`** — a minimum of eleven characters that every
derived style inherits. A one-glyph "?" rendered 89px wide until `HelpLink.TButton` set
`width=0`, and segment buttons were 103px instead of 32px. Any content-width button style in
this project must set `width=0` explicitly.
- **Never mix geometry managers on one widget.** Hide a grid-managed widget with `grid_remove()` and a packed one with `pack_forget()`; the stubs accept either, real Tk raises.
- **A muted colour is not automatically a readable one.** Both palettes in `theme.py` carry the same `accent` (`#2563eb`) so the selected-segment blue is identical in light and dark, and a dedicated `disabled_foreground` (`#6b7280` light, `#9ca3af` dark) that the `Segment`/`CustomSegment` disabled maps use. They used to reuse `border`, which is a *line* colour: at 1.5:1 against the dark surface it left disabled **Remote** unreadable rather than merely dimmed. Pick disabled text from a text ramp, not from the border tone.
- **Before hiding a control, enumerate every path that could still need it.** Hiding the Server URL row outside remote mode made remote mode permanently unreachable on a fresh config: that row holds the only URL entry and **Discover** button, while **Remote** disables itself until a URL exists. The row now also shows whenever `server_url_var` is empty. Two individually reasonable rules produced a deadlock.
- **Recompute visibility on the state that owns it, not on every write.** `server_url_var` traces into `_update_processing_mode_state`, so recomputing the row on URL changes hid the field mid-keystroke; `on_server_url_change` passes `update_row=False` to keep row visibility a function of the *mode* alone.

## Segmented Control Conventions
Rules for `SegmentedChoice` (`talks_reducer/gui/segmented.py`) and its `layout.add_segmented` wrapper.
- The inline `ttk.Entry` that replaces the `…` button must match that button's width, so committing or cancelling an edit never reflows the row.
- Help and article links belong on the setting's **label**, not as an extra widget in the value row. The value row holds values.
- A choice control sizes itself to its content plus 10px padding rather than a fixed width.
- A control backed by user-authored options (presets) carries a **Custom** entry that selects itself whenever the live values match no stored option — the same reverse-match `presets.match_preset` already drives for the Advanced dropdown.
- `set_value` must clamp to the control's `CustomSpec` bounds. It is the programmatic entry point presets arrive through, and an unclamped value silently diverges from what the buttons display and from what gets persisted.
- `set_value` deliberately does **not** fire `on_change`; `layout.add_segmented`'s `apply_and_persist` wrapper restores the persistence half at the integration layer. Keep that split — firing `on_change` from `set_value` would re-enter through the variable trace.
