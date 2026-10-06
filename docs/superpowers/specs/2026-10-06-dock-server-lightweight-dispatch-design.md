# Dispatch `dock-server` before the heavy imports

Date: 2026-10-06. Diagnosis: `docs/plans/20261006-dock-server-openblas-commit.md`.

## Problem

`talks-reducer.exe dock-server` idles at 575 MB of committed memory and
21 threads. The process never processes media itself (`handle_process`
spawns a child executable), yet it loads tkinter, pystray, numpy and
OpenBLAS, because both entry points import the GUI and `cli` before they
look at the arguments:

1. `launcher.py::_run_application` imports `talks_reducer.gui` first.
2. `talks_reducer/__main__.py` and the GUI's CLI fallback import
   `talks_reducer.cli`, which imports `audio`, `glue` and `pipeline` at
   module level, pulling in numpy and OpenBLAS.
3. `cli.main` only then notices `dock-server` and imports `dock_server`.

OpenBLAS commits one buffer per CPU thread on DLL load. With
`OPENBLAS_NUM_THREADS=1` the same process commits 29 MB, which pins the
cause. The commit is static, not a leak.

## Decision

Dispatch the dock server before anything heavy is imported. No
`OPENBLAS_NUM_THREADS` cap: the dock's children inherit its environment
through `subprocess.Popen` without `env=`, so a cap would also throttle the
real processing runs. A subprocess test guards the regression instead.

## Changes

### `talks_reducer/dock_server.py`

Add `DOCK_SERVER_COMMANDS = frozenset({"dock-server", "obs-dock"})` near
the other module constants. Nothing else changes; the module stays free of
numpy, tkinter and gradio imports.

### `launcher.py`

In `_run_application`, before the GUI import:

```python
if sys.argv[1:2] and sys.argv[1] in DOCK_SERVER_COMMANDS:
    from talks_reducer.dock_server import main as dock_main
    dock_main(sys.argv[2:])
    return
```

The constant is imported from `talks_reducer.dock_server` inside the
function so the launcher module itself keeps importing nothing from the
package at load time. `multiprocessing.freeze_support()` and the console
attachment stay ahead of the dispatch, unchanged.

### `talks_reducer/__main__.py`

Same check before `from .cli import main`, so
`python -m talks_reducer dock-server` is lightweight from source too.

### `talks_reducer/cli.py`

`main` compares `argv_list[0]` against `dock_server.DOCK_SERVER_COMMANDS`
instead of its inline literal, so the three entry points cannot drift.
`_launch_dock_server` stays: the `talks-reducer` console script from
`pyproject.toml` still reaches the dock through `cli.main`.

## Tests

`tests/test_launcher.py` gains a subprocess test. It runs the launcher as
`__main__` with argv `["launcher.py", "dock-server"]` inside a Python child
that first replaces `talks_reducer.dock_server.main` with a stub printing
`sorted(sys.modules)`, then asserts that `numpy`, `tkinter`,
`talks_reducer.cli`, `talks_reducer.gui` and `gradio` are absent and that
the stub received `[]` as argv. A sibling test does the same for
`python -m talks_reducer dock-server`. The existing
`freeze_support -> gui` ordering test is unaffected because it passes no
arguments.

`tests/test_dock_server.py::test_cli_dispatches_dock_server` keeps covering
the `cli.main` path.

## Acceptance

- Frozen build: `talks-reducer.exe dock-server --port 48888` after 10 s
  shows `PrivateMemorySize64` under 60 MB, fewer than 8 threads, and no
  `libscipy_openblas64_*.dll`, `_multiarray_umath*.pyd` or `tk86t.dll` in
  its module list (PowerShell snippet in the diagnosis file).
- The dock still processes a file end to end and `GET /presets` answers.
- `pytest tests/test_launcher.py tests/test_dock_server.py tests/test_cli.py`
  green; `black` and `isort` clean.

## Docs

- README, OBS dock section: one sentence that the dock server process does
  not load the processing pipeline or the GUI and runs conversions as child
  processes.
- `docs/TODO.md`: mark the dock-server line done.

## Out of scope

- `OPENBLAS_NUM_THREADS` for `server` / `server-tray` / GUI idle.
- Lazy `audio` / `glue` / `pipeline` imports in `cli.py`.
- The 2.3 GB peak seen during a real processing run.
