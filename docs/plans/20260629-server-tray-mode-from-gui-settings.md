# Server-tray mode from GUI settings

## Overview
- Add a persisted **"Run as server in tray"** toggle to the desktop GUI's Advanced
  panel so users can enter the server-tray experience (Gradio server + system
  tray/menu-bar icon) directly from the app icon, instead of only via the
  `talks-reducer-server-tray` CLI command in a terminal.
- **Problem it solves:** on macOS the only way to run the LAN server + tray today
  is a terminal command from the pip install. Double-clicking the `.app` only
  opens the plain GUI. This makes the server mode discoverable and one-click.
- **Key constraint that shapes the design:** on macOS, pystray's tray icon
  (`icon.run()`) and Tkinter's `mainloop()` **both require the process main
  thread** and cannot coexist in one process (see `resolve_tray_mode` in
  `server_tray.py`). Therefore the tray must be the *parent* process and the GUI
  a *child*. We reuse the already-working `talks-reducer-server-tray --with-gui`
  path, which runs the server + tray on the main thread and spawns the GUI as a
  `--server-managed` subprocess.
- **Chosen approach (all platforms):** toggling the setting **switches now and
  persists**. Turning it on relaunches the app into `--server --with-gui` mode
  and closes the current window; turning it off (from the server-managed GUI)
  relaunches a plain GUI and stops the parent tray. On the next cold start the
  launcher honors the persisted preference.

## Context (from discovery)
- Files/components involved:
  - `talks_reducer/gui/preferences.py` — `GUIPreferences` (generic
    `get`/`update`/`save`) + `PreferenceController` (per-key `on_*_change`
    callbacks). Config at `~/Library/Application Support/talks-reducer/settings.json`
    (macOS) / `%APPDATA%` / `~/.config`.
  - `talks_reducer/gui/app.py` — `TalksReducerGUI` (ctor accepts
    `server_managed`, `local_server_url`; sets close protocol + activity log when
    server-managed at lines ~392-394; `_on_close` at ~1693).
  - `talks_reducer/gui/layout.py` — Advanced panel (~542-695); existing
    checkboxes (optimize, use_global_ffmpeg) are the pattern to copy.
  - `talks_reducer/gui/startup.py` — `main()` already parses `--server`
    (delegates to `server_tray.main(remaining)`), `--server-managed`,
    `--server-url`; reads `sys.argv[1:]` when `argv is None`.
  - `talks_reducer/server_tray.py` — `main()` parses `--with-gui`;
    `_ServerTrayApplication.run()` starts server (bg thread) + tray (main
    thread) + optional GUI child; `_build_gui_command()` (~390) builds the
    child-GUI command.
  - `launcher.py` — PyInstaller entry → `talks_reducer.gui.main()` (forwards the
    bundle's own argv via `sys.argv[1:]`).
  - `talks-reducer.spec` — builds `talks-reducer.app` (bundle id
    `com.popstas.talks-reducer`).
  - `pyproject.toml` `[project.scripts]` — `talks-reducer-gui`,
    `talks-reducer-server-tray`, etc.
- Related patterns found: trace-based `BooleanVar` + `preferences.update(...)`
  per toggle; subprocess launch via `subprocess.Popen` with a daemon monitor
  thread (`server_tray._launch_gui`).
- Dependencies identified: `pystray`, `PIL`, Tkinter, `subprocess`, `sys.frozen`
  detection for PyInstaller bundles.

## Development Approach
- **Testing approach**: Regular (implement, then add/update unit tests) — matches
  the style in `tests/test_server_tray.py` and the GUI preference tests.
- Complete each task fully before moving to the next.
- Make small, focused changes; keep backward compatibility (default OFF, no
  behavior change for existing users).
- **CRITICAL: every task MUST include new/updated tests** for its code changes
  (success + error/edge scenarios), listed as separate checklist items.
- **CRITICAL: all tests must pass before starting the next task.**
- **CRITICAL: update this plan file when scope changes during implementation.**
- Run `black` + `isort` before considering a task done (project requirement).

## Testing Strategy
- **Unit tests**: required for every task.
  - Command-builder logic is the highest-value, fully unit-testable surface:
    test frozen vs non-frozen, server-tray vs plain-GUI commands by monkeypatching
    `sys.frozen` / `sys.executable` / `sys.platform`.
  - Preference persistence + controller callback via a temp config dir.
  - Toggle branch logic via monkeypatched spawn/close hooks (no real processes).
  - Startup routing decision via monkeypatched `server_tray.main` + a fake
    preferences object.
- **E2E tests**: the project has **no** automated UI e2e harness (no
  Playwright/Cypress); the GUI is Tkinter. Real end-to-end behavior (menu-bar
  icon appears, window close keeps server alive, toggle round-trips) is covered
  in **Post-Completion** manual checks, not automated here.

## Progress Tracking
- Mark completed items with `[x]` immediately when done.
- Add newly discovered tasks with ➕ prefix; blockers with ⚠️ prefix.
- Keep this plan in sync with actual work.

## What Goes Where
- **Implementation Steps** (`[ ]`): code, unit tests, docs in this repo.
- **Post-Completion** (no checkboxes): manual GUI/macOS `.app` testing, packaging
  verification, cross-platform spot checks.

## Implementation Steps

### Task 1: Frozen-aware app relaunch helper
- [x] Add `talks_reducer/gui/relaunch.py` with `build_app_command(mode, *, extra_args=None)`
      returning the argv to start the app in a given mode, handling both frozen
      PyInstaller bundles (`getattr(sys, "frozen", False)` → `[sys.executable, *args]`)
      and source/console runs (`[sys.executable, "-m", "talks_reducer.<module>", *args]`).
- [x] Support two modes: `"server-tray"` → server tray + managed GUI
      (frozen: `[exe, "--server", "--with-gui"]`; source: `[exe, "-m",
      "talks_reducer.server_tray", "--with-gui"]`) and `"gui"` → plain desktop GUI
      (frozen: `[exe]`; source: `[exe, "-m", "talks_reducer.gui"]`).
- [x] Add `spawn_detached(command)` that launches the process decoupled from the
      parent (`start_new_session=True` on POSIX; `DETACHED_PROCESS`/`CREATE_NEW_PROCESS_GROUP`
      creationflags on Windows) and returns the `Popen`.
- [x] write tests for `build_app_command` (frozen vs non-frozen × both modes,
      monkeypatching `sys.frozen`/`sys.executable`).
- [x] write tests for `spawn_detached` (monkeypatch `subprocess.Popen`, assert
      command + platform-appropriate kwargs; error path when Popen raises).
- [x] run `black`/`isort`; run tests — must pass before Task 2.

### Task 2: Add `start_in_server_tray` preference + Advanced checkbox
- [x] Define the preference key (default `False`) and seed
      `self.start_in_server_tray_var = tk.BooleanVar(...)` in `TalksReducerGUI`
      from `preferences.get("start_in_server_tray", False)`; set an internal
      `_suppress_server_tray_toggle` guard so seeding doesn't fire the action.
- [x] Add a **"Run as server in tray"** checkbox to the Advanced panel in
      `gui/layout.py` (mirror the optimize / use_global_ffmpeg checkbox wiring),
      bound to `start_in_server_tray_var`.
- [x] Add `on_start_in_server_tray_change()` to `PreferenceController` that calls
      `preferences.update("start_in_server_tray", bool(value))` and dispatches to
      the Task 3 switch logic.
- [x] write tests: `GUIPreferences` persists/loads the key round-trip via a temp dir.
- [x] write tests: controller callback updates the preference (monkeypatched
      switch hook so no process spawns).
- [x] run `black`/`isort`; run tests — must pass before Task 3.

### Task 3: Switch modes immediately when the toggle changes
- [x] Implement `TalksReducerGUI._apply_server_tray_toggle(enabled)`:
      when `enabled` and **not** `server_managed` → `spawn_detached(build_app_command("server-tray"))`,
      then close the current window; ignore (no-op) if already `server_managed`.
- [x] When **disabling** from a `server_managed` GUI → persist `False`,
      `spawn_detached(build_app_command("gui"))`, best-effort stop the parent tray
      (`os.kill(os.getppid(), signal.SIGTERM)` on POSIX; `CTRL_BREAK`/`taskkill`
      fallback on Windows, wrapped in `suppress(Exception)`), then close.
- [x] Guard re-entrancy: skip the action while `_suppress_server_tray_toggle` is set
      and never act inside a `--server-managed` child when *enabling* (prevents
      spawn loops).
- [x] write tests for the enable branch (non-managed): asserts command built +
      window-close hook called (monkeypatch `spawn_detached` and `root.destroy`).
- [x] write tests for the disable branch (managed): asserts plain-GUI command +
      best-effort parent-stop invoked (monkeypatch `os.kill`/Popen).
- [x] write tests for the guard: no spawn while suppressed / when managed+enable.
- [x] run `black`/`isort`; run tests — must pass before Task 4.

### Task 4: Honor the preference on cold start
- [ ] In `gui/startup.py:main`, after arg parsing, when there is **no** `--server`,
      **no** `--server-managed`, **no** positional inputs/seeded launch, and
      `GUIPreferences().get("start_in_server_tray", False)` is `True`, route into
      `server_tray.main(["--with-gui"])` and return (so the app boots straight into
      tray mode). Keep `--server-managed` children always running the plain GUI.
- [ ] Ensure the routing reads preferences without importing heavy GUI state
      (use the existing `GUIPreferences` loader) and is safe when the config file
      is missing/corrupt (treat as `False`).
- [ ] write tests: routing fires when pref True + no flags (monkeypatch
      `server_tray.main`, fake prefs); does **not** fire when `--server-managed`,
      when inputs present, or when pref False.
- [ ] run `black`/`isort`; run tests — must pass before Task 5.

### Task 5: Make the server-tray child-GUI command frozen-aware
- [ ] Update `server_tray._ServerTrayApplication._build_gui_command()` to use the
      Task 1 helper (`build_app_command("gui", extra_args=["--server-managed",
      "--server-url", url])`) so `--with-gui` works inside the frozen `.app`
      (current `-m talks_reducer.gui` fails when frozen).
- [ ] update existing `tests/test_server_tray.py` expectations for the command and
      add a frozen-case test (monkeypatch `sys.frozen`).
- [ ] run `black`/`isort`; run tests — must pass before Task 6.

### Task 6: Verify acceptance criteria
- [ ] Verify all Overview requirements are implemented (toggle present, persists,
      switches now, cold-start routing, frozen-aware commands).
- [ ] Verify edge cases: default OFF preserves current behavior; managed child never
      loops; missing config treated as OFF.
- [ ] Run the full unit test suite — must pass.
- [ ] Run `black --check` and `isort --check-only` — must be clean.
- [ ] (No automated e2e harness in this project — manual checks live in Post-Completion.)

### Task 7: [Final] Update documentation
- [ ] Update `README.md` (the macOS/Homebrew + GUI sections) to document the new
      "Run as server in tray" setting and how it relates to
      `talks-reducer-server-tray`.
- [ ] Update `CLAUDE.md` GUI notes to describe the toggle, the relaunch model, and
      the main-thread Tkinter-vs-pystray rationale.

*Note: ralphex automatically moves completed plans to `docs/plans/completed/`.*

## Technical Details
- **Mode detection at startup:** precedence is explicit flags first
  (`--server`, `--server-managed`, positional inputs/seeded launch) → then the
  persisted `start_in_server_tray` preference → else plain GUI.
- **Relaunch command matrix:**
  - Enable (non-managed): frozen `[exe, "--server", "--with-gui"]`; source
    `[exe, "-m", "talks_reducer.server_tray", "--with-gui"]`.
  - Disable (managed): frozen `[exe]`; source `[exe, "-m", "talks_reducer.gui"]`.
  - Child GUI (from tray): `... "--server-managed" "--server-url" <url>`.
- **Preference:** single boolean `start_in_server_tray` in the existing
  `settings.json`; no schema/versioning change needed (`GUIPreferences` is a flat
  key/value store).
- **Parent-stop on disable:** the managed GUI knows its parent via `os.getppid()`;
  the tray's `atexit`/`stop()` already tears down the server, so a SIGTERM to the
  parent is sufficient on POSIX. All parent-stop calls are best-effort
  (`suppress(Exception)`), so a failure never blocks switching back to the GUI.
- **Window close = "minimize to tray":** when `server_managed`, closing the window
  runs `_on_close` (destroy window only); the parent tray + server keep running and
  the tray's **Open GUI** item brings the window back. Confirm this remains true.

## Post-Completion
*Items requiring manual intervention or external systems — no checkboxes, informational only.*

**Manual verification:**
- macOS `.app`: enable the toggle → menu-bar icon appears (monochrome, from the
  recent icon work), GUI relaunches as a managed child; verify only one GUI window.
- Close the GUI window → server + menu-bar icon stay alive; **Open GUI** restores it.
- Disable the toggle from the managed GUI → plain GUI returns and the menu-bar
  icon/server shut down.
- Cold start with the preference enabled (quit + relaunch the `.app`) → boots
  straight into server-tray mode.
- Windows + Linux spot check: toggle on relaunches into tray; system tray icon
  appears; toggle off returns to the plain GUI.
- Port-in-use sanity: enabling when a server already runs on the default port —
  confirm the failure is surfaced (tray notify / log), not a silent hang.

**Packaging:**
- Rebuild the PyInstaller bundles (`scripts/build-gui.sh` / `talks-reducer.spec`)
  and confirm the frozen relaunch commands resolve (`sys.frozen` path), since
  `-m` module execution is unavailable in the bundle.
