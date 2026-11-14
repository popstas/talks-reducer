# GUI Log Conversion Blocks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make each conversion in the GUI log a findable block — `### Processing` header, blank-line separator, two-line `Completed:` summary — and drop the noise lines.

**Architecture:** Pure formatters live in `gui/summaries.py`; `SummaryManager` gains explicit `begin_conversion` / `finish_run` methods so run state no longer depends on log wording; the local worker (`gui/app.py`) and remote loop (`gui/remote.py`) call them through thin `TalksReducerGUI` wrappers. The duplicated `… completed` lines are fixed at the root in `CallbackProgressHandle.finish()`.

**Tech Stack:** Python, Tkinter, pytest.

**Spec:** `docs/superpowers/specs/2026-11-14-gui-log-conversion-blocks-design.md`

## Global Constraints

- Header: `### Processing <filename>: <params>`; params always the effective settings, in this order, joined by `, `: resolution, codec, fps, `silent ×N`, `sounded ×N`, `threshold N` or `no voice`, then `cut A–B`, `remove N range(s)` when set.
- Summary line 1: `Completed: <full output path>`.
- Summary line 2: `Duration: HH:MM:SS, Time: NN.NN% (HH:MM:SS), Size: NN.NN% (N.N MB)` — Duration = wall-clock conversion time of that file; percents two decimals.
- Two empty lines between conversion blocks; none before the first block in the widget.
- `All jobs finished successfully.` is never written to the log.
- CLI output, status-bar text, progress bar, taskbar and bell behaviour unchanged.
- Run tests with `.venv\Scripts\python -m pytest`; format with `black` + `isort` before each commit.
- Work on branch `feat/gui-log-blocks` (master is the default branch). Final PR title: `feat: Separate GUI log into per-conversion blocks with a summary`.

## Review Focus

- A conversion that fails or is stopped mid-way: the next run's block must still be separated, and `_finish_run` must not fire (status stays `Error`/`Aborted`).
- Remote fallback to local after a server failure: the local header for the same file must start a new separated block.
- Remote output files that cannot be probed (missing ffprobe, file absent): the summary degrades to the parts it can compute, never raises.
- mp3 codec: header must not claim a video resolution or fps.
- Values with float noise from the GUI (`silent_speed=10.0`, `silent_threshold=0.010000001` after `round(…, 2)`): header renders `×10`, `0.01`.

---

### Task 1: Fire `CallbackProgressHandle` finish once

**Files:**
- Modify: `talks_reducer/progress.py:86-144` (`CallbackProgressHandle`)
- Test: `tests/test_progress.py`

**Interfaces:**
- Produces: `CallbackProgressHandle.finish()` is idempotent — a second call (including the one from `__exit__`) invokes neither `on_update` nor `on_finish`.

- [ ] **Step 1: Write the failing tests**

```python
def test_callback_handle_finish_fires_once_inside_with_block():
    finished = []
    handle = CallbackProgressHandle(desc="Generating final:", total=10,
                                    on_finish=lambda c, t, d: finished.append(d))
    with handle as progress:
        progress.finish()
    assert finished == ["Generating final:"]

def test_gui_handle_logs_completed_once():
    logs = []
    reporter = _TkProgressReporter(logs.append)
    with reporter.task(desc="Extracting audio:", total=5) as progress:
        progress.finish()
    assert logs.count("Extracting audio: completed") == 1
```
(second test goes in `tests/test_gui_progress.py`)

- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_progress.py tests/test_gui_progress.py -v` — Expected: both new tests FAIL (2 finish calls / 2 log lines).
- [ ] **Step 3: Implement** a `_finished: bool` flag in `CallbackProgressHandle.__init__`; `finish()` returns immediately when set, sets it otherwise. Docstring says why (`run_timed_ffmpeg_command` calls `finish()` inside its `with`).
- [ ] **Step 4: Run** the full suite `.venv\Scripts\python -m pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** `fix: Log each GUI stage completion once`

---

### Task 2: Header and summary formatters

**Files:**
- Modify: `talks_reducer/gui/summaries.py`
- Test: `tests/test_gui_summaries.py` (create)

**Interfaces:**
- Produces:
  - `format_conversion_params(args: Mapping[str, object]) -> str`
  - `format_conversion_header(filename: str, args: Mapping[str, object]) -> str` → `f"### Processing {filename}: {params}"` (no `: ` suffix when params is empty)
  - `format_conversion_summary(output_file: Path, *, elapsed_seconds: Optional[float], time_ratio: Optional[float], output_duration: Optional[float], size_ratio: Optional[float], output_size: Optional[int]) -> list[str]` → `[line1, line2]`, or `[line1]` when nothing in line 2 is known
  - `measure_media(path: Path) -> tuple[Optional[float], Optional[int]]` → `(duration_seconds, size_bytes)`, `None` for anything unknown; returns `(None, None)` without probing when the file does not exist; uses `talks_reducer.ffmpeg.get_video_duration` (0.0 → `None`).
  - `format_file_size(size_bytes: int, *, sep: str = "") -> str` — existing function gains `sep` between number and unit; status bar keeps the default.

Param rules (`args` is the dict from `TalksReducerGUI._collect_arguments`):
- resolution: `f"{small_target_height}p"` when `args.get("small")`, else `orig`.
- codec: `h264→h.264`, `hevc→h.265`, `av1→av1`, `mp3→mp3`; missing → `h.264`.
- fps: `f"{max_frame_rate:g} fps"` when set, else `orig fps`.
- **mp3:** omit resolution and fps (audio-only output; Claude's call, see Review Focus).
- `silent ×{silent_speed:g}`, `sounded ×{sounded_speed:g}`, each skipped when absent.
- `no voice` when `args.get("vad")`, else `threshold {silent_threshold:g}` (skipped when absent).
- `cut {format_timecode(start)}–{format_timecode(end) or "end"}` when `cut_start_seconds` or `cut_end_seconds` is in args (end `0` → `end`); en dash.
- `remove 1 range` / `remove N ranges` when `remove_ranges` is non-empty.

Summary line 2 parts, joined by `, `, each skipped when its inputs are `None`:
`Duration: {format_timecode(elapsed)}`, `Time: {time_ratio:.2%}` + ` ({format_timecode(output_duration)})` when known, `Size: {size_ratio:.2%}` + ` ({format_file_size(output_size, sep=" ")})` when known.

- [ ] **Step 1: Write the failing tests**

```python
def test_header_lists_effective_settings():
    args = {"small": True, "small_target_height": 480, "video_codec": "hevc",
            "max_frame_rate": 30.0, "silent_speed": 10.0, "sounded_speed": 1.0,
            "silent_threshold": 0.01, "vad": False}
    assert format_conversion_header("VID.mp4", args) == (
        "### Processing VID.mp4: 480p, h.265, 30 fps, silent ×10, sounded ×1, threshold 0.01")

def test_header_vad_replaces_threshold_and_orig_defaults():
    args = {"video_codec": "h264", "silent_speed": 5.0, "sounded_speed": 1.3,
            "silent_threshold": 0.05, "vad": True}
    assert format_conversion_params(args) == "orig, h.264, orig fps, silent ×5, sounded ×1.3, no voice"

def test_header_mp3_omits_video_fields():
    args = {"small": True, "small_target_height": 720, "video_codec": "mp3",
            "max_frame_rate": 30.0, "silent_speed": 10.0, "sounded_speed": 1.0,
            "silent_threshold": 0.01}
    assert format_conversion_params(args) == "mp3, silent ×10, sounded ×1, threshold 0.01"

def test_header_cut_and_remove():
    args = {"video_codec": "h264", "cut_start_seconds": 65.0, "cut_end_seconds": 0.0,
            "remove_ranges": ((1.0, 2.0), (3.0, 4.0))}
    assert format_conversion_params(args).endswith("cut 00:01:05–end, remove 2 ranges")

def test_summary_matches_spec_example():
    lines = format_conversion_summary(Path("C:/v/out.mp4"), elapsed_seconds=682,
        time_ratio=0.9931, output_duration=733, size_ratio=0.0157,
        output_size=int(1.5 * 1024 * 1024))
    assert lines[1] == "Duration: 00:11:22, Time: 99.31% (00:12:13), Size: 1.57% (1.5 MB)"
    assert lines[0].startswith("Completed: ") and lines[0].endswith("out.mp4")

def test_summary_degrades_when_ratios_unknown():
    lines = format_conversion_summary(Path("out.mp4"), elapsed_seconds=5,
        time_ratio=None, output_duration=None, size_ratio=None, output_size=None)
    assert lines[1] == "Duration: 00:00:05"

def test_measure_media_missing_file_does_not_probe(tmp_path, monkeypatch):
    monkeypatch.setattr(summaries, "get_video_duration", lambda *_: pytest.fail("probed"))
    assert measure_media(tmp_path / "absent.mp4") == (None, None)
```

- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_gui_summaries.py -v` — Expected: FAIL (ImportError).
- [ ] **Step 3: Implement** the five functions above in `gui/summaries.py`; import `format_timecode` from `..timecode` and `get_video_duration` from `..ffmpeg` at module level (so tests can monkeypatch `summaries.get_video_duration`).
- [ ] **Step 4: Run** `.venv\Scripts\python -m pytest tests/test_gui_summaries.py tests/test_gui_app.py -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: Add GUI conversion header and summary formatters`

---

### Task 3: `SummaryManager` blocks and explicit run finish

**Files:**
- Modify: `talks_reducer/gui/summaries.py` (`SummaryManager`)
- Modify: `talks_reducer/gui/app.py:1933-1940` (wrappers next to `_append_log`)
- Test: `tests/test_gui_app.py` (next to the existing `test_summary_manager_*` tests; extend `_make_summary_gui` with a `log_text` stub whose `after(0, fn)` calls `fn` and whose `insert` records text)

**Interfaces:**
- Consumes: `format_conversion_header` (Task 2).
- Produces:
  - `SummaryManager.append_separator() -> None` — inserts `"\n\n"` into `log_text` only when `_block_written` is true, then clears it.
  - `SummaryManager.begin_conversion(header: str) -> None` — `append_separator()`; write `header` to the widget **without** running `update_status_from_message`; then the per-file reset the old `processing` branch did: `gui._reset_progress_baseline()`, clear `_video_duration_seconds`, `_encode_target_duration_seconds`, `_encode_total_frames`, `_encode_current_frame`, `_last_progress_seconds`, `gui._reset_audio_progress_state(clear_source=True)`, `gui._set_status("processing", "Processing")`; finally set `_block_written = True`.
  - `SummaryManager.finish_run() -> None` — the exact body of today's `"all jobs finished successfully"` branch in `handle_status_transitions`, moved out; that branch is deleted.
  - `TalksReducerGUI._begin_conversion_log(filename: str, args: Mapping[str, object]) -> None` → `summary_manager.begin_conversion(format_conversion_header(filename, args))`
  - `TalksReducerGUI._log_conversion_summary(output_file: Path, **stats) -> None` → `_append_log` each line of `format_conversion_summary(output_file, **stats)`
  - `TalksReducerGUI._start_log_run() -> None` → `summary_manager.append_separator()`
  - `TalksReducerGUI._finish_run() -> None` → `summary_manager.finish_run()`

Leave the existing `processing` prefix branch in `handle_status_transitions` in place: it still serves streamed server lines like `Processing 2/3: clip.mp4`; the `###` header never reaches it.

- [ ] **Step 1: Write the failing tests**

```python
def test_begin_conversion_separates_only_after_a_block():
    gui = _make_summary_gui(); manager = summaries.SummaryManager(gui)
    manager.append_separator()                       # empty widget: nothing
    manager.begin_conversion("### Processing a.mp4: orig")
    manager.append_log("Completed: a")
    manager.begin_conversion("### Processing b.mp4: orig")
    assert gui.inserted == ["### Processing a.mp4: orig\n", "Completed: a\n",
                            "\n\n", "### Processing b.mp4: orig\n"]

def test_run_separator_consumes_block_flag():
    gui = _make_summary_gui(); manager = summaries.SummaryManager(gui)
    manager.begin_conversion("### Processing a.mp4: orig")
    manager.append_separator()                       # next run starts
    manager.append_log("Starting processing…")
    manager.begin_conversion("### Processing b.mp4: orig")
    assert gui.inserted.count("\n\n") == 1
    assert gui.inserted.index("\n\n") < gui.inserted.index("Starting processing…\n")

def test_begin_conversion_resets_progress_and_status():
    gui = _make_summary_gui(); gui._progress_floor = 100.0
    summaries.SummaryManager(gui).begin_conversion("### Processing a.mp4: orig")
    gui._reset_progress_baseline.assert_called_once()
    gui._reset_audio_progress_state.assert_called_once_with(clear_source=True)
    gui._set_status.assert_called_with("processing", "Processing")

def test_finish_run_sets_success_status():
    gui = _make_summary_gui(); gui._run_start_time = None
    gui._last_time_ratio = 0.5; gui._last_size_ratio = 0.25
    gui._last_output_duration = None; gui._last_output_size = None
    summaries.SummaryManager(gui).finish_run()
    assert gui._set_status.call_args[0][0] == "success"
    gui._set_progress.assert_called_with(100)

def test_old_marker_text_no_longer_finishes_the_run():
    gui = _make_summary_gui()
    summaries.SummaryManager(gui).update_status_from_message("All jobs finished successfully.")
    assert all(c[0][0] != "success" for c in gui._set_status.call_args_list)
```

- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_gui_app.py -k "begin_conversion or separator or finish_run or marker" -v` — Expected: FAIL (AttributeError).
- [ ] **Step 3: Implement** the four `SummaryManager` changes and four `TalksReducerGUI` wrappers above. A private `_write(text)` helper holds the `log_text` NORMAL/insert/see/DISABLED updater so `append_log`, `append_separator` and `begin_conversion` share it.
- [ ] **Step 4: Run** `.venv\Scripts\python -m pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: Add explicit GUI log blocks and run finish`

---

### Task 4: Local worker uses the blocks

**Files:**
- Modify: `talks_reducer/gui/app.py:567` (run start) and `:646-686` (local loop)
- Test: `tests/test_gui_app.py`

**Interfaces:**
- Consumes: `_start_log_run`, `_begin_conversion_log`, `_log_conversion_summary`, `_finish_run` (Task 3).

Changes:
- Call `self._start_log_run()` immediately before `self._append_log("Starting processing…")`.
- Replace `self._append_log(f"Processing: {os.path.basename(file)}")` with `self._begin_conversion_log(os.path.basename(file), args)`. Keep the explicit `_reset_progress_baseline()` call before it.
- Time each file: `started = time.monotonic()` before `speed_up_video`, `elapsed = time.monotonic() - started` after.
- Replace the `completion_msg` block with `self._log_conversion_summary(result.output_file, elapsed_seconds=elapsed, time_ratio=result.time_ratio, output_duration=result.output_duration, size_ratio=result.size_ratio, output_size=self._last_output_size)`.
- Replace `self._append_log("All jobs finished successfully.")` with `self._finish_run()`.

- [ ] **Step 1: Write the failing test** `test_local_run_logs_header_summary_and_finishes` — drive the worker with `speed_up_video` monkeypatched to return a `ProcessingResult` (`output_duration=733`, `time_ratio=0.9931`, `size_ratio=0.0157`) for two files, using the same GUI stub pattern the existing local-worker tests in `tests/test_gui_app.py` use (find them by `speed_up_video` monkeypatch). Assert: logs contain `### Processing a.mp4: …` and `### Processing b.mp4: …`; a line starting `Duration: ` containing `Time: 99.31% (00:12:13)` after each `Completed: `; no `Processing: ` line; no `All jobs finished successfully.`; `_finish_run` called once. Add `test_local_run_failure_does_not_finish_run`: `speed_up_video` raises `ProcessingAborted` → `_finish_run` not called, status `Aborted`.
- [ ] **Step 2: Run** it — Expected: FAIL.
- [ ] **Step 3: Implement** the changes listed above.
- [ ] **Step 4: Run** `.venv\Scripts\python -m pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: Log local GUI conversions as separated blocks`

---

### Task 5: Remote loop uses the blocks

**Files:**
- Modify: `talks_reducer/gui/remote.py:441-552`
- Test: `tests/test_gui_remote.py` (extend `StubGUI` with `_begin_conversion_log`, `_log_conversion_summary`, `_finish_run` that record calls; `_log_conversion_summary` also appends the formatted lines to `self.logs`)

**Interfaces:**
- Consumes: `measure_media`, `format_conversion_summary` via `gui._log_conversion_summary`, `gui._begin_conversion_log`, `gui._finish_run`.

Changes:
- Before the `Uploading …` log of each file: `gui._begin_conversion_log(basename, args)`; keep the existing `index > 1` `_reset_progress_baseline()`.
- Time `send_video` with `time.monotonic()`.
- After it: `in_dur, in_size = measure_media(input_path)`, `out_dur, out_size = measure_media(Path(destination))`; `time_ratio = out_dur / in_dur` when both known, else the `parse_summary` value; `size_ratio = out_size / in_size` likewise. Set `gui._last_time_ratio`, `_last_size_ratio`, `_last_output_duration = out_dur`, `_last_output_size = out_size`.
- Replace `for line in summary.splitlines(): gui._append_log(line)` with `gui._log_conversion_summary(Path(destination), elapsed_seconds=…, time_ratio=…, output_duration=out_dur, size_ratio=…, output_size=out_size)`. Keep the `Server log:` dump after it.
- Replace `gui._append_log("All jobs finished successfully.")` with `gui._finish_run()`.

- [ ] **Step 1: Update/write tests.** In `test_process_files_via_server_processes_each_file`: change `gui.logs[0]` to `any("Uploading 1/1: input.mp4" in l for l in gui.logs)`; assert `"Summary line" not in gui.logs`, `"All jobs finished successfully." not in gui.logs`, `gui.finish_run_calls == 1`, header recorded for `input.mp4`; ratios still `0.5`/`0.25` (files absent → fallback). Add `test_process_files_via_server_measures_local_files` that writes real `input.mp4` (400 bytes) and output (100 bytes) and monkeypatches `summaries.get_video_duration` to return 100.0 / 50.0, asserting `gui._last_size_ratio == 0.25`, `gui._last_time_ratio == 0.5`, `gui._last_output_size == 100`.
- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_gui_remote.py -v` — Expected: new assertions FAIL.
- [ ] **Step 3: Implement** the changes listed above.
- [ ] **Step 4: Run** `.venv\Scripts\python -m pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: Log remote GUI conversions as separated blocks`

---

### Task 6: Docs and real-window check

**Files:**
- Modify: `docs/gui.md:219-221`, and the matching paragraph in `CLAUDE.md:358` and `AGENTS.md:150`

- [ ] **Step 1:** Add to that paragraph: each conversion opens with `### Processing <file>: <settings>`, blocks are separated by two blank lines and end with `Completed:` plus a `Duration / Time / Size` line; the success status is set by `SummaryManager.finish_run()`, not by a log line (so log wording never drives state).
- [ ] **Step 2:** Launch the GUI from `.venv` (`.venv\Scripts\python -m talks_reducer.gui`), convert two short files in Advanced mode, and confirm in the log: header per file, two blank lines between blocks, one `Extracting audio: completed`, one `Generating final: completed`, summary lines, no `All jobs finished successfully.`, green success status with the bell.
- [ ] **Step 3: Commit** `docs: Describe GUI log conversion blocks`
