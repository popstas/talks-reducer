# GUI Launch and Remote Transfer Progress Improvements

## Overview

Talks Reducer's desktop GUI and remote-server workflow have several launch and
progress gaps that hurt the user experience on macOS and Windows. Remote uploads
of a single large file jump straight to 100% before any bytes are sent and never
show download progress afterward. The Windows shortcut and macOS pip app cannot
launch the desktop GUI together with a server or pre-seed a dropped file, and the
system-tray icon does not appear on macOS. This plan addresses all four issues so
that launching the app and offloading work to a remote server behaves predictably
across platforms.

## Context

- Impacted components:
  - `talks_reducer/service_client.py` — remote upload/download client used by CLI and GUI remote mode.
  - `talks_reducer/gui/remote_io.py`, `talks_reducer/gui/remote.py` — GUI remote submission and progress mapping.
  - `talks_reducer/gui/progress.py` — `STAGE_PROGRESS_RANGES` / `map_stage_progress()` GUI percentage bands.
  - `talks_reducer/gui/startup.py` — GUI/CLI launch routing and `--server` flag handling.
  - `talks_reducer/server_tray.py` — tray-managed server entry point and pystray backend.
  - `talks_reducer/cli.py` — CLI argument parsing.
- Relevant constraints:
  - Progress must keep routing through `_set_progress_monotonic()` so the GUI bar never moves backwards (see project CLAUDE.md GUI Progress Convention).
  - Platform-specific behavior (desktop window, macOS pystray tray, Windows file-association drop, real remote upload) is verified manually, not in CI.
  - Keep `README.md` in sync with new CLI options/flags; run `black` and `isort` before committing.
- Adopted from `docs/TODO.md` (4 open task-list items).

## Development Approach

- Testing approach: regular (unit/integration tests for testable logic; manual e2e for platform/GUI behavior)
- Complete each task fully before moving to the next
- Update this plan when scope changes during implementation

## Testing Strategy

- Unit/integration tests required for every code-changing Task: CLI/GUI argument parsing and launch routing, `--server` + GUI launch wiring, remote upload progress callbacks / progress streaming, and download progress.
- Platform-specific behavior is verified manually on the actual machines (see Post-Completion): the desktop GUI window, the macOS pystray tray icon, dropping an mp4 onto a Windows shortcut, and a real remote upload to a server such as `http://192.168.1.26:9005`.
- Run project tests after each Task before proceeding.

## Technical Details

- Remote upload currently reports a single 100% jump because the upload step has no byte-level progress callback; it should stream real progress through the `Uploading` 0–5% band, then add a download phase after remote processing completes.
- `gui/startup.py` routes `--server` to `server_tray.main()` and returns before the desktop GUI is created, so server and GUI cannot run together; a combined launch path (new flag or extended `--server` behavior) is needed.
- The macOS pystray tray icon does not appear under `--server`; needs a working backend or a documented fallback (`--tray-mode headless` already exists for the no-icon case).

## Implementation Steps

### Task 1: Stream remote upload progress and add download progress

- [x] Add a byte-level progress callback to the remote upload path in `service_client.py` so a single large file advances incrementally instead of jumping to 100% at the start of "Uploading 1/1: <file> to <server>".
- [x] Route the streamed upload progress through the GUI `Uploading` band and the existing monotonic progress helper so the bar reflects real upload state in remote mode.
- [x] Show the incoming upload progress in the server console/log as the file is received, not only on the client.
- [x] After remote processing completes, report download progress on the client while the finished file is fetched back from the server.
- [x] Show the outgoing download-to-client progress in the server console/log as the finished file is sent back, mirroring the upload-side logging.
- [x] write tests for the upload/download progress callbacks and progress mapping
- [x] run project tests - must pass before next task

### Task 2: Launch GUI with positional file and CLI settings (file-association)

- [x] Update launch routing in `gui/startup.py` so that when the app is started with CLI args plus a positional/dropped file path (e.g. a Windows shortcut to `talks-reducer.exe --small --silent-speed 5` receiving a dropped mp4), it opens the GUI pre-seeded with that input file rather than doing nothing.
- [x] Apply the passed CLI settings (e.g. `--small`, `--silent-speed`) to the GUI controls when launching this way.
- [x] write tests for argument parsing and the launch-routing decision (args + positional file -> seeded GUI)
- [x] run project tests - must pass before next task

### Task 3: Run server and desktop GUI together from the macOS pip app

- [x] Add a way to start both the tray-managed server and the desktop GUI window from the macOS pip app (a combined flag such as `--with-gui`, or have `--server` also open the GUI), instead of `--server` launching only the server with no window.
- [x] Wire the launch path so the GUI and server processes/threads start cleanly together and shut down without leaks.
- [x] Update `README.md` to document the combined launch option.
- [x] write tests for the launch wiring/routing of the combined server+GUI mode
- [x] run project tests - must pass before next task

### Task 4: Make the macOS system-tray icon work

- [ ] Investigate why the pystray tray icon does not appear on macOS under `--server` and make it render (correct backend/run mode), or provide a documented working fallback.
- [ ] Ensure the existing `--tray-mode headless` path remains a clean no-icon fallback and document the macOS guidance in `README.md`.
- [ ] write tests for the tray-mode selection/backend resolution logic that can be exercised off-platform
- [ ] run project tests - must pass before next task

### Task 5: Verify acceptance criteria

- [ ] verify all requirements from Overview are implemented
- [ ] run full project test suite
- [ ] run project linter (black, isort) - all issues must be fixed

## Post-Completion

*Items requiring manual intervention - no checkboxes, informational only*

- Manual e2e (remote progress): upload a single large mp4 to a real server such as `http://192.168.1.26:9005` and confirm the upload progress advances incrementally (not an instant 100%) on both the client and the server console/log, and that download progress is shown after remote processing on both the client and the server console/log.
- Manual e2e (Windows file-association): create a Windows shortcut to `talks-reducer.exe --small --silent-speed 5`, drop an mp4 onto it in Explorer, and confirm the GUI opens pre-seeded with the file and the passed settings applied.
- Manual e2e (macOS server+GUI): launch the macOS pip app in the combined mode and confirm both the server and the desktop GUI window appear.
- Manual e2e (macOS tray): run `--server` on macOS and confirm the tray icon appears and its menu works; if using the documented fallback, confirm the server is reachable at its URL.
