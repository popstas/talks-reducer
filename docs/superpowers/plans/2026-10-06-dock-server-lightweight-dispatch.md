# Lightweight `dock-server` Dispatch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `talks-reducer dock-server` start without loading the GUI, `cli`, numpy or OpenBLAS, cutting its idle commit from ~575 MB to ~30 MB.

**Architecture:** Three entry points (`launcher.py` for the frozen build, `talks_reducer/__main__.py` for `python -m`, `cli.main` for the console script) recognise the dock-server keyword through one shared constant and call `talks_reducer.dock_server.main` before anything heavy is imported. The package `__init__` stops importing `cli` eagerly so that importing `talks_reducer.dock_server` is itself cheap. A subprocess test asserts the heavy modules never enter `sys.modules`.

**Tech Stack:** Python 3.9+ (`.venv` is 3.13), pytest, `black` + `isort` via `pyproject.toml`.

Spec: `docs/superpowers/specs/2026-10-06-dock-server-lightweight-dispatch-design.md`.
Diagnosis with the memory measurements: `docs/plans/20261006-dock-server-openblas-commit.md`.

## Global Constraints

- Run Python through the project venv: `.venv/Scripts/python.exe -m pytest …` (Windows). Never install a global interpreter.
- Run `.venv/Scripts/python.exe -m black .` and `.venv/Scripts/python.exe -m isort .` before every commit (project rule in `CLAUDE.md`).
- No `OPENBLAS_NUM_THREADS` / `OMP_NUM_THREADS` changes anywhere (spec decision: dock children inherit the environment).
- `multiprocessing.freeze_support()` must stay the first statement executed in `launcher.py` under `__main__`.
- Commit messages follow Angular style; this work is a `perf:` change. End every commit message with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Prefer docstrings over inline comments for new logic (`CLAUDE.md`).

## File Structure

| File | Responsibility after this plan |
|---|---|
| `talks_reducer/__init__.py` | Exposes `__version__` eagerly and `main` lazily via `__getattr__`. |
| `talks_reducer/dock_server.py` | Owns `DOCK_SERVER_COMMANDS`; otherwise unchanged. |
| `talks_reducer/cli.py` | `main` uses `DOCK_SERVER_COMMANDS` instead of its literal set. |
| `talks_reducer/__main__.py` | Dispatches dock-server before importing `cli`. |
| `launcher.py` | Dispatches dock-server before importing the GUI. |
| `tests/test_package_imports.py` | New: subprocess tests proving the light import paths. |
| `tests/test_launcher.py` | New subprocess test for the launcher dispatch. |
| `README.md`, `docs/TODO.md` | One sentence in the OBS dock section; TODO line closed. |

---

### Task 1: Lazy `main` in the package `__init__`

**Files:**
- Modify: `talks_reducer/__init__.py` (whole file, 8 lines)
- Create: `tests/test_package_imports.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `talks_reducer.main` still resolves to `talks_reducer.cli.main` on attribute access; `import talks_reducer.dock_server` no longer imports `talks_reducer.cli` or `numpy`. Task 4 and Task 5 rely on this.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_package_imports.py`:

```python
"""Import-weight tests: the dock server must not drag in the processing stack."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

HEAVY_MODULES = ("numpy", "tkinter", "gradio", "talks_reducer.cli", "talks_reducer.gui")


def _loaded_modules_after(code: str) -> list[str]:
    """Run ``code`` in a fresh interpreter and return the modules it left loaded."""

    script = (
        "import json, sys\n"
        f"{code}\n"
        "print(json.dumps(sorted(sys.modules)))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_importing_dock_server_skips_the_processing_stack() -> None:
    """``import talks_reducer.dock_server`` must not load numpy, tkinter or cli."""

    loaded = _loaded_modules_after("import talks_reducer.dock_server")

    assert "talks_reducer.dock_server" in loaded
    assert not [name for name in loaded if name.split(".")[0] in HEAVY_MODULES or name in HEAVY_MODULES]


def test_package_main_still_resolves_to_cli_main() -> None:
    """``talks_reducer.main`` stays available for callers that import it lazily."""

    import talks_reducer
    from talks_reducer import cli

    assert talks_reducer.main is cli.main
```

- [ ] **Step 2: Run the tests to verify the first one fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_package_imports.py -v`
Expected: `test_importing_dock_server_skips_the_processing_stack` FAILS (the assertion lists `numpy`, `talks_reducer.cli`, …). `test_package_main_still_resolves_to_cli_main` PASSES already.

- [ ] **Step 3: Make `main` lazy**

Replace the whole of `talks_reducer/__init__.py` with:

```python
"""talks_reducer exposes a CLI for speeding up videos with silent sections."""

from __future__ import annotations

from typing import Any

from .__about__ import __version__

__all__ = ["main", "__version__"]


def __getattr__(name: str) -> Any:
    """Resolve ``talks_reducer.main`` lazily.

    Importing ``cli`` eagerly pulled numpy and OpenBLAS into every process
    that touched any submodule, including the OBS dock server, which never
    processes media itself. Deferring the import keeps
    ``import talks_reducer.dock_server`` cheap.
    """

    if name == "main":
        from .cli import main

        return main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_package_imports.py -v`
Expected: both PASS.

- [ ] **Step 5: Run the whole suite to catch anything that relied on the eager import**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all green (same count as before the change).

- [ ] **Step 6: Format and commit**

```bash
.venv/Scripts/python.exe -m black talks_reducer/__init__.py tests/test_package_imports.py
.venv/Scripts/python.exe -m isort talks_reducer/__init__.py tests/test_package_imports.py
git add talks_reducer/__init__.py tests/test_package_imports.py
git commit -m "perf: Resolve the package-level main lazily

Importing talks_reducer.cli from the package __init__ loaded numpy and
OpenBLAS into every process that touched any submodule.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Shared `DOCK_SERVER_COMMANDS` constant used by `cli.main`

**Files:**
- Modify: `talks_reducer/dock_server.py:31-37` (constants block)
- Modify: `talks_reducer/cli.py:934` (`main`, the `dock-server` branch)
- Test: `tests/test_dock_server.py` (extend near `test_cli_dispatches_dock_server`, line 276)

**Interfaces:**
- Produces: `talks_reducer.dock_server.DOCK_SERVER_COMMANDS: frozenset[str]` containing exactly `{"dock-server", "obs-dock"}`. Tasks 3 and 4 import it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dock_server.py`:

```python
def test_dock_server_commands_constant() -> None:
    """Every entry point dispatches on one shared keyword set."""

    assert dock_server.DOCK_SERVER_COMMANDS == frozenset({"dock-server", "obs-dock"})


def test_cli_dispatches_obs_dock_alias(monkeypatch) -> None:
    """The ``obs-dock`` alias routes into the dock server too."""

    captured: list[list[str]] = []
    monkeypatch.setattr(
        dock_server, "main", lambda argv=None: captured.append(list(argv or []))
    )

    cli.main(["obs-dock", "--host", "0.0.0.0"])

    assert captured == [["--host", "0.0.0.0"]]
```

- [ ] **Step 2: Run the tests to verify the constant test fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_dock_server.py -k "commands_constant or obs_dock_alias" -v`
Expected: `test_dock_server_commands_constant` FAILS with `AttributeError: module 'talks_reducer.dock_server' has no attribute 'DOCK_SERVER_COMMANDS'`; the alias test PASSES (the literal already covers it).

- [ ] **Step 3: Add the constant**

In `talks_reducer/dock_server.py`, directly after `MAX_BODY_BYTES = 1024 * 1024`:

```python
DOCK_SERVER_COMMANDS = frozenset({"dock-server", "obs-dock"})
"""Positional keywords that select the dock server in every entry point.

``launcher.py``, ``talks_reducer/__main__.py`` and ``cli.main`` all check
this set before importing anything heavy, so the three cannot drift apart.
"""
```

- [ ] **Step 4: Use it in `cli.main`**

In `talks_reducer/cli.py`, replace

```python
    if argv_list and argv_list[0] in {"dock-server", "obs-dock"}:
```

with

```python
    if argv_list and argv_list[0] in DOCK_SERVER_COMMANDS:
```

and add the import to the module's relative-import block (after `from .ffmpeg import FFmpegNotFoundError`):

```python
from .dock_server import DOCK_SERVER_COMMANDS
```

`dock_server` imports only the standard library and `.icons`, so this costs nothing. Keep `_launch_dock_server` and its `import_module` call exactly as they are: `test_cli_dispatches_dock_server` monkeypatches `dock_server.main` and relies on that lookup happening at call time.

- [ ] **Step 5: Run the dock and CLI tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_dock_server.py tests/test_cli.py tests/test_package_imports.py -v`
Expected: all PASS, including the subprocess import test from Task 1 (`cli` importing `dock_server` is fine; the reverse never happens).

- [ ] **Step 6: Format and commit**

```bash
.venv/Scripts/python.exe -m black talks_reducer/dock_server.py talks_reducer/cli.py tests/test_dock_server.py
.venv/Scripts/python.exe -m isort talks_reducer/dock_server.py talks_reducer/cli.py tests/test_dock_server.py
git add talks_reducer/dock_server.py talks_reducer/cli.py tests/test_dock_server.py
git commit -m "refactor: Share the dock-server keyword set between entry points

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Dispatch in `talks_reducer/__main__.py`

**Files:**
- Modify: `talks_reducer/__main__.py` (whole file, 11 lines)
- Test: `tests/test_package_imports.py` (extend)

**Interfaces:**
- Consumes: `talks_reducer.dock_server.DOCK_SERVER_COMMANDS` (Task 2), `talks_reducer.dock_server.main(argv: Sequence[str] | None) -> None`.
- Produces: `python -m talks_reducer dock-server …` runs the dock without importing `cli`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_package_imports.py`:

```python
def _run_entry_point_with_stubbed_dock(args: list[str], *, runner: str) -> dict:
    """Invoke an entry point with ``dock_server.main`` stubbed; report what loaded.

    ``runner`` is Python source that starts the entry point. The stub records
    the argv it received and the modules present at that moment.
    """

    script = "\n".join(
        [
            "import json, sys",
            "import talks_reducer.dock_server as dock",
            "report = {}",
            "def stub(argv=None):",
            "    report['argv'] = list(argv or [])",
            "    report['modules'] = sorted(sys.modules)",
            "dock.main = stub",
            f"sys.argv = {json.dumps(args)}",
            runner,
            "print(json.dumps(report))",
        ]
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def _heavy(loaded: list[str]) -> list[str]:
    return [
        name
        for name in loaded
        if name in HEAVY_MODULES or name.split(".")[0] in HEAVY_MODULES
    ]


def test_module_entry_point_dispatches_dock_server_lightly() -> None:
    """``python -m talks_reducer dock-server`` never imports cli, numpy or the GUI."""

    report = _run_entry_point_with_stubbed_dock(
        ["talks_reducer", "dock-server", "--port", "4242"],
        runner="import runpy; runpy.run_module('talks_reducer', run_name='__main__')",
    )

    assert report["argv"] == ["--port", "4242"]
    assert _heavy(report["modules"]) == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_package_imports.py::test_module_entry_point_dispatches_dock_server_lightly -v`
Expected: FAIL. `report["argv"]` is `["--port", "4242"]` (cli's own dispatch still reaches the stub) but `_heavy(...)` lists `numpy…` and `talks_reducer.cli`.

- [ ] **Step 3: Dispatch before importing `cli`**

Replace the whole of `talks_reducer/__main__.py` with:

```python
"""Module executed when running ``python -m talks_reducer``."""

from __future__ import annotations

import sys


def _run() -> None:
    """Dispatch the dock server before the CLI pulls in the processing stack.

    ``cli`` imports ``audio`` and ``pipeline`` at module level, and with them
    numpy and OpenBLAS; the dock server only spawns child processes and needs
    none of it.
    """

    from talks_reducer.dock_server import DOCK_SERVER_COMMANDS

    if sys.argv[1:2] and sys.argv[1] in DOCK_SERVER_COMMANDS:
        from talks_reducer.dock_server import main as dock_main

        dock_main(sys.argv[2:])
        return

    from talks_reducer.cli import main

    main()


if __name__ == "__main__":
    _run()
```

Absolute imports are used because the previous file's `try/except ImportError` fallback existed for the frozen build where relative imports in `__main__` fail.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_package_imports.py -v`
Expected: all PASS.

- [ ] **Step 5: Smoke-check the non-dock path still reaches the CLI**

Run: `.venv/Scripts/python.exe -m talks_reducer --version`
Expected: prints `talks-reducer 1.3.0` (or the current version) and exits 0.

- [ ] **Step 6: Format and commit**

```bash
.venv/Scripts/python.exe -m black talks_reducer/__main__.py tests/test_package_imports.py
.venv/Scripts/python.exe -m isort talks_reducer/__main__.py tests/test_package_imports.py
git add talks_reducer/__main__.py tests/test_package_imports.py
git commit -m "perf: Dispatch dock-server from python -m before importing the CLI

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Dispatch in `launcher.py` (frozen build)

**Files:**
- Modify: `launcher.py:63-95` (`_run_application`)
- Test: `tests/test_launcher.py`

**Interfaces:**
- Consumes: `talks_reducer.dock_server.DOCK_SERVER_COMMANDS` (Task 2), `talks_reducer.dock_server.main`.
- Produces: `talks-reducer.exe dock-server …` runs the dock without importing the GUI or `cli`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_launcher.py` (reuse the existing `LAUNCHER` constant; add the imports shown):

```python
import json
import subprocess
import sys

HEAVY_MODULES = ("numpy", "tkinter", "gradio", "talks_reducer.cli", "talks_reducer.gui")


def test_launcher_dispatches_dock_server_before_importing_the_gui() -> None:
    """``talks-reducer.exe dock-server`` must not load the GUI, cli or numpy.

    Runs in a child interpreter so this process's already-imported modules do
    not pollute the measurement.
    """

    script = "\n".join(
        [
            "import json, runpy, sys",
            "import talks_reducer.dock_server as dock",
            "report = {}",
            "def stub(argv=None):",
            "    report['argv'] = list(argv or [])",
            "    report['modules'] = sorted(sys.modules)",
            "dock.main = stub",
            f"sys.argv = {json.dumps([str(LAUNCHER), 'dock-server', '--port', '4242'])}",
            f"runpy.run_path({json.dumps(str(LAUNCHER))}, run_name='__main__')",
            "print(json.dumps(report))",
        ]
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=LAUNCHER.parent,
        capture_output=True,
        text=True,
        check=True,
    )
    report = json.loads(completed.stdout.strip().splitlines()[-1])

    assert report["argv"] == ["--port", "4242"]
    heavy = [
        name
        for name in report["modules"]
        if name in HEAVY_MODULES or name.split(".")[0] in HEAVY_MODULES
    ]
    assert heavy == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_launcher.py -v`
Expected: the new test FAILS with a non-empty `heavy` list (`talks_reducer.gui`, `tkinter`, `numpy`, …). The existing ordering test still PASSES.

- [ ] **Step 3: Dispatch before importing the GUI**

In `launcher.py`, change `_run_application` so its body starts with the dispatch:

```python
def _run_application() -> None:
    """Entry point used by the PyInstaller launcher."""

    if _dispatch_dock_server(sys.argv[1:]):
        return

    try:
        from talks_reducer.gui import main as gui_main
    except Exception:
```

(the rest of the function is unchanged) and add this helper directly above `_run_application`:

```python
def _dispatch_dock_server(argv: "list[str]") -> bool:
    """Run the OBS dock server and return ``True`` when ``argv`` selects it.

    This runs before the GUI import below. Importing the GUI pulls in
    tkinter and pystray, and the CLI fallback pulls in numpy and OpenBLAS,
    whose per-CPU buffer pool alone committed ~550 MB in an idle dock
    server that only ever spawns child processes.
    """

    from talks_reducer.dock_server import DOCK_SERVER_COMMANDS

    if not argv or argv[0] not in DOCK_SERVER_COMMANDS:
        return False

    from talks_reducer.dock_server import main as dock_main

    dock_main(argv[1:])
    return True
```

Do not touch anything above `_run_application`: `multiprocessing.freeze_support()` and the console attachment stay first.

- [ ] **Step 4: Run the launcher tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_launcher.py -v`
Expected: both PASS.

- [ ] **Step 5: Run the full suite, black and isort**

```bash
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m black .
.venv/Scripts/python.exe -m isort .
```

Expected: pytest green; black/isort report no changes to files outside this plan (if they reformat something unrelated, revert that with `git checkout -- <file>` and report it).

- [ ] **Step 6: Commit**

```bash
git add launcher.py tests/test_launcher.py
git commit -m "perf: Dispatch dock-server from the launcher before importing the GUI

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Documentation and TODO

**Files:**
- Modify: `README.md:65-70` (OBS Processing Dock, step 1)
- Modify: `docs/TODO.md:4`

**Interfaces:** none.

- [ ] **Step 1: README sentence**

In `README.md`, after the fenced `talks-reducer dock-server` block inside step 1 of **OBS Processing Dock (Windows)**, add a line (same indentation as the step text):

```markdown
   The dock server is a thin HTTP process: it does not load the processing
   pipeline or the desktop GUI and runs each conversion as a separate
   `talks-reducer` child, so it idles at a few tens of megabytes.
```

- [ ] **Step 2: Close the TODO line**

In `docs/TODO.md`, change the leading `- [ ]` of the dock-server line to `- [x]`.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/TODO.md
git commit -m "docs: Describe the dock server as a thin process and close the TODO

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Acceptance on the frozen build (manual, Windows)

**Files:** none modified. This task verifies the spec's acceptance criteria against a rebuilt installer and is a gate for merging, not for the earlier commits.

- [ ] **Step 1: Rebuild the frozen executable**

Follow `CONTRIBUTION.md` for the PyInstaller build (the spec file is `talks-reducer.spec`). Install or point `OBS_DOCK_EXE` at the fresh `talks-reducer.exe`.

- [ ] **Step 2: Measure the idle dock on a spare port**

```powershell
$p = Start-Process "$env:LOCALAPPDATA\Programs\talks-reducer\talks-reducer.exe" -ArgumentList 'dock-server','--port','48888' -PassThru -WindowStyle Hidden
Start-Sleep 10; $p.Refresh()
"private={0:N0} MB ws={1:N0} MB threads={2}" -f ($p.PrivateMemorySize64/1MB), ($p.WorkingSet64/1MB), $p.Threads.Count
$p.Modules | Where-Object { $_.ModuleName -match 'openblas|umath|tk86' } | Select-Object ModuleName
Stop-Process -Id $p.Id -Force
```

Expected: `private` under 60 MB, `threads` under 8, and the module filter prints nothing.

- [ ] **Step 3: Functional check**

With the measured instance running (before `Stop-Process`):

```powershell
curl.exe http://127.0.0.1:48888/presets
curl.exe -X POST http://127.0.0.1:48888/process -H "Content-Type: application/json" -d '{"file": "C:\path\to\short.mp4", "speed": 10, "resolution": "720p", "codec": "h264", "autoClose": true}'
```

Expected: the first call returns a JSON preset list; the second returns HTTP 202, a child `talks-reducer.exe` appears in Task Manager, and a `short_speedup.mp4` (or codec-suffixed name) is written next to the input. The payload keys mirror `tests/test_dock_server.py::test_handle_process_validates_and_spawns`.

- [ ] **Step 4: Record the numbers**

Paste the before/after table into the PR description and, if the figures differ materially from the spec's expectation, into `docs/plans/20261006-dock-server-openblas-commit.md` under a new `## Result` heading.
