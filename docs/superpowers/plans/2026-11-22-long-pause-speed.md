# Long Pause Speed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stretches of silence longer than a threshold (default 60 s) play at a second, absolute speed (GUI default 20), with short sounds inside the stretch absorbed into it.

**Architecture:** A pure `chunks.apply_long_pauses` relabels qualifying silent stretches with a new speed index 3 right after `build_chunks`; the pipeline appends the long-pause speed to `new_speeds`, and audio/`setpts` pick it up by index. Two new `ProcessingOptions` fields are plumbed through CLI, the Advanced GUI (one checkbox row), the gradio endpoint and `service_client`.

**Tech Stack:** Python 3.11, NumPy, Tkinter/ttk, gradio, pytest, black/isort.

**Spec:** `docs/superpowers/specs/2026-11-22-long-pause-speed-design.md`

## Global Constraints

- Off by default everywhere: with `long_pause_speed is None` output must be byte-identical to today.
- Speed is absolute, never a multiplier of `silent_speed`.
- Not a preset field; no `presets.py` / `PRESETS_VERSION` change; Simple mode never applies it.
- Sound tolerance is the internal constant `LONG_PAUSE_SOUND_TOLERANCE_SECONDS = 2.0` (no setting).
- `long_pause_speed <= silent_speed` → feature skipped with a log line.
- GUI ranges: speed 1–100, seconds 5–3600; GUI defaults: speed 20, seconds 60, enabled `False`.
- Every pipeline run with the feature on and audio analysed logs a line starting `Long pauses:`.
- Work on branch `feat/long-pause-speed` (create from `master` before Task 1). Run `black` and `isort` before each commit. Use `.venv` (`.venv/Scripts/python -m pytest`).

## Review Focus

- A stretch that *starts or ends* with a short sound (e.g. a notification right before speech resumes) — the sound stays at its own speed; only interior sounds are absorbed. Pinned in Task 1.
- Long-pause on with `silent_speed == sounded_speed == 1` ("No speedup") — must still analyse audio and shorten long pauses, not take the neutral-speed shortcut. Pinned in Task 2.
- Long pause plus remove ranges overlapping a long stretch — removed part must stay removed. Pinned in Task 2.
- Remote with long pause on but VAD off — the client must still send the VAD slots so the long-pause values land at positions 19–20, and an old server must raise `ServerTooOldError`. Pinned in Task 4.
- Typed-but-uncommitted entry text when the user clicks Run / drops a file — collection must parse the entry text, not a stale variable. Pinned in Task 5.

---

### Task 1: `apply_long_pauses` in chunks

**Files:**
- Modify: `talks_reducer/chunks.py`
- Test: `tests/test_chunks.py`

**Interfaces:**
- Produces: `LONG_PAUSE_SPEED_INDEX = 3`, `LONG_PAUSE_SOUND_TOLERANCE_SECONDS = 2.0`, `apply_long_pauses(chunks: Sequence[Sequence[int]], min_frames: int, tolerance_frames: int) -> List[List[int]]`, all in `__all__`.

Chunks are `[start_frame, end_frame, speed_index]` straight from `build_chunks` (alternating 0 = silent, 1 = sounded).

- [ ] **Step 1: Write the failing tests**

```python
def test_apply_long_pauses_merges_across_short_sound():
    chunks = [[0, 10, 1], [10, 100, 0], [100, 105, 1], [105, 200, 0], [200, 210, 1]]
    assert apply_long_pauses(chunks, min_frames=150, tolerance_frames=10) == [
        [0, 10, 1], [10, 200, LONG_PAUSE_SPEED_INDEX], [200, 210, 1]]

def test_apply_long_pauses_sound_longer_than_tolerance_splits_stretch():
    chunks = [[0, 100, 0], [100, 130, 1], [130, 200, 0]]
    assert apply_long_pauses(chunks, min_frames=150, tolerance_frames=10) == chunks

def test_apply_long_pauses_single_silence_over_threshold():
    chunks = [[0, 5, 1], [5, 205, 0], [205, 210, 1]]
    assert apply_long_pauses(chunks, 200, 10)[1] == [5, 205, LONG_PAUSE_SPEED_INDEX]

def test_apply_long_pauses_short_stretch_left_unchanged():
    chunks = [[0, 50, 0], [50, 55, 1], [55, 100, 0]]
    assert apply_long_pauses(chunks, 150, 10) == chunks

def test_apply_long_pauses_edge_sounds_not_absorbed():
    # Short sounds at the ends of the recording are outside any silent stretch.
    chunks = [[0, 3, 1], [3, 200, 0], [200, 203, 1]]
    assert apply_long_pauses(chunks, 150, 10) == [
        [0, 3, 1], [3, 200, LONG_PAUSE_SPEED_INDEX], [200, 203, 1]]

def test_apply_long_pauses_threshold_is_inclusive_and_returns_copies():
    chunks = [[0, 150, 0]]
    result = apply_long_pauses(chunks, 150, 10)
    assert result == [[0, 150, LONG_PAUSE_SPEED_INDEX]]
    assert chunks == [[0, 150, 0]]
```

- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_chunks.py -k long_pauses -v` — Expected: FAIL (ImportError).

- [ ] **Step 3: Implement** in `talks_reducer/chunks.py`. Greedy scan: at a silent chunk `i`, extend while the next chunk is sounded with length `<= tolerance_frames` *and* the one after it is silent; the stretch spans `chunks[i][0]..chunks[j][1]` (j = last silent chunk reached). If its length `>= min_frames` emit one `[start, end, LONG_PAUSE_SPEED_INDEX]`, else emit copies of `chunks[i..j]`; continue at `j + 1`. Non-silent chunks are copied through. Docstring explains why interior sounds are absorbed (notifications during long script runs).

- [ ] **Step 4: Run** the same command — Expected: PASS.

- [ ] **Step 5: Commit** — `git add talks_reducer/chunks.py tests/test_chunks.py && git commit -m "feat: add long pause chunk relabelling"`

---

### Task 2: Options and pipeline wiring

**Files:**
- Modify: `talks_reducer/models.py` (`ProcessingOptions`, after `vad_min_silence_ms`)
- Modify: `talks_reducer/pipeline.py:613-615` (`neutral_speeds`), `:704-713` (chunks, `new_speeds`)
- Test: `tests/test_pipeline.py` (reuse `_run_vad_pipeline`, which captures `state["chunks"]`; pass `vad=False` plus option overrides and a `mask`)

**Interfaces:**
- Consumes: Task 1's `apply_long_pauses`, `LONG_PAUSE_SPEED_INDEX`, `LONG_PAUSE_SOUND_TOLERANCE_SECONDS`.
- Produces: `ProcessingOptions.long_pause_speed: Optional[float] = None`, `ProcessingOptions.long_pause_seconds: float = 60.0`; log marker text `Long pauses:`.

- [ ] **Step 1: Write the failing tests** (`tests/test_pipeline.py`), building a mask with a long silent run and a 1-frame blip inside it:

```python
def test_long_pause_relabels_long_silence(tmp_path, monkeypatch):
    # mask: loud 0-9, silent 10-..., blip at the middle, loud at the end; frame_rate 30
    _, state, _, logs = _run_vad_pipeline(tmp_path, monkeypatch, vad=False, mask=LONG_MASK,
        silent_speed=10.0, long_pause_speed=20.0, long_pause_seconds=3.0)
    assert any(c[2] == pipeline.chunk_utils.LONG_PAUSE_SPEED_INDEX for c in state["chunks"])
    assert any(line.startswith("Long pauses: 1 stretch") for line in logs)

def test_long_pause_off_by_default_keeps_chunks(tmp_path, monkeypatch):
    _, state, _, _ = _run_vad_pipeline(tmp_path, monkeypatch, vad=False, mask=LONG_MASK)
    assert all(c[2] != pipeline.chunk_utils.LONG_PAUSE_SPEED_INDEX for c in state["chunks"])

def test_long_pause_not_faster_than_silent_is_skipped(tmp_path, monkeypatch):
    _, state, _, logs = _run_vad_pipeline(tmp_path, monkeypatch, vad=False, mask=LONG_MASK,
        silent_speed=10.0, long_pause_speed=5.0, long_pause_seconds=3.0)
    assert all(c[2] != pipeline.chunk_utils.LONG_PAUSE_SPEED_INDEX for c in state["chunks"])
    assert any(line.startswith("Long pauses: skipped") for line in logs)

def test_long_pause_runs_with_neutral_speeds(tmp_path, monkeypatch):
    _, state, _, _ = _run_vad_pipeline(tmp_path, monkeypatch, vad=False, mask=LONG_MASK,
        silent_speed=1.0, sounded_speed=1.0, long_pause_speed=20.0, long_pause_seconds=3.0)
    assert any(c[2] == pipeline.chunk_utils.LONG_PAUSE_SPEED_INDEX for c in state["chunks"])

def test_long_pause_keeps_remove_ranges_removed(tmp_path, monkeypatch):
    _, state, _, _ = _run_vad_pipeline(tmp_path, monkeypatch, vad=False, mask=LONG_MASK,
        silent_speed=10.0, long_pause_speed=20.0, long_pause_seconds=3.0,
        remove_ranges=((1.0, 1.5),))
    kinds = {c[2] for c in state["chunks"]}
    assert {pipeline.chunk_utils.LONG_PAUSE_SPEED_INDEX, pipeline.chunk_utils.REMOVED_SPEED_INDEX} <= kinds
```

Adapt the helper's return/log capture to what `_run_vad_pipeline` already exposes; if it does not route `mask` when `vad=False`, extend it to stub `detect_loud_frames` with the same mask. Also assert the `new_speeds` passed to `process_audio_chunks` ends with `20.0` in the first test if the helper captures it.

- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_pipeline.py -k long_pause -v` — Expected: FAIL.

- [ ] **Step 3: Implement.**
  - `models.py`: the two fields with a docstring line each.
  - `pipeline.py`: `neutral_speeds` additionally requires `options.long_pause_speed is None`.
  - After `build_chunks` and **before** `apply_remove_ranges`: when `long_pause_speed` is set — if `<= silent_speed` log `Long pauses: skipped, x{speed:g} is not faster than silent x{silent:g}`; otherwise call `apply_long_pauses(chunks, math.ceil(seconds * frame_rate), round(LONG_PAUSE_SOUND_TOLERANCE_SECONDS * frame_rate))` and log either `Long pauses: {n} stretch(es), {minutes:.1f} min at x{speed:g}` or `Long pauses: none longer than {seconds:g} s`.
  - `new_speeds = [silent, sounded, math.inf, options.long_pause_speed or options.silent_speed]`, update the index comment.

- [ ] **Step 4: Run** `.venv/Scripts/python -m pytest tests/test_pipeline.py tests/test_chunks.py -v` — Expected: PASS, no existing test changed.

- [ ] **Step 5: Commit** — `feat: speed up long pauses in the pipeline`

---

### Task 3: CLI flags

**Files:**
- Modify: `talks_reducer/cli.py` (parser near `--silent_speed`; local option kwargs near `:690-707`; `--url` unsupported-options list; remote values near `:833`)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: Task 2 fields.
- Produces: `--long-pause-speed SPEED` (`dest="long_pause_speed"`, float, default `None`), `--long-pause-seconds SECONDS` (`dest="long_pause_seconds"`, float, default `None` → options default 60); `_remote_long_pause_options(parsed_args) -> Dict[str, object]` returning `{}` when `long_pause_speed` is `None`, else `{"long_pause_speed": float, "long_pause_seconds": float}` (seconds only when given).

- [ ] **Step 1: Write failing tests**: parsing both flags sets the dests; a local run with `--long-pause-speed 20 --long-pause-seconds 90` builds `ProcessingOptions(long_pause_speed=20.0, long_pause_seconds=90.0)` (follow the existing `vad_*` option-capture test pattern); `--long-pause-seconds 90` alone leaves `long_pause_speed is None`; `_remote_long_pause_options` returns `{}` / the dict; `--url` with the flags does **not** print them in the "ignored when using --url" warning.
- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_cli.py -k long_pause -v` — Expected: FAIL.
- [ ] **Step 3: Implement** flags (help text: "Absolute speed for silent stretches longer than --long-pause-seconds; short sounds inside them are sped up too. Off by default." / "Minimum length of a long pause in seconds. Defaults to 60."), local kwargs, remote merge via `remote_option_values.update(_remote_long_pause_options(parsed_args))`.
- [ ] **Step 4: Run** the test file — Expected: PASS.
- [ ] **Step 5: Commit** — `feat: add --long-pause-speed and --long-pause-seconds`

---

### Task 4: Remote server and client

**Files:**
- Modify: `talks_reducer/server.py` (`_stream_pipeline`, `process_video_api`, `process_video`)
- Modify: `talks_reducer/service_client.py` (`send_video`, too-old error, log marker)
- Modify: `talks_reducer/gui/remote.py:368-380` (allowed keys), `:515-535` (`send_video` kwargs)
- Test: `tests/test_server.py`, `tests/test_service_client.py`, `tests/test_gui_remote.py`

**Interfaces:**
- Consumes: Task 2 fields; Task 3's remote dict keys.
- Produces: `send_video(..., long_pause_speed: Optional[float] = None, long_pause_seconds: Optional[float] = None, ...)`; endpoint positions 19–20 (`long_pause_speed`, `long_pause_seconds`); `LONG_PAUSE_LOG_MARKER = "Long pauses:"`.

- [ ] **Step 1: Write failing tests.**
  - server: `process_video_api` with `long_pause_speed=20.0, long_pause_seconds=90.0` builds options with those values (reuse the existing vad-forwarding test's dependency stub); `long_pause_speed=None` leaves the defaults.
  - client: with `long_pause_speed=20.0`, `vad=False` the submitted args are the 13 base args + `(0, 0.0)` + `(False, None, None, None)` + `(20.0, 60.0 or given)` — 21 total; without it the tuple is unchanged from today (13 args); with an endpoint reporting 19 parameters → `ServerTooOldError` mentioning "Long pause speed" before `submit`; with an undescribable endpoint and a final log lacking `Long pauses:` → `ServerTooOldError` before writing the destination.
  - gui remote: args with `long_pause_speed`/`long_pause_seconds` are not reported as ignored and reach `send_video`.
- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_server.py tests/test_service_client.py tests/test_gui_remote.py -k long_pause -v` — Expected: FAIL.
- [ ] **Step 3: Implement.**
  - server: keyword `long_pause_speed: Optional[float] = None`, `long_pause_seconds: Optional[float] = None` on all three functions; `_stream_pipeline` sets `option_kwargs` only when speed `> 0`; update `process_video_api`'s docstring position list. No Web UI control.
  - client: `long_pause = long_pause_speed is not None and long_pause_speed > 0`; append the fps pair when `vad or long_pause or …`, the four VAD slots when `vad or long_pause` (`bool(vad)` and `None`s when off), then `(float(long_pause_speed), float(long_pause_seconds or 60.0))`. Replace `_server_too_old_for_vad` with `_server_too_old(server_url, feature: str)` ("Speedup no voice" / "Long pause speed", message otherwise unchanged); the parameter-count check runs when `vad or long_pause`; the log fallback tracks each requested feature's marker separately.
  - gui/remote.py: add both keys to `allowed_remote_keys`, pass `args.get(...)` to `send_video`.
- [ ] **Step 4: Run** the three test files in full — Expected: PASS (existing vad tests still green after the rename).
- [ ] **Step 5: Commit** — `feat: send long pause speed to the remote server`

---

### Task 5: GUI row

**Files:**
- Modify: `talks_reducer/gui/layout.py` (new row after Silent at `:1014-1035`; shift Sounded→6, Threshold→7, Mode→8 incl. `:1146`, Theme→9)
- Modify: `talks_reducer/gui/app.py:1663-1725` (`_collect_arguments`)
- Modify: `talks_reducer/gui/cut_marks_ui.py:17-25` (`_OVERRIDDEN_KEYS`)
- Modify: `talks_reducer/gui/summaries.py:238-274` (`format_conversion_params`)
- Test: `tests/test_gui_layout.py`, `tests/test_gui_app.py`, `tests/test_gui_cut_marks_ui.py`, `tests/test_gui_summaries.py`

**Interfaces:**
- Consumes: Task 2 option names (args keys `long_pause_speed`, `long_pause_seconds`).
- Produces in `layout.py`: `LONG_PAUSE_SPEED_RANGE = (1.0, 100.0)`, `LONG_PAUSE_SECONDS_RANGE = (5.0, 3600.0)`, `DEFAULT_LONG_PAUSE_SPEED = 20.0`, `DEFAULT_LONG_PAUSE_SECONDS = 60.0`; `parse_clamped(text: str, bounds: tuple[float, float], fallback: float) -> float`; `update_long_pause_state(gui) -> None`. GUI attributes: `long_pause_enabled_var` (BooleanVar), `long_pause_speed_text_var`, `long_pause_seconds_text_var` (StringVar), `long_pause_check`, `long_pause_speed_entry`, `long_pause_seconds_entry`. Preference keys `long_pause_enabled`, `long_pause_speed`, `long_pause_seconds`.

- [ ] **Step 1: Write failing tests.**
  - `parse_clamped("30", (1, 100), 20) == 30`, `("500", …) == 100`, `("0", …) == 1`, `("abc", …, 20) == 20`, `("", …, 20) == 20`, `("2,5", …)` → fallback.
  - layout: after `build_layout`, the row frame sits at `row=5` of `basic_options_frame` and `test_basic_options_frame_grid_positions_do_not_collide` still passes; check text `"Speedup x"`; entries start `state="disabled"` when the preference is off; toggling `long_pause_enabled_var` enables them and persists `long_pause_enabled`; committing an entry (Enter / FocusOut binding) clamps, rewrites the text with `{:g}`, persists the float.
  - `_collect_arguments` (extend `_make_collect_gui` defaults with the three vars, enabled `False`): enabled + Advanced → `long_pause_speed == 20.0`, `long_pause_seconds == 60.0`; enabled + Simple mode → keys absent; disabled → keys absent; uncommitted text `"35"` in the speed entry → `35.0` (collection parses text with `parse_clamped`, not a cached value).
  - `remove_only_overrides` drops both keys.
  - `format_conversion_params` with `long_pause_speed=20, long_pause_seconds=60` contains `long pauses ×20 >60s` right after the threshold / `no voice` part; absent otherwise.
- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_gui_layout.py tests/test_gui_app.py tests/test_gui_cut_marks_ui.py tests/test_gui_summaries.py -v` — Expected: new tests FAIL.
- [ ] **Step 3: Implement.** Row = `ttk.Frame` gridded `row=5, column=0, columnspan=3, sticky="w", pady=SETTING_ROW_PADY`, children **packed** left: `ttk.Checkbutton(text="Speedup x")`, speed `ttk.Entry(width=4)`, `ttk.Label("pauses longer than")`, seconds `ttk.Entry(width=5)`, `ttk.Label("seconds")`, small `padx` between. Not registered in `_basic_defaults`/`_basic_variables`/`_slider_updaters`. Entry commit: `<Return>` and `<FocusOut>` → `parse_clamped(text, range, fallback=last persisted)`, write back, `preferences.update`. `_collect_arguments`: `if not simple_mode and long_pause_enabled_var.get()` add both keys from `parse_clamped(text, range, DEFAULT_…)`. Shift the following rows' `row=` values.
- [ ] **Step 4: Run** the full suite `.venv/Scripts/python -m pytest -q` — Expected: PASS.
- [ ] **Step 5: Check a real window** (stubs do not model geometry, see CLAUDE.md): launch `.venv/Scripts/python -m talks_reducer.gui`, Advanced mode, screenshot — the row sits under Silent, entries align, nothing overlaps; Simple mode hides it.
- [ ] **Step 6: Commit** — `feat: add long pause speed row to the GUI`

---

### Task 6: Docs, TODO and live verification

**Files:**
- Modify: `README.md`, `docs/cli.md`, `docs/gui.md`, `CLAUDE.md` (GUI bullet for the row, speed index 3 in the `chunks.py` bullet, `Long pauses:` remote marker next to `VAD_LOG_MARKER`), `docs/TODO.md` (check off the item)

- [ ] **Step 1: Build a test clip** in the scratchpad: 10 s tone, 150 s silence with a 1 s beep at 70 s, 10 s tone:
  `ffmpeg -f lavfi -i "sine=f=440:d=10" -f lavfi -i "anullsrc=d=69" -f lavfi -i "sine=f=880:d=1" -f lavfi -i "anullsrc=d=80" -f lavfi -i "sine=f=440:d=10" -f lavfi -i "color=c=gray:s=320x240:r=30:d=170" -filter_complex "[0:a][1:a][2:a][3:a][4:a]concat=n=5:v=0:a=1[a]" -map 5:v -map "[a]" -shortest long_pause.mp4`
- [ ] **Step 2: Run** `.venv/Scripts/python -m talks_reducer long_pause.mp4 -s 10 -o base.mp4` and `… -s 10 --long-pause-speed 20 -o long.mp4`; compare durations with `ffprobe`. Expected: `long.mp4` silent part ≈ half of `base.mp4`'s (≈ 7.5 s vs ≈ 15 s), log shows `Long pauses: 1 stretch`, the beep is inside the stretch.
- [ ] **Step 3: Remote**: start `.venv/Scripts/python -m talks_reducer.server`, run the same with `--url http://127.0.0.1:9005` (port from server output); expected same duration as local and `Long pauses:` in the server log.
- [ ] **Step 4: Update docs** and check off the TODO item; verify each new flag appears in `docs/cli.md` and README by grepping `long-pause`.
- [ ] **Step 5: Commit** — `docs: document long pause speed`
