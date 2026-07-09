# Desktop GUI reference

Launch the desktop window with `talks-reducer` (no arguments), the installed shortcut, or
`python -m talks_reducer.gui`.

## Simple and Advanced layouts

The default **Simple mode** shrinks the window to a large drop zone, hides the manual run
controls and the log, and processes new files as soon as you drop them. Uncheck the box to
return to the full layout with file pickers, the Run button, and detailed logging.

Drag files or folders from your desktop onto the drop zone, click it to open the system file
picker, or add them via the Explorer/Finder dialog; duplicates are ignored.

In **Simple mode** a single **Preset** dropdown replaces the individual encoding controls:
pick a saved preset (see [Presets](#presets) below) to fan its resolution, speeds, threshold,
and codec onto the hidden Advanced knobs. The **Open output** checkbox sits to the right of the
dropdown on the same line (it reveals each exported file in your system file manager as soon as
its job finishes), with the **Simple mode** checkbox on the line below. On launch the dropdown
re-selects the preset you used last, or the first preset when none is remembered. When no
presets exist (you deleted them all) the dropdown is hidden entirely and the manual resolution
checkboxes return.

In **Advanced mode** the basic options mirror the CLI presets directly: **Small video**, a
**Video codec** picker that swaps between h.265 (25% smaller), h.264 (10% faster), av1 (no
advantages), and mp3 (audio only), and the timing/audio sliders.

**Advanced** settings reveal the output path, temp folder, the timing/audio knobs mirrored
from the command line, **Keyframe interval (s)** to balance scroll smoothness against output
size, a **Use global FFmpeg** toggle (disabled automatically when no system binary is
detected) that prioritises the system binary when you need encoders the bundled build lacks,
and an appearance picker that can force dark or light mode or follow your operating system.

## Presets

A **preset** is a named bundle of processing settings — any of resolution (1080p/720p/480p),
silent and sounded speed, silent threshold, and video codec — that you author once and apply
read-only everywhere: Simple mode, the Web UI, the OBS dock, and the CLI's `--preset` flag.
Presets are **sparse**: a preset stores only the settings you choose, so applying it changes
just those and leaves everything else as it is. Presets are stored in the shared
`settings.json`, so a preset created on the desktop GUI also appears in the Web UI and dock
served from that machine. On first launch three defaults are seeded: **720p 10x speedup H.264**,
**480p 10x speedup H.265**, and **720p no speedup H.264**. Each surface opens on the preset you
used last (or the first preset when none is remembered).

**Simple mode** exposes only a **Preset** dropdown; selecting a preset applies its fields and
persists the choice (it is re-selected on the next launch).

**Advanced mode** adds a management strip above the encoding knobs with a **Preset** dropdown
and **Save as… / Update / Delete** buttons:

- **Save as…** opens a dialog with a name field plus a checkbox per setting (resolution, silent
  speed, sounded speed, silent threshold, codec) — like the "Create link" dialog. Only the
  checked settings are captured, so you can save, for example, a codec-only preset. Reusing an
  existing name overwrites it.
- **Update** opens the same dialog pre-filled with the selected preset's name and the settings
  it already controls, then overwrites it with the checked live values.
- **Delete** removes the selected preset.

Editing any knob so the values no longer match the selected preset flips the dropdown to
**Custom**. Every save/update/delete refreshes the dropdowns on both the Simple and Advanced
layouts.

## Processing mode and Discover

Open **Advanced** settings to provide a server URL and click **Discover** to scan your local
network for Talks Reducer instances listening on port `9005`. The button updates with the
discovery progress, showing the scanned/total host count as `scanned / total`.

A **Processing mode** toggle decides whether work stays local or uploads to the configured
server — the **Remote** option becomes available as soon as a URL is supplied. Leave the
toggle on **Local** to keep rendering on this machine even if a server is saved; switch to
**Remote** to hand jobs off while the GUI downloads the finished files automatically.

## Cut video

Tick **Cut video** (an **Advanced-only** control — it is hidden in Simple mode) to reveal two
linked start/end range sliders, each paired with an editable time field that accepts manual
`HH:MM:SS.mmm` input (millisecond precision), plus a tall **Convert** button spanning both
rows. After you pick a file the slider range is set from the video duration, and conversion
does not start automatically: adjust the keep range and click **Convert** when you are ready.

The keep range matches the CLI's `--cut-start`/`--cut-end` semantics. The checkbox state and
last start/end values persist across launches; clearing it (or switching to Simple mode)
omits the trim entirely.

## Watch directory

An Advanced setting: choose a folder and Talks Reducer polls it (~2s) for the
most-recently-modified video. The main action button then shows **"Convert `<filename>`"**
for a raw recording, or **"Open last"** when the newest file is already processed (its name
contains `_speedup` or `_small`). The button is available in both Simple and Advanced modes;
the folder chooser lives under Advanced. The choice persists across launches.

## Progress feedback

Whether you render locally or stream from a remote server, the desktop progress bar advances
through stable ranges as the job moves between stages — upload (0–5%), audio extraction
(5–20%), audio processing (20–35%), and final encoding (35–100%) — so it keeps moving after
audio processing instead of stalling until the encode finishes. The bar only ever moves
forward within a file, so a GPU→CPU encoder fallback never snaps it backward.

When a remote job finishes encoding, the GUI shows a refreshing **Waiting for download…**
status during the short gap before the file transfer begins, so the window never sits
silently at 100% while the server prepares the result. The download bar advances to 100%
exactly once instead of cycling through 100% several times. While a remote upload or download
is in flight the status also shows the live transfer rate next to the percentage, e.g.
`Uploading: 55%, 5.5 MB/s`.

Progress updates stream into the 10-line log panel while the processing runs in a background
thread. Once every queued job succeeds an **Open last output** button appears so you can jump
straight to the exported file in your system file manager.

### Taskbar progress and completion bell

On **Windows** the taskbar button mirrors the in-window progress bar while a conversion runs,
so you can minimize the app and still watch the job advance. When the run ends the taskbar
keeps showing the result — full green on success, red on failure — until you focus the window
again; pressing **Stop** clears it right away. Other platforms have no equivalent indicator
and simply skip it.

On every platform the GUI also **rings the system bell** when a run finishes or fails, so you
hear the result without watching the window. It stays silent when the window is already
focused — you can see the result — and when you stop a run yourself.

## Window position

The GUI remembers **where you last placed the window**. On close it saves the window's screen
position and reopens there on the next launch; the width/height still follow the Simple/Full
layout as before. A position saved on a monitor that is no longer connected is ignored so the
window never reopens off-screen — the operating system places it instead.

## Seeded launches and shortcuts

On Windows you can create a desktop shortcut to `talks-reducer.exe` with preset flags (for
example `talks-reducer.exe --small --silent-speed 5`) and drop a video file onto it in
Explorer. Instead of doing nothing, the GUI opens pre-seeded with the dropped file and the
shortcut's flags applied to the matching controls (Small video, silent speed, codec,
output/temp paths, and — via `--host` — the remote server URL with Remote mode enabled), then
processing starts automatically. Flag names accept either hyphens or underscores
(`--silent-speed` and `--silent_speed` both work). Launching such a shortcut *without* a file
(for example by double-clicking it) simply opens the GUI with those settings applied so you
can drop files in. Only the flags you pass are applied; your stored preferences are preserved
for everything else.

Two GUI-only flags control what happens *after* a seeded conversion finishes, without adding
any checkbox to the window: `--open-location` reveals each exported file in the system file
manager (regardless of the saved "Open after convert" setting), and `--auto-close` closes the
window once every queued file finishes successfully (it stays open on error so you can read
the log). For example, a shortcut carrying `--small --open-location --auto-close` converts a
dropped recording, shows the result in Explorer, and closes itself.

### Create lnk

On Windows, the full (non-Simple) layout shows a **Create lnk** button next to the
**Advanced** button (hidden on other platforms). It opens a small dialog where you tick the
presets you want — **Small**, **720** or **480** (these imply Small), **Silent speed**,
**Sounded speed**, **Silent threshold**, **Codec**, and **Auto close and open file location**
(adds `--auto-close --open-location` so the shortcut closes the GUI and reveals the exported
file when each convert finishes) — each pre-checked to match your current GUI state. A live
preview shows the resulting command line as you toggle options, and clicking **Create** writes
a `.lnk` shortcut to your Desktop seeded with those CLI flags. The shortcut doubles as a
drop-target: drag a video onto it to launch the GUI with the chosen presets and auto-convert
the file.

## Check updates

On macOS, the **Advanced** panel adds a **Check updates** button that queries the latest
GitHub release and compares it against the running version. When a newer release is found it
reports the available version with the command to apply it, `brew upgrade --cask
talks-reducer`, alongside a link to the Releases page. macOS builds are unsigned and
distributed through the
[`popstas/homebrew-talks-reducer`](https://github.com/popstas/homebrew-talks-reducer) tap, so
the button never downloads or installs anything automatically — you upgrade with Homebrew.

The Windows build keeps its own **Check updates** button (next to the run controls) that
downloads and launches the installer, then closes the app automatically so the installer can
replace the running executable.

Other platforms show neither button.

## Run as server in tray

The **Advanced** panel has a persisted **Run as server in tray** checkbox (default off) that
switches into the tray-managed experience with one click — handy on macOS, where
double-clicking the `.app` previously only opened the plain window. Ticking it relaunches the
app into `server-tray --with-gui` mode (a detached process) and closes the current window; the
menu-bar/system-tray icon appears and the window returns as a managed child. Unticking it from
that managed window relaunches the plain desktop GUI and stops the parent tray (and its
server). The preference is stored with the other GUI toggles, so the next cold start boots
straight into server-tray mode when it is left enabled.

Because pystray's tray icon and Tkinter's event loop both require the process main thread on
macOS and cannot share one process, the tray always runs as the parent and the GUI as a
child — the toggle simply relaunches the app in whichever arrangement you asked for. The
default is off, so existing standalone launches are unchanged.

The window launched this way gains a **Server:** label and a **Connected clients** panel; see
[server.md](server.md#the-server-managed-gui).
