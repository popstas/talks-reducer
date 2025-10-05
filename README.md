# Talks Reducer
Focus of this product: reduce talks recordings by time and by size without data loss. It use cuda when possible.

Talks Reducer trims the quiet gaps in long-form presentations while keeping every word intelligible. When CUDA-capable hardware is available the pipeline leans on GPU encoders to keep export times low, but it still runs great on CPUs.

## Highlights
- Builds on gegell's classic jumpcutter workflow with more efficient frame and audio processing
- Generates ffmpeg filter graphs instead of writing temporary frames to disk
- Streams audio transformations in memory to avoid slow intermediate files
- Accepts multiple inputs or directories of recordings in a single run
- Provides progress feedback via `tqdm`

## Quick Start
1. Install FFmpeg and ensure it is on your `PATH`
2. Install Python dependencies with `pip install -r requirements.txt`
3. Inspect available options with `python talks_reducer.py -h`
4. Process a recording using `python talks_reducer.py -i INPUT_FILE`

## Requirements
- Python 3 with `numpy`, `scipy`, `audiotsm`, and `tqdm`
- FFmpeg with optional NVIDIA NVENC support for CUDA acceleration

## Contributing
See `CONTRIBUTION.md` for development setup details and guidance on sharing improvements.

## License
Talks Reducer is released under the MIT License. See `LICENSE` for the full text.
