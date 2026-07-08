# Windows taskbar progress — design

## Goal

Mirror the GUI progress bar onto the Windows taskbar button while a conversion runs, so a user
who switched away can watch progress without raising the window. When the run ends, hold the
indicator (green 100% on success, red on failure) until the window regains focus.

Windows-only. Other platforms get a no-op; macOS/Linux have no equivalent that is worth the
complexity.

## Module: `talks_reducer/gui/taskbar.py`

`create_taskbar_progress(root) -> TaskbarProgress` returns a live instance only when
`sys.platform == "win32"` and COM initialization plus `ITaskbarList3` creation succeed. Any
failure — wrong platform, no COM, a stubbed Tk root — yields a `TaskbarProgress` wrapping a null
backend, so every call is a silent no-op. The GUI never has to guard its call sites.

`TaskbarProgress` owns the state machine and knows nothing about COM:

| Method | Effect |
| --- | --- |
| `begin()` | clears the hold, sets the normal state at 0% |
| `set_value(percent)` | clamps to 0–100 and forwards; ignored while a hold is active |
| `finish()` | 100% normal, sets the hold |
| `set_error()` | error (red) state at the current value, sets the hold |
| `clear()` | removes the indicator, drops the hold |
| `on_focus()` | `clear()` only when a hold is active |

The hold is what implements "keep 100% until focus": nothing auto-clears the indicator, and stray
progress callbacks arriving after a terminal state cannot overwrite it.

The COM layer is a `_Win32Backend` behind two methods, `set_value(percent)` and
`set_state(state)` where state is `normal`, `error`, or `none`. It uses `ctypes` only — no new
dependency, nothing to add to the PyInstaller spec:

- `ole32.CoInitializeEx` (apartment threaded; `S_FALSE` and `RPC_E_CHANGED_MODE` are tolerated)
- `ole32.CoCreateInstance(CLSID_TaskbarList, CLSCTX_INPROC_SERVER, IID_ITaskbarList3)`
- vtable slots `HrInit = 3`, `SetProgressValue = 9`, `SetProgressState = 10`
- HWND from `user32.GetParent(root.winfo_id())`, falling back to `winfo_id()`

Because the backend is injectable, tests never touch `ctypes`.

## Hooks in `gui/app.py`

COM objects must be used on the thread that initialized COM. Both hook points already run inside
`root.after(0, ...)` updaters, so every call lands on the Tk main thread.

| Moment | Call |
| --- | --- |
| `_start_run()` | `begin()` |
| `_reset_progress_baseline()` | `begin()` — a batch's next file must not inherit the previous file's hold |
| `_set_progress()` updater | `set_value(value)` |
| `_set_status()` sees a success status | `finish()`, then clear at once if the window already has focus |
| `_set_status("Error")` | `set_error()`, then clear at once if the window already has focus |
| `_set_status("Aborted")` | `clear()` — the user stopped it deliberately and is already looking |
| `<FocusIn>` on `root` | `on_focus()` |
| `_on_close()` | `clear()` |

Per-file `success` statuses in a batch set the hold, and the next file's
`_reset_progress_baseline()` clears it again, so the indicator recovers on its own.

## Testing

`tests/test_gui_taskbar.py` drives `TaskbarProgress` against a recording fake backend: clamping,
each state transition, the hold surviving stray `set_value` calls, focus clearing only while held,
and `create_taskbar_progress` returning a no-op off Windows.
