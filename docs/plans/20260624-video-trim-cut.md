# Video Trim (Cut Begin/End) Before Converting

## Overview
- Add an optional **trim** step that keeps only a chosen `[start, end]` fragment of each input
  before the speed-up pipeline runs, dropping leading/trailing portions.
- Semantics: **keep-range in/out timestamps** (like a video editor). `--cut-start` is the
  timestamp to start keeping; `--cut-end` is the timestamp to stop keeping. Both accept either
  seconds (`12.5`) or `HH:MM:SS[.ms]` (`00:01:45`). Defaults: start `0`, end `0` meaning
  "until end of video" (i.e. no trim when both are `0`).
- Surfaces in all three UIs:
  - **CLI** — `--cut-start` / `--cut-end`.
  - **Desktop GUI (Tkinter)** — a **"Cut video"** checkbox that reveals two linked range
    sliders (start/end) plus a live **frame-scrub thumbnail** (a still extracted via ffmpeg and
    rendered with Pillow) so the user can pick the fragment after selecting a file. Available in
    both Simple and Advanced layouts.
  - **Web UI (gradio)** — a "Cut video" checkbox + start/end number/slider inputs, using the
    existing `gr.Video` player for scrubbing.
- Benefit: removes intros/outros/dead air before the (expensive) speed-up encode, so users don't
  need a separate editor pass.

## Context (from discovery)
- Files/components involved:
  - `talks_reducer/models.py` — `ProcessingOptions` frozen dataclass (fields at L43–59).
  - `talks_reducer/cli.py` — `_build_parser()` and `CliApplication.run()` option wiring.
  - `talks_reducer/ffmpeg.py` — `build_extract_audio_command()` (L549) and
    `build_video_commands()` (L576); ffprobe helpers (`get_ffprobe_path` L201).
  - `talks_reducer/pipeline.py` — `speed_up_video()` (L160); uses `original_duration` (L211)
    and `frame_count` (L212) from `_extract_video_metadata` for progress/encode-duration math
    (L262–264, L445–499). **These must be adjusted when a trim is active.**
  - `talks_reducer/server.py` — `process_video()` (L740) and `build_interface()` (L880).
  - `talks_reducer/gui/app.py` — variable init + `_collect_arguments()` +
    `_create_processing_options()`; `talks_reducer/gui/layout.py` — Simple/Advanced layout
    builders; `talks_reducer/gui/preferences.py` — persisted prefs.
- Related patterns found:
  - Boolean/scalar options flow CLI → dict (None-filtered) → `ProcessingOptions(**kwargs)` →
    `speed_up_video`. GUI mirrors via `_collect_arguments()` → `_create_processing_options()`.
  - GUI vars use `tk.*Var` + `trace_add("write", ...)` to persist via `GUIPreferences.update`.
  - Tests are per-module: `tests/test_cli.py`, `test_ffmpeg.py`, `test_pipeline.py`,
    `test_gui_app.py`, `test_gui_layout.py`, `test_server.py` (pytest, `tmp_path`/`monkeypatch`).
- Dependencies identified: **Pillow (≥9.0)** and **gradio (≥4.0)** are already required — the
  chosen GUI approach needs **no new dependency**.

## Development Approach
- **Testing approach**: **TDD (tests first)** for every task.
- Complete each task fully before moving to the next; small, focused changes.
- **CRITICAL: every task MUST include new/updated tests** (success + error/edge cases) as
  separate checklist items.
- **CRITICAL: all tests must pass before starting the next task.**
- **CRITICAL: update this plan file when scope changes during implementation.**
- Maintain backward compatibility: with no trim flags / checkbox off, behaviour is byte-for-byte
  unchanged (no `-ss`/`-t` injected).
- Formatting: run `black` and `isort` before committing (per CLAUDE.md/AGENTS.md).

## Testing Strategy
- **Unit tests**: required for every task (parsing, ffmpeg command construction, pipeline
  metadata adjustment, GUI var wiring, server param wiring).
- **E2E / UI tests**: this project has no Playwright/Cypress suite. GUI and gradio behaviour are
  covered by the existing headless widget/interface tests (`test_gui_*`, `test_server.py`); add
  to those with the same rigor (must pass before next task). Real video playback / thumbnail
  rendering is verified manually (see Post-Completion).

## Progress Tracking
- Mark completed items with `[x]` immediately when done.
- Add newly discovered tasks with ➕ prefix; document blockers with ⚠️ prefix.
- Keep the plan in sync with actual work.

## What Goes Where
- **Implementation Steps** (`[ ]`): code, tests, docs achievable in this repo.
- **Post-Completion** (no checkboxes): manual visual checks of the thumbnail/player and real
  trimmed-output inspection.

## Implementation Steps

### Task 1: Timecode parsing helper
- [x] create `talks_reducer/timecode.py` with `parse_timecode(value) -> float` accepting a
      float/int seconds value or a `HH:MM:SS[.ms]` / `MM:SS` / `SS` string, returning seconds
- [x] add `format_timecode(seconds) -> str` (→ `HH:MM:SS`) for GUI/log display
- [x] raise `ValueError` for negative or malformed input
- [x] write tests in `tests/test_timecode.py` for valid forms (`"12.5"`, `"01:45"`, `"00:01:45.5"`, numeric)
- [x] write tests for error cases (negative, `"aa:bb"`, empty)
- [x] run `pytest tests/test_timecode.py` — must pass before Task 2

### Task 2: Add trim fields to ProcessingOptions
- [x] add `cut_start_seconds: float = 0.0` and `cut_end_seconds: float = 0.0` to
      `ProcessingOptions` in `talks_reducer/models.py`
- [x] document the keep-range semantics in the class/field docstring (end `0.0` = until EOF)
- [x] write tests in `tests/test_models.py` (or existing model test) asserting defaults and that
      a constructed options object carries the values
- [x] run `pytest tests/test_models.py` — must pass before Task 3

### Task 3: CLI options `--cut-start` / `--cut-end`
- [ ] add `--cut-start` and `--cut-end` to `_build_parser()` in `talks_reducer/cli.py`
      (type via `parse_timecode`, `dest="cut_start_seconds"` / `cut_end_seconds`, default `0.0`)
- [ ] wire both into the `option_kwargs` built in `CliApplication.run()` so they reach
      `ProcessingOptions`
- [ ] validate `cut_end == 0 or cut_end > cut_start`, else exit with a clear error message
- [ ] write tests in `tests/test_cli.py`: parsing seconds and `HH:MM:SS`, values reach options
- [ ] write tests for invalid range (`--cut-start 30 --cut-end 10`) producing an error
- [ ] run `pytest tests/test_cli.py` — must pass before Task 4

### Task 4: Inject trim into ffmpeg commands
- [ ] extend `build_extract_audio_command()` (`talks_reducer/ffmpeg.py`) with
      `cut_start_seconds`/`cut_end_seconds` params, emitting input-level `-ss <start>` and
      `-t <end-start>` (use `-t duration`, not `-to`, to avoid the `-ss`+`-to` relativity gotcha)
- [ ] extend `build_video_commands()` the same way so audio and video are trimmed identically
- [ ] when `cut_end == 0`, emit only `-ss <start>` (trim to EOF); when both `0`, emit nothing
- [ ] write tests in `tests/test_ffmpeg.py`: command contains `-ss`/`-t` with correct duration,
      and is unchanged when no trim is set
- [ ] write tests for start-only (no `-t`) and full-range cases
- [ ] run `pytest tests/test_ffmpeg.py` — must pass before Task 5

### Task 5: Wire trim through the pipeline + fix duration/frame math
- [ ] pass `options.cut_start_seconds`/`cut_end_seconds` from `speed_up_video()` into both
      ffmpeg command builders (`talks_reducer/pipeline.py`)
- [ ] compute an **effective duration** = `(cut_end or original_duration) - cut_start` and use it
      (instead of full `original_duration`) for progress estimation and final-encode frame/
      duration math (L262–264, L445–499) so the progress bar and "target duration" are correct
- [ ] adjust `frame_count`/`estimated_total_frames` to the trimmed span (scale by
      effective/original duration, or recompute from effective duration × frame_rate)
- [ ] clamp/validate the trim against `original_duration` (cap `cut_end` at EOF; ignore trim that
      would yield ≤ 0 length, logging a warning)
- [ ] write tests in `tests/test_pipeline.py` (mock ffmpeg/metadata) asserting builders receive
      the trim and that effective duration/frame estimates reflect the trimmed span
- [ ] write tests for the no-trim path (unchanged behaviour) and the cap-at-EOF case
- [ ] run `pytest tests/test_pipeline.py` — must pass before Task 6

### Task 6: Web UI (gradio) trim controls
- [ ] add a **"Cut video"** `gr.Checkbox` and `cut_start`/`cut_end` inputs (sliders or
      `gr.Number`, seconds) to `build_interface()` in `talks_reducer/server.py`
- [ ] add `cut_start_seconds`/`cut_end_seconds` params to `process_video()` and map them into
      the `ProcessingOptions` it builds (only applied when the checkbox is on)
- [ ] add the new components to the `inputs=[...]` list feeding `process_video`
- [ ] write tests in `tests/test_server.py`: `process_video` honours trim args and ignores them
      when the checkbox is off
- [ ] write tests asserting `build_interface()` exposes the new components
- [ ] run `pytest tests/test_server.py` — must pass before Task 7

### Task 7: Desktop GUI — state, preferences, arg collection
- [ ] add `cut_enabled_var` (`BooleanVar`), `cut_start_var`, `cut_end_var` (`DoubleVar`) in
      `TalksReducerGUI.__init__` (`talks_reducer/gui/app.py`), seeded from preferences with
      `trace_add("write", ...)` callbacks
- [ ] add a `_on_cut_change` handler persisting the three values via `GUIPreferences.update`
      (extend `gui/preferences.py` defaults/keys: `cut_enabled`, `cut_start`, `cut_end`)
- [ ] extend `_collect_arguments()` / `_create_processing_options()` to include
      `cut_start_seconds`/`cut_end_seconds` **only when `cut_enabled_var` is true**
- [ ] write tests in `tests/test_gui_app.py`: args include trim when enabled, omit when disabled,
      and preferences round-trip
- [ ] run `pytest tests/test_gui_app.py` — must pass before Task 8

### Task 8: Desktop GUI — frame-scrub thumbnail + range sliders
- [ ] add `build_extract_frame_command(input_file, timestamp, output_image, ffmpeg_path)` to
      `talks_reducer/ffmpeg.py` (`-ss <t> -i <in> -frames:v 1 <out.jpg>`) and a
      `get_video_duration(path)` ffprobe helper, both with tests in `tests/test_ffmpeg.py`
- [ ] in `talks_reducer/gui/layout.py`, build a collapsible **Cut video** panel shown when the
      checkbox is on: two linked `ttk.Scale` sliders (start ≤ end, range `0..duration`) and a
      `Label` hosting a Pillow `ImageTk` thumbnail; available in **both Simple and Advanced**
- [ ] in `app.py`, on file-select set the slider range from `get_video_duration`; debounce slider
      drags to refresh the thumbnail (extract frame at the active handle, render with Pillow);
      guard against missing ffmpeg/ffprobe by hiding the preview gracefully
- [ ] write tests in `tests/test_gui_layout.py`/`test_gui_app.py` for panel construction, the
      enable/disable visibility toggle, slider clamping (start ≤ end), and the duration→range wiring
      (mock frame extraction; no real rendering in tests)
- [ ] write tests for the no-ffmpeg fallback (panel still constructs, preview hidden)
- [ ] run `pytest tests/test_gui_layout.py tests/test_gui_app.py` — must pass before Task 9

### Task 9: Verify acceptance criteria
- [ ] verify CLI, web UI, and desktop GUI all produce a correctly trimmed output for a sample
      keep-range, and that audio stays in sync with video
- [ ] verify Simple mode (desktop GUI) and the gradio UI expose and apply the trim
- [ ] verify no-trim path is unchanged (no `-ss`/`-t` emitted)
- [ ] run the full unit suite (`pytest`)
- [ ] run `black` and `isort` — formatting clean
- [ ] verify coverage of new modules/functions meets project standard

### Task 10: Documentation
- [ ] update `README.md` with the `--cut-start`/`--cut-end` CLI options and the GUI/web "Cut
      video" controls
- [ ] update the **Graphical Interface** section in `CLAUDE.md`/`AGENTS.md` describing the Cut
      video checkbox, range sliders, and frame-scrub thumbnail (Simple + Advanced)

*Note: ralphex automatically moves completed plans to `docs/plans/completed/`.*

## Technical Details
- **Trim model:** keep `[start, end]`. ffmpeg input-level `-ss <start> -t <end-start>` on **both**
  the audio-extract and final-video commands keeps streams aligned. `-t` (duration) is used
  rather than `-to` because `-to` combined with a pre-input `-ss` is interpreted inconsistently
  across ffmpeg versions.
- **Timecode:** `parse_timecode` accepts `SS(.ms)`, `MM:SS`, `HH:MM:SS(.ms)`, or numeric seconds.
- **Pipeline math:** effective length = `(cut_end or original_duration) - cut_start`. Progress
  estimation and final-encode frame/duration calculations switch to the effective length so the
  monotonic progress bar and logged "target duration" remain accurate (see GUI Progress
  Convention in CLAUDE.md — all progress still routes through `_set_progress_monotonic`).
- **GUI preview:** Pillow (`ImageTk.PhotoImage`) renders a single ffmpeg-extracted frame; slider
  drags are debounced to avoid spawning an ffmpeg process per pixel. Two `ttk.Scale` widgets
  emulate a range selector with a `start ≤ end` constraint.
- **Defaults / backward compat:** start `0`, end `0` ⇒ no trim ⇒ no ffmpeg changes. GUI checkbox
  off ⇒ trim args omitted entirely.

## Post-Completion
*Manual / external verification — informational only, no checkboxes.*

**Manual verification:**
- Drop a real video in the desktop GUI, enable **Cut video**, drag the start/end sliders, and
  confirm the thumbnail updates to the correct frames and the exported file is trimmed to the
  selected fragment with in-sync audio.
- Repeat in the gradio web UI using the embedded player + start/end inputs.
- Sanity-check a trimmed CLI run (`--cut-start 00:00:10 --cut-end 00:01:00`) and confirm progress
  reporting reflects the trimmed length.
- Confirm behaviour is unchanged when the feature is off.
