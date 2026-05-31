# Progress Reporting Improvements

## Overview
Implement the progress-related items from `docs/TODO.md`:
- show remote upload progress before server processing begins
- keep the remote GUI progress bar moving after audio processing
- replace imprecise synthetic audio progress with real audio-processing progress where possible
- stop stale audio progress updates as soon as video encoding starts

The original request named `data/TODO.md`, but the progress log records the user answer to use `docs/TODO.md` because `data/TODO.md` is absent.

## Context
- Files involved:
  - `talks_reducer/progress.py`
  - `talks_reducer/audio.py`
  - `talks_reducer/pipeline.py`
  - `talks_reducer/ffmpeg.py`
  - `talks_reducer/service_client.py`
  - `talks_reducer/server.py`
  - `talks_reducer/gui/progress.py`
  - `talks_reducer/gui/remote.py`
  - `talks_reducer/gui/summaries.py`
  - `talks_reducer/gui/app.py`
  - `README.md`
  - `tests/test_progress.py`
  - `tests/test_audio.py`
  - `tests/test_pipeline_service.py`
  - `tests/test_service_client.py`
  - `tests/test_server.py`
  - `tests/test_gui_progress.py`
  - `tests/test_gui_remote.py`
  - `tests/test_gui_app.py`
  - `tests/test_cli.py`
- Related patterns:
  - Pipeline progress is reported through `ProgressReporter.task()`.
  - FFmpeg frame progress is parsed in `run_timed_ffmpeg_command()`.
  - Server progress is bridged through `GradioProgressReporter` and Gradio progress events.
  - Remote CLI progress is already streamed through `service_client` `progress_callback`.
  - Remote GUI currently streams logs but does not pass a `progress_callback` into `send_video()`.
- Dependencies:
  - No new project dependency should be added.
  - If byte-level upload progress is implemented for `gradio_client` uploads, keep it isolated in `service_client.py` and reuse `gradio_client`/`httpx` runtime dependencies already present through Gradio.
- Constraint:
  - Gradio starts `process_video()` only after the HTTP upload has completed, so the Python server callback cannot report true server-side upload bytes without replacing Gradio's upload endpoint. This plan reports client-side upload bytes and adds server-side "upload received" status/logging when the app receives the file.

## Development Approach
- **Testing approach**: TDD
- Complete each task fully before moving to the next.
- Prefer function-level docstrings for new Python logic.
- Keep changes scoped to the existing progress, service client, server, and GUI modules.
- Do not add new dependencies.
- **CRITICAL: every task MUST include new/updated tests**
- **CRITICAL: all tests must pass before starting next task**

## Implementation Steps

### Task 1: Normalize remote progress payloads and expose upload progress

**Files:**
- Modify: `talks_reducer/service_client.py`
- Modify: `tests/test_service_client.py`
- Modify: `tests/test_cli.py` if CLI output expectations change

- [x] Add tests for `_emit_progress_update` covering `progress_data` with `index`, raw count progress, and fractional progress.
- [x] Fix `_emit_progress_update` so it forwards the normalized current value, not the raw progress field.
- [x] Add tests showing `send_video()` emits an `Uploading:` progress event before the remote job starts and a completed `Uploading:` event once submission has completed.
- [x] Implement upload progress reporting through the existing `progress_callback` signature: `desc="Uploading:"`, current bytes, total bytes, `unit="bytes"`.
- [x] Keep upload progress optional so existing callers without `progress_callback` behave exactly as before.
- [x] Run `pytest tests/test_service_client.py tests/test_cli.py` and confirm it passes before Task 2.

### Task 2: Report real audio-processing progress from the pipeline

**Files:**
- Modify: `talks_reducer/audio.py`
- Modify: `talks_reducer/pipeline.py`
- Modify: `tests/test_audio.py`
- Modify: `tests/test_pipeline_service.py`

- [x] Add a failing test for `process_audio_chunks()` proving an optional progress callback is called as chunks are processed.
- [x] Extend `process_audio_chunks()` with an optional progress callback that receives incremental processed source-sample counts.
- [x] Add a failing pipeline service test proving `speed_up_video()` opens a reporter task with `desc="Audio processing:"` and advances it during `process_audio_chunks()`.
- [x] Wrap `process_audio_chunks()` in `pipeline.py` with `reporter.task(desc="Audio processing:", total=<source sample total>, unit="samples")`.
- [x] Ensure zero-length chunks do not produce negative progress and empty inputs still complete cleanly.
- [x] Run `pytest tests/test_audio.py tests/test_pipeline_service.py` and confirm it passes before Task 3.

### Task 3: Map streamed progress into stable desktop GUI percentages

**Files:**
- Modify: `talks_reducer/gui/progress.py`
- Modify: `talks_reducer/gui/remote.py`
- Modify: `tests/test_gui_progress.py`
- Modify: `tests/test_gui_remote.py`

- [x] Add tests for a shared GUI progress mapper that maps task progress into stable ranges:
  - `Uploading:` 0-5%
  - `Extracting audio:` 5-20%
  - `Audio processing:` 20-35%
  - `Generating final:` and fallback final encode 35-100%
  - unknown tasks preserve the existing 0-100 behavior
- [x] Implement the mapper in `gui/progress.py` and use it from `_GuiProgressHandle`.
- [x] Update `process_files_via_server()` to pass a `progress_callback` into `service_module.send_video()`.
- [x] In the remote GUI progress callback, schedule `_set_progress()` and `_set_status("processing", ...)` on the UI thread.
- [x] Add GUI remote tests proving streamed `Generating final:` progress advances the progress bar after audio processing.
- [x] Run `pytest tests/test_gui_progress.py tests/test_gui_remote.py` and confirm it passes before Task 4.

### Task 4: Stop stale audio progress and parse log-only progress milestones

**Files:**
- Modify: `talks_reducer/gui/summaries.py`
- Modify: `talks_reducer/gui/app.py` if helper exports are needed
- Modify: `tests/test_gui_app.py`

- [ ] Add parser tests for log lines such as `Generating final: 30%`, `Generating final (fallback): 30%`, and `Audio processing: 45%`.
- [ ] Implement a small parser for task-percent log messages in `gui/summaries.py`.
- [ ] Update `SummaryManager` so final encode target messages and final progress messages call `_complete_audio_phase()`.
- [ ] Update `SummaryManager` so log-only percent milestones also update the progress bar using the same stage mapper from Task 3.
- [ ] Keep the existing synthetic audio timer only as a fallback, and cancel it as soon as real audio-processing or final-encode progress arrives.
- [ ] Run `pytest tests/test_gui_app.py tests/test_gui_progress.py` and confirm it passes before Task 5.

### Task 5: Surface server upload receipt and browser/server progress context

**Files:**
- Modify: `talks_reducer/server.py`
- Modify: `tests/test_server.py`

- [ ] Add a server test proving `process_video()` logs the received upload filename and file size before processing starts.
- [ ] Add the upload-received log/status in `process_video()` after the file exists and before workspace/output setup.
- [ ] Ensure this log appears in streamed remote logs without changing the final output tuple shape.
- [ ] Confirm Gradio processing progress still emits `Extracting audio:`, `Audio processing:`, and `Generating final:` task events.
- [ ] Run `pytest tests/test_server.py tests/test_service_client.py` and confirm it passes before Task 6.

### Task 6: Update documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/TODO.md`

- [ ] Update `README.md` remote progress documentation to describe upload, audio-processing, and final-encode progress in CLI, desktop remote mode, and server/browser workflows.
- [ ] Remove or update the completed entries in `docs/TODO.md` if that is the repository convention for completed TODO work.
- [ ] Run `black talks_reducer tests`.
- [ ] Run `isort talks_reducer tests`.
- [ ] Run `pytest tests/test_service_client.py tests/test_server.py tests/test_audio.py tests/test_pipeline_service.py tests/test_gui_progress.py tests/test_gui_remote.py tests/test_gui_app.py tests/test_cli.py` and confirm it passes before Task 7.

### Task 7: Verify acceptance criteria

**Files:**
- Inspect: `talks_reducer/service_client.py`
- Inspect: `talks_reducer/audio.py`
- Inspect: `talks_reducer/pipeline.py`
- Inspect: `talks_reducer/server.py`
- Inspect: `talks_reducer/gui/progress.py`
- Inspect: `talks_reducer/gui/remote.py`
- Inspect: `talks_reducer/gui/summaries.py`
- Inspect: `README.md`
- Inspect: `docs/TODO.md`

- [ ] Run `pytest` and confirm the full test suite passes.
- [ ] Run `black --check talks_reducer tests` and confirm formatting passes.
- [ ] Run `isort --check-only talks_reducer tests` and confirm import ordering passes.
- [ ] Run `pytest --cov=talks_reducer --cov-report=term-missing` and verify coverage remains at or above 80%.
- [ ] Verify every completed `docs/TODO.md` progress item is covered by implementation, tests, and README documentation.
