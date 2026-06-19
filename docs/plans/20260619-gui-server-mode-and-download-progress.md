# GUI Server-Mode Visibility and Remote Download Progress Fixes

## Overview

Four user-facing gaps in the desktop GUI's remote/server workflow:

1. **Progress gap before download** — after remote processing finishes and before
   the download starts, the GUI shows "Processing" at 100% for ~10s with no
   feedback. Show a distinct, periodically-updated status (e.g. "Waiting for
   download…") so the user knows the job is still progressing.
2. **Triple 100% download** — while downloading the processed file, the download
   progress reaches 100% three separate times. Download progress must advance to
   100% only once.
3. **Connected-clients activity log (server mode)** — when the GUI runs in server
   mode it shows no indication of who is using the server. Surface a scrolling
   activity log of recent client requests (timestamp + client IP + action).
4. **Local server URL (server mode)** — when started with `--server`, show a text
   label near "Processing mode" with the LAN-reachable server URL
   (e.g. `http://192.168.x.x:<port>`) so other users on the network can connect.

Items 1–2 are bug fixes in the remote client/progress path. Items 3–4 are
server-mode features. The benefit is a clearer remote workflow and an operator
view of server usage.

## Context (from discovery)

### Process architecture (critical constraint)

`talks-reducer-gui --server` does **not** run the server in the GUI process.
`cli.py:633` routes `--server` to `_launch_server_tray`, which starts the Gradio
server in the **tray process** and launches the desktop GUI as a **separate
subprocess** (`server_tray.py:323` → `subprocess.Popen([sys.executable, "-m",
"talks_reducer.gui"])`). Therefore items 3–4 require **cross-process**
communication: the GUI cannot read the server's in-memory state directly.

- Server identity/IP: `talks_reducer/server.py:268` `_describe_server_host()`
  (returns hostname + IP); `talks_reducer/server_tray.py:41` `_guess_local_url()`
  / `:68` `_normalize_local_url()` compute the browser URL.
- Gradio app: `talks_reducer/server.py` `build_interface()` (~line 603) builds the
  `gr.Blocks` demo; `build_launch_app_kwargs()` configures launch. Gradio is
  FastAPI/Starlette-based, so request middleware and extra routes can be mounted
  on the underlying app.
- Tray → GUI launch: `server_tray.py:307` `_launch_gui()` spawns the GUI subprocess
  (no extra args today). `TrayApp.__init__` has `launch_gui` flag (`:202`/`:208`)
  and is created via `create_tray_app(... launch_gui=...)` (`:503`).

### Remote progress path (GUI client)

- `talks_reducer/service_client.py:70` `_ProgressResponse.iter_bytes()` emits
  `"Downloading:"` events: a `0` at start (`:88`) then per-chunk (`:91`). Each
  separate download response runs a full 0→100 cycle — the likely source of the
  "100% three times" (the remote returns more than one file / the endpoint is hit
  multiple times). `send_video()` (`:243`) orchestrates upload → poll → download.
- `talks_reducer/gui/remote.py:306` `_handle_remote_progress()` maps streamed
  progress to the bar (`map_stage_progress`, `:320`) and status text (`:340`,
  `gui._set_status("processing", text)`). There is **no** status emitted between
  the last processing event and the first `"Downloading:"` event → the ~10s gap.
- `talks_reducer/gui/progress.py:13` `STAGE_PROGRESS_RANGES` /
  `:21` `map_stage_progress()`. `"Downloading:"` is **not** a known stage prefix,
  so it falls through to raw `fraction * 100.0` (`:44`) — each download cycle
  drives the bar 0→100 independently.

### GUI layout / processing-mode UI

- `talks_reducer/gui/layout.py:315` "Processing mode" label + Local/Remote radios;
  `:336` "Server URL" entry + "Discover" button (this is the *client's remote
  target*, not a display of the *local* server URL).
- `talks_reducer/gui/app.py:267` `processing_mode_var`; `:280` `server_url_var`;
  `:306` startup server ping. The GUI `__main__` entry parses its own argv.

### Tests (pytest)

- `tests/test_gui_progress.py` — `map_stage_progress` + progress handle/reporter.
- `tests/test_service_client.py` — `DummyJob`/`StreamingDummyJob`/`DummyClient`
  stubs; upload/download progress events (`test_send_video_emits_upload_progress`).
- `tests/test_gui_remote.py` — `StubGUI` with `progress_values`, `status_history`,
  `stage_transitions`; `test_process_files_via_server_streams_upload_and_download`
  (asserts download 100% status reaches the history).
- `tests/test_server.py` — `_describe_server_host`, pipeline jobs, transfer
  middleware.
- `tests/test_server_tray.py` — tray mode/URL helpers (verify exact name during
  implementation).

## Development Approach

- **Testing approach**: Regular (implement, then write/update unit tests in the
  same task, then run before moving on).
- Complete each task fully before the next; small focused changes.
- **CRITICAL: every task MUST include new/updated tests** for its code changes
  (success + error/edge cases), listed as separate checklist items.
- **CRITICAL: all tests must pass before starting the next task.**
- Run `black` and `isort` (configured in `pyproject.toml`) on touched files.
- Maintain backward compatibility: behavior with no `--server` and with the
  standalone CLI must be unchanged. New server endpoints/args must be additive.
- **Update this plan file when scope changes during implementation.**

## Testing Strategy

- **Unit tests**: required every task (see above). Use the existing stub classes
  (`StubGUI`, `DummyClient`, `DummyProgress`) rather than real Tk/Gradio/network.
- **E2E / manual**: there is no automated UI e2e harness (Tkinter GUI + Gradio).
  Manual server-mode verification (real LAN URL, real second client) is listed in
  Post-Completion, not as task checkboxes.

## Progress Tracking

- Mark completed items `[x]` immediately when done.
- Add newly discovered tasks with ➕ prefix; blockers with ⚠️ prefix.
- Keep this plan in sync with actual work.

## What Goes Where

- **Implementation Steps** (`[ ]`): code, tests, docs achievable in this repo.
- **Post-Completion** (no checkboxes): manual macOS/Windows/LAN verification and
  real multi-client checks.

## Implementation Steps

### Task 1: Fix download progress reaching 100% only once
- [x] In `talks_reducer/service_client.py`, diagnose why `"Downloading:"` reaches
      100% multiple times (multiple download responses / repeated `iter_bytes`
      0-start). Confirm the exact trigger before changing behavior
      (`superpowers:systematic-debugging`). **Diagnosis:** the gradio client
      invokes the patched `_download_file` more than once per job — intermediate
      streamed outputs plus the two file output components (`video_path` at index
      0 and `download_path` at index 3 of the response tuple) each trigger a
      download, and every invocation drives a fresh `_ProgressResponse.iter_bytes`
      0→100 byte cycle through the shared `progress_callback`.
- [x] Make download progress monotonic to a single 0→100: track cumulative
      received bytes across the whole download (or suppress repeated terminal
      `100%` emissions / extra non-primary file downloads) so only one 0→100
      sequence reaches the callback. **Done:** added
      `_MonotonicDownloadProgress`, created once per `_install_transfer_progress`
      so its `_max_fraction` state persists across every `_download_file` call;
      it forwards only strictly increasing download fractions (one terminal 100%).
- [x] Ensure the `"Downloading:"` desc maps to a non-decreasing bar value in
      `talks_reducer/gui/progress.py` (decide: keep raw 0–100 but dedupe at the
      source, or add a bounded download band — prefer source dedupe to avoid
      changing existing stage bands; document the choice in this plan).
      **Decision:** kept the raw 0–100 mapping (no change to
      `STAGE_PROGRESS_RANGES`); deduped at the source in `service_client.py` so
      the existing upload/extract/audio/final bands are untouched. The GUI bar
      stays monotonic via `_set_progress_monotonic`.
- [x] write tests in `tests/test_service_client.py`: a download that internally
      emits 100% more than once (and/or multiple responses) yields a single
      monotonic 0→100 sequence with exactly one final 100% to the callback.
      (`test_monotonic_download_progress_collapses_repeated_cycles`,
      `test_monotonic_download_progress_passes_through_other_descs`,
      `test_monotonic_download_progress_forwards_unknown_total`,
      `test_install_transfer_progress_dedupes_repeated_downloads`)
- [x] write/extend tests in `tests/test_gui_remote.py` (`StubGUI`) asserting the
      download bar value reaches 100 once and never decreases.
      (`test_process_files_via_server_download_bar_reaches_100_once`)
- [x] run `pytest` (at least the touched test modules) — must pass before Task 2.
      (68 passed across `test_service_client.py`, `test_gui_remote.py`,
      `test_gui_progress.py`)

### Task 2: Show "Waiting for download…" during the processing→download gap
- [x] In `talks_reducer/gui/remote.py` `_handle_remote_progress` (or the
      `send_video` flow in `service_client.py`), emit a distinct status when
      remote processing completes and before the first `"Downloading:"` event.
      **Done:** `_handle_remote_progress` now calls `gui._begin_download_wait()`
      after the `"Generating final:"` stage reports completion (`current >=
      total`), emitting the `"Waiting for download…"` status after the
      completion status is queued and before the first `"Downloading:"` event.
- [x] Refresh the waiting status at least every 5s (e.g. a lightweight repeating
      `root.after`/timer that clears as soon as the first download bytes arrive)
      so the GUI never sits silent for ~10s. Route any bar change through
      `_set_progress_monotonic` per the GUI Progress Convention.
      **Done:** added `TalksReducerGUI._begin_download_wait` /
      `_emit_download_wait` / `_cancel_download_wait`. `_emit_download_wait`
      re-emits the status and reschedules itself every
      `DOWNLOAD_WAIT_INTERVAL_MS` (5000 ms) via `root.after`. The heartbeat only
      changes status text, not the bar.
- [x] Ensure the waiting status/timer is cancelled on download start, on error,
      and on stop-request (no leaked timers between batch files).
      **Done:** `_handle_remote_progress` cancels on the first `"Downloading:"`
      event; `process_files_via_server` cancels after each `send_video` returns,
      in the `ProcessingAborted` (stop) branch, and in the generic error branch.
- [x] write tests in `tests/test_gui_remote.py`: a `("processing", "Waiting for
      download…")`-style status appears between the last processing event and the
      first download event, and the timer stops once download begins.
      (`test_process_files_via_server_waits_for_download_after_processing`,
      `test_process_files_via_server_does_not_wait_without_final_completion`)
      plus GUI timer unit tests in `tests/test_gui_app.py`
      (`test_begin_download_wait_emits_status_and_schedules_refresh`,
      `test_emit_download_wait_reschedules_itself`,
      `test_begin_download_wait_cancels_existing_timer_before_restart`,
      `test_cancel_download_wait_cancels_active_timer`,
      `test_cancel_download_wait_is_noop_when_idle`).
- [x] write a test for the cancel/stop path (waiting status does not linger after
      stop or error). (`test_process_files_via_server_cancels_waiting_on_stop`)
- [x] run `pytest` — must pass before Task 3. (403 passed; `black`/`isort`
      clean on touched files.)

### Task 3: Server-side client activity recorder + activity endpoint
- [x] Add a bounded in-memory activity recorder (a `collections.deque(maxlen=N)`)
      in `talks_reducer/server.py` capturing `(timestamp, client_ip, action)` for
      incoming requests (use a FastAPI/Starlette middleware mounted on the Gradio
      app, or hook the existing transfer middleware). Keep it process-local and
      thread-safe. **Done:** added `ActivityEntry`, `ActivityRecorder`
      (`deque(maxlen=_ACTIVITY_MAXLEN=100)` guarded by a `threading.Lock`), and a
      module-level `_ACTIVITY_RECORDER` singleton. `ActivityMiddleware` records
      meaningful client requests (upload/download/process via `_classify_activity`)
      and is registered alongside `TransferProgressMiddleware` in
      `build_launch_app_kwargs`.
- [x] Add a small read-only JSON endpoint (e.g. `GET /activity`) on the Gradio
      app returning recent entries plus server identity/URL
      (reuse `_describe_server_host` / `_guess_local_url`). Additive only; does not
      alter existing routes. **Done:** `ActivityMiddleware` intercepts
      `GET /activity` and returns `{"server": {"identity", "url"}, "entries":
      [...]}`. Identity reuses `_describe_server_host`; the LAN URL is built from
      the new `_resolve_host_ip` helper plus the bound port from the ASGI scope
      (falls back to `null` when unavailable). All other paths pass through
      untouched.
- [x] write tests in `tests/test_server.py`: middleware records entries with
      client IP + timestamp + action; deque respects `maxlen`; endpoint returns
      recent entries and identity in the expected JSON shape.
      (`test_activity_recorder_records_and_respects_maxlen`,
      `test_activity_middleware_records_upload_with_client_ip`,
      `test_activity_middleware_records_download_and_uses_forwarded_for`,
      `test_activity_middleware_ignores_unrelated_routes`,
      `test_activity_endpoint_returns_entries_and_identity`,
      `test_activity_recorder_clear_empties_entries`, plus the extended
      `test_build_launch_app_kwargs_registers_middleware`)
- [x] write a test for the empty/no-activity case.
      (`test_activity_endpoint_handles_empty_recorder`)
- [x] run `pytest` — must pass before Task 4. (410 passed; `black`/`isort` clean
      on `talks_reducer/server.py` and `tests/test_server.py`.)

### Task 4: Plumb server-mode context into the GUI subprocess
- [x] In `talks_reducer/server_tray.py` `_launch_gui()`, pass the server context
      to the GUI subprocess (e.g. `--server-managed` flag + `--server-url <local
      url>` arg, or env vars) so the GUI knows it is running under a managed
      server and where to reach it. **Done:** added
      `_ServerTrayApplication._build_gui_command`, which appends `--server-managed`
      plus `--server-url <local url>` (preferring the server's reported
      `_local_url`, falling back to `_guess_local_url(host, port)`), and
      `_launch_gui` now spawns that command via `subprocess.Popen`.
- [x] In the GUI entry point (`talks_reducer/gui/__main__`/`app.py` argv parsing),
      accept and store the server-mode flag + local URL; expose them to the GUI
      app (e.g. a `server_managed` attribute and `local_server_url`). **Done:**
      `gui/startup.py:main` now registers `--server-managed`/`--server-url` on the
      pre-parser and forwards `server_managed`/`local_server_url` to every
      `TalksReducerGUI(...)` construction; `TalksReducerGUI.__init__` accepts the
      two keyword args and stores `self.server_managed` / `self.local_server_url`.
- [x] Keep standalone GUI launch (no args) and standalone CLI unchanged when the
      flag/args are absent. **Done:** without `--server-managed` the attrs default
      to `False`/`None`; a bare `--server-url` (CLI/seeded launch) is re-injected
      into the remaining argv so the downstream CLI parser still receives it.
- [x] write tests for the argv/env parsing (flag present → server-mode attrs set;
      absent → defaults/unchanged). (`test_main_sets_server_managed_context`,
      `test_main_defaults_to_standalone_without_managed_flag`,
      `test_main_server_url_without_managed_flag_passes_to_cli` in
      `tests/test_gui_startup.py`)
- [x] write a test that `_launch_gui` builds the subprocess command including the
      server-mode args (mock `subprocess.Popen`).
      (`test_build_gui_command_uses_guessed_url_before_server_ready`,
      `test_build_gui_command_prefers_reported_local_url`, and the updated
      `test_launch_gui_resets_completed_process` in `tests/test_server_tray.py`)
- [x] run `pytest` — must pass before Task 5. (415 passed; `black`/`isort` clean
      on touched files.)

### Task 5: Display local server URL near "Processing mode"
- [x] In `talks_reducer/gui/layout.py` near the "Processing mode" controls
      (`:315`), add a label widget that shows the local server URL; in
      `talks_reducer/gui/app.py` populate it from the server-mode context (Task 4)
      and show it only in server mode (hidden/blank otherwise). **Done:**
      `build_layout` now creates `gui.local_server_url_label` at row 4, column 2
      (next to the Local/Remote radios), populated via the new module-level
      `format_local_server_url()` helper when `gui.server_managed` is set and
      `grid_remove()`-hidden otherwise. `TalksReducerGUI._update_local_server_url_display()`
      re-applies the text/visibility from `self.server_managed` /
      `self.local_server_url` for later refreshes.
- [x] Format the URL as the LAN-reachable address (prefer the IP from
      `_describe_server_host`, not loopback) with the port. **Done:** the URL is
      already resolved to the LAN address upstream in Task 4 (tray passes the
      reported `_local_url` / `_guess_local_url(host, port)` via `--server-url`);
      `format_local_server_url()` renders it as `Server: http://<ip>:<port>`
      (trailing slash trimmed) for display.
- [x] write tests asserting the URL label is populated/visible in server mode and
      empty/hidden in normal mode, and that the formatted URL matches expected.
      (`test_format_local_server_url`,
      `test_build_layout_shows_local_server_url_in_managed_mode`,
      `test_build_layout_hides_local_server_url_in_standalone_mode` in
      `tests/test_gui_layout.py`; `test_update_local_server_url_display_shows_url_in_server_mode`,
      `test_update_local_server_url_display_hidden_in_standalone_mode`,
      `test_update_local_server_url_display_noop_without_label` in
      `tests/test_gui_app.py`)
- [x] run `pytest` — must pass before Task 6. (147 passed across
      `test_gui_layout.py`, `test_gui_app.py`, `test_gui_remote.py`,
      `test_gui_startup.py`; `black`/`isort` clean on touched files.)

### Task 6: Display connected-clients activity log in the GUI (server mode)
- [x] In `talks_reducer/gui/layout.py`, add a read-only scrolling log/text panel
      (server mode only) for client activity; wire visibility in
      `talks_reducer/gui/app.py`. **Done:** `build_layout` now creates
      `gui.activity_frame` (row 4 of `main`) with a "Connected clients" label and
      a read-only `gui.activity_text` Text widget plus scrollbar; it is
      `grid_remove()`-hidden unless `gui.server_managed` is set.
- [x] In server mode, poll the server `/activity` endpoint (Task 3) on an interval
      (e.g. via `root.after`, ~5s) and render entries as
      `HH:MM:SS  <ip>  <action>` lines; handle the server being unreachable
      gracefully (no crash, no spam). **Done:** added
      `TalksReducerGUI._poll_activity` (worker thread → `_fetch_activity` →
      `_finish_activity_poll` on the UI thread, re-armed every
      `ACTIVITY_POLL_INTERVAL_MS` = 5000 ms). `_fetch_activity` GETs
      `<url>/activity` via `urllib` with a 5s timeout and returns `None` on any
      error/malformed payload; `_render_activity` renders lines via the new
      `layout.format_activity_line()` helper.
- [x] Ensure the poller starts only in server mode and is cancelled on close
      (no leaked timers/threads). **Done:** `_start_activity_log` no-ops unless
      `server_managed` + `local_server_url` are set and refuses to double-start;
      `__init__` registers `WM_DELETE_WINDOW` → `_on_close`, which calls
      `_stop_activity_log` (cancels the `root.after` timer) and
      `_cancel_download_wait` before `root.destroy()`.
- [x] write tests for the activity-line formatting and for the poll-update path
      (stub the HTTP fetch; feed sample entries → expected rendered lines).
      (`test_format_activity_line_renders_clock_ip_action`,
      `test_format_activity_line_tolerates_missing_fields`,
      `test_build_layout_shows_activity_log_in_managed_mode`,
      `test_build_layout_hides_activity_log_in_standalone_mode` in
      `tests/test_gui_layout.py`; `test_render_activity_writes_formatted_lines`,
      `test_render_activity_clears_when_empty`,
      `test_render_activity_noop_without_widget`,
      `test_fetch_activity_returns_entries`,
      `test_finish_activity_poll_renders_and_reschedules`,
      `test_poll_activity_runs_worker_and_finishes`,
      `test_start_activity_log_*`, `test_stop_activity_log_*`,
      `test_on_close_cancels_timers_and_destroys` in `tests/test_gui_app.py`)
- [x] write a test for the unreachable-server path (poller tolerates errors).
      (`test_fetch_activity_tolerates_unreachable_server`,
      `test_fetch_activity_handles_malformed_payload`,
      `test_finish_activity_poll_skips_render_on_error_but_reschedules`,
      `test_finish_activity_poll_stops_when_not_server_managed`)
- [x] run `pytest` — must pass before Task 7. (445 passed; `black`/`isort` clean
      on touched files.)

### Task 7: Verify acceptance criteria
- [ ] Verify all four Overview requirements are implemented end to end in code.
- [ ] Verify edge cases: stop mid-download, batch of multiple files (no leaked
      timers, monotonic bar per file), normal (non-server) mode unaffected.
- [ ] Run the full test suite (`pytest`) — all green.
- [ ] Run `black` and `isort` — no changes needed / all applied.
- [ ] Confirm no regression in existing progress/remote/server tests.

### Task 8: [Final] Update documentation
- [ ] Update `README.md` for the new server-mode local-URL label and clients
      activity log, and any new `--server`-related GUI args.
- [ ] Update `CLAUDE.md`/`AGENTS.md` GUI section if new server-mode UI or progress
      conventions were introduced.

## Technical Details

- **Download dedupe**: prefer fixing at the source in `service_client.py` (track
  cumulative bytes / suppress repeated terminal 100% or non-primary downloads)
  over reshaping `STAGE_PROGRESS_RANGES`, to avoid disturbing the existing
  upload/extract/audio/final bands. The GUI bar must remain monotonic via
  `_set_progress_monotonic`.
- **Waiting status**: a repeating UI-thread timer (`root.after`) emitting the
  waiting status every ≤5s, cleared on the first `"Downloading:"` byte, on error,
  and on stop.
- **Cross-process server state**: server records activity in a bounded deque and
  exposes `GET /activity` (recent entries + identity); the GUI subprocess receives
  `--server-managed`/`--server-url` from the tray and polls that endpoint. This is
  required because the GUI runs in a different process than the server.
- **Activity entry**: `(timestamp, client_ip, action)`; rendered as
  `HH:MM:SS  <ip>  <action>`.

## Post-Completion
*Manual / external verification — no checkboxes.*

**Manual verification:**
- Run `talks-reducer-gui --server` on macOS and Windows; confirm the GUI window
  shows the LAN URL near "Processing mode" and that the URL is reachable from a
  second machine on the LAN.
- From a second client, upload a file and confirm an activity line appears in the
  server-mode GUI log with the client IP and a timestamp.
- Process a large single file via remote mode; confirm: a visible "Waiting for
  download…" status (refreshing) during the post-processing gap, and the download
  bar reaches 100% exactly once.
- Confirm standalone GUI (no `--server`) and the plain CLI are unchanged.
