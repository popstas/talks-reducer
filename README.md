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

- **Windows** — `talks-reducer-windows.zip`
- **macOS** — `talks-reducer.app.zip` (but it doesn't work for me)

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

When CUDA-capable hardware is available the pipeline leans on GPU encoders to keep export times low, but it still runs great on
CPUs.

## Contributing
See `CONTRIBUTION.md` for development setup details and guidance on sharing improvements.

## License
Talks Reducer is released under the MIT License. See `LICENSE` for the full text.
