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
- **Presets** — user-named bundles of processing settings (`resolution`,
`silent_speed`, `sounded_speed`, `silent_threshold`, `video_codec`) stored in the
shared `settings.json` (`presets` key) via `talks_reducer/presets.py` and applied
read-only on every surface (Simple mode, Web UI, OBS dock, CLI `--preset`). Presets
are **sparse**: every value field on `Preset` is `Optional`, `to_dict()` stores only
the fields that are set, and `preset.present_fields()` reports them. Apply/CLI/match
all skip absent fields (`apply_preset_to_gui`, `_apply_preset_to_args`,
`preset_to_web_controls` return sparse control maps, `match_preset` compares only
present fields — a zero-field preset never matches). `load_presets()` seeds three
fully-populated `DEFAULT_PRESETS` on first run when the key is absent; an emptied
list persists as `[]`. Each surface opens on the remembered `selected_preset`, else
the first preset (`layout.seed_initial_preset`, `server.resolve_initial_web_preset`,
dock `populatePresetDropdown`). **Simple mode** replaces the old
`simple_speedup_frame`/`simple_codec_frame` with a single `Preset` dropdown
(`simple_preset_var`) plus a preset-row **Open output** checkbox
(`simple_open_output_check`, shares `open_after_convert_var`); selecting a preset
fans its fields onto the underlying vars via `layout.apply_preset_to_gui` and
persists the choice via `set_selected_preset`. The selector is hidden when
`load_presets()` returns `[]` (manual resolution checkboxes return). **Advanced
mode** adds a management strip (`Preset` dropdown + **Save as… / Update / Delete**):
editing any knob flips the dropdown to **"Custom"** via `presets.match_preset`.
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
- **Small video** — toggles the `--small` preset used by the CLI.
- **Open after convert** — controls whether the exported file is revealed in
your system file manager as soon as each job finishes.
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
**Server:** label near **Processing mode** with the LAN-reachable address and a
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
  - `ffmpeg.py` discovers the FFmpeg binary, checks CUDA availability, and assembles command strings.
  - `gui/progress.py` defines `STAGE_PROGRESS_RANGES` and `map_stage_progress()`, which map each remote pipeline stage onto fixed GUI percentage bands (`Uploading:` 0–5%, `Extracting audio:` 5–20%, `Audio processing:` 20–35%, `Generating final` 35–100%).
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
- Automatically detects NVENC availability, so you no longer need to pass `--cuda`

## Processing Pipeline

1. Validate that each input file contains an audio stream using `ffprobe`.
2. Extract audio and calculate loudness to identify silent regions.
3. Stretch the non-silent segments with `audiotsm` to maintain speech clarity.
4. Stitch the processed audio and video together with FFmpeg, using NVENC if the GPU encoders are detected.

## GUI Progress Convention

- Update the desktop progress bar through `TalksReducerGUI._set_progress_monotonic()`, which clamps each value against the synchronous `_progress_floor` so the bar never moves backwards (e.g. when the final encode falls back from GPU to CPU and restarts its stage at zero). Call `_reset_progress_baseline()` to re-base the floor for the next file in a batch.
- Never read `progress_var` from a worker thread to compute the next value: it is applied via a queued `root.after` callback and will be stale. `_progress_floor` is the single source of truth.
- Every progress channel — structured `progress.advance`, remote streaming, frame/time encode parsing, log-only `Task: NN%` milestones, and the synthetic audio timer — must route through `_set_progress_monotonic()`.
- `gui/taskbar.py` mirrors the bar onto the **Windows** taskbar button via `ITaskbarList3` (pure `ctypes`, no new dependency). `create_taskbar_progress()` returns a null-backed no-op on every other platform and on any COM failure, so call sites need no platform guard. `TaskbarProgress` holds terminal states: `finish()`/`set_error()` set a hold that drops later `set_value()` calls, and only `on_focus()` (bound to `<FocusIn>` on `root`), `begin()`, or `clear()` release it — that hold is what keeps 100% visible until the user returns to the window. Hooks: `_start_run` → `begin()`; `_reset_progress_baseline` → `begin()` (via `_schedule_on_ui_thread`, since it is called from the worker thread and COM lives in the Tk main thread's apartment); `_set_progress`'s updater → `set_value()`; `_set_status` → `_update_taskbar_for_status()` (a focused window → `clear()` outright, otherwise success → `finish()`, `Error` → `set_error()`; `Aborted` always → `clear()`); `_on_close` → `clear()`.
- `_set_status` also calls `_ring_completion_bell()`, which rings Tk's `root.bell()` on a success or `Error` status and stays silent for `Aborted`, for every non-terminal status, and whenever `_is_window_focused()` is true. It is cross-platform (unlike the taskbar) and `suppress(Exception)`-guarded, since a display without a bell raises rather than staying quiet.
- `_is_window_focused()` wraps `root.focus_displayof()` — `None` for another app's window, and it *raises* when the focused window is one Tk cannot name. Both mean "not us", and a raise reports unfocused so an outcome is announced rather than silently swallowed. Both `_update_taskbar_for_status()` and the bell gate on it.
- `TaskbarProgress.clear()` deactivates the indicator rather than merely releasing the hold, and only `begin()` reactivates it. A finished run reports itself as `_set_status("success")` immediately followed by `_set_progress(100)` (`summaries.py`), both queued through `root.after`; without the gate the trailing progress update repaints the bar a focused status just cleared, stranding a 100% indicator forever.

