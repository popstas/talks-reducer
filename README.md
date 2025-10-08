# Talks Reducer
Talks Reducer shortens long-form presentations by removing silent gaps and optionally re-encoding them to smaller files. The
project was renamed from **jumpcutter** to emphasize its focus on conference talks and screencasts.

![Main demo](docs/assets/screencast-main.gif)

## Example
- 1h 37m, 571 MB — Original OBS video recording
- 1h 19m, 751 MB — Talks Reducer
- 1h 19m, 171 MB — Talks Reducer `--small`

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## Install GUI (Windows, macOS)
Go to the [releases page](https://github.com/popstas/talks-reducer/releases) and download the appropriate artifact:

- **Windows** — `talks-reducer-windows-0.4.0.zip`
- **macOS** — `talks-reducer.app.zip`

  > **Troubleshooting:** If launching the bundle (or running `python talks_reducer/gui.py`) prints `macOS 26 (2600) or later required, have instead 16 (1600)!`, make sure you're using a Python build that ships a modern Tk. The stock [python.org 3.13.5 installer](https://www.python.org/downloads/release/python-3135/) includes Tk 8.6 and has been verified to work.

When extracted on Windows the bundled `talks-reducer.exe` behaves like the
`python talks_reducer/gui.py` entry point: double-clicking it launches the GUI
and passing a video file path (for example via *Open with…* or drag-and-drop
onto the executable) automatically queues that recording for processing.

## Install CLI (Linux, Windows, macOS)
```
pip install talks-reducer
```

**Note:** FFmpeg is now bundled automatically with the package, so you don't need to install it separately. You you need, don't know actually.

The `--small` preset applies a 720p video scale and 128 kbps audio bitrate, making it useful for sharing talks over constrained
connections. Without `--small`, the script aims to preserve original quality while removing silence.

Example CLI usage:

```sh
talks-reducer --small input.mp4
```

Need to offload work to a remote Talks Reducer server? Pass `--url` with the
server address and the CLI will upload the input, wait for processing to finish,
and download the rendered video:

```sh
talks-reducer --url http://localhost:9005 demo.mp4
```

### Speech detection

Talks Reducer now relies on its built-in volume thresholding to detect speech. Adjust `--silent_threshold` if you need to fine-tune when segments count as silence. Dropping the optional Silero VAD integration keeps the install lightweight and avoids pulling in PyTorch.

When CUDA-capable hardware is available the pipeline leans on GPU encoders to keep export times low, but it still runs great on
CPUs.

## Simple web server

Prefer a lightweight browser interface? Launch the Gradio-powered simple mode with:

```sh
talks-reducer server
```

Want the server to live in your system tray instead of a terminal window? Use:

```sh
talks-reducer server-tray
```

Bundled Windows builds include the same behaviour: run
`talks-reducer.exe --server` to launch the tray-managed server directly from the
desktop shortcut without opening the GUI first.

Pass `--debug` to print verbose logs about the tray icon lifecycle, and
`--tray-mode pystray-detached` to try pystray's alternate detached runner. If
the icon backend refuses to appear, fall back to `--tray-mode headless` to keep
the web server running without a tray process. The tray menu includes an **Open GUI**
item (also triggered by double-clicking the icon) that launches the desktop
Talks Reducer interface alongside an **Open WebUI** entry that opens the Gradio
page in your browser. Close the GUI window to return to the tray without
stopping the server. Launching the GUI directly now starts the tray-backed
server in the background before the window appears so the icon stays available
after you close it; add `--no-tray` when running `python -m talks_reducer.gui`
if you prefer to skip the background server entirely. The tray command itself
never launches the GUI automatically, so use the menu item (or rerun the GUI
with `--no-tray`) whenever you want to reopen it. The tray no longer opens a
browser automatically—pass `--open-browser` if you prefer the web page to
launch as soon as the server is ready.

This opens a local web page featuring a drag-and-drop upload zone, a **Small video** checkbox that mirrors the CLI preset, a live
progress indicator, and automatic previews of the processed output. Once the job completes you can inspect the resulting compression
ratio and download the rendered video directly from the page.

The desktop GUI mirrors this behaviour. Open **Advanced** settings to provide a
server URL and click **Discover** to scan your local network for Talks Reducer
instances listening on port `9005`. Leaving the field blank keeps processing
local; selecting a discovered server delegates rendering to that machine while
the GUI downloads the finished files automatically.

### Uploading and retrieving a processed video

1. Open the printed `http://localhost:<port>` address (the default port is `9005`).
2. Drag a video onto the **Video file** drop zone or click to browse and select one from disk.
3. **Small video** starts enabled to apply the 720p/128 kbps preset. Clear the box before the upload finishes if you want to keep the original resolution and bitrate.
4. Wait for the progress bar and log to report completion—the interface queues work automatically after the file arrives.
5. Watch the processed preview in the **Processed video** player and click **Download processed file** to save the result locally.

Need to change where the server listens? Run `talks-reducer server --host 0.0.0.0 --port 7860` (or any other port) to bind to a
different address.

### Automating uploads from the command line

Prefer to script uploads instead of using the browser UI? Start the server and use the bundled helper to submit a job and save
the processed video locally:

```sh
python -m talks_reducer.service_client --server http://127.0.0.1:9005/ --input demo.mp4 --output output/demo_processed.mp4
```

The helper wraps the Gradio API exposed by `server.py`, waits for processing to complete, then copies the rendered file to the
path you provide. Pass `--small` to mirror the **Small video** checkbox or `--print-log` to stream the server log after the
download finishes.

## Contributing
See `CONTRIBUTION.md` for development setup details and guidance on sharing improvements.

## License
Talks Reducer is released under the MIT License. See `LICENSE` for the full text.
