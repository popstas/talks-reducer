# Add "mp3" Option to the Codec Selector (Audio-Only Output)

## Overview
- Add `mp3` as a fourth value of the existing **Video codec** selector (alongside
  `h264`, `hevc`, `av1`) across the CLI (`--video-codec mp3`), the desktop GUI, the
  gradio web/server UI, and the remote client path.
- When `mp3` is selected, the pipeline produces an **audio-only `.mp3` file** instead
  of a video: the talk is still silence-trimmed and speed-adjusted exactly as today,
  but the final render encodes the processed audio with `libmp3lame` and writes
  `<name>.mp3` rather than `<name>.mp4`.
- Quality is a fixed sensible default (`libmp3lame -q:a 2`, ~190 kbps VBR). No new
  bitrate/quality knob (YAGNI).
- Because `video_codec` already flows end-to-end (CLI → `ProcessingOptions` → pipeline
  → ffmpeg; GUI/server widgets → `service_client.send_video`), the change is mostly:
  (1) add `mp3` to every codec choice list/guard-set, (2) pick the `.mp3` extension in
  output naming, and (3) branch the pipeline to an audio-only ffmpeg command before
  `build_video_commands` (whose guard would otherwise coerce unknown codecs to `hevc`).

## Context (from discovery)
- Files/components involved:
  - `talks_reducer/pipeline.py` — `speed_up_video()` final-render call at lines ~486–504;
    `_input_to_output_filename()` at lines 653–694 (extension hardcoded `.mp4` at line 694).
  - `talks_reducer/ffmpeg.py` — `build_video_commands()` at lines 669–928; codec guard at
    line 726 coerces anything not in `{h264,hevc,av1}` to `hevc` (mp3 must bypass this).
  - `talks_reducer/cli.py` — `--video-codec` arg + `choices` at lines 106–112; option
    assembly at lines 335–336.
  - `talks_reducer/gui/layout.py` — `CODEC_LABELS` dict at line 78; advanced-mode codec
    radiobuttons at lines 417–423; simple-mode codec combobox uses `CODEC_LABELS.values()`.
  - `talks_reducer/gui/app.py` — codec guard-sets at lines 291, 1193, 1304 (default reset
    to `h264`).
  - `talks_reducer/gui/preferences.py` — `on_video_codec_change` guard-set at line 170.
  - `talks_reducer/server.py` — codec guard at line 773; `codec_dropdown` choices at
    lines 930–938; UI help markdown at line 911.
  - `talks_reducer/service_client.py` — `send_video(video_codec=...)` already forwarded
    (lines 480, 520); remote `--video-codec` `choices` near line 886.
  - `talks_reducer/models.py` — `ProcessingOptions.video_codec` field already exists
    (no new field needed; `mp3` is just a new value).
- Related patterns found: the `video_codec` string option already threads through all
  surfaces; we extend the allowed value set rather than adding a new option.
- Dependencies identified: `libmp3lame` must be available in the bundled/static and
  global ffmpeg builds (static-ffmpeg includes lame; verify in Task 2 test).

## Development Approach
- **Testing approach**: TDD (tests first) — write/extend the failing test, then implement.
- Complete each task fully before moving to the next.
- Make small, focused changes.
- **CRITICAL: every task MUST include new/updated tests** for code changes in that task
  (success + error/edge scenarios), listed as separate checklist items.
- **CRITICAL: all tests must pass before starting next task** — no exceptions.
- **CRITICAL: update this plan file when scope changes during implementation.**
- Run `black` and `isort` before committing (per `CLAUDE.md`).
- Maintain backward compatibility: default codec stays `hevc`; existing `.mp4` behavior
  for `h264`/`hevc`/`av1` is unchanged.

## Testing Strategy
- **Unit tests**: required for every task. Run with `.venv` active:
  `python -m pytest tests/ -q`.
- **E2E tests**: this project has no Playwright/Cypress UI e2e suite; end-to-end
  verification is a real ffmpeg conversion run, covered as a Post-Completion manual check.
  GUI/server logic is covered by the existing `tests/test_gui_app.py`,
  `tests/test_gui_preferences.py`, and `tests/test_server.py` unit suites.
- Keep tests fast by mocking `dependencies.build_audio_only_command` /
  `run_timed_ffmpeg_command` where the existing pipeline tests already mock ffmpeg.

## Progress Tracking
- Mark completed items with `[x]` immediately when done.
- Add newly discovered tasks with ➕ prefix.
- Document issues/blockers with ⚠️ prefix.
- Keep this plan in sync with actual work.

## What Goes Where
- **Implementation Steps** (`[ ]`): code, tests, docs achievable in this repo.
- **Post-Completion** (no checkboxes): real ffmpeg conversion smoke test, manual GUI/web
  click-through, codec-availability verification on each platform build.

## Implementation Steps

### Task 1: Audio-only output filename (`.mp3` extension)
- [x] In `talks_reducer/pipeline.py` `_input_to_output_filename()` (lines 653–694),
      compute the extension from the normalized codec: `.mp3` when
      `normalized_codec == "mp3"`, otherwise `.mp4` (replace the hardcoded `.mp4` at
      line 694). Keep the existing suffix-token logic (e.g. `_speedup`) so output is like
      `talk_speedup.mp3`.
- [x] For `mp3`, do not append a redundant `mp3` codec suffix token (the extension already
      conveys it) — adjust `include_codec_suffix` so `normalized_codec == "mp3"` is excluded.
- [x] In `tests/test_pipeline.py`, extend the `test_input_to_output_filename`
      parametrization with `video_codec="mp3"` cases asserting a `.mp3` extension
      (with speedup, and with neutral speeds).
- [x] Add an error/edge test: codecs other than `mp3` still yield `.mp4`.
- [x] Run `python -m pytest tests/test_pipeline.py -q` — must pass before next task.

### Task 2: Audio-only ffmpeg command builder
- [x] In `talks_reducer/ffmpeg.py`, add `build_audio_only_command(input_file, audio_file,
      output_file, *, ffmpeg_path=None, cut_start_seconds=0.0, cut_end_seconds=0.0,
      quality="2")` that returns a single command string:
      `"<ffmpeg>" -y [trim args] -i "<src>" -vn -map 0:a:0 -c:a libmp3lame -q:a 2
      "<output>" -loglevel warning -stats -hide_banner`. Prefer `audio_file` (the
      processed WAV) as `<src>` when provided; otherwise use `input_file` with
      `build_trim_input_args(cut_start_seconds, cut_end_seconds)` applied. No CUDA, no
      fallback command.
- [x] Leave `build_video_commands()`' guard at line 726 unchanged (mp3 never reaches it).
- [x] In `tests/test_ffmpeg.py`, add tests asserting `build_audio_only_command` emits
      `libmp3lame`, `-q:a 2`, `-vn`, ends in the `.mp3` output path, and uses the processed
      WAV when supplied.
- [x] Add an edge test: when `audio_file` is `None`, the command reads from `input_file`
      and includes trim args when `cut_start_seconds`/`cut_end_seconds` are set.
- [x] Run `python -m pytest tests/test_ffmpeg.py -q` — must pass before next task.

### Task 3: Branch the pipeline to audio-only render for mp3
- [x] In `talks_reducer/pipeline.py` `speed_up_video()`, before the
      `build_video_commands(...)` call (lines ~486–504), branch when
      `str(options.video_codec).strip().lower() == "mp3"`: call the new
      `dependencies.build_audio_only_command(...)` with `audio_new_path` (or the input
      file when no processed audio exists), `output_path`, trim seconds, and ffmpeg path;
      set `command_str`, `fallback_command_str=None`, `use_cuda_encoder=False`. Skip the
      video filter-graph requirement check for this path.
- [x] Wire `build_audio_only_command` into the pipeline's `dependencies` namespace the
      same way `build_video_commands` is exposed (so tests can mock it).
- [x] Handle the no-audio edge: if `mp3` is requested but the input has no audio stream,
      raise a clear error (e.g. `ValueError("mp3 output requires an audio stream")`) and
      clean up the temp dir.
- [x] Confirm the post-render metadata/size step (lines 616–635) tolerates an audio-only
      output (ffprobe returns duration; frame_rate falls back to the source value).
- [x] In `tests/test_pipeline.py`, add a test that `speed_up_video` with
      `video_codec="mp3"` calls `build_audio_only_command` (not `build_video_commands`),
      writes a `.mp3` output path, and returns a `ProcessingResult`.
- [x] Add an error test for the no-audio + mp3 case.
- [x] Run `python -m pytest tests/test_pipeline.py -q` — must pass before next task.

### Task 4: CLI `--video-codec mp3`
- [x] In `talks_reducer/cli.py`, add `"mp3"` to the `--video-codec` `choices` (line 107)
      and mention mp3 (audio-only output) in the help text (lines 110–112).
- [x] Confirm the option assembly (lines 335–336) forwards `mp3` unchanged into
      `ProcessingOptions` (no extra handling expected).
- [x] In `tests/test_cli.py`, add a test that `--video-codec mp3` parses and produces
      `ProcessingOptions(video_codec="mp3")`.
- [x] Add a test that an invalid codec is still rejected by argparse `choices`.
- [x] Run `python -m pytest tests/test_cli.py -q` — must pass before next task.

### Task 5: Desktop GUI codec selector + persistence
- [x] In `talks_reducer/gui/layout.py`: add `"mp3": "mp3 (audio only)"` to `CODEC_LABELS`
      (line 78) and add `("mp3", "mp3 (audio only)")` to the advanced-mode radiobutton
      tuple (lines 417–423). The simple-mode combobox picks this up via
      `CODEC_LABELS.values()` automatically.
- [x] In `talks_reducer/gui/app.py`, add `"mp3"` to the codec guard-sets at lines 291,
      1193, and 1304 so the value is accepted on load and in `_collect_arguments`.
- [x] In `talks_reducer/gui/preferences.py`, add `"mp3"` to the guard-set in
      `on_video_codec_change` (line 170) so the choice persists.
- [x] In `tests/test_gui_app.py`, add tests that selecting `mp3` is accepted (not reset to
      `h264`) and that `_collect_arguments` emits `video_codec="mp3"`.
- [x] In `tests/test_gui_preferences.py`, add a test that `mp3` round-trips through
      preferences.
- [x] Run `python -m pytest tests/test_gui_app.py tests/test_gui_preferences.py -q` —
      must pass before next task.

### Task 6: Server (gradio) + remote client codec choice
- [x] In `talks_reducer/server.py`: add `("mp3 (audio only)", "mp3")` to `codec_dropdown`
      choices (lines 930–938), add `"mp3"` to the codec guard-set at line 773, and update
      the UI help markdown (line 911) to mention mp3 audio-only output.
- [x] In `talks_reducer/service_client.py`: add `"mp3"` to the remote `--video-codec`
      `choices` near line 886. (The `send_video(video_codec=...)` forwarding at lines 480,
      520 already passes the value through — verify no extra change needed.)
- [x] In `tests/test_server.py`, add a test that `process_video(..., video_codec="mp3")`
      produces `ProcessingOptions(video_codec="mp3")` and that the dropdown choices include
      `mp3`.
- [x] In `tests/test_service_client.py`, add a test that `--video-codec mp3` is accepted
      and forwarded in the submit args.
- [x] Run `python -m pytest tests/test_server.py tests/test_service_client.py -q` —
      must pass before next task.

### Task 7: Verify acceptance criteria
- [x] Verify mp3 selectable and functional in CLI, desktop GUI, web/server UI, and remote
      client (value reaches `ProcessingOptions`/`send_video`).
- [x] Verify output is `<name>.mp3` and other codecs remain `.mp4`.
- [x] Run the full unit suite: `python -m pytest tests/ -q` — all pass (614 passed; fixed
      a stale `test_gui_layout.py` codec-button assertion that missed mp3).
- [x] Run `black .` and `isort .` — no diffs / formatting clean.
- [x] Run any configured linter (flake8/ruff if present) — fix all issues (neither
      flake8 nor ruff is installed in this environment; skipped).

### Task 8: [Final] Update documentation
- [x] Update `README.md`: document `--video-codec mp3` and the audio-only behavior in the
      CLI options and codec sections.
- [x] Update `CLAUDE.md` GUI notes if the codec selector description needs the mp3 option
      (no change needed — CLAUDE.md has no codec-selector description to extend).
- [x] Note the new codec value in `CHANGELOG.md` context if applicable (release notes are
      generated from `feat:`-prefixed commits; this `feat:` commit supplies the context).

*Note: ralphex automatically moves completed plans to `docs/plans/completed/`.*

## Technical Details
- `ProcessingOptions.video_codec` gains an accepted value `"mp3"`; no schema change.
- Output extension decision lives solely in `_input_to_output_filename()`.
- Audio-only ffmpeg command: `libmp3lame -q:a 2 -vn -map 0:a:0`, sourcing the already
  silence-trimmed/speed-adjusted `audioNew.wav` when present (trim/speed already baked in),
  else the original input with `build_trim_input_args` applied.
- Progress: the existing `run_timed_ffmpeg_command(..., desc="Generating final:")` call is
  reused; the GUI progress bands in `gui/progress.py` need no change (final encode is fast).
- Backward compatibility: default `hevc`, existing `.mp4` flows untouched.

## Post-Completion
*Items requiring manual intervention or external systems — informational only.*

**Manual verification:**
- Run a real conversion end-to-end with `--video-codec mp3` on a sample talk and confirm a
  playable `.mp3` with trimmed silence and adjusted speed.
- Click-through the desktop GUI (simple + advanced) and the gradio web UI selecting mp3.
- Exercise the remote path (GUI/CLI → server) with mp3 to confirm the wire value works.

**External system / build verification:**
- Confirm `libmp3lame` is present in the bundled static-ffmpeg build used by releases and
  in typical global ffmpeg installs; document any platform where mp3 is unavailable.
