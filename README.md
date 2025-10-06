# Talks Reducer
Talks Reducer shortens long-form presentations by removing silent gaps and optionally re-encoding them to smaller files. The
project was renamed from **jumpcutter** to emphasize its focus on conference talks and screencasts.

## Example
- 1h 37m, 571 MB — Original OBS video recording
- 1h 19m, 751 MB — Talks Reducer
- 1h 19m, 171 MB — Talks Reducer `--small`

## Install GUI (Windows, macOS)
Go to the [releases page](https://github.com/popstas/talks-reducer/releases) and download the appropriate artifact:

- **Windows** — `talks-reducer-gui.exe`
- **macOS** — `talks-reducer-gui-macos-universal` (requires macOS 10.13 High Sierra or
  newer). The bundle is built as a universal (`x86_64` + `arm64`) app so it runs
  natively on Apple Silicon without Rosetta.

## Install CLI (Linux, Windows, macOS)
```
pip install talks-reducer
```

**Note:** FFmpeg is now bundled automatically with the package, so you don't need to install it separately. However, if you have FFmpeg already installed on your system, it will be used instead of the bundled version.

The `--small` preset applies a 720p video scale and 128 kbps audio bitrate, making it useful for sharing talks over constrained
connections. Without `--small`, the script aims to preserve original quality while removing silence.

> **Tip:** Running `talks-reducer-gui` without arguments opens the Tkinter interface. Passing regular CLI options (for example,
> `talks-reducer-gui --small input.mp4`) now executes the command-line pipeline, so you can keep a single shortcut for both
> workflows.

When CUDA-capable hardware is available the pipeline leans on GPU encoders to keep export times low, but it still runs great on
CPUs.

### macOS codesigning and notarization

Maintainers with Apple Developer credentials can optionally sign and notarize
the GUI release to avoid Gatekeeper warnings on download:

1. Export or create a keychain profile for `notarytool` (see `man
   notarytool`) and note the profile name.
2. Set the following environment variables before running `scripts/build-gui.sh`:
   - `MACOS_CODESIGN_IDENTITY` — the signing identity, for example
     `Developer ID Application: Example Corp (TEAMID)`.
   - `MACOS_CODESIGN_ENTITLEMENTS` *(optional)* — path to an entitlements plist
     used during codesigning.
   - `MACOS_NOTARIZE_PROFILE` *(optional)* — the keychain profile name to submit
     the archive for notarization. When present, the script zips the `.app`,
     submits it with `notarytool --wait`, and staples the returned ticket.

The codesigning step executes only when the variables are provided, so the build
continues to work unchanged for local development.

### Graphical Interface

- **Simple mode** — the default experience shrinks the window to a large drop
  zone, hides the manual run controls and log, and automatically processes new
  files as soon as you drop them. Uncheck the box to return to the full layout
  with file pickers, the Run button, and detailed logging.
- **Input drop zone** — drag files or folders from your desktop or add them via
  the Explorer/Finder dialog; duplicates are ignored.
- **Small video** — toggles the `--small` preset used by the CLI.
- **Open after convert** — controls whether the exported file is revealed in
  your system file manager as soon as each job finishes.
- **Advanced** — reveals optional controls for the output path, temp folder,
  timing/audio knobs mirrored from the command line, and an appearance picker
  that can force dark or light mode or follow your operating system.

Progress updates stream into the 10-line log panel while the processing runs in
a background thread. Once every queued job succeeds an **Open last output**
button appears so you can jump straight to the exported file in your system
file manager.

The GUI stores your last-used Simple mode, Small video, Open after convert, and
theme preferences in a cross-platform configuration file so they persist across
launches.

## Repository Structure
- `talks_reducer/` — Python package that exposes the CLI and reusable pipeline:
  - `cli.py` parses arguments and dispatches to the pipeline.
  - `pipeline.py` orchestrates FFmpeg, audio processing, and temporary assets.
  - `audio.py` handles audio validation, volume analysis, and phase vocoder processing.
  - `chunks.py` builds timing metadata and FFmpeg expressions for frame selection.
  - `ffmpeg.py` discovers the FFmpeg binary, checks CUDA availability, and assembles command strings.
- `requirements.txt` — Python dependencies for local development.
- `default.nix` — reproducible environment definition for Nix users.
- `CONTRIBUTION.md` — development workflow, formatting expectations, and release checklist.
- `AGENTS.md` — maintainer tips and coding conventions for this repository.

## Highlights
- Builds on gegell's classic jumpcutter workflow with more efficient frame and audio processing
- Generates FFmpeg filter graphs instead of writing temporary frames to disk
- Streams audio transformations in memory to avoid slow intermediate files
- Accepts multiple inputs or directories of recordings in a single run
- Provides progress feedback via `tqdm`
- Automatically detects NVENC availability, so you no longer need to pass `--cuda`

## Processing Pipeline
1. Validate that each input file contains an audio stream using `ffprobe`.
2. Extract audio and calculate loudness to identify silent regions.
3. Stretch the non-silent segments with `audiotsm` to maintain speech clarity.
4. Stitch the processed audio and video together with FFmpeg, using NVENC if the GPU encoders are detected.

## Recent Updates
- **October 2025** — Project renamed to *Talks Reducer* across documentation and scripts.
- **October 2025** — Added `--small` preset with 720p/128 kbps defaults for bandwidth-friendly exports.
- **October 2025** — Removed the `--cuda` flag; CUDA/NVENC support is now auto-detected.

## Changelog
Major and minor releases are tracked in `CHANGELOG.md`. The log is generated from
Conventional Commits that start with either `feat:` or `fix:`. Only tags in the
form `v<major>.<minor>.0` are included so patch releases (for example,
`v1.1.1`) are omitted. Regenerate the file whenever you cut a release:

```bash
python scripts/generate_changelog.py
```

CI will fail if the generated changelog does not match the committed version, so
run the script before opening a pull request that updates release tags.

## Contributing
See `CONTRIBUTION.md` for development setup details and guidance on sharing improvements.

## License
Talks Reducer is released under the MIT License. See `LICENSE` for the full text.
