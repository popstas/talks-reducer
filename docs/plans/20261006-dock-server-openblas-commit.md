# dock-server reserves ~575 MB of commit at idle (OpenBLAS thread pool)

Handoff written 2026-10-06 from a RAM investigation of the laptop
(`popstas-nb`, 16 GB soldered, Windows 11). Read-only diagnosis, nothing in the
repo was changed. The fix is small and self-contained.

## Symptom

`talks-reducer.exe dock-server` (the OBS dock HTTP server, autostarted from the
Startup folder shortcut "Talks Reducer OBS Dock Server") looks tiny in Task
Manager (26 MB private working set) but holds **575 MB of committed private
memory** and **4.7 GB of virtual address space** while doing nothing. Commit
charge is what Windows checks against the commit limit (RAM + pagefile), so
this is half a gigabyte permanently subtracted from the budget that caused the
"low virtual memory" crashes on the laptop (Event ID 2004, 11 events between
29.09 and 02.10, `talks-reducer.exe` itself appears in one of them at 2.3 GB
during an actual processing run).

Measured on the installed build 1.3.0 (`%LOCALAPPDATA%\Programs\talks-reducer`),
second instance started on a spare port so the live dock was not touched:

| Run | Private bytes (commit) | Working set | Virtual size | Threads |
|---|---|---|---|---|
| `talks-reducer.exe dock-server --port 48888` | **575 MB** | 44 MB | 4.7 GB | 21 |
| same, with `OPENBLAS_NUM_THREADS=1` in the environment | **29 MB** | 43 MB | 4.2 GB | 4 |

The environment variable alone removes 546 MB. That pins the cause.

## Root cause

OpenBLAS allocates its worker-thread buffer pool when the DLL is loaded, one
buffer per CPU thread (`NUMBER_OF_PROCESSORS` is 18 on this laptop), roughly
32 MB each, committed up front and never touched by the dock server. The loaded
module list of the idle process confirms it: `libscipy_openblas64_-*.dll`
(19.5 MB mapped), `_multiarray_umath.cp311-win_amd64.pyd`, plus `tcl86t.dll` /
`tk86t.dll` / `_tkinter.pyd` that the dock server has no use for either.

Why the dock server loads numpy at all — the import chain:

1. `launcher.py::_run_application` does `from talks_reducer.gui import main as gui_main`
   **before** looking at `sys.argv`. That imports the whole GUI package (tkinter,
   pystray, layout, …). `gui_main()` then sees arguments and returns `False`,
   delegating to the CLI — but the GUI is already resident.
2. `talks_reducer/cli.py` imports `audio`, `pipeline`, `glue` at module top
   (lines 17–21). `audio.py` imports `numpy` and `audiotsm`; `pipeline.py`
   imports `numpy`, `chunks`, `wav_io`. Somewhere in that tree scipy's / numpy's
   bundled OpenBLAS gets loaded (trace it with
   `python -X importtime -c "import talks_reducer.cli" 2> importtime.log`).
3. Only then, at `cli.py:934`, does `main()` notice `argv[0] in {"dock-server",
   "obs-dock"}` and call `_launch_dock_server`, which imports `dock_server`
   lazily — the one module that is actually needed.

`dock_server.py` itself imports nothing heavy (`argparse`, `json`, `http.server`,
`.icons`, lazy `.presets`). Processing requests are not run in-process: `handle_process`
spawns the executable as a child (`subprocess.Popen([exe_path, *args], …)`,
`dock_server.py:135`), so numpy, scipy, audiotsm and tkinter are pure dead
weight in this process.

The same chain affects every other long-lived surface: the Gradio `server` /
`server-tray` mode and the desktop GUI sitting idle also carry the ~550 MB
OpenBLAS reservation, because `cli.py` and `gui` pull `pipeline` in at import
time. There it is at least used eventually; in the dock server it never is.

## Fix (recommended, do both)

1. **Dispatch `dock-server` before anything heavy is imported.** In
   `launcher.py::_run_application` (and `talks_reducer/__main__.py` for the
   unfrozen path) check `sys.argv[1:2]` for `dock-server` / `obs-dock` first and
   call `talks_reducer.dock_server.main(argv)` directly, skipping the GUI and
   `cli` imports. Alternatively make the `audio` / `pipeline` / `glue` imports
   in `cli.py` lazy (move them into the functions that use them) so that
   `cli.main` can dispatch server modes without loading numpy. The first
   variant is smaller and keeps `cli.py` untouched; the second also helps the
   `server` mode and `--help`. Expected result: dock-server commit drops from
   575 MB to ~30 MB and thread count from 21 to ~4.
2. **Cap OpenBLAS threads for the long-lived modes** as a belt-and-braces
   measure, in case a future import drags numpy back in:
   `os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")` (and `OMP_NUM_THREADS`)
   at the very top of `launcher.py`, before any numpy import, when the mode is
   `dock-server` / `server` / `server-tray`. Do **not** apply it blindly to
   processing runs without measuring: the audio stage uses `audiotsm` on numpy
   arrays and `multiprocessing` workers (`launcher.py` calls
   `multiprocessing.freeze_support()`), so BLAS threading is probably irrelevant
   there, but check wall time on a sample file before and after.

Optional follow-ups, lower value:

- Setting the variable for the GUI too would cut the idle desktop app by the
  same ~550 MB of commit if benchmarking shows no slowdown.
- `launcher.py` importing the GUI for every CLI invocation (`--help`, `server`)
  is the same anti-pattern; the dispatch-first change fixes it for all modes.

## Acceptance

- `talks-reducer.exe dock-server --port 48888` (frozen build) after 10 s:
  `PrivateMemorySize64` < 60 MB, threads < 8, module list without
  `libscipy_openblas64_*.dll`, `_multiarray_umath*.pyd`, `tk86t.dll`.
- The dock still processes a file end to end (the subprocess path in
  `handle_process` is unchanged) and `GET /presets` still answers.
- `pytest tests/test_dock_server.py tests/test_cli.py` green; `black` / `isort`
  clean per `CLAUDE.md`.
- Rebuild the installer and re-measure; the Startup shortcut keeps working.

PowerShell to measure (run from any directory):

```powershell
$p = Start-Process "$env:LOCALAPPDATA\Programs\talks-reducer\talks-reducer.exe" -ArgumentList 'dock-server','--port','48888' -PassThru -WindowStyle Hidden
Start-Sleep 10; $p.Refresh()
"private={0:N0} MB ws={1:N0} MB threads={2}" -f ($p.PrivateMemorySize64/1MB), ($p.WorkingSet64/1MB), $p.Threads.Count
$p.Modules | Where-Object { $_.ModuleName -match 'openblas|umath|tk86' } | Select-Object ModuleName
Stop-Process -Id $p.Id -Force
```

## Context

- Laptop RAM write-up (vault): `Notes/2026/10/Потребление RAM на nb - разбор.md`.
- Dock docs: `docs/obs-dock.md` (autostart via Startup shortcut / `schtasks`).
- Installed build: 1.3.0, repo HEAD `9f0bfef` at the time of writing.
