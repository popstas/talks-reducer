# Talks Reducer [![Coverage Status](https://coveralls.io/repos/github/popstas/talks-reducer/badge.svg?branch=master)](https://coveralls.io/github/popstas/talks-reducer?branch=master)

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

  > **Troubleshooting:** If launching the bundle (or running `python -m talks_reducer.gui`) prints `macOS 26 (2600) or later required, have instead 16 (1600)!`, make sure you're using a Python build that ships a modern Tk. The stock [python.org 3.13.5 installer](https://www.python.org/downloads/release/python-3135/) includes Tk 8.6 and has been verified to work.

When extracted on Windows the bundled `talks-reducer.exe` behaves like running
`python -m talks_reducer.gui`: double-clicking it launches the GUI
and passing a video file path (for example via *Open with…* or drag-and-drop
onto the executable) automatically queues that recording for processing.

## Install CLI (Linux, Windows, macOS)
```
pip install talks-reducer
```

**Note:** FFmpeg is now bundled automatically with the package, so you don't need to install it separately. You you need, don't know actually.

By default the CLI applies the same tuned encoder settings everywhere: adaptive keyframes, 128 kbps AAC audio, and NVENC fallbacks that previously lived behind `--small`. The `--small` preset now layers on a 720p scale (or 480p with `--480`) for a smaller output, while `--no-optimize` switches to a speed-focused CUDA preset that prioritizes turnaround time over compression efficiency.

Example CLI usage:

```sh
talks-reducer input.mp4  # optimized encoding at the source resolution
talks-reducer --small input.mp4  # optimized encoding plus 720p scaling
talks-reducer --no-optimize input.mp4  # fastest CUDA preset with a _fast suffix when applicable
```

Need to offload work to a remote Talks Reducer server? Pass `--url` with the
server address and the CLI will upload the input, wait for processing to finish,
and download the rendered video. You can also provide `--host` to expand to the
default Talks Reducer port (`http://<host>:9005`):

```sh
talks-reducer --url http://localhost:9005 demo.mp4
talks-reducer --host 192.168.1.42 demo.mp4
```

Remote jobs respect the same timing controls as the local CLI. Provide
`--silent-threshold`, `--sounded-speed`, or `--silent-speed` to tweak how the
server trims and accelerates segments without falling back to local mode.

Need a different compression target? HEVC (`--video-codec hevc`) is now the
default and targets roughly 25% smaller files with tuned presets, adaptive
quantization, and multipass lookahead. Switch to `--video-codec h264` when you
need the quickest NVENC path or `--video-codec av1` to experiment with modern
AV1 output.
Every interface—the CLI, GUI, and browser UI—shares the same encoder choices so
you can pick once and get consistent results everywhere.

Bundled FFmpeg builds prioritise compatibility, but they may lack newer GPU
encoders such as `av1_nvenc`. When your local FFmpeg install exposes additional
hardware options, add `--prefer-global-ffmpeg` so the CLI and GUI prefer the
binary on your `PATH` before falling back to the static package.

Tuned the jumpiness of the new scrolling-friendly preset in commit
`c25a8f7b2dcb2735782bff71b02ee6a30445fa9e` and want to claw some bitrate back?
Pass `--keyframe-interval 15` (or any other positive number of seconds) to space
keyframes further apart when using `--small`, trading seek responsiveness for a
smaller output file. The advanced GUI slider defaults to 30 seconds and lets you
pick anywhere between snappy one-second GOPs and ultra-light 60-second spacing.

Want to see progress as the remote server works? Add `--server-stream` so the
CLI prints live progress bars and log lines while you wait for the download.

### Speech detection

Talks Reducer now relies on its built-in volume thresholding to detect speech. Adjust `--silent_threshold` if you need to fine-tune when segments count as silence. Dropping the optional Silero VAD integration keeps the install lightweight and avoids pulling in PyTorch.

When CUDA-capable hardware is available the pipeline leans on GPU encoders to keep export times low, but it still runs great on
CPUs.

## Simple web server

Prefer a lightweight browser interface? Launch the Gradio-powered simple mode with:

```sh
talks-reducer server
```

The browser UI mirrors the CLI timing controls with sliders for the silent
threshold and playback speeds, so you can tune exports without leaving the
remote workflow.

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
the web server running without a tray process. The tray menu highlights the
running Talks Reducer version and includes an **Open GUI**
item (also triggered by double-clicking the icon) that launches the desktop
Talks Reducer interface alongside an **Open WebUI** entry that opens the Gradio
page in your browser. Close the GUI window to return to the tray without
stopping the server. Launch the tray explicitly whenever you need it—either run
`talks-reducer server-tray` directly or start the GUI with
`python -m talks_reducer.gui --server` to boot the tray-managed server instead
of the desktop window. The GUI now runs standalone and no longer spawns the tray
automatically; the deprecated `--no-tray` flag is ignored for compatibility.
The tray command itself never launches the GUI automatically, so use the menu
item (or relaunch the GUI separately) whenever you want to reopen it. The tray
no longer opens a browser automatically—pass `--open-browser` if you prefer the
web page to launch as soon as the server is ready.

This opens a local web page featuring a drag-and-drop upload zone, **Small video**, **Target 480p**, and **Optimized encoding** checkboxes that mirror the CLI presets, a **Video codec** dropdown that switches between h.265 (25% smaller), h.264 (10% faster), and av1 (no advantages), a **Use global FFmpeg** toggle (disabled automatically when no system binary is detected) to prioritise the system binary when you need encoders the bundled build lacks, a live
progress indicator, and automatic previews of the processed output. The page header and browser tab title include the current
Talks Reducer version so you can confirm which build the server is running. Once the job completes you can inspect the resulting
compression ratio and download the rendered video directly from the page.
The desktop GUI mirrors this behaviour. A **Video codec** picker in the
basic options lets you swap between h.265 (25% smaller), h.264 (10% faster), and av1 (no advantages) without touching the CLI. Open **Advanced** settings to provide a
server URL and click **Discover** to scan your local network for Talks Reducer
instances listening on port `9005`. The button now updates with the discovery
progress, showing the scanned/total host count as `scanned / total`. A new
**Processing mode** toggle lets you decide whether work stays local or uploads
to the configured server—the **Remote** option becomes available as soon as a
URL is supplied. Leave the toggle on **Local** to keep rendering on this
machine even if a server is saved; switch to **Remote** to hand jobs off while
the GUI downloads the finished files automatically. While you're there, enable
**Use global FFmpeg** whenever your PATH provides newer GPU encoders—the toggle disables itself when no system binary is available—and adjust
**Keyframe interval (s)** under **Advanced** to balance scroll smoothness and
output size without touching the CLI.

### Uploading and retrieving a processed video

1. Open the printed `http://localhost:<port>` address (the default port is `9005`).
2. Drag a video onto the **Video file** drop zone or click to browse and select one from disk.
3. **Optimized encoding** stays enabled to apply the tuned codec arguments, and **Small video** starts enabled to apply the 720p/128 kbps preset. Pair it with **Target 480p** to downscale further or clear the checkboxes before the upload finishes to keep the original resolution and bitrate. Use the **Video codec** dropdown to decide between the default h.265 (25% smaller), h.264 (10% faster), and av1 (no advantages) compression profiles, and enable **Use global FFmpeg** (when available) if your system FFmpeg exposes GPU encoders that the bundled build omits before you submit. Disable **Optimized encoding** or pass `--no-optimize` when you want the fastest CUDA-oriented preset.
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
path you provide. Pass `--small` (and optionally `--480`) to mirror the **Small video**/**Target 480p** checkboxes, toggle `--no-optimize` to disable the optimized encoding preset, `--video-codec hevc`, `--video-codec h264`, or `--video-codec av1` to match the codec radio buttons, `--add-codec-suffix` to append the selected codec to the default output filename, `--prefer-global-ffmpeg` to reuse the system FFmpeg before the bundled copy, or `--print-log` to stream the server log after the
download finishes.

## Windows installer packaging

The repository ships an Inno Setup script that wraps the PyInstaller GUI bundle
into a per-user installer named `talks-reducer-<version>-setup.exe`.

1. Build the PyInstaller distribution so that `dist/talks-reducer` contains
   `talks-reducer.exe` and its support files (for example by running
   `scripts\build-gui.sh`).
2. Install [Inno Setup](https://jrsoftware.org/isinfo.php) on a Windows machine.
3. Compile the installer with:
   ```powershell
   iscc /DAPP_VERSION=$(python -c "import talks_reducer.__about__ as a; print(a.__version__)") `
        /DSOURCE_DIR=..\dist\talks-reducer `
        /DAPP_ICON=..\talks_reducer\resources\icons\app.ico `
        scripts\talks-reducer-installer.iss
   ```
   or use the convenience wrapper on Windows runners:
   ```bash
   bash scripts/build-installer.sh
   ```
   Override `/DAPP_ICON=...` or `/DAPP_PUBLISHER=...` (or set `APP_ICON`/`APP_PUBLISHER`
   when calling the wrapper) if you need custom branding.

The installer defaults to `C:\Users\%USERNAME%\AppData\Local\Programs\talks-reducer`,
creates Start Menu and desktop shortcuts, and registers an **Open with Talks
Reducer** shell entry for files and folders so that you can launch the GUI with a
dropped path. Use the Additional Tasks page at install time to skip the optional
shortcuts or shell integration.

## Faster PyInstaller builds

PyInstaller spends most of its time walking imports. To keep GUI builds snappy:

- Create a dedicated virtual environment for packaging the GUI and install only
  the runtime dependencies you need (for example `pip install -r
  requirements.txt -r scripts/requirements-pyinstaller.txt`). Avoid installing
  heavy ML stacks such as Torch or TensorFlow in that environment so PyInstaller
  never attempts to analyze them.
- Use the committed `talks-reducer.spec` file via `./scripts/build-gui.sh`.
  The spec excludes Torch, TensorFlow, TensorBoard, torchvision/torchaudio,
  Pandas, Qt bindings, setuptools' vendored helpers, and other bulky modules
  that previously slowed the analysis stage. Set
  `PYINSTALLER_EXTRA_EXCLUDES=module1,module2` if you need to drop additional
  imports for an experimental build.
- Keep optional imports in the codebase lazy (wrapped in `try/except` or moved
  inside functions) so the analyzer only sees the dependencies required for the
  shipping GUI.

The script keeps incremental build artifacts in `build/` between runs. Pass
`--clean` to `scripts/build-gui.sh` when you want a full rebuild.

## Contributing
See `CONTRIBUTION.md` for development setup details and guidance on sharing improvements.

## License
Talks Reducer is released under the MIT License. See `LICENSE` for the full text.
