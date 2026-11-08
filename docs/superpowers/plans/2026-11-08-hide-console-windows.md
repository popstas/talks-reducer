# Hide Console Windows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the console window that flashes on Windows at the start and end of every conversion, and keep it from coming back.

**Architecture:** One leaf helper, `talks_reducer.subprocess_utils.hidden_subprocess_kwargs()`, returns `{"creationflags": 0x08000000}` on Windows and `{}` elsewhere. Every FFmpeg/ffprobe/PowerShell/self-test spawn passes `**hidden_subprocess_kwargs()`. A static AST test fails on any `subprocess.run/Popen/call/check_call/check_output` call in `talks_reducer/` that does not, outside a short allowlist.

**Tech Stack:** Python 3 stdlib (`subprocess`, `ast`), pytest. Spec: `docs/superpowers/specs/2026-11-08-hide-console-windows-design.md`.

## Global Constraints

- Use the project venv: `.venv/Scripts/python.exe` (Windows) for every command.
- `hidden_subprocess_kwargs()` reads `sys.platform` **at call time**, never at import.
- The flag is the literal `0x08000000`; never `subprocess.CREATE_NO_WINDOW` (missing on Linux CI).
- `subprocess_utils.py` imports nothing from `talks_reducer`.
- Do not change `cli.py:_launch_server_tray_binary` (own console gating, asserted by `tests/test_cli.py`).
- Run `black` and `isort` on changed files before each commit.
- Commit messages: angular format. Only user-visible fixes use `fix:` (Task 2: conversion flash, Task 4: Create lnk flash); the rest use `refactor:`/`test:`.
- End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## File Structure

- Create `talks_reducer/subprocess_utils.py`: the helper (single responsibility: spawn kwargs that hide consoles).
- Create `tests/test_subprocess_utils.py`: helper unit tests.
- Create `tests/test_no_console_windows.py`: AST guard over the whole package.
- Modify `talks_reducer/pipeline.py`: `_extract_video_metadata` (the bug).
- Modify `talks_reducer/audio.py`, `ffmpeg.py`, `glue.py`, `spherical.py`, `dock_server.py`: swap inline flags for the helper.
- Modify `talks_reducer/gui/shortcut.py`, `gui/startup.py`: add the helper.
- Modify `tests/test_pipeline.py`, `tests/test_audio.py`: follow the changed call shape.
- Modify `CLAUDE.md`, `AGENTS.md`: one Repository Structure line.

---

### Task 0: Branch

- [ ] **Step 1: Create the branch from master**

```bash
git checkout -b fix/hide-console-windows
```

---

### Task 1: `hidden_subprocess_kwargs` helper

**Files:**
- Create: `talks_reducer/subprocess_utils.py`
- Test: `tests/test_subprocess_utils.py`

**Interfaces:**
- Produces: `talks_reducer.subprocess_utils.CREATE_NO_WINDOW: int = 0x08000000` and `hidden_subprocess_kwargs() -> Dict[str, int]`. Every later task imports `hidden_subprocess_kwargs`.

- [ ] **Step 1: Write the failing test**

`tests/test_subprocess_utils.py`:

```python
"""Tests for the console-hiding subprocess helper."""

from __future__ import annotations

import sys

import pytest

from talks_reducer import subprocess_utils


def test_hidden_subprocess_kwargs_sets_create_no_window_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")

    assert subprocess_utils.hidden_subprocess_kwargs() == {
        "creationflags": 0x08000000
    }


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_hidden_subprocess_kwargs_is_empty_elsewhere(
    monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    monkeypatch.setattr(sys, "platform", platform)

    assert subprocess_utils.hidden_subprocess_kwargs() == {}


def test_hidden_subprocess_kwargs_returns_a_fresh_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Callers may mutate the result; that must not leak into the next call."""

    monkeypatch.setattr(sys, "platform", "win32")
    first = subprocess_utils.hidden_subprocess_kwargs()
    first["creationflags"] = 0

    assert subprocess_utils.hidden_subprocess_kwargs() == {
        "creationflags": 0x08000000
    }
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_subprocess_utils.py -v`
Expected: FAIL, `ImportError: cannot import name 'subprocess_utils'`.

- [ ] **Step 3: Implement**

`talks_reducer/subprocess_utils.py`:

```python
"""Spawn helpers that keep child processes from opening console windows.

A console program (``ffmpeg``, ``ffprobe``, ``powershell``) started from the
windowed Windows build gets a brand-new console window unless it is created
with ``CREATE_NO_WINDOW``. Every such spawn in the package passes
``**hidden_subprocess_kwargs()``; ``tests/test_no_console_windows.py`` fails
the build when one does not.
"""

from __future__ import annotations

import sys
from typing import Dict

CREATE_NO_WINDOW = 0x08000000
"""``subprocess.CREATE_NO_WINDOW``, spelled out because the attribute exists
only on Windows and the package is imported (and tested) everywhere."""


def hidden_subprocess_kwargs() -> Dict[str, int]:
    """Return ``subprocess`` keyword arguments that hide the child's console.

    On Windows this is ``{"creationflags": CREATE_NO_WINDOW}``; elsewhere it is
    empty, since ``creationflags`` is Windows-only. ``sys.platform`` is read on
    every call so tests can switch platforms with ``monkeypatch``.
    """

    if sys.platform == "win32":
        return {"creationflags": CREATE_NO_WINDOW}
    return {}
```

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_subprocess_utils.py -v`
Expected: 4 passed.

- [ ] **Step 5: Format and commit**

```bash
.venv/Scripts/python.exe -m black talks_reducer/subprocess_utils.py tests/test_subprocess_utils.py
.venv/Scripts/python.exe -m isort talks_reducer/subprocess_utils.py tests/test_subprocess_utils.py
git add talks_reducer/subprocess_utils.py tests/test_subprocess_utils.py
git commit -m "refactor: Add helper for hiding subprocess console windows

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Fix the flashing ffprobe in `_extract_video_metadata`

This is the reported bug. The function runs at the start (input file) and the end (output file) of each conversion.

**Files:**
- Modify: `talks_reducer/pipeline.py` (`_extract_video_metadata`, currently `subprocess.Popen(...)` + `process.communicate()` around line 974; imports at the top)
- Test: `tests/test_pipeline.py` (`test_extract_video_metadata_uses_ffprobe` ~line 317, `test_extract_video_metadata_snaps_noisy_concat_frame_rate` ~line 388)

**Interfaces:**
- Consumes: `hidden_subprocess_kwargs()` from Task 1.

- [ ] **Step 1: Switch the two existing tests to `subprocess.run` and add a Windows test**

In `tests/test_pipeline.py`, replace the body of `test_extract_video_metadata_uses_ffprobe` from `class DummyProcess:` through `monkeypatch.setattr(pipeline.subprocess, "Popen", fake_popen)` with:

```python
    stdout = "\n".join(
        [
            "[STREAM]",
            "avg_frame_rate=25/1",
            "nb_frames=125",
            "width=1920",
            "height=1080",
            "[/STREAM]",
            "[FORMAT]",
            "duration=5.0",
            "[/FORMAT]",
        ]
    )

    def fake_run(command, *args, **kwargs):
        captured_commands.append(list(command))
        assert os.fspath(demo_path) in command
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)
```

In `test_extract_video_metadata_snaps_noisy_concat_frame_rate`, replace the `DummyProcess` class and its `monkeypatch.setattr(pipeline.subprocess, "Popen", ...)` with:

```python
    monkeypatch.setattr(
        pipeline.subprocess,
        "run",
        lambda command, *args, **kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout="avg_frame_rate=130631680/4354391\nduration=1700.9\n",
            stderr="",
        ),
    )
```

Add after it:

```python
def test_extract_video_metadata_hides_console_on_windows(monkeypatch) -> None:
    """The start/end ffprobe must not flash a console window on Windows."""

    monkeypatch.setattr(ffmpeg_module, "get_ffprobe_path", lambda: "ffprobe")
    monkeypatch.setattr(sys, "platform", "win32")
    captured_kwargs: dict = {}

    def fake_run(command, *args, **kwargs):
        captured_kwargs.update(kwargs)
        return subprocess.CompletedProcess(
            command, 0, stdout="avg_frame_rate=30/1\n", stderr=""
        )

    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)

    pipeline._extract_video_metadata(Path("input.mp4"), frame_rate=25.0)

    assert captured_kwargs.get("creationflags") == 0x08000000
```

Add `import subprocess` and `import sys` to the top of `tests/test_pipeline.py` if they are not imported yet.

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_pipeline.py -k extract_video_metadata -v`
Expected: the three tests FAIL (the code still calls `Popen`, so the real `ffprobe` runs or the fake `run` is never called).

- [ ] **Step 3: Implement**

In `talks_reducer/pipeline.py`, add next to the other package imports:

```python
from .subprocess_utils import hidden_subprocess_kwargs
```

Replace

```python
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
        universal_newlines=True,
    )
    stdout, _ = process.communicate()
```

with

```python
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        **hidden_subprocess_kwargs(),
    )
    stdout = result.stdout
```

The rest of the function already parses `str(stdout)`, so nothing else changes.

- [ ] **Step 4: Run them to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_pipeline.py -v`
Expected: all pass.

- [ ] **Step 5: Format and commit**

```bash
.venv/Scripts/python.exe -m black talks_reducer/pipeline.py tests/test_pipeline.py
.venv/Scripts/python.exe -m isort talks_reducer/pipeline.py tests/test_pipeline.py
git add talks_reducer/pipeline.py tests/test_pipeline.py
git commit -m "fix: Stop the console window flashing at the start and end of a conversion on Windows

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Move the other FFmpeg/ffprobe spawns onto the helper

Behaviour stays the same (all of these already hide the console). This removes the hand-copied `0x08000000` so the guard in Task 5 can require the helper everywhere.

**Files:**
- Modify: `talks_reducer/audio.py` (`is_valid_video_file`, `is_valid_input_file`)
- Modify: `talks_reducer/ffmpeg.py` (`_probe_ffmpeg_output`, `_trial_encode`, `run_timed_ffmpeg_command`, `get_video_duration`)
- Modify: `talks_reducer/glue.py` (`_probe_streams`)
- Modify: `talks_reducer/spherical.py` (`probe_spherical`)
- Modify: `talks_reducer/dock_server.py` (`start_talks_reducer`, module constant `_CREATE_NO_WINDOW`)
- Test: `tests/test_audio.py` (`test_is_valid_input_file_sets_creationflags_on_windows`)

**Interfaces:**
- Consumes: `hidden_subprocess_kwargs()` from Task 1.

- [ ] **Step 1: Point the audio Windows test at `sys` instead of `audio.sys`**

`audio.py` will no longer import `sys`. In `tests/test_audio.py::test_is_valid_input_file_sets_creationflags_on_windows`, replace

```python
    monkeypatch.setattr(audio.sys, "platform", "win32")
```

with

```python
    monkeypatch.setattr(sys, "platform", "win32")
```

and add `import sys` at the top of `tests/test_audio.py` if missing. (It is the same module object, so the test still checks the same thing.)

- [ ] **Step 2: `audio.py`**

Add `from .subprocess_utils import hidden_subprocess_kwargs` after `from .ffmpeg import get_ffprobe_path`. In both `is_valid_video_file` and `is_valid_input_file`, delete the block

```python
    # Hide console window on Windows
    creationflags = 0
    if sys.platform == "win32":
        # CREATE_NO_WINDOW = 0x08000000
        creationflags = 0x08000000
```

and in the `subprocess.run(...)` below it replace `creationflags=creationflags,` with `**hidden_subprocess_kwargs(),`. Then delete `import sys` (its only uses were these two blocks; confirm with `grep -n "sys\." talks_reducer/audio.py` returning nothing).

- [ ] **Step 3: `ffmpeg.py`**

Add `from .subprocess_utils import hidden_subprocess_kwargs` after `from . import config`. Keep `import sys` (used elsewhere).

- `_probe_ffmpeg_output` and `get_video_duration`: delete the `creationflags = 0` / `if sys.platform == "win32":` / `creationflags = 0x08000000` block and replace `creationflags=creationflags,` with `**hidden_subprocess_kwargs(),`.
- `_trial_encode`: delete `creationflags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW` and replace `creationflags=creationflags,` with `**hidden_subprocess_kwargs(),`.
- `run_timed_ffmpeg_command`: delete the `# Hide console window on Windows` block and leave `popen_kwargs: dict = {}` (the Unix `start_new_session` setup) as it is. The Task 5 guard looks for the helper *in the call itself*, so write the call as:

```python
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            bufsize=1,
            errors="replace",
            **hidden_subprocess_kwargs(),
            **popen_kwargs,
        )
```

- [ ] **Step 4: `glue.py` and `spherical.py`**

In each, add `from .subprocess_utils import hidden_subprocess_kwargs` to the package imports, delete `creationflags = 0x08000000 if sys.platform == "win32" else 0`, and replace `creationflags=creationflags,` with `**hidden_subprocess_kwargs(),`. Delete `import sys` from each (confirm `grep -n "sys\." talks_reducer/glue.py talks_reducer/spherical.py` returns nothing).

- [ ] **Step 5: `dock_server.py`**

Add `from .subprocess_utils import hidden_subprocess_kwargs` next to `from .icons import find_icon_path`. Delete the module constant `_CREATE_NO_WINDOW = 0x08000000`. In `start_talks_reducer`, delete `creationflags = _CREATE_NO_WINDOW if os.name == "nt" else 0` and change the launch to:

```python
    subprocess.Popen([exe_path, *args], **hidden_subprocess_kwargs())
```

Confirm nothing else references the constant: `grep -rn "_CREATE_NO_WINDOW" talks_reducer tests` returns nothing.

- [ ] **Step 6: Run the affected tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_audio.py tests/test_ffmpeg.py tests/test_glue.py tests/test_spherical.py tests/test_dock_server.py tests/test_pipeline.py -v`
Expected: all pass. A failure here means a test fake declares `creationflags` as an explicit parameter; give that parameter a default (`creationflags=0`) rather than changing the production call.

- [ ] **Step 7: Format and commit**

```bash
.venv/Scripts/python.exe -m black talks_reducer/audio.py talks_reducer/ffmpeg.py talks_reducer/glue.py talks_reducer/spherical.py talks_reducer/dock_server.py tests/test_audio.py
.venv/Scripts/python.exe -m isort talks_reducer/audio.py talks_reducer/ffmpeg.py talks_reducer/glue.py talks_reducer/spherical.py talks_reducer/dock_server.py tests/test_audio.py
git add talks_reducer/audio.py talks_reducer/ffmpeg.py talks_reducer/glue.py talks_reducer/spherical.py talks_reducer/dock_server.py tests/test_audio.py
git commit -m "refactor: Route FFmpeg and ffprobe spawns through hidden_subprocess_kwargs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Hide the PowerShell and Tk self-test consoles

**Files:**
- Modify: `talks_reducer/gui/shortcut.py` (`write_shortcut`)
- Modify: `talks_reducer/gui/startup.py` (`_check_tkinter_available`)
- Test: `tests/test_gui_shortcut.py`, `tests/test_gui_startup.py`

**Interfaces:**
- Consumes: `hidden_subprocess_kwargs()` from Task 1.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gui_shortcut.py` (add `import subprocess`, `import sys` and `from talks_reducer.gui import shortcut` at the top if missing):

```python
def test_write_shortcut_hides_powershell_console_on_windows(monkeypatch) -> None:
    """Create lnk must not flash a PowerShell console window."""

    monkeypatch.setattr(sys, "platform", "win32")
    captured_kwargs: dict = {}

    def fake_run(command, *args, **kwargs):
        captured_kwargs.update(kwargs)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(shortcut.subprocess, "run", fake_run)

    shortcut.write_shortcut(
        "C:/Users/me/Desktop/Talks Reducer.lnk",
        {
            "target_path": "C:/app/talks-reducer.exe",
            "arguments": "",
            "working_directory": "C:/app",
            "icon_location": "C:/app/talks-reducer.exe",
        },
    )

    assert captured_kwargs.get("creationflags") == 0x08000000
```

(The keys are the ones `build_powershell_script` reads from `target`.)

Append to `tests/test_gui_startup.py` (add `import subprocess`, `import sys` and `from talks_reducer.gui import startup` at the top if missing):

```python
def test_tkinter_check_hides_console_on_windows(monkeypatch) -> None:
    """The Tk self-test subprocess must not flash a console window."""

    monkeypatch.setattr(sys, "platform", "win32")
    captured_kwargs: dict = {}

    def fake_run(command, *args, **kwargs):
        captured_kwargs.update(kwargs)
        return subprocess.CompletedProcess(
            command, 0, stdout='{"status": "ok"}', stderr=""
        )

    monkeypatch.setattr(startup.subprocess, "run", fake_run)

    startup._check_tkinter_available()

    assert captured_kwargs.get("creationflags") == 0x08000000
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gui_shortcut.py tests/test_gui_startup.py -k "hides" -v`
Expected: 2 FAIL, `assert None == 134217728`.

- [ ] **Step 3: Implement**

`talks_reducer/gui/shortcut.py`: add `from ..subprocess_utils import hidden_subprocess_kwargs` after the stdlib imports, and add `**hidden_subprocess_kwargs(),` as the last argument of the `subprocess.run(...)` in `write_shortcut`.

`talks_reducer/gui/startup.py`: add `from ..subprocess_utils import hidden_subprocess_kwargs` next to `from ..cli import _build_parser`, and change the call in `_check_tkinter_available` to:

```python
        result = subprocess.run(
            [sys.executable, "-c", test_code],
            capture_output=True,
            text=True,
            timeout=5,
            **hidden_subprocess_kwargs(),
        )
```

- [ ] **Step 4: Run them to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gui_shortcut.py tests/test_gui_startup.py -v`
Expected: all pass.

- [ ] **Step 5: Format and commit**

```bash
.venv/Scripts/python.exe -m black talks_reducer/gui/shortcut.py talks_reducer/gui/startup.py tests/test_gui_shortcut.py tests/test_gui_startup.py
.venv/Scripts/python.exe -m isort talks_reducer/gui/shortcut.py talks_reducer/gui/startup.py tests/test_gui_shortcut.py tests/test_gui_startup.py
git add talks_reducer/gui/shortcut.py talks_reducer/gui/startup.py tests/test_gui_shortcut.py tests/test_gui_startup.py
git commit -m "fix: Hide the console window when creating a desktop shortcut on Windows

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Static guard against console-flashing spawns, plus docs

**Files:**
- Create: `tests/test_no_console_windows.py`
- Modify: `CLAUDE.md`, `AGENTS.md` (Repository Structure, after the `spherical.py` bullet)

**Interfaces:**
- Consumes: the call sites as left by Tasks 2–4. At the start of this task the only direct `subprocess` calls without `**hidden_subprocess_kwargs()` are the six allowlisted ones below.

- [ ] **Step 1: Write the guard test**

`tests/test_no_console_windows.py`:

```python
"""Fail when a subprocess spawn could flash a console window on Windows.

A console program started from the windowed Windows build opens its own
console unless it gets ``CREATE_NO_WINDOW``. The flag used to be copied by hand
into each call, and a call that missed it (``pipeline._extract_video_metadata``)
flashed a window at the start and end of every conversion. Every spawn must now
pass ``**hidden_subprocess_kwargs()`` in the call itself, or be listed in
``ALLOWED`` with the reason it is safe.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterator, Optional, Tuple

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "talks_reducer"
SPAWN_FUNCTIONS = {"run", "Popen", "call", "check_call", "check_output"}
HELPER_NAME = "hidden_subprocess_kwargs"

# (path relative to talks_reducer/, enclosing function) -> why it is safe.
ALLOWED = {
    (
        "cli.py",
        "_launch_server_tray_binary",
    ): "own _should_hide_subprocess_console() gating; see tests/test_cli.py",
    (
        "gui/relaunch.py",
        "spawn_detached",
    ): "deliberately DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP",
    (
        "server_tray.py",
        "_launch_gui",
    ): "launches the GUI, which has no console in the frozen build",
    (
        "gui/app.py",
        "_on_download_complete",
    ): "non-Windows branch; Windows uses os.startfile",
    (
        "gui/app.py",
        "_open_in_file_manager",
    ): "explorer / open / xdg-open are GUI programs",
    ("gui/theme.py", "run_defaults_command"): "macOS only",
}

Spawn = Tuple[str, int, str]


def _passes_helper(call: ast.Call) -> bool:
    """Return True when *call* has ``**hidden_subprocess_kwargs()``."""

    for keyword in call.keywords:
        value = keyword.value
        if keyword.arg is not None or not isinstance(value, ast.Call):
            continue
        func = value.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name == HELPER_NAME:
            return True
    return False


def _is_subprocess_spawn(call: ast.Call) -> bool:
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr in SPAWN_FUNCTIONS
        and isinstance(func.value, ast.Name)
        and func.value.id == "subprocess"
    )


def _unhidden_spawns() -> Iterator[Spawn]:
    """Yield ``(relative path, line, enclosing function)`` for each bad spawn."""

    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        relative = path.relative_to(PACKAGE_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        yield from _walk(tree, relative, None)


def _walk(node: ast.AST, relative: str, function: Optional[str]) -> Iterator[Spawn]:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            inner = child.name
        else:
            inner = function
        if (
            isinstance(child, ast.Call)
            and _is_subprocess_spawn(child)
            and not _passes_helper(child)
        ):
            yield relative, child.lineno, function or "<module>"
        yield from _walk(child, relative, inner)


def test_every_subprocess_spawn_hides_its_console() -> None:
    offenders = [
        f"talks_reducer/{path}:{line} in {function}()"
        for path, line, function in _unhidden_spawns()
        if (path, function) not in ALLOWED
    ]

    assert not offenders, (
        "These subprocess calls can flash a console window on Windows. Pass "
        "**hidden_subprocess_kwargs() (talks_reducer/subprocess_utils.py), or "
        "add them to ALLOWED with a reason:\n  " + "\n  ".join(offenders)
    )


def test_allowlist_has_no_stale_entries() -> None:
    """An entry whose call was fixed or removed must leave the allowlist."""

    seen = {(path, function) for path, _, function in _unhidden_spawns()}
    stale = sorted(set(ALLOWED) - seen)

    assert not stale, f"Remove these ALLOWED entries, they match nothing: {stale}"


def test_guard_flags_a_spawn_without_the_helper() -> None:
    """The detector itself must catch the bug that started this."""

    bad = ast.parse("subprocess.Popen(cmd, stdout=subprocess.PIPE)").body[0].value
    good = ast.parse("subprocess.run(cmd, **hidden_subprocess_kwargs())").body[0].value

    assert _is_subprocess_spawn(bad) and not _passes_helper(bad)
    assert _is_subprocess_spawn(good) and _passes_helper(good)
```

- [ ] **Step 2: Run it**

Run: `.venv/Scripts/python.exe -m pytest tests/test_no_console_windows.py -v`
Expected: 3 passed. If `test_every_subprocess_spawn_hides_its_console` lists a site, a call from Tasks 2–4 was missed: fix that call, do not allowlist it.

- [ ] **Step 3: Prove the guard catches the original bug**

Temporarily delete the `**hidden_subprocess_kwargs(),` line from `pipeline._extract_video_metadata` and rerun the test.
Expected: FAIL naming `talks_reducer/pipeline.py:<line> in _extract_video_metadata()`. Restore the line (`git diff talks_reducer/pipeline.py` shows nothing) and rerun: 3 passed.

- [ ] **Step 4: Docs**

In both `CLAUDE.md` and `AGENTS.md`, under Repository Structure, add this bullet right after the `spherical.py` bullet:

```markdown
  - `subprocess_utils.py` holds `hidden_subprocess_kwargs()`, which every FFmpeg/ffprobe/PowerShell spawn passes as `**hidden_subprocess_kwargs()` so the windowed Windows build never flashes a console window (`CREATE_NO_WINDOW`, spelled `0x08000000` because the `subprocess` attribute is Windows-only). The flag used to be copied into each call, and the one that missed it flashed a window at the start and end of every conversion; `tests/test_no_console_windows.py` now fails on any `subprocess` call without the helper unless it is in its reasoned `ALLOWED` list.
```

No README change: no user-facing option changes.

- [ ] **Step 5: Format and commit**

```bash
.venv/Scripts/python.exe -m black tests/test_no_console_windows.py
.venv/Scripts/python.exe -m isort tests/test_no_console_windows.py
git add tests/test_no_console_windows.py CLAUDE.md AGENTS.md
git commit -m "test: Fail on subprocess spawns that can flash a console window

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Full verification

- [ ] **Step 1: Full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all pass. If a failure looks unrelated to this change, confirm it also fails on master (`git worktree add ../tr-master master`, run the same test there) and report it instead of fixing it here.

- [ ] **Step 2: Formatting check**

Run: `.venv/Scripts/python.exe -m black --check talks_reducer tests` and `.venv/Scripts/python.exe -m isort --check-only talks_reducer tests`
Expected: no changes needed in files touched by this plan.

- [ ] **Step 3: Manual check on Windows (the test cannot see windows)**

Run the GUI from source with a windowless interpreter so a flash would be visible:

```bash
.venv/Scripts/pythonw.exe -m talks_reducer.gui
```

Convert a short video (for example `docs/assets/demo.mp4`) and watch the start and the end of the run: no console window should appear. Also press **Create lnk** once: no PowerShell window. Report what you saw; if a window still flashes, note when (start / audio stage / end) so the remaining spawn can be found.
