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
- **Advanced** — reveals optional controls for the output path, temp folder,
timing/audio knobs mirrored from the command line, and an appearance picker
that can force dark or light mode or follow your operating system.
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

