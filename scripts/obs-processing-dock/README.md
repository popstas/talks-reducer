# OBS Processing Dock

A compact OBS Custom Browser Dock that watches for finished recordings and starts
Talks Reducer processing with one click.

## Overview

The dock connects to OBS over obs-websocket, captures the path of the last
stopped recording, and exposes quick controls for resolution, silent-speed, and
codec. A small local Node.js server (`process-server.js`) receives HTTP requests
from the dock and spawns `talks-reducer.exe` with the matching CLI flags.

This keeps OBS and Talks Reducer loosely coupled: OBS only needs the browser
dock and WebSocket server; Talks Reducer runs as a normal CLI process with the
same arguments you would use from a terminal or shortcut.

## Requirements

- OBS Studio with **WebSocket server** enabled (`Tools → WebSocket Server Settings`)
- [Node.js](https://nodejs.org/) (for `process-server.js`)
- Installed **Talks Reducer** executable (Windows installer or local build)

Default executable path:

```text
%LOCALAPPDATA%\Programs\talks-reducer\talks-reducer.exe
```

## Setup

1. Start the local processing server:

```powershell
.\obs-talks-reducer.ps1
```

To start automatically at logon with no window, see
[Run at logon (Task Scheduler)](#run-at-logon-task-scheduler).

The server listens on `http://127.0.0.1:17890` by default.

2. In OBS, add a Custom Browser Dock:

```text
Docks → Custom Browser Docks
```

| Field | Value |
| --- | --- |
| Name | `Processing` (or any label) |
| URL | `file:///D:/path/to/scripts/obs-processing-dock/dock.html` |

Replace the path with the real location of `dock.html` on your machine.

3. Open **Settings** in the dock and confirm:

- **Talks Reducer** points to your `talks-reducer.exe`
- **OBS WebSocket** URL matches OBS (default `ws://127.0.0.1:4455`)
- **Password** is filled in if OBS WebSocket authentication is enabled

The dock connects to OBS automatically on load. When connected, the button shows
**Connected to OBS** and is disabled.

## Dock controls

### Toolbar (always visible)

| Control | Description |
| --- | --- |
| **1080p / 720p / 480p** | Output resolution preset (720p is the default) |
| **1x / 5x / 10x** | Silent-speed multiplier passed to Talks Reducer |
| **Settings** | Expandable panel for advanced options and OBS connection |

Speed buttons stay disabled until OBS reports a stopped recording path. The dock
must be open when you stop recording so it can receive the `RecordStateChanged`
event.

When the dock panel is wider than 300 px, controls are centered; on narrow
panels, items wrap to the next line.

### Settings

| Setting | Description |
| --- | --- |
| **Codec** | `h264`, `hevc` (default), `av1`, or `mp3` |
| **Auto close** | When enabled, adds `--open-location --auto-close` |
| **Talks Reducer** | Path to `talks-reducer.exe`; `%LOCALAPPDATA%` and other `%VAR%` forms are expanded on the server |
| **Log** | Recent dock and processing messages |
| **OBS WebSocket / Password** | Connection settings |
| **Connect to OBS** | Reconnect manually; hidden status line appears only while disconnected or connecting |

Settings are stored in the browser `localStorage` under keys prefixed with
`obsDock.`.

## How it works

1. `dock.html` opens a WebSocket to OBS (obs-websocket v5 protocol).
2. On `RecordStateChanged` with `OBS_WEBSOCKET_OUTPUT_STOPPED`, the dock saves
   `outputPath` as the last recording.
3. Clicking **1x**, **5x**, or **10x** sends a JSON `POST` to `/process` on the
   local server.
4. `process-server.js` validates the payload, resolves the executable path, and
   spawns Talks Reducer in the background.

### HTTP payload

```json
{
  "file": "D:\\Videos\\recording.mkv",
  "speed": 5,
  "resolution": "720p",
  "codec": "hevc",
  "autoClose": false,
  "exe": "%LOCALAPPDATA%\\Programs\\talks-reducer\\talks-reducer.exe"
}
```

| Field | Values |
| --- | --- |
| `speed` | `1`, `5`, or `10` |
| `resolution` | `1080p`, `720p`, or `480p` |
| `codec` | `h264`, `hevc`, `av1`, `mp3` |
| `autoClose` | `true` adds `--open-location --auto-close` |
| `exe` | Optional; defaults to `%LOCALAPPDATA%\Programs\talks-reducer\talks-reducer.exe` |

### CLI arguments

The server maps dock choices to Talks Reducer flags:

| Dock choice | CLI flags |
| --- | --- |
| 1080p | `--no-small` |
| 720p | `--small` |
| 480p | `--small --480` |
| Speed button | `--silent-speed <1\|5\|10>` |
| Codec | `--video-codec <codec>` |
| Auto close | `--open-location --auto-close` |

Example command for 720p at 5× with HEVC:

```text
talks-reducer.exe recording.mkv --small --silent-speed 5 --video-codec hevc
```

Output files follow normal Talks Reducer naming (for example `_speedup` /
`_small` suffixes) next to the source recording.

## Server configuration

Environment variables read by `process-server.js`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `OBS_DOCK_PORT` | `17890` | HTTP listen port |
| `OBS_DOCK_EXE` | `%LOCALAPPDATA%\Programs\talks-reducer\talks-reducer.exe` | Fallback executable when the dock does not send `exe` |

Example:

```cmd
set OBS_DOCK_PORT=17891
set OBS_DOCK_EXE=D:\tools\talks-reducer.exe
powershell.exe -NoProfile -ExecutionPolicy Bypass -File obs-talks-reducer.ps1
```

## Run at logon (Task Scheduler)

Use Task Scheduler to start the HTTP server when you sign in, with no visible
console. The task runs PowerShell headlessly via `conhost.exe --headless`.

1. Open **Task Scheduler** (`taskschd.msc`).
2. **Create Task…** (not “Create Basic Task”).
3. **General** tab:
   - Name: `OBS Talks Reducer`
   - Select **Run only when user is logged on**
   - Check **Hidden**
4. **Triggers** tab → **New…** → **At log on** → OK.
5. **Actions** tab → **New…**:
   - Action: **Start a program**
   - Program/script: `conhost.exe`
   - Add arguments:

```text
--headless powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "D:\path\to\scripts\obs-processing-dock\obs-talks-reducer.ps1"
```

   Replace the path with your real folder.
6. **Conditions** tab — uncheck **Start the task only if the computer is on AC power** if you use a laptop on battery.
7. OK and enter your Windows password if prompted.

### `schtasks` one-liner

```cmd
schtasks /Create /TN "OBS Talks Reducer" /SC ONLOGON /RL LIMITED /F /TR "conhost.exe --headless powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"D:\path\to\scripts\obs-processing-dock\obs-talks-reducer.ps1\""
```

### Verify

After logon, the dock should reach `http://127.0.0.1:17890/process`. If jobs
fail with “Processing server error”, check that Node.js is on your user `PATH`
(the scheduled task runs in your account, not as a service).

To remove the task:

```cmd
schtasks /Delete /TN "OBS Talks Reducer" /F
```

## Files

| File | Role |
| --- | --- |
| `dock.html` | OBS browser dock UI and OBS WebSocket client |
| `process-server.js` | Local HTTP server that spawns Talks Reducer |
| `obs-talks-reducer.ps1` | PowerShell launcher for the Node server |

## Troubleshooting

- **Speed buttons stay disabled** — stop a recording while the dock is open; OBS
  must emit `RecordStateChanged` with `outputPath`.
- **Processing server error** — ensure `obs-talks-reducer.ps1` is running (or the
  Task Scheduler job is active) and the port matches (`17890` by default).
- **Executable not found** — check the path in Settings; use `%LOCALAPPDATA%` for
  the standard per-user install location.
- **OBS WebSocket errors** — verify WebSocket is enabled in OBS and the password
  matches if authentication is on.
