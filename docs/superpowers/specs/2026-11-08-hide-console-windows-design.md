# Hide console windows on Windows — design

Date: 2026-11-08

## Problem

On Windows a console window flashes briefly at the start and at the end of
every conversion.

## Cause

`pipeline._extract_video_metadata` (`talks_reducer/pipeline.py`) runs `ffprobe`
through `subprocess.Popen` without `creationflags`. A console program spawned
from a windowed process (the PyInstaller build is `console=False`) gets a fresh
console window unless `CREATE_NO_WINDOW` (`0x08000000`) is passed. The function
is called exactly twice per job:

- at the start, for the input file (`metadata = _extract_video_metadata(input_path, ...)`);
- at the end, for the output file (`output_metadata = _extract_video_metadata(output_path, ...)`).

That matches the symptom. This call never had the flag. Every other
FFmpeg/ffprobe spawn (`audio.py`, `ffmpeg.py`, `glue.py`, `spherical.py`,
`dock_server.py`) sets it by hand with an inline `0x08000000`. Nothing stops
the next new call site from forgetting it, which is why the flash keeps coming
back.

## Ruled out

`audio_workers.py` renders the phase vocoder in a `spawn` process pool. In the
frozen build `sys.executable` is the same `console=False` exe, so the workers
get no console. From source they inherit the parent's console. Not a source of
the flash.

## 1. Helper

New leaf module `talks_reducer/subprocess_utils.py` (it imports nothing from
the package, so no new import cycles):

```python
CREATE_NO_WINDOW = 0x08000000

def hidden_subprocess_kwargs() -> dict:
    """Return ``subprocess`` kwargs that keep a child from opening a console."""
    if sys.platform == "win32":
        return {"creationflags": CREATE_NO_WINDOW}
    return {}
```

Constraints:

- `sys.platform` is read **at call time**, not at import.
  `tests/test_audio.py::test_is_valid_input_file_sets_creationflags_on_windows`
  monkeypatches `sys.platform` to `"win32"` and expects `0x08000000`.
- The flag is the literal `0x08000000`, not `subprocess.CREATE_NO_WINDOW`: that
  attribute exists only on Windows, and CI runs on Linux.
- On non-Windows the kwargs are empty, so `creationflags=0` is no longer passed
  there. That is equivalent: `0` is the default.

## 2. Fix

In `pipeline._extract_video_metadata`, replace `Popen(..., bufsize=1,
universal_newlines=True)` + `communicate()` with
`subprocess.run(command, capture_output=True, text=True, **hidden_subprocess_kwargs())`
and read `result.stdout`. Nothing uses the process object, so this is
equivalent.

## 3. Migrate the other call sites

Replace the inline `creationflags` logic with `**hidden_subprocess_kwargs()`.
Behaviour is unchanged:

- `audio.py`: both `ffprobe` calls;
- `ffmpeg.py`: all four calls (`_probe_ffmpeg_output`, `_trial_encode`,
  `run_timed_ffmpeg_command`'s `Popen`, `get_video_duration`);
- `glue.py`: the `ffprobe` call;
- `spherical.py`: the `ffprobe` call;
- `dock_server.py`: the exe launch (drop the module-level `_CREATE_NO_WINDOW`).

Two more Windows spawns that also flash a console get the helper (not the
reported bug, but a one-line change each):

- `gui/shortcut.py:write_shortcut`: `powershell -Command`, run when the user
  presses **Create lnk**;
- `gui/startup.py`: the `sys.executable -c` Tk self-test, which flashes when
  run from source with a console Python.

## 4. Guard test

New `tests/test_no_console_windows.py`. It parses the AST of every `.py` under
`talks_reducer/` (AST, not grep, because docstrings and comments mention
`subprocess.Popen`) and fails on any direct call to `subprocess.run`, `Popen`,
`call`, `check_call` or `check_output` that does not pass
`**hidden_subprocess_kwargs()` in the call itself, outside an explicit
allowlist. A bare `creationflags=` does not count: `creationflags=0` would
pass a "has the keyword" check. The failure
message names the file, line and the fix (use `hidden_subprocess_kwargs()`).

The allowlist is keyed by `(module path, enclosing function name)`, so moving
lines does not break it. Each entry carries a reason:

| Site | Reason |
| --- | --- |
| `cli.py` (server-tray launch) | Has its own `_should_hide_subprocess_console()` gating: a tray started from a real console keeps it. Asserted by `tests/test_cli.py`. |
| `gui/relaunch.py:spawn_detached` | Deliberately uses `DETACHED_PROCESS \| CREATE_NEW_PROCESS_GROUP`. |
| `server_tray.py` (GUI launch) | Launches the GUI, which has no console in the frozen build. |
| `gui/app.py` (installer launch, file manager) | Non-Windows branches (Windows uses `os.startfile`), or `explorer`, which is a GUI program. |
| `gui/theme.py:run_defaults_command` | macOS only. |

Calls passing `**kwargs` built elsewhere (`cli.py`, `relaunch.py`) are covered
by the allowlist rather than by trying to infer their contents.

The test is pure static analysis, so it runs on Linux CI, which is where it
must catch a regression.

Existing tests stay green, in particular `test_audio.py` (flag on win32) and
`test_cli.py` (tray gating). Two kinds of small test edits are expected:
`test_pipeline.py` fakes `subprocess.run` instead of `Popen`, and
`test_audio.py` patches `sys.platform` instead of `audio.sys.platform`
(`audio.py` no longer imports `sys`). Add a unit test for
`hidden_subprocess_kwargs()` on `win32` and `linux`, and one asserting that
`_extract_video_metadata` passes `creationflags` on win32.

## 5. Docs

Add one line to the Repository Structure section of `CLAUDE.md` / `AGENTS.md`:
every FFmpeg/ffprobe/helper spawn goes through
`subprocess_utils.hidden_subprocess_kwargs()`, enforced by
`tests/test_no_console_windows.py`. No README change: no user-facing option
changes.

## Out of scope

- Changing `cli.py`'s tray console gating.
- The audio worker pool (ruled out above).
- Manual verification on Windows is required: the test proves the flag is
  passed, not that no window appears. Run a conversion in the built GUI and
  watch for the flash at start and end.
