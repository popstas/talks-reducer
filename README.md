# Talks Reducer
Talks Reducer shortens long-form presentations by removing silent gaps and optionally re-encoding them to smaller files. The
project was renamed from **jumpcutter** to emphasize its focus on conference talks and lectures.

When CUDA-capable hardware is available the pipeline leans on GPU encoders to keep export times low, but it still runs great on
CPUs.

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

## Example
- 1h 37m, 571 MB — Original OBS video
- 1h 19m, 751 MB — Talks Reducer
- 1h 19m, 171 MB — Talks Reducer `--small`

The `--small` preset applies a 720p video scale and 128 kbps audio bitrate, making it useful for sharing talks over constrained
connections. Without `--small`, the script aims to preserve original quality while removing silence.

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
- **October 2025** — Improved `--small` encoder arguments to balance size and clarity.
- **October 2025** — CLI argument parsing fixes to prevent crashes on invalid combinations.
- **October 2025** — Added example output comparison to the README.

## Quick Start
1. Install FFmpeg and ensure it is on your `PATH`
2. Install Talks Reducer with `pip install .` (this exposes the `talks-reducer` command)
3. Inspect available options with `talks-reducer --help`
4. Process a recording using `talks-reducer -i INPUT_FILE`

## Requirements
- Python 3 with `numpy`, `scipy`, `audiotsm`, and `tqdm`
- FFmpeg with optional NVIDIA NVENC support for CUDA acceleration

## Contributing
See `CONTRIBUTION.md` for development setup details and guidance on sharing improvements.

## License
Talks Reducer is released under the MIT License. See `LICENSE` for the full text.
