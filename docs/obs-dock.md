# OBS Processing Dock

A compact OBS Custom Browser Dock that watches for finished recordings and starts
Talks Reducer processing with one click.

## Overview

The dock connects to OBS over obs-websocket, captures the path of the last
stopped recording, and exposes quick controls for resolution, silent-speed, and
codec. Talks Reducer ships a built-in local HTTP server —
`talks-reducer dock-server` — that hosts the dock UI and receives its requests,
spawning a Talks Reducer job with the matching CLI flags.

This keeps OBS and Talks Reducer loosely coupled: OBS only needs the browser
dock and WebSocket server; Talks Reducer runs as a normal process with the same
arguments you would use from a terminal or shortcut.

Because the server is part of the (windowless) Talks Reducer executable, there is
**no separate Node.js runtime and no PowerShell/VBS window-hiding wrapper**. The
scheduled task runs a single process, so stopping it (Task Scheduler → **End**)
closes everything cleanly.

## Requirements

- OBS Studio with **WebSocket server** enabled (`Tools → WebSocket Server Settings`)
- Installed **Talks Reducer** executable (Windows installer or local build)

Default executable path:

```text
%LOCALAPPDATA%\Programs\talks-reducer\talks-reducer.exe
```

## Setup

1. Start the dock server:

```powershell
talks-reducer dock-server
```

It listens on `http://127.0.0.1:17890` by default and serves the dock UI at that
address. Options:

| Flag | Default | Purpose |
| --- | --- | --- |
| `--port` | `17890` (env `OBS_DOCK_PORT`) | HTTP listen port |
| `--host` | `127.0.0.1` | Interface to bind |
| `--exe` | `%LOCALAPPDATA%\...\talks-reducer.exe` (env `OBS_DOCK_EXE`) | Fallback executable when a request omits `exe` |

To start automatically at logon with no window, see
[Run at logon](#run-at-logon).

2. In OBS, add a Custom Browser Dock:

```text
Docks → Custom Browser Docks
```

| Field | Value |
| --- | --- |
| Name | `Processing` (or any label) |
| URL | `http://127.0.0.1:17890/` |

The dock UI is served by `dock-server`, so the URL follows `--host`/`--port`.

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
| **Preset** | Dropdown of saved presets (shown only when the server has presets); a **Custom** entry keeps the manual controls |
| **Process** | Runs the selected preset (enabled once a preset is chosen and a recording path is known) |
| **1080p / 720p / 480p** | Output resolution preset (720p is the default) |
| **1x / 5x / 10x** | Silent-speed multiplier passed to Talks Reducer |
| **Settings** | Expandable panel for advanced options and OBS connection |

When the server exposes presets (the shared `settings.json` populates
`GET /presets`), the dock shows the **Preset** dropdown as the primary control and
**moves** the resolution/speed selects into the **Settings** panel (the codec radios
already live there). Selecting a real preset processes with that preset's full
fidelity; choosing **Custom** moves the resolution/speed controls back into the
toolbar. When the server has no presets the resolution/speed controls stay in the
toolbar exactly as before. The chosen preset persists in `localStorage` under
`obsDock.preset`.

Speed buttons stay disabled until OBS reports a stopped recording path. The dock
must be open when you stop recording so it can receive the `RecordStateChanged`
event.

When the dock panel is wider than 300 px, controls are centered; on narrow
panels, items wrap to the next line.

### Settings

| Setting | Description |
| --- | --- |
| **Resolution / Speed** | Moved here from the toolbar when presets exist; shown in the toolbar otherwise |
| **Codec** | `h264` (default), `hevc`, `av1`, or `mp3` |
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
4. The server validates the payload, resolves the executable path, and spawns
   Talks Reducer in the background.

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
| `preset` | Optional; a saved preset name. When present the dock emits `--preset NAME` and ignores the resolution/speed/codec fields |

The dock also serves `GET /presets`, which returns the saved preset list as JSON
(`[{ "name", "resolution", "silent_speed", "sounded_speed", "silent_threshold",
"video_codec" }, …]`) — the same list authored in the desktop GUI. The dock fetches
this to populate its **Preset** dropdown.

### CLI arguments

The server maps dock choices to Talks Reducer flags:

| Dock choice | CLI flags |
| --- | --- |
| Preset | `--preset NAME` (the CLI fans the preset's resolution/speed/codec; the payload's other fields are ignored) |
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

## Run at logon

### Windows installer (easiest)

The Talks Reducer Windows installer offers two **OBS Processing Dock** checkboxes
(both **off by default**):

- **Add "OBS Dock Server" to the Start menu** — a shortcut that runs
  `talks-reducer dock-server`.
- **Start the OBS Dock Server automatically at logon** — adds the same shortcut
  to your per-user Startup folder.

The installer also closes any running Talks Reducer instances (including the dock
server) before updating, so the executable can be replaced; enable the Startup
checkbox to have it relaunch on the next logon.

### Task Scheduler (manual)

Because `talks-reducer.exe` is windowless, no wrapper is needed — schedule the
executable directly. Stopping the task (**End**) terminates the single process
cleanly.

1. Open **Task Scheduler** (`taskschd.msc`).
2. **Create Task…** (not “Create Basic Task”).
3. **General** tab:
   - Name: `OBS Talks Reducer`
   - Select **Run only when user is logged on** (the dock's `--open-location`
     reveals output in Explorer on your desktop, which requires your session)
4. **Triggers** tab → **New…** → **At log on** → OK.
5. **Actions** tab → **New…**:
   - Action: **Start a program**
   - Program/script: `%LOCALAPPDATA%\Programs\talks-reducer\talks-reducer.exe`
   - Add arguments: `dock-server`
6. **Conditions** tab — uncheck **Start the task only if the computer is on AC power** if you use a laptop on battery.
7. OK and enter your Windows password if prompted.

### `schtasks` one-liner

```cmd
schtasks /Create /TN "OBS Talks Reducer" /SC ONLOGON /RL LIMITED /F /TR "\"%LOCALAPPDATA%\Programs\talks-reducer\talks-reducer.exe\" dock-server"
```

### Verify

After logon, browse to `http://127.0.0.1:17890/` — the dock UI should load. If
jobs fail with “Executable not found”, check the **Talks Reducer** path in
Settings.

To remove the task:

```cmd
schtasks /Delete /TN "OBS Talks Reducer" /F
```

## Troubleshooting

- **Speed buttons stay disabled** — stop a recording while the dock is open; OBS
  must emit `RecordStateChanged` with `outputPath`.
- **Processing server error** — ensure `talks-reducer dock-server` is running (or
  the Task Scheduler job is active) and the port matches (`17890` by default).
- **Executable not found** — check the path in Settings; use `%LOCALAPPDATA%` for
  the standard per-user install location.
- **OBS WebSocket errors** — verify WebSocket is enabled in OBS and the password
  matches if authentication is on.
