# macOS Update Check (Advanced settings button)

## Overview
- Extend the existing **Windows-only** update checker so the desktop GUI can also
  check for new releases on **macOS** via a "Check updates" button placed in the
  **Advanced settings** panel (mirroring the Windows button UX).
- Problem it solves: macOS users currently have no in-app way to learn a newer
  version exists. The app is **unsigned** and **installed via Homebrew**
  (`popstas/homebrew-talks-reducer`), so self-replacing the `.app` is out of scope
  and unsafe (Gatekeeper/quarantine, code signing). Instead, the macOS flow
  detects a newer release and points the user to it — the GitHub releases page and
  the `brew upgrade --cask talks-reducer` command — without downloading or
  installing anything automatically.
- Integrates with the current `update_checker` module and the existing
  `_check_for_updates` / `_on_update_check_complete` GUI flow, branching by
  platform so Windows behavior is unchanged.

## Context (from discovery)
- Files/components involved:
  - `talks_reducer/gui/update_checker.py` — version fetch/compare/url helpers;
    `fetch_latest_version()` currently early-returns an error on non-Windows
    (`is_windows()` guard, lines 15-30). Release-tag fetch logic itself is
    platform-agnostic.
  - `talks_reducer/gui/app.py` — `_check_for_updates()` (line 837, early-returns
    on non-win32), `_on_update_check_complete()` (line 895, switches button to a
    Windows installer "Download" action), `_download_and_install_update()` /
    `_on_download_complete()` (Windows installer launch), and the
    `_set_update_status*` / `_clear_update_status` label helpers (~line 1037).
  - `talks_reducer/gui/layout.py` — builds `check_updates_button` +
    `update_status_label` inside `button_frame`, gated `if sys.platform == "win32"`
    (lines 516-540). `advanced_frame` (the collapsible Advanced panel) starts at
    line 542.
  - `talks_reducer/__about__.py` — `__version__` (single source of truth).
  - `.github/workflows/ci.yml` line 78 — macOS asset named
    `talks-reducer-macos.app-{VERSION}.zip`.
- Related patterns found: threaded check worker + `_schedule_on_ui_thread`
  callbacks; status label updates guarded by `hasattr(self, "update_status_label")`.
- Dependencies identified: `urllib` (stdlib), `webbrowser` (stdlib, for opening the
  releases page). No new third-party dependencies.

## Development Approach
- **Testing approach**: Regular (code first, then tests) — chosen by user.
- Complete each task fully before moving to the next.
- Make small, focused changes; keep Windows behavior byte-for-byte unchanged.
- **CRITICAL: every task MUST include new/updated tests** for code changes in that
  task (success + error/edge scenarios).
- **CRITICAL: all tests must pass before starting the next task.**
- Run `black` and `isort` (configured in `pyproject.toml`) before committing.
- Maintain backward compatibility (Windows installer flow untouched).

## Testing Strategy
- **Unit tests**: new `tests/test_update_checker.py` covering platform gating, the
  macOS URL/command helpers, and `fetch_latest_version` no longer being gated out
  on macOS (network mocked via `monkeypatch`/fake `urlopen`). Keep pure logic in
  `update_checker` so it is unit-testable without Tk.
- **No e2e suite**: project has no Playwright/Cypress e2e tests; GUI wiring is
  verified by the existing pytest GUI tests (`tests/test_gui_*.py`) plus manual
  verification (see Post-Completion).

## Progress Tracking
- Mark completed items with `[x]` immediately when done.
- Add newly discovered tasks with ➕ prefix; blockers with ⚠️ prefix.
- Keep this plan in sync with actual work.

## What Goes Where
- **Implementation Steps** (`[ ]`): code, tests, docs in this repo.
- **Post-Completion** (no checkboxes): manual macOS app verification on a real
  Homebrew install.

## Implementation Steps

### Task 1: Make `update_checker` macOS-aware (pure logic + helpers)
- [ ] in `talks_reducer/gui/update_checker.py`, add `is_macos()` returning
      `sys.platform == "darwin"` and `is_update_check_supported()` returning
      `is_windows() or is_macos()`.
- [ ] change the `fetch_latest_version()` guard from `if not is_windows()` to
      `if not is_update_check_supported()` so macOS reaches the (already
      platform-agnostic) GitHub release-tag fetch; keep the Windows path identical.
- [ ] add `get_macos_app_url(version)` returning
      `https://github.com/popstas/talks-reducer/releases/download/v{version}/talks-reducer-macos.app-{version}.zip`.
- [ ] add `get_brew_upgrade_command()` returning
      `"brew upgrade --cask talks-reducer"` (single source for the message/clipboard).
- [ ] create `tests/test_update_checker.py`: tests for `is_macos`,
      `is_update_check_supported`, `get_macos_app_url`, `get_brew_upgrade_command`,
      `compare_versions` (newer/older/equal/padded/malformed), and
      `fetch_latest_version` on macOS (monkeypatch `sys.platform="darwin"` + a fake
      `urlopen` redirecting to `/releases/tag/v9.9.9`) plus the
      unsupported-platform error case.
- [ ] run `pytest tests/test_update_checker.py` — must pass before Task 2.

### Task 2: Branch the GUI check-complete flow for macOS
- [ ] in `talks_reducer/gui/app.py`, relax `_check_for_updates()` so it runs when
      the check is supported and the button exists: replace
      `if not sys.platform == "win32": return` with a guard using
      `update_checker.is_update_check_supported()` (still no-op without a
      `check_updates_button`).
- [ ] in `_on_update_check_complete()`, branch when `latest_version` is newer: on
      **Windows**, keep the existing installer "Download" wiring; on **macOS**, set
      status to `New version {v} is available! Update with: brew upgrade --cask
      talks-reducer` with links `[("Releases page", get_releases_page_url())]` and
      leave the button as "Check updates" (no installer download). Use
      `update_checker.is_macos()` to branch.
- [ ] do NOT call `_download_and_install_update` on macOS (no installer .exe);
      ensure the macOS branch never wires that command onto the button.
- [ ] extract the "build update-available presentation" decision into a small pure
      helper (e.g. `update_checker.build_update_message(version, platform)` or a
      module-level function) so the branch is unit-testable without Tk.
- [ ] add tests in `tests/test_update_checker.py` for the message-builder helper
      (Windows vs macOS text/links; brew command present only on macOS).
- [ ] run `pytest tests/test_update_checker.py tests/test_gui_app.py` — must pass
      before Task 3.

### Task 3: Add the Advanced-panel "Check updates" button on macOS
- [ ] in `talks_reducer/gui/layout.py`, add a macOS branch that creates
      `gui.check_updates_button` (command `gui._check_for_updates`) and
      `gui.update_status_label` inside the **Advanced** panel (`gui.advanced_frame`),
      not the always-visible `button_frame`, so it appears under Advanced settings.
- [ ] keep the existing Windows block (in `button_frame`) unchanged; ensure the two
      branches are mutually exclusive and a non-Windows/non-macOS platform creates
      neither (no `check_updates_button` attribute → handlers remain no-ops).
- [ ] confirm `_set_update_status`, `_set_update_status_with_links`, and
      `_clear_update_status` operate via `hasattr(self, "update_status_label")` so
      they work for the macOS label placement.
- [ ] add/extend a test in `tests/test_gui_layout.py` (monkeypatching
      `sys.platform="darwin"`) asserting the macOS layout creates
      `check_updates_button` + `update_status_label` and that they live under the
      Advanced frame; assert a Linux platform creates neither.
- [ ] run `pytest tests/test_gui_layout.py tests/test_update_checker.py` — must pass
      before Task 4.

### Task 4: Verify acceptance criteria
- [ ] verify Overview requirements: macOS button in Advanced settings, detects newer
      release, points to releases page + brew command, no auto-install.
- [ ] verify Windows installer flow is unchanged (button text/commands identical).
- [ ] run the full unit suite (`pytest`).
- [ ] run `black .` and `isort .` — no diffs left.
- [ ] verify new code paths have tests (success + error/edge).

### Task 5: [Final] Update documentation
- [ ] update `README.md` (and `CLAUDE.md` GUI section if appropriate) to note the
      macOS "Check updates" button under Advanced settings and that macOS updates
      are applied via `brew upgrade --cask talks-reducer`.

*Note: ralphex automatically moves completed plans to `docs/plans/completed/`.*

## Technical Details
- macOS "update available" presentation: status text plus the brew command and a
  link to `get_releases_page_url()`; the macOS `.app` zip URL
  (`get_macos_app_url`) is provided as a helper for the link/future use but is
  **not** auto-downloaded.
- Version comparison reuses the existing integer-tuple `compare_versions`.
- Platform branching is centralized in `update_checker` (`is_macos`,
  `is_update_check_supported`) so `app.py`/`layout.py` only ask yes/no questions.
- No new dependencies; `webbrowser`/`urllib` are stdlib. Opening the releases page
  reuses the existing link mechanism in `_set_update_status_with_links`.

## Post-Completion
*Items requiring manual intervention or external systems — informational only.*

**Manual verification**:
- On a real macOS Homebrew install of an older version, open Advanced settings,
  click **Check updates**, and confirm it reports the newer version with the brew
  command and a working Releases-page link.
- Confirm "up to date" and network-error messages render correctly on macOS.
- Confirm the Windows build still shows the button in its usual place and the
  installer download/launch still works.
