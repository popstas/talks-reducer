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
- **Glue multiple inputs** — when a run resolves to 2+ media files (a multi-file
drop, a picker selection, or a folder that expands), the worker asks
`_ask_glue_confirmation` — a `messagebox.askyesno` marshalled onto the UI thread
with the worker blocking on a `threading.Event`, since the dialog cannot be
raised from the processing thread. **Yes** routes the queue through
`glue.prepare_glued_input` (`_maybe_glue_inputs`), which concatenates the parts
into a `glue_*` directory under the temp folder **before** the local/remote
branch, so remote mode uploads one file too; `_cleanup_glue_workspace` removes
that directory in the worker's `finally`. The glued temp file keeps the **first**
part's *name*, and the output is renamed onto the first part's *folder* via
`pipeline.resolve_output_path(options, source=glue_source)` — without that
override the result would be written inside the temp directory and deleted with
it. The remote path gets the same treatment by wrapping
`default_remote_destination` so it names the download after the glue source
rather than the temp input. Nothing is persisted: the question is asked on every
multi-file run, and a single file never triggers it.
- **Presets** — user-named bundles of processing settings (`resolution`,
`silent_speed`, `sounded_speed`, `silent_threshold`, `video_codec`) stored in the
shared `settings.json` (`presets` key) via `talks_reducer/presets.py` and applied
read-only on every surface (Simple mode, Web UI, OBS dock, CLI `--preset`). Presets
are **sparse**: every value field on `Preset` is `Optional`, `to_dict()` stores only
the fields that are set, and `preset.present_fields()` reports them. Apply/CLI/match
all skip absent fields (`apply_preset_to_gui`, `_apply_preset_to_args`,
`preset_to_web_controls` return sparse control maps, `match_preset` compares only
present fields — a zero-field preset never matches). `load_presets()` seeds five
`DEFAULT_PRESETS` on first run when the key is absent — **Compatible** (720p ×10 h.264, the
first-run default on every surface), **Optimal** (720p ×10 h.265), **Smallest** (480p ×10
h.265), **Compress** (720p h.264, silence ×1) and the deliberately sparse **mp3** (no
resolution, so it leaves the video settings alone). They are named for the outcome rather
than the settings, since the values are one hover away (`describe_preset`). An emptied
list persists as `[]`. Each surface opens on the remembered `selected_preset`, else
the first preset (`layout.seed_initial_preset`, `server.resolve_initial_web_preset`,
dock `populatePresetDropdown`). **Simple mode** replaces the old
`simple_speedup_frame`/`simple_codec_frame` with a single `Preset` dropdown
(`simple_preset_var`) plus a preset-row **Open output** checkbox
(`simple_open_output_check`, shares `open_after_convert_var`); selecting a preset
fans its fields onto the underlying vars via `layout.apply_preset_to_gui` and
persists the choice via `set_selected_preset`. The selector is hidden when
`load_presets()` returns `[]` (manual resolution checkboxes return). **Advanced
mode** adds a management strip (a `SegmentedChoice` preset row + **Save as… / Update / Delete**):
editing any knob flips the selection to **"Custom"** via `presets.match_preset`. That row is
buttons rather than a dropdown so every preset is visible at once; **Custom** is a real option in
it, and because presets can be added, renamed, reordered or deleted while the window is open,
`refresh_preset_dropdowns` calls `advanced_preset_control.set_options(preset_options(...))`, which
destroys and rebuilds the buttons instead of reconfiguring a `values` list. Every preset button
carries a hover summary of what the preset applies (`presets.describe_preset` →
`Option.tooltip`) — one `Label: value` line per **present** field, so a sparse preset visibly
lists only the settings it controls; **Custom**'s tooltip explains why it is selected. The
labels come from `presets.PRESET_FIELD_LABELS`/`CODEC_LABELS`, which
`preset_dialog.FIELD_SPECS` also derives from, so the tooltip and the Save-dialog checkboxes
cannot drift apart. Simple mode keeps its
`ttk.Combobox` — its 470px-wide window has no room for a row of preset-name buttons.
Save/Update open `preset_dialog.open_save_preset_dialog` — a name field plus a
checkbox per param (Create-link style) returning `(name, selected_fields)`;
`layout.build_sparse_preset` captures only the checked fields, so presets can be
partial. Update pre-checks the existing preset's `present_fields()`. **↑/↓** buttons
reorder the selected preset via `presets.move_preset`/`layout.move_advanced_preset`
(order is shared and decides the first-default). Persistence routes through
`presets.save_presets` (pure `add_preset`/`update_preset`/`delete_preset`/`move_preset`)
and refreshes every dropdown. The CLI applies `--preset NAME` before explicit flags
(`cli._apply_preset_to_args`, precedence explicit > preset > default), resolution
expanded to `--no-small`/`--small --720`/`--small --480`; `--list-presets` prints
names. The Web UI `Preset` dropdown (`server.build_interface`) inits its controls
from the default preset and persists selection on change. The OBS dock serves
`GET /presets` and, when presets exist, shows the dropdown as the primary control,
**moving** the resolution/speed selects into the ⚙️ settings panel and back on
**Custom** (`dock.html`, `obsDock.preset` `localStorage`), sending a `preset` field
that `dock_server.build_args` maps to `--preset NAME`. The dock's controls use
squared 4px corners to match OBS and cap the preset select width for a single-line row.
- **Basic options** — the panel (`layout.py`, inside `options_frame`) is a plain `ttk.Frame`
sitting flush under the Preset strip: it used to be a `ttk.Labelframe`, but an empty
`labelwidget` still reserves a full text line, which — with the frame's own `pady` — is what left
a wide gap under the presets. It is a **flat run of labelled rows with no group captions**: the
old `BASIC OPTIONS` / `SPEED & SILENCE` / `OUTPUT` / `PROCESSING & APPEARANCE` headings (and the
`add_group_heading` helper and `Heading.TLabel` style behind them) are gone, since every row is
already labelled and the captions only spent vertical space. Spacing carries the grouping
instead: `SETTING_ROW_PADY` (`(12, 0)`) above every option row, and the deliberately wider
`PRESET_ROW_PADY` (`(36, 24)`) around the Preset strip so it reads as its own band rather than as
the first of the rows. Row `pady` is therefore a shared constant, not a per-row literal — a row
that hardcodes its own gap drifts out of the rhythm the moment either constant changes.
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
is gone); **Threshold** offers 0.01/0.03/0.05/0.10 (custom 0–`THRESHOLD_MAXIMUM`, which is
0.9 — past that the detector calls almost the whole track silence — default 0.01), the group
carries one tooltip listing what each value trims, and a narrow `?` link (`HelpLink.TButton`,
`webbrowser.open` on
`THRESHOLD_ARTICLE_URL`, the telegra.ph write-up on trimming silence before speech-to-text
breaks) sits in the setting's **label**, not in the value row — `add_segmented`'s `help_url`
builds the label as a frame holding the text plus the link and exposes it as
`control.help_button`. **Mode** offers Local/Remote and carries the whole
remote group on its own line — the address `ttk.Entry` (`SERVER_URL_WIDTH`), **Discover**, then
the readiness text, in that order. **Discover** is styled `Segment.TButton` so it matches the
height and inset of the mode buttons beside it (a plain `ttk.Button` inherits ttk's eleven-character
minimum width and a taller padding, leaving it standing above the row), and the entry hugs both
neighbours with the shared `SERVER_URL_GAP` (4px) instead of the row's wider spacing, so mode
buttons + entry + Discover read as one control group. `server_url_row` and `remote_status_label` are both packed
into the Mode row's frame, so `update_processing_mode_visibility` hides them with
`pack_forget` and re-packs the row `before=remote_status_label` to keep that order. **Theme**
offers OS/Light/Dark. A trailing `…` slot on the custom-range controls swaps itself for an
inline `ttk.Entry` — Enter **and focus-out** both commit (clamped to the control's bounds), so
clicking away never discards a typed value; only Escape cancels, and a non-number falls back to
the last committed value. Once a value is committed the slot **stays** an entry so it can be edited in
place; only clicking one of the preset options clears it back to `…`. Button and entry are sized
to match (`CUSTOM_SLOT_WIDTH`, plus the near-padless `CustomSegment.TButton`/`SegmentEntry.TEntry`
styles) so the swap never reflows the row — both measure 52px. Every bound control traces its variable and is registered into
`gui._slider_updaters` through `layout.add_segmented`'s `apply_and_persist` wrapper, so
`apply_preset_to_gui` and presets applied on other surfaces keep moving the buttons exactly as
they moved the sliders they replaced — losing a key from `_slider_updaters` makes presets stop
applying silently, with no error. `gui._sliders` — the list `theme.py` iterates to restyle
`tk.Scale` widgets — now holds only the two Cut video range sliders (`cut_start_slider`,
`cut_end_slider`); a continuous time position stayed a slider because it isn't a small set of
choices. The **Silence speedup** macro row (**Silence ×10** / **Silence ×5** / **No speedup**, keyed
`silence_x10`/`silence_x5`/`compress_only`) is
also a `SegmentedChoice` (`gui.basic_preset_control`, `variable=None`, highlighted externally via
`update_basic_preset_highlight`); **Silence ×5** (`gui.reset_basic_button`) used to disable
itself when the sliders already matched the defaults, but a button rendered as "selected" must
not simultaneously be disabled, so `update_basic_reset_state` no longer disables it — clicking
it always re-applies the defaults.
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
your system file manager as soon as each job finishes. Its checkbox shares one packed row
(`checkbox_row1`) with **Simple mode** and **Cut video**, gap `layout.CHECKBOX_ROW_GAP`.
**Simple mode** is packed *first* because it is the only one of the three never hidden:
`apply_simple_mode` `pack_forget`s the other two and re-`pack`s them on the way back, and a
re-packed widget rejoins at the **end** of the row — so anything packed behind them would
shift on every toggle, and the two restore calls must stay in Open-output-then-Cut-video
order. Every `pack` of those two (build *and* both restore paths) passes the same
`CHECKBOX_ROW_GAP`, or a toggle silently collapses the spacing.
- **Cut video** — an **Advanced-only** checkbox (`apply_simple_mode` hides
`cut_check`/`cut_panel` in Simple mode) that reveals a collapsible trim panel
with two linked range sliders (start ≤ end, range `0..duration`), each paired
with an editable `ttk.Entry` time field (`cut_start_text_var`/`cut_end_text_var`)
and a tall **Convert** button that spans both slider rows. On file-select the
slider range is seeded from `get_video_duration` (ffprobe). The entries mirror
the handles as `HH:MM:SS.mmm` via `format_timecode(..., milliseconds=True)` and
accept manual edits parsed by `parse_timecode` (`_on_cut_entry_commit`), so
milliseconds can be typed directly. When **Cut video** is on (always Advanced),
dropping a file does **not** auto-convert
(`InputController._cut_requires_manual_convert`); the user reviews the trim and
clicks **Convert** (`_update_cut_convert_button` shows the button only in that
state). `_collect_arguments` ignores the trim entirely while Simple mode is on,
so a persisted `cut_enabled` flag never trims there. When applied the GUI emits
the same keep-range used by the `--cut-start`/`--cut-end` CLI flags as
`cut_start_seconds`/`cut_end_seconds` (in/out timestamps, end `0` = EOF) into
`ProcessingOptions` locally or into `service_client.send_video` for the remote
path; when off the trim args are omitted. The enabled flag plus the last
start/end values persist via `GUIPreferences` (`cut_enabled`, `cut_start`,
`cut_end`).
- **Watch directory** — an **Advanced** setting (`watch_check`,
`watch_directory_entry`, `watch_browse_button` in `advanced_frame`, auto-hidden
in Simple mode) that lets you pick a folder for `WatchController`
(`talks_reducer/gui/watch.py`) to poll (~2s) for its most-recently-modified
video. The controller owns a dynamic `watch_button` in `status_frame`, sharing
that slot with the Stop/Open/Drop button via `refresh_button`: it reads
**"Convert `<filename>`"** for a raw recording, or **"Open last"** when the
newest file's name already contains a processed marker (`_speedup` or
`_small`). The button itself is visible in both Simple and Advanced modes even
though the folder chooser is Advanced-only. The enabled flag and chosen path
persist via `GUIPreferences` (`watch_enabled`, `watch_directory`).
- **Advanced** — reveals optional controls for the output path, temp folder,
timing/audio knobs mirrored from the command line, and an appearance picker
that can force dark or light mode or follow your operating system.
- **Check updates** — a platform-gated button (`update_checker.is_update_check_supported()`
returns `True` on Windows and macOS). On **Windows** the button lives in the
always-visible `button_frame` and downloads/launches the release installer, then
closes the GUI (`_on_download_complete` schedules `_on_close` when
`sys.platform == "win32"`) so the installer can overwrite the running exe. On
**macOS** `layout.py` instead places `check_updates_button` +
`update_status_label` inside `advanced_frame` (under Advanced settings); when a
newer release is found `_on_update_check_complete` uses
`update_checker.build_update_message(version, platform)` to show
`New version {v} is available! Update with: brew upgrade --cask talks-reducer`
plus a Releases-page link, and never wires `_download_and_install_update`
(macOS builds are unsigned and installed via the `popstas/homebrew-talks-reducer`
Homebrew tap, so no auto-install). Other platforms create neither widget, so the
status helpers (`_set_update_status*`/`_clear_update_status`, all guarded by
`hasattr(self, "update_status_label")`) stay no-ops.
- **Run as server in tray** — an **Advanced** checkbox bound to
`start_in_server_tray_var` and persisted via `GUIPreferences`
(`start_in_server_tray`, default `False`). Toggling it both switches now and
persists. `GUIPreferences.save()`/`update()` return a bool and `update` rolls
back its in-memory value on a failed write, so `on_start_in_server_tray_change`
aborts the relaunch (and restores the checkbox via `_restore_server_tray_var`)
when persistence fails rather than spawning a process that would cold-start from
a stale `settings.json`. When enabled from a standalone GUI, `_apply_server_tray_toggle` calls
`spawn_detached(build_app_command("server-tray"))` (see `gui/relaunch.py`) and
closes the window; the relaunched process runs `server-tray --with-gui`, putting
the tray + Gradio server on the main thread and the GUI back as a
`--server-managed` child. When disabled from that managed child, it relaunches
`build_app_command("gui")`, best-effort stops the parent tray
(`os.kill(os.getppid(), SIGTERM)` on POSIX; `taskkill /PID <pid> /T /F` on
Windows, all `suppress(Exception)`), and closes. Seeding the var never fires the
action because `start_in_server_tray_var` is created before its `trace_add` is
installed, and a managed child never re-enters server-tray mode when enabling
(no spawn loops). `build_app_command` is
frozen-aware: in a PyInstaller bundle it returns `[sys.executable, *args]`
(e.g. `[exe, "--server", "--with-gui"]`); from source it returns
`[sys.executable, "-m", "talks_reducer.<module>", *args]`, since `-m` execution
is unavailable in the frozen `.app`. On cold start `gui/startup.py:main` honors
the persisted preference — when no `--server`/`--server-managed` flag, no
positional inputs/seeded launch, and `start_in_server_tray` is `True` (missing or
corrupt config treated as `False`), it routes into `server_tray.main(["--with-gui"])`.
The rationale for the tray-as-parent/GUI-as-child split: on macOS pystray's
`icon.run()` and Tkinter's `mainloop()` both require the process main thread and
cannot coexist in one process, so the toggle relaunches the app into whichever
arrangement is requested rather than spawning a tray thread.
- **Server mode (`--server-managed`)** — when the tray launches the GUI it passes
`--server-managed` and `--server-url <local url>`. The window then shows a
**Server:** label near **Mode** with the LAN-reachable address and a
**Connected clients** panel that polls the server's `GET /activity` endpoint
(~5s) and renders recent client requests as `HH:MM:SS  <ip>  <action>`. The
LAN-reachable address comes from `_resolve_host_ip()` in `server.py`, which
prefers a `192.168.x.x` interface address over a VPN tunnel (`10.x`) or
container bridge (`172.16–31.x`); `_iter_interface_ipv4_addresses` enumerates
interfaces, using a Linux `SIOCGIFADDR` fallback since the hostname there often
resolves only to loopback. Both are
hidden in the standalone GUI. While downloading a remote result the GUI shows a
refreshing **Waiting for download…** status during the processing→download gap,
and the download bar advances to 100% only once. While a remote upload or
download is streaming the status appends the live transfer rate (e.g.
`Uploading: 55%, 5.5 MB/s`), computed by `_TransferSpeedTracker` in
`gui/remote.py`.

`service_client.send_video` builds the gradio `Client` with `download_files=False`
(`_build_client`) and streams the single processed file itself
(`_download_filedata`, 1 MiB chunks) — gradio would otherwise auto-download the
same file twice (the `gr.Video` preview and the `gr.File` output). Byte-level
upload/download progress is coalesced to ~10 Hz via `_ThrottledEmitter` so the
per-chunk callbacks don't flood the UI thread. The server's queue concurrency is
configurable via `--concurrency` (`server_args.py` → `build_interface`), but file
transfers bypass the queue so it only affects concurrent processing.

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
  - `glue.py` concatenates several inputs into one file before the pipeline runs (`--glue`, GUI confirmation). It stream-copies only when `inputs_can_be_copied` reports matching probes — FFmpeg will happily copy parts of different resolutions into a file whose frames change size mid-playback — and otherwise re-encodes through the concat filter, scaling every part to the first one's frame size.
  - `ffmpeg.py` discovers the FFmpeg binary, checks GPU encoder availability (`check_cuda_available` for NVENC, `check_videotoolbox_available` for Apple VideoToolbox), and assembles command strings.
  - `gui/progress.py` defines `STAGE_PROGRESS_RANGES` and `map_stage_progress()`, which map each remote pipeline stage onto fixed GUI percentage bands (`Uploading:` 0–5%, `Extracting audio:` 5–20%, `Audio processing:` 20–35%, `Generating final` 35–100%).
  - `gui/segmented.py` defines `SegmentedChoice`, the button-row control (with an optional custom-value `…` slot) used throughout the Advanced "Basic options" panel in place of `tk.Scale` sliders.
- `requirements.txt` — Python dependencies for local development.
- `default.nix` — reproducible environment definition for Nix users.
- `CONTRIBUTION.md` — development workflow, formatting expectations, and release checklist.
- `AGENTS.md` — maintainer tips and coding conventions for this repository.
- `.github/workflows/ci.yml` — CI pipeline: tests, builds, releases, and automatic Homebrew tap updates on tagged releases.

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

## GUI Progress Convention

- Update the desktop progress bar through `TalksReducerGUI._set_progress_monotonic()`, which clamps each value against the synchronous `_progress_floor` so the bar never moves backwards (e.g. when the final encode falls back from GPU to CPU and restarts its stage at zero). Call `_reset_progress_baseline()` to re-base the floor for the next file in a batch.
- Never read `progress_var` from a worker thread to compute the next value: it is applied via a queued `root.after` callback and will be stale. `_progress_floor` is the single source of truth.
- Every progress channel — structured `progress.advance`, remote streaming, frame/time encode parsing, log-only `Task: NN%` milestones, and the synthetic audio timer — must route through `_set_progress_monotonic()`.
- `gui/taskbar.py` mirrors the bar onto the **Windows** taskbar button via `ITaskbarList3` (pure `ctypes`, no new dependency). `create_taskbar_progress()` returns a null-backed no-op on every other platform and on any COM failure, so call sites need no platform guard. `TaskbarProgress` holds terminal states: `finish()`/`set_error()` set a hold that drops later `set_value()` calls, and only `on_focus()` (bound to `<FocusIn>` on `root`), `begin()`, or `clear()` release it — that hold is what keeps 100% visible until the user returns to the window. Hooks: `_start_run` → `begin()`; `_reset_progress_baseline` → `begin()` (via `_schedule_on_ui_thread`, since it is called from the worker thread and COM lives in the Tk main thread's apartment); `_set_progress`'s updater → `set_value()`; `_set_status` → `_update_taskbar_for_status()` (a focused window → `clear()` outright, otherwise success → `finish()`, `Error` → `set_error()`; `Aborted` always → `clear()`); `_on_close` → `clear()`.
- `_set_status` also calls `_ring_completion_bell()`, which rings Tk's `root.bell()` on a success or `Error` status and stays silent for `Aborted`, for every non-terminal status, and whenever `_is_window_focused()` is true. It is cross-platform (unlike the taskbar) and `suppress(Exception)`-guarded, since a display without a bell raises rather than staying quiet.
- `_is_window_focused()` wraps `root.focus_displayof()` — `None` for another app's window, and it *raises* when the focused window is one Tk cannot name. Both mean "not us", and a raise reports unfocused so an outcome is announced rather than silently swallowed. Both `_update_taskbar_for_status()` and the bell gate on it.
- `TaskbarProgress.clear()` deactivates the indicator rather than merely releasing the hold, and only `begin()` reactivates it. A finished run reports itself as `_set_status("success")` immediately followed by `_set_progress(100)` (`summaries.py`), both queued through `root.after`; without the gate the trailing progress update repaints the bar a focused status just cleared, stranding a 100% indicator forever.

## GUI Layout Convention

- **The GUI test suite runs against hand-written widget stubs (`WidgetStub`/`WidgetFactory` in `tests/test_gui_layout.py`), never real Tk, and those stubs model widget *API calls* but not *geometry*.** Cell occupancy under `columnspan`, slack distribution from `columnconfigure(weight=...)`, and the `TclError` from calling `grid()` on a `pack`-managed widget are all invisible to them. Every layout defect that reached review on the segmented-settings branch was in that one class: two controls landing on the same grid row, a `?` button drifting ~680px right because a `columnspan=2` neighbour absorbed the row's slack, and a status label hidden with the wrong geometry manager. Assume a green suite says nothing about layout; check a real window, and prefer extending `test_basic_options_frame_grid_positions_do_not_collide` (which expands `columnspan`/`rowspan` into per-cell occupancy) over adding another stub assertion.
- **ttk's `TButton` style carries `width: -11`** — a minimum of eleven characters that every
derived style inherits. A one-glyph "?" rendered 89px wide until `HelpLink.TButton` set
`width=0`, and segment buttons were 103px instead of 32px. Any content-width button style in
this project must set `width=0` explicitly.
- **Never mix geometry managers on one widget.** Hide a grid-managed widget with `grid_remove()` and a packed one with `pack_forget()`; the stubs accept either, real Tk raises.
- **A muted colour is not automatically a readable one.** Both palettes in `theme.py` carry the same `accent` (`#2563eb`) so the selected-segment blue is identical in light and dark, and a dedicated `disabled_foreground` (`#6b7280` light, `#9ca3af` dark) that the `Segment`/`CustomSegment` disabled maps use. They used to reuse `border`, which is a *line* colour: at 1.5:1 against the dark surface it left disabled **Remote** unreadable rather than merely dimmed. Pick disabled text from a text ramp, not from the border tone.
- **Before hiding a control, enumerate every path that could still need it.** `update_processing_mode_visibility` hides the Server URL row outside remote mode, but that row holds the only URL entry and the only **Discover** button, and `_update_processing_mode_state` disables **Remote** until a URL exists — hiding it unconditionally made remote mode permanently unreachable on a fresh config. The row therefore also shows whenever `server_url_var` is empty. Two individually reasonable rules produced a deadlock; a hidden control is only safe when some other path can still reveal it.
- **Recompute visibility on the state that owns it, not on every write.** `server_url_var` traces into `_update_processing_mode_state`, so recomputing the row on URL changes hid the field mid-keystroke. `_update_processing_mode_state(update_row=False)` from `on_server_url_change` keeps row visibility a function of the *mode* alone.

## Segmented Control Conventions

Rules for `SegmentedChoice` (`talks_reducer/gui/segmented.py`) and its `layout.add_segmented` wrapper.

- The inline `ttk.Entry` that replaces the `…` button must match that button's width, so committing or cancelling an edit never reflows the row.
- Help and article links belong on the setting's **label**, not as an extra widget in the value row. The value row holds values.
- A choice control sizes itself to its content plus 10px padding rather than a fixed width.
- A control backed by user-authored options (presets) carries a **Custom** entry that selects itself whenever the live values match no stored option — the same reverse-match `presets.match_preset` already drives for the Advanced dropdown.
- `set_value` must clamp to the control's `CustomSpec` bounds. It is the programmatic entry point presets arrive through, and an unclamped value silently diverges from what the buttons display and from what gets persisted.
- `set_value` deliberately does **not** fire `on_change`; `layout.add_segmented`'s `apply_and_persist` wrapper restores the persistence half at the integration layer. Keep that split — firing `on_change` from `set_value` would re-enter through the variable trace.

