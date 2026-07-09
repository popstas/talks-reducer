# Web server and tray reference

## Starting the server

```sh
talks-reducer server        # browser interface, stays in the terminal
talks-reducer server-tray   # the same server with a system tray icon
```

Bundled Windows builds include the same behaviour: run `talks-reducer.exe --server` to launch
the tray-managed server directly from the desktop shortcut without opening the GUI first.

### Options

Both commands accept:

- `--host` — address to bind (default `0.0.0.0`).
- `--port` — port number (default `9005`).
- `--concurrency N` — how many jobs the queue processes at once (default `1`). Raising it
  lets several clients process simultaneously; each concurrent job runs its own FFmpeg, so
  keep `N` small. This only affects concurrent *processing* — file uploads and downloads are
  served outside the queue, so it does not speed up a single client's transfer.
- `--open-browser` / `--no-browser` — whether to open the web page once the server is ready.
  The tray does not open a browser by default; pass `--open-browser` if you prefer it to.
- `--share` — create a temporary public Gradio link.

```sh
talks-reducer server --host 0.0.0.0 --port 7860
```

`server-tray` additionally accepts `--tray-mode`, `--with-gui`, and `--debug` (see below).

## The browser UI

The page features a drag-and-drop upload zone with **Small video**, **Target 480p**, and
**Optimized encoding** checkboxes that mirror the CLI presets; a **Video codec** dropdown that
switches between h.264 (10% faster), h.265 (25% smaller), av1 (no advantages), and mp3 (audio
only); a **Use global FFmpeg** toggle (disabled automatically when no system binary is
detected) to prioritise the system binary when you need encoders the bundled build lacks; and
a **Cut video** checkbox plus always-visible **Cut start**/**Cut end** number inputs (in
seconds) — the keep range is applied only when the checkbox is ticked, and you can scrub with
the embedded player to find the timestamps.

A **Preset** dropdown near the top lists the saved presets from the shared `settings.json`
(the same list the desktop GUI authors). Selecting a preset sets the resolution, speedup,
codec, and threshold controls to its values; the dropdown is hidden when no presets are
defined. See [gui.md](gui.md#presets) for how presets are created.

Sliders for the silent threshold and playback speeds mirror the CLI timing controls, so you
can tune exports without leaving the remote workflow.

A live progress indicator and automatic previews of the processed output round out the page.
The page header and browser tab title include the current Talks Reducer version so you can
confirm which build the server is running. Once the job completes you can inspect the
resulting compression ratio and download the rendered video directly from the page.

### Uploading and retrieving a processed video

1. Open the printed `http://localhost:<port>` address (the default port is `9005`).
2. Drag a video onto the **Video file** drop zone or click to browse and select one from
   disk.
3. **Optimized encoding** stays enabled to apply the tuned codec arguments, and **Small
   video** starts enabled to apply the 720p/128 kbps preset. Pair it with **Target 480p** to
   downscale further or clear the checkboxes before the upload finishes to keep the original
   resolution and bitrate. Use the **Video codec** dropdown to decide between the default
   h.264 (10% faster), h.265 (25% smaller), and av1 (no advantages) compression profiles, or
   pick **mp3 (audio only)** to export an audio-only `.mp3` instead of a video, and enable
   **Use global FFmpeg** (when available) if your system FFmpeg exposes GPU encoders that the
   bundled build omits before you submit. Disable **Optimized encoding** or pass
   `--no-optimize` when you want the fastest CUDA-oriented preset.
4. Wait for the progress bar and log to report completion — the interface queues work
   automatically after the file arrives. While the file uploads the server console streams
   `Receiving upload: …%` lines as the bytes arrive, then logs an `Upload received:` line with
   the filename and size, then streams the `Extracting audio:`, `Audio processing:`, and
   `Generating final:` stages back to the browser so you can watch real progress for each
   phase. As the finished file is sent back to the client the console streams matching
   `Sending download <filename>: …%` lines.
5. Watch the processed preview in the **Processed video** player and click **Download
   processed file** to save the result locally. When you choose the **mp3 (audio only)** codec
   the result has no video stream, so the preview stays empty and you simply use **Download
   processed file** to grab the `.mp3`.

### Installing the page as an app (PWA)

The web UI is an installable Progressive Web App: open it in a Chromium-based browser and use
**Install app** to add a standalone Talks Reducer window with the app's own icon (served from
`/manifest.json` and `/talks-reducer-icon.png`). Browsers only offer installation over
`https://` or `http://localhost`, so reach a LAN server through a TLS proxy if the install
prompt does not appear.

## Tray mode

Pass `--debug` to print verbose logs about the tray icon lifecycle, and `--tray-mode
pystray-detached` to try pystray's alternate detached runner. If the icon backend refuses to
appear, fall back to `--tray-mode headless` to keep the web server running without a tray
process.

On macOS the tray icon must run on the process' main thread because pystray's AppKit backend
drives the Cocoa run loop there. The default `--tray-mode pystray` already does this, so
launch the tray with `talks-reducer server-tray` (the bundled pip app's `--server` entry
point) and the icon appears in the menu bar as a monochrome template image that automatically
follows the light or dark menu bar. `--tray-mode pystray-detached` cannot render on macOS — it
runs the icon on a worker thread — so the launcher automatically downgrades it to the blocking
`pystray` runner and logs a warning. When you only need the web server (for example over SSH
or in a headless build), pass `--tray-mode headless` to skip the icon entirely and reach the
server at its printed URL.

The tray menu highlights the running Talks Reducer version and includes an **Open GUI** item
(also triggered by double-clicking the icon) that launches the desktop Talks Reducer interface
alongside an **Open WebUI** entry that opens the Gradio page in your browser. Close the GUI
window to return to the tray without stopping the server.

Launch the tray explicitly whenever you need it — either run `talks-reducer server-tray`
directly or start the GUI with `python -m talks_reducer.gui --server` to boot the tray-managed
server instead of the desktop window. The GUI runs standalone and no longer spawns the tray
automatically; the deprecated `--no-tray` flag is ignored for compatibility. The tray command
itself never launches the GUI automatically, so use the menu item (or relaunch the GUI
separately) whenever you want to reopen it.

### Starting the server and the GUI together

Want both the server and the desktop GUI to appear together (handy for the macOS pip app)? Add
`--with-gui` to start the GUI window alongside the tray-managed server in one launch:

```sh
talks-reducer server-tray --with-gui
```

The same flag works through the GUI launcher — `python -m talks_reducer.gui --server
--with-gui` boots the tray-managed server and opens the desktop window together. The GUI runs
in its own process and is shut down cleanly when the server stops.

You can also switch modes without the terminal: the desktop GUI's **Advanced** panel has a
persisted **Run as server in tray** checkbox. See [gui.md](gui.md#run-as-server-in-tray).

## The server-managed GUI

When the tray launches the desktop window, it passes `--server-managed` and
`--server-url <local url>` so the GUI knows it is running alongside a managed server. In this
mode the window gains two extra pieces of server-operator feedback:

- A **Server:** label next to the **Processing mode** controls shows the LAN-reachable address
  (for example `Server: http://192.168.1.42:9005`) so you can read off the URL other machines
  on your network should open. The label is hidden when the GUI runs standalone.
- A **Connected clients** panel lists recent client activity — each line shows
  `HH:MM:SS  <client IP>  <action>` for the uploads, downloads, and processing jobs other
  users send to the server. The GUI polls the server's read-only `GET /activity` endpoint
  about every 5 seconds and tolerates the server being temporarily unreachable without
  crashing or spamming the log.

These controls only appear in server-managed mode; the standalone GUI
(`python -m talks_reducer.gui` without `--server-managed`) is unchanged.

## The `GET /activity` endpoint

The read-only `GET /activity` endpoint is mounted on **every** server launch (not only when a
managed GUI is attached). It returns
`{"server": {"identity", "url"}, "entries": [{"timestamp", "client_ip", "action"}]}`, where
`action` is `upload`, `download`, or `process` and `url` is the LAN-reachable address other
machines should open. The recorder keeps the last 100 requests in memory (process-local, not
persisted).

> **Caveat:** the endpoint is unauthenticated, so anyone who can reach the server port can read
> which client IPs have used it.

## Automating uploads from the command line

Prefer to script uploads instead of using the browser UI? Start the server and use the bundled
helper to submit a job and save the processed video locally:

```sh
python -m talks_reducer.service_client --server http://127.0.0.1:9005/ --input demo.mp4 --output output/demo_processed.mp4
```

The helper wraps the Gradio API exposed by `server.py`, waits for processing to complete, then
copies the rendered file to the path you provide. Pass `--small` (and optionally `--480`) to
mirror the **Small video**/**Target 480p** checkboxes, toggle `--no-optimize` to disable the
optimized encoding preset, `--video-codec hevc`, `--video-codec h264`, `--video-codec av1`, or
`--video-codec mp3` (audio-only `.mp3` output) to match the codec radio buttons,
`--add-codec-suffix` to append the selected codec to the default output filename,
`--prefer-global-ffmpeg` to reuse the system FFmpeg before the bundled copy, or `--print-log`
to stream the server log after the download finishes.

The plain CLI can also submit jobs to a server with `--url`/`--host`; see
[cli.md](cli.md#remote-processing).
