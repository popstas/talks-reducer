# Watch Directory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Watch-directory chooser to the GUI's Advanced settings that polls a folder and drives one dynamic action button — "Convert `<name>`" for a raw video or "Open last" for an already-processed one — in both Simple and Advanced modes.

**Architecture:** A Tk-free helper pair (`latest_video`, `is_processed`) plus a `WatchController` (mirrors `InputController`) live in a new `talks_reducer/gui/watch.py`. The controller polls the chosen folder via `root.after`, owns the shared action-button slot in `status_frame` when active, and reuses the existing input/run/reveal machinery. Persistence follows the existing `cut_enabled` preference pattern.

**Tech Stack:** Python 3, Tkinter/ttk, pytest. No new dependencies.

## Global Constraints

- No new runtime dependencies — detection is a `root.after` polling loop, not `watchdog`.
- Video extensions (case-insensitive): `.mp4 .mkv .mov .avi .m4v` (same set as the `gui/inputs.py` file picker).
- Processed-output markers (case-insensitive substring in filename): `_speedup` **or** `_small`.
- Preference keys: `watch_enabled` (bool, default `False`), `watch_directory` (str, default `""`).
- Poll interval: 2000 ms.
- Format Python with `black` and `isort` before committing (configured in `pyproject.toml`).
- Favor function-level docstrings over inline comments for new logic.
- Keep `README.md` and the GUI docs (`CLAUDE.md`, `AGENTS.md`) in sync with the feature.

---

### Task 1: Tk-free helpers `latest_video` and `is_processed`

**Files:**
- Create: `talks_reducer/gui/watch.py`
- Test: `tests/test_gui_watch.py`

**Interfaces:**
- Produces:
  - `VIDEO_EXTENSIONS: tuple[str, ...]` = `(".mp4", ".mkv", ".mov", ".avi", ".m4v")`
  - `PROCESSED_MARKERS: tuple[str, ...]` = `("_speedup", "_small")`
  - `POLL_INTERVAL_MS: int` = `2000`
  - `latest_video(directory) -> Optional[Path]` — newest video by `st_mtime`, ties broken by name; `None` for empty/missing/unreadable dirs.
  - `is_processed(path) -> bool` — filename (lowercased) contains any `PROCESSED_MARKERS` entry.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for :mod:`talks_reducer.gui.watch`."""

from __future__ import annotations

import os
from pathlib import Path

from talks_reducer.gui.watch import (
    POLL_INTERVAL_MS,
    PROCESSED_MARKERS,
    VIDEO_EXTENSIONS,
    is_processed,
    latest_video,
)


def _touch(path: Path, mtime: float) -> Path:
    path.write_bytes(b"data")
    os.utime(path, (mtime, mtime))
    return path


def test_latest_video_returns_newest_by_mtime(tmp_path):
    _touch(tmp_path / "old.mp4", 1000)
    newest = _touch(tmp_path / "new.mkv", 2000)
    _touch(tmp_path / "notes.txt", 3000)  # non-video ignored

    assert latest_video(tmp_path) == newest


def test_latest_video_breaks_ties_by_name(tmp_path):
    a = _touch(tmp_path / "a.mp4", 1000)
    b = _touch(tmp_path / "b.mp4", 1000)

    # Deterministic tie-break: greatest name wins.
    assert latest_video(tmp_path) == max(a, b, key=lambda p: p.name)


def test_latest_video_none_for_empty_dir(tmp_path):
    assert latest_video(tmp_path) is None


def test_latest_video_none_for_missing_dir(tmp_path):
    assert latest_video(tmp_path / "does-not-exist") is None


def test_is_processed_detects_markers():
    assert is_processed(Path("talk_speedup.mp4")) is True
    assert is_processed(Path("talk_small.mp4")) is True
    assert is_processed(Path("talk_SPEEDUP_small.mp4")) is True
    assert is_processed(Path("raw_recording.mp4")) is False


def test_constants_match_contract():
    assert VIDEO_EXTENSIONS == (".mp4", ".mkv", ".mov", ".avi", ".m4v")
    assert PROCESSED_MARKERS == ("_speedup", "_small")
    assert POLL_INTERVAL_MS == 2000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_gui_watch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'talks_reducer.gui.watch'`

- [ ] **Step 3: Write minimal implementation**

Create `talks_reducer/gui/watch.py`:

```python
"""Watch-directory polling and the dynamic Convert/Open-last button."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from .app import TalksReducerGUI

VIDEO_EXTENSIONS: tuple[str, ...] = (".mp4", ".mkv", ".mov", ".avi", ".m4v")
PROCESSED_MARKERS: tuple[str, ...] = ("_speedup", "_small")
POLL_INTERVAL_MS: int = 2000


def latest_video(directory) -> Optional[Path]:
    """Return the most-recently-modified video file in *directory*.

    Files are filtered to :data:`VIDEO_EXTENSIONS`; the newest by ``st_mtime``
    wins with ties broken by the greatest filename. Missing, empty, or
    unreadable directories yield ``None``.
    """

    folder = Path(directory)
    try:
        entries = list(folder.iterdir())
    except (OSError, ValueError):
        return None

    candidates: list[tuple[float, str, Path]] = []
    for entry in entries:
        if entry.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        try:
            if not entry.is_file():
                continue
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        candidates.append((mtime, entry.name, entry))

    if not candidates:
        return None
    return max(candidates)[2]


def is_processed(path) -> bool:
    """Return ``True`` when *path*'s name carries a processed-output marker."""

    name = Path(path).name.lower()
    return any(marker in name for marker in PROCESSED_MARKERS)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_gui_watch.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Format and commit**

```bash
.venv/bin/black talks_reducer/gui/watch.py tests/test_gui_watch.py
.venv/bin/isort talks_reducer/gui/watch.py tests/test_gui_watch.py
git add talks_reducer/gui/watch.py tests/test_gui_watch.py
git commit -m "feat: add watch-directory helpers for newest-video detection"
```

---

### Task 2: `WatchController` — polling, button ownership, and actions

**Files:**
- Modify: `talks_reducer/gui/watch.py`
- Test: `tests/test_gui_watch.py`

**Interfaces:**
- Consumes: `latest_video`, `is_processed`, `POLL_INTERVAL_MS` from Task 1.
- Consumes from the GUI (duck-typed, provided by Tasks 4/5): `gui.root` (with `after`/`after_cancel`), `gui.watch_enabled_var`, `gui.watch_directory_var`, `gui.watch_button` (ttk.Button with `configure`/`grid`/`grid_remove`), `gui.stop_button` (with `winfo_viewable`), `gui.open_button`, `gui.drop_hint_button`, `gui.inputs` (`clear_input_files`, `extend_inputs`), `gui._start_run()`, `gui._open_in_file_manager(path)`, `gui._restore_default_action_button()`.
- Produces (used by Tasks 3–5):
  - `WatchController(gui)` with `_candidate: Optional[Path]`, `_processed: bool`.
  - `start() -> None`, `stop() -> None` (idempotent polling control).
  - `refresh_candidate() -> None` (recompute candidate then refresh the button).
  - `refresh_button() -> None` (apply current candidate to `watch_button` + slot ownership).
  - `convert_latest() -> None`, `open_latest() -> None` (button commands).
  - `_display_name(name: str) -> str` (truncate long labels).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_gui_watch.py`:

```python
from types import SimpleNamespace

from talks_reducer.gui.watch import WatchController


class _FakeButton:
    def __init__(self):
        self.visible = False
        self.kwargs: dict = {}

    def configure(self, **kwargs):
        self.kwargs.update(kwargs)

    def grid(self):
        self.visible = True

    def grid_remove(self):
        self.visible = False

    def winfo_viewable(self):
        return self.visible


def _make_watch_gui(tmp_path, *, enabled=True):
    started: list[bool] = []
    opened: list[Path] = []
    restored: list[bool] = []
    inputs = SimpleNamespace(
        cleared=[],
        extended=[],
        clear_input_files=lambda: inputs.cleared.append(True),
        extend_inputs=lambda paths, **kw: inputs.extended.append(list(paths)),
    )
    gui = SimpleNamespace(
        root=SimpleNamespace(after=lambda *_: "id", after_cancel=lambda *_: None),
        watch_enabled_var=SimpleNamespace(get=lambda: enabled),
        watch_directory_var=SimpleNamespace(get=lambda: str(tmp_path)),
        watch_button=_FakeButton(),
        stop_button=_FakeButton(),
        open_button=_FakeButton(),
        drop_hint_button=_FakeButton(),
        inputs=inputs,
        _start_run=lambda: started.append(True),
        _open_in_file_manager=lambda path: opened.append(path),
        _restore_default_action_button=lambda: restored.append(True),
    )
    gui._started = started
    gui._opened = opened
    gui._restored = restored
    return gui


def test_refresh_button_shows_convert_for_raw_file(tmp_path):
    _touch(tmp_path / "raw.mp4", 1000)
    gui = _make_watch_gui(tmp_path)

    WatchController(gui).refresh_candidate()

    assert gui.watch_button.visible is True
    assert gui.watch_button.kwargs["text"] == "Convert raw.mp4"
    assert gui.open_button.visible is False


def test_refresh_button_shows_open_last_for_processed_file(tmp_path):
    _touch(tmp_path / "raw_speedup.mp4", 1000)
    gui = _make_watch_gui(tmp_path)

    WatchController(gui).refresh_candidate()

    assert gui.watch_button.kwargs["text"] == "Open last"


def test_refresh_button_hides_and_restores_when_no_candidate(tmp_path):
    gui = _make_watch_gui(tmp_path)  # empty dir

    WatchController(gui).refresh_candidate()

    assert gui.watch_button.visible is False
    assert gui._restored == [True]


def test_convert_latest_clears_inputs_and_runs(tmp_path):
    _touch(tmp_path / "raw.mp4", 1000)
    gui = _make_watch_gui(tmp_path)
    controller = WatchController(gui)
    controller.refresh_candidate()

    controller.convert_latest()

    assert gui.inputs.cleared == [True]
    assert gui.inputs.extended == [[str(tmp_path / "raw.mp4")]]
    assert gui._started == [True]


def test_open_latest_reveals_candidate(tmp_path):
    processed = _touch(tmp_path / "raw_speedup.mp4", 1000)
    gui = _make_watch_gui(tmp_path)
    controller = WatchController(gui)
    controller.refresh_candidate()

    controller.open_latest()

    assert gui._opened == [processed]


def test_refresh_button_yields_slot_to_active_run(tmp_path):
    _touch(tmp_path / "raw.mp4", 1000)
    gui = _make_watch_gui(tmp_path)
    gui.stop_button.grid()  # a run is active

    WatchController(gui).refresh_candidate()

    assert gui.watch_button.visible is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_gui_watch.py -k "refresh_button or convert_latest or open_latest" -v`
Expected: FAIL — `ImportError: cannot import name 'WatchController'`

- [ ] **Step 3: Write minimal implementation**

Append to `talks_reducer/gui/watch.py`:

```python
_MAX_LABEL_CHARS = 40


class WatchController:
    """Poll a folder and drive the dynamic Convert/Open-last action button."""

    def __init__(self, gui: "TalksReducerGUI") -> None:
        self.gui = gui
        self._after_id: Optional[str] = None
        self._candidate: Optional[Path] = None
        self._processed: bool = False

    def start(self) -> None:
        """Begin (or restart) the polling loop; safe to call repeatedly."""

        self.stop()
        self._tick()

    def stop(self) -> None:
        """Cancel any scheduled poll; safe to call when not running."""

        if self._after_id is not None:
            try:
                self.gui.root.after_cancel(self._after_id)
            except Exception:  # pragma: no cover - defensive
                pass
            self._after_id = None

    def _tick(self) -> None:
        self.refresh_candidate()
        self._after_id = self.gui.root.after(POLL_INTERVAL_MS, self._tick)

    def _watch_directory(self) -> Optional[Path]:
        if not self.gui.watch_enabled_var.get():
            return None
        raw = str(self.gui.watch_directory_var.get()).strip()
        if not raw:
            return None
        folder = Path(raw)
        return folder if folder.is_dir() else None

    def refresh_candidate(self) -> None:
        """Recompute the newest video and update the button."""

        directory = self._watch_directory()
        candidate = latest_video(directory) if directory is not None else None
        self._candidate = candidate
        self._processed = is_processed(candidate) if candidate is not None else False
        self.refresh_button()

    @staticmethod
    def _display_name(name: str) -> str:
        if len(name) <= _MAX_LABEL_CHARS:
            return name
        return "…" + name[-(_MAX_LABEL_CHARS - 1) :]

    def refresh_button(self) -> None:
        """Apply the current candidate to the shared action-button slot."""

        button = getattr(self.gui, "watch_button", None)
        if button is None:
            return

        if self._candidate is None:
            button.grid_remove()
            self.gui._restore_default_action_button()
            return

        if self.gui.stop_button.winfo_viewable():
            button.grid_remove()
            return

        self.gui.open_button.grid_remove()
        drop_hint = getattr(self.gui, "drop_hint_button", None)
        if drop_hint is not None:
            drop_hint.grid_remove()

        if self._processed:
            button.configure(text="Open last", command=self.open_latest)
        else:
            label = self._display_name(self._candidate.name)
            button.configure(text=f"Convert {label}", command=self.convert_latest)
        button.grid()

    def convert_latest(self) -> None:
        """Convert exactly the tracked candidate with the current options."""

        candidate = self._candidate
        if candidate is None or not candidate.exists():
            self.refresh_candidate()
            return
        self.gui.inputs.clear_input_files()
        self.gui.inputs.extend_inputs([str(candidate)])
        self.gui._start_run()

    def open_latest(self) -> None:
        """Reveal the tracked processed output in the system file manager."""

        if self._candidate is not None:
            self.gui._open_in_file_manager(self._candidate)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_gui_watch.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Format and commit**

```bash
.venv/bin/black talks_reducer/gui/watch.py tests/test_gui_watch.py
.venv/bin/isort talks_reducer/gui/watch.py tests/test_gui_watch.py
git add talks_reducer/gui/watch.py tests/test_gui_watch.py
git commit -m "feat: add WatchController polling and dynamic action button"
```

---

### Task 3: Persist `watch_enabled` / `watch_directory` and toggle the poller

**Files:**
- Modify: `talks_reducer/gui/preferences.py:174` (add `on_watch_change` after `on_cut_change`)
- Test: `tests/test_gui_preferences.py`

**Interfaces:**
- Consumes: `WatchController.start`/`stop`/`refresh_candidate` (Task 2), `gui.watch_enabled_var`, `gui.watch_directory_var`, `gui.watch`.
- Produces: `PreferenceController.on_watch_change(*_)` — persists both keys and starts/stops the poller.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_gui_preferences.py`:

```python
def test_on_watch_change_persists_and_starts(tmp_path):
    config_path = tmp_path / "settings.json"
    prefs = GUIPreferences(config_path)
    events: list[str] = []
    watch = SimpleNamespace(
        start=lambda: events.append("start"),
        stop=lambda: events.append("stop"),
        refresh_candidate=lambda: events.append("refresh"),
    )
    gui = SimpleNamespace(
        preferences=prefs,
        watch_enabled_var=SimpleNamespace(get=lambda: True),
        watch_directory_var=SimpleNamespace(get=lambda: "/videos/in"),
        watch=watch,
    )

    PreferenceController(gui).on_watch_change()

    loaded = load_settings(config_path)
    assert loaded["watch_enabled"] is True
    assert loaded["watch_directory"] == "/videos/in"
    assert events == ["start"]


def test_on_watch_change_stops_when_disabled(tmp_path):
    config_path = tmp_path / "settings.json"
    prefs = GUIPreferences(config_path)
    events: list[str] = []
    watch = SimpleNamespace(
        start=lambda: events.append("start"),
        stop=lambda: events.append("stop"),
        refresh_candidate=lambda: events.append("refresh"),
    )
    gui = SimpleNamespace(
        preferences=prefs,
        watch_enabled_var=SimpleNamespace(get=lambda: False),
        watch_directory_var=SimpleNamespace(get=lambda: "/videos/in"),
        watch=watch,
    )

    PreferenceController(gui).on_watch_change()

    assert load_settings(config_path)["watch_enabled"] is False
    assert events == ["stop", "refresh"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_gui_preferences.py -k on_watch_change -v`
Expected: FAIL — `AttributeError: 'PreferenceController' object has no attribute 'on_watch_change'`

- [ ] **Step 3: Write minimal implementation**

In `talks_reducer/gui/preferences.py`, add this method to `PreferenceController` directly after `on_cut_change`:

```python
    def on_watch_change(self, *_: object) -> None:
        """Persist the watch-directory settings and toggle the poller."""

        enabled = bool(self.gui.watch_enabled_var.get())
        self.gui.preferences.update("watch_enabled", enabled)
        self.gui.preferences.update(
            "watch_directory", str(self.gui.watch_directory_var.get())
        )
        watch = getattr(self.gui, "watch", None)
        if watch is None:
            return
        if enabled:
            watch.start()
        else:
            watch.stop()
            watch.refresh_candidate()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_gui_preferences.py -k on_watch_change -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Format and commit**

```bash
.venv/bin/black talks_reducer/gui/preferences.py tests/test_gui_preferences.py
.venv/bin/isort talks_reducer/gui/preferences.py tests/test_gui_preferences.py
git add talks_reducer/gui/preferences.py tests/test_gui_preferences.py
git commit -m "feat: persist watch-directory preferences and toggle poller"
```

---

### Task 4: Wire watch state into the GUI (vars, controller, slot restore)

**Files:**
- Modify: `talks_reducer/gui/app.py` (imports ~47; var creation ~291-306; controller creation ~273; trace wiring ~339-346; new delegator + `_restore_default_action_button`; hook `_hide_stop_button` ~1386; hook the status `apply()` closure ~1866)
- Test: `tests/test_gui_app.py`

**Interfaces:**
- Consumes: `WatchController` (Task 2), `PreferenceController.on_watch_change` (Task 3).
- Produces (used by Task 5): `gui.watch_enabled_var`, `gui.watch_directory_var`, `gui.watch`, `gui._on_watch_change`, `gui._restore_default_action_button()`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_gui_app.py` (top-level, uses the module's existing import of `TalksReducerGUI`; if the file imports it differently, match that import):

```python
def test_restore_default_action_button_prefers_open_when_output_exists():
    from types import SimpleNamespace

    from talks_reducer.gui.app import TalksReducerGUI

    open_btn = SimpleNamespace(visible=False)
    open_btn.grid = lambda: setattr(open_btn, "visible", True)
    open_btn.grid_remove = lambda: setattr(open_btn, "visible", False)
    open_btn.lift = lambda: None
    stop_btn = SimpleNamespace(winfo_viewable=lambda: False)
    drop_btn = SimpleNamespace(visible=False)
    drop_btn.grid = lambda: setattr(drop_btn, "visible", True)

    gui = SimpleNamespace(
        stop_button=stop_btn,
        open_button=open_btn,
        drop_hint_button=drop_btn,
        _last_output="out.mp4",
        simple_mode_var=SimpleNamespace(get=lambda: True),
    )

    TalksReducerGUI._restore_default_action_button(gui)

    assert open_btn.visible is True
    assert drop_btn.visible is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_gui_app.py -k restore_default_action_button -v`
Expected: FAIL — `AttributeError: type object 'TalksReducerGUI' has no attribute '_restore_default_action_button'`

- [ ] **Step 3: Write the implementation**

3a. Import the controller. In `talks_reducer/gui/app.py` near the other GUI imports (~line 47, beside `from .inputs import InputController`):

```python
from .watch import WatchController
```

3b. Create the controller. After `self.inputs = InputController(self)` (~line 273):

```python
        self.watch = WatchController(self)
```

3c. Create the vars. After the cut text-var block (right after `self.cut_end_text_var = ...`, ~line 306), seed **before** any trace is installed:

```python
        self.watch_enabled_var = tk.BooleanVar(
            value=bool(self.preferences.get("watch_enabled", False))
        )
        self.watch_directory_var = tk.StringVar(
            value=str(self.preferences.get("watch_directory", ""))
        )
```

3d. Install the traces. Beside the cut traces (~line 341, after the three `cut_*` `trace_add` lines):

```python
        self.watch_enabled_var.trace_add("write", self._on_watch_change)
        self.watch_directory_var.trace_add("write", self._on_watch_change)
```

3e. Add the delegator method next to `_on_cut_change` (~line 1155):

```python
    def _on_watch_change(self, *_: object) -> None:
        self.preference_controller.on_watch_change(*_)
```

3f. Add the slot-restore helper (place near `_open_last_output`, ~line 1490):

```python
    def _restore_default_action_button(self) -> None:
        """Show the normal action button after the watch button hides itself.

        The watch button shares the ``status_frame`` slot with the Stop/Open/Drop
        buttons; when watching is inactive this restores the Open-last button (when
        a session output exists) or the Simple-mode drop hint.
        """

        if self.stop_button.winfo_viewable():
            return
        if getattr(self, "_last_output", None) is not None:
            self.open_button.grid()
            self.open_button.lift()
        elif hasattr(self, "drop_hint_button") and self.simple_mode_var.get():
            self.drop_hint_button.grid()
```

3g. Let the watch button re-assert after a run ends. In `_hide_stop_button` (~line 1386), append after the existing drop-hint block:

```python
        watch = getattr(self, "watch", None)
        if watch is not None:
            watch.refresh_button()
```

3h. Let the watch button re-assert after every status change. At the very end of the `apply()` closure inside the status-styling method (~line 1866, after the final `else:` branch that toggles `open_button`/`drop_hint_button`):

```python
            watch = getattr(self, "watch", None)
            if watch is not None:
                watch.refresh_button()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_gui_app.py -k restore_default_action_button -v`
Expected: PASS

- [ ] **Step 5: Run the watch + preferences suites to confirm no regressions**

Run: `.venv/bin/pytest tests/test_gui_watch.py tests/test_gui_preferences.py -v`
Expected: PASS

- [ ] **Step 6: Format and commit**

```bash
.venv/bin/black talks_reducer/gui/app.py tests/test_gui_app.py
.venv/bin/isort talks_reducer/gui/app.py tests/test_gui_app.py
git add talks_reducer/gui/app.py tests/test_gui_app.py
git commit -m "feat: wire watch controller and shared action-button slot into GUI"
```

---

### Task 5: Build the watch widgets in the layout

**Files:**
- Modify: `talks_reducer/gui/layout.py` (status-frame action buttons ~757-775; advanced-frame rows after the server-tray checkbox ~700; start the poller at the end of `build_layout`)
- Test: `tests/test_gui_layout.py`

**Interfaces:**
- Consumes: `gui.watch_enabled_var`, `gui.watch_directory_var`, `gui.watch` (Task 4), `gui.inputs.browse_path` (existing).
- Produces: `gui.watch_button` (in `status_frame`), `gui.watch_check`, `gui.watch_directory_entry`, `gui.watch_browse_button` (in `advanced_frame`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_gui_layout.py`. Match the file's existing helper for constructing a layout GUI double (search it for how `status_frame`/`advanced_frame` widgets are asserted, e.g. an existing `test_*` that checks `gui.open_button` or `gui.cut_check`) and mirror that fixture. The assertions to add:

```python
def test_build_layout_creates_watch_widgets(layout_gui):
    # layout_gui is the shared fixture/double used by other layout tests.
    from talks_reducer.gui import layout as layout_helpers

    layout_helpers.build_layout(layout_gui)

    assert hasattr(layout_gui, "watch_button")
    assert hasattr(layout_gui, "watch_check")
    assert hasattr(layout_gui, "watch_directory_entry")
    assert hasattr(layout_gui, "watch_browse_button")
```

> If `test_gui_layout.py` builds widgets against a real hidden Tk root (several tests here do), reuse that same setup rather than inventing a double. The concrete assertion is only that the four attributes exist after `build_layout`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_gui_layout.py -k watch_widgets -v`
Expected: FAIL — `AttributeError: ... has no attribute 'watch_button'`

- [ ] **Step 3: Write the implementation**

3a. Add the watch button to the shared action slot. In `talks_reducer/gui/layout.py`, immediately after the `drop_hint_button` block (~line 775, after `gui._configure_drop_targets(gui.drop_hint_button)`):

```python
    # Dynamic watch-directory action button. It shares the status_frame slot with
    # the Stop/Open/Drop buttons; WatchController owns its visibility and label.
    gui.watch_button = gui.ttk.Button(
        status_frame,
        text="Convert",
    )
    gui.watch_button.grid(row=2, column=0, columnspan=3, sticky="ew", pady=gui.PADDING)
    gui.watch_button.grid_remove()  # Hidden until a candidate appears
```

3b. Add the Advanced chooser rows. After the `start_in_server_tray_check` block (~line 700, before the macOS `check_updates` branch):

```python
    gui.watch_check = gui.ttk.Checkbutton(
        gui.advanced_frame,
        text="Watch directory",
        variable=gui.watch_enabled_var,
    )
    gui.watch_check.grid(row=9, column=0, columnspan=3, sticky="w", pady=4)

    gui.watch_directory_entry = gui.ttk.Entry(
        gui.advanced_frame,
        textvariable=gui.watch_directory_var,
    )
    gui.watch_directory_entry.grid(row=10, column=0, columnspan=2, sticky="ew", pady=4)

    gui.watch_browse_button = gui.ttk.Button(
        gui.advanced_frame,
        text="Browse…",
        command=lambda: gui.inputs.browse_path(gui.watch_directory_var, "watch folder"),
    )
    gui.watch_browse_button.grid(row=10, column=2, sticky="e", padx=(8, 0), pady=4)
```

> Note: the macOS `check_updates` widgets sit at row 8; the watch rows use 9–10 so they never collide. The chooser lives inside `advanced_frame`, which `apply_simple_mode` already hides in Simple mode — no extra hide/show wiring is needed. The `watch_button` is in `status_frame` (visible in both modes) and is owned by `WatchController`, so it is deliberately **not** added to `apply_simple_mode`.

3c. Start the poller if the persisted preference is enabled. At the end of `build_layout` (after all widgets are built), add:

```python
    watch = getattr(gui, "watch", None)
    if watch is not None and gui.watch_enabled_var.get():
        watch.start()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_gui_layout.py -k watch_widgets -v`
Expected: PASS

- [ ] **Step 5: Run the full GUI suite**

Run: `.venv/bin/pytest tests/test_gui_layout.py tests/test_gui_app.py tests/test_gui_watch.py tests/test_gui_preferences.py -q`
Expected: PASS

- [ ] **Step 6: Format and commit**

```bash
.venv/bin/black talks_reducer/gui/layout.py tests/test_gui_layout.py
.venv/bin/isort talks_reducer/gui/layout.py tests/test_gui_layout.py
git add talks_reducer/gui/layout.py tests/test_gui_layout.py
git commit -m "feat: add watch-directory chooser and dynamic action button to GUI"
```

---

### Task 6: Documentation and TODO

**Files:**
- Modify: `README.md` (GUI features section)
- Modify: `CLAUDE.md` and `AGENTS.md` (Graphical Interface section)
- Modify: `docs/TODO.md` (check off the watch task)

- [ ] **Step 1: Update README**

In `README.md`, in the GUI controls list (near the Cut video / Advanced bullets), add:

```markdown
- **Watch directory** — an Advanced setting: choose a folder and Talks Reducer
  polls it (~2s) for the most-recently-modified video. The main action button
  then shows **"Convert `<filename>`"** for a raw recording, or **"Open last"**
  when the newest file is already processed (its name contains `_speedup` or
  `_small`). The button is available in both Simple and Advanced modes; the
  folder chooser lives under Advanced. The choice persists across launches
  (`watch_enabled`, `watch_directory`).
```

- [ ] **Step 2: Update GUI docs**

Add an equivalent **Watch directory** bullet to the "Graphical Interface" list in both `CLAUDE.md` and `AGENTS.md`, noting: polling via `WatchController` in `gui/watch.py`; markers `_speedup`/`_small`; the button shares the `status_frame` slot with Stop/Open/Drop and is owned by `WatchController`; the chooser is in `advanced_frame` (auto-hidden in Simple mode); persistence keys `watch_enabled`/`watch_directory`.

- [ ] **Step 3: Check off the TODO**

In `docs/TODO.md`, change the watch line to:

```markdown
- [x] Добавить в Advanced настройки выбор watch directory. Следить за папкой, выводить кнопку "Convert <filename>" где filename — последний изменённый в папке файл
```

- [ ] **Step 4: Commit**

```bash
git add README.md CLAUDE.md AGENTS.md docs/TODO.md
git commit -m "docs: document watch-directory feature"
```

---

### Task 7: Full verification

- [ ] **Step 1: Run the complete test suite**

Run: `.venv/bin/pytest -q`
Expected: PASS (no regressions)

- [ ] **Step 2: Formatting sanity check**

Run: `.venv/bin/black --check talks_reducer/gui tests && .venv/bin/isort --check-only talks_reducer/gui tests`
Expected: no reformatting needed

- [ ] **Step 3: Manual/E2E smoke test (document results in the PR)**

  1. Launch the GUI (`.venv/bin/python -m talks_reducer.gui`).
  2. Open Advanced, enable **Watch directory**, pick a folder.
  3. Drop a raw video into the folder → the main button shows **Convert `<name>`** in both Simple and Advanced.
  4. Click it → the file converts with the current options.
  5. When the `_speedup`/`_small` output lands in the folder → the button flips to **Open last** and reveals the file.
  6. Disable Watch → the normal Open-last/drop-hint behavior returns.
  7. Restart the GUI → the watch folder and enabled state persist.

---

## Notes for the implementer

- **`_start_run` vs `auto_run`:** `convert_latest` calls `gui._start_run()` directly (not `extend_inputs(auto_run=True)`) so the Convert button always runs regardless of `run_after_drop_var`, and cut/other options still apply via the normal run path.
- **Line numbers** in "Files" are approximate anchors from the 2026-07-03 tree — locate the surrounding code by the quoted symbols, not by absolute line.
- **Test doubles:** existing GUI tests use `types.SimpleNamespace` fakes (see `tests/test_gui_inputs.py`, `tests/test_gui_preferences.py`). Reuse that style; don't spin up a real Tk root except where `tests/test_gui_layout.py` already does.
