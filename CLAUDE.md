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
- **Advanced** — reveals optional controls for the output path, temp folder,
timing/audio knobs mirrored from the command line, and an appearance picker
that can force dark or light mode or follow your operating system.
- **Server mode (`--server-managed`)** — when the tray launches the GUI it passes
`--server-managed` and `--server-url <local url>`. The window then shows a
**Server:** label near **Processing mode** with the LAN-reachable address and a
**Connected clients** panel that polls the server's `GET /activity` endpoint
(~5s) and renders recent client requests as `HH:MM:SS  <ip>  <action>`. Both are
hidden in the standalone GUI. While downloading a remote result the GUI shows a
refreshing **Waiting for download…** status during the processing→download gap,
and the download bar advances to 100% only once.

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

