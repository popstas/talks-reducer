# Packaging and build reference

See [CONTRIBUTION.md](../CONTRIBUTION.md) for the general development workflow.

## Windows installer packaging

The repository ships an Inno Setup script that wraps the PyInstaller GUI bundle into a
per-user installer named `talks-reducer-<version>-setup.exe`.

1. Build the PyInstaller distribution so that `dist/talks-reducer` contains
   `talks-reducer.exe` and its support files (for example by running `scripts\build-gui.sh`).
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

   Override `/DAPP_ICON=...` or `/DAPP_PUBLISHER=...` (or set `APP_ICON`/`APP_PUBLISHER` when
   calling the wrapper) if you need custom branding.

The installer defaults to `C:\Users\%USERNAME%\AppData\Local\Programs\talks-reducer`, creates
Start Menu and desktop shortcuts, and registers an **Open with Talks Reducer** shell entry for
files and folders so that you can launch the GUI with a dropped path. Use the Additional Tasks
page at install time to skip the optional shortcuts or shell integration.

## Faster PyInstaller builds

PyInstaller spends most of its time walking imports. To keep GUI builds snappy:

- Create a dedicated virtual environment for packaging the GUI and install only the runtime
  dependencies you need (for example `pip install -r requirements.txt -r
  scripts/requirements-pyinstaller.txt`). Avoid installing heavy ML stacks such as Torch or
  TensorFlow in that environment so PyInstaller never attempts to analyze them.
- Use the committed `talks-reducer.spec` file via `./scripts/build-gui.sh`. The spec excludes
  Torch, TensorFlow, TensorBoard, torchvision/torchaudio, Pandas (plus its pytz/tzdata timezone
  data, pulled in transitively by Gradio but unused by the server), Qt bindings, setuptools'
  vendored helpers, and other bulky modules that previously slowed the analysis stage. Set
  `PYINSTALLER_EXTRA_EXCLUDES=module1,module2` if you need to drop additional imports for an
  experimental build.
- SciPy is intentionally *not* a runtime dependency: WAV I/O goes through the tiny
  `talks_reducer/wav_io.py` helper instead of `scipy.io.wavfile`, which keeps ~75 MB of unused
  SciPy out of the bundle. SciPy is installed only in the CI test job, where
  `tests/test_wav_io.py` asserts the helper stays byte-compatible with `scipy.io.wavfile`.
- Keep optional imports in the codebase lazy (wrapped in `try/except` or moved inside
  functions) so the analyzer only sees the dependencies required for the shipping GUI.

The script keeps incremental build artifacts in `build/` between runs. Pass `--clean` to
`scripts/build-gui.sh` when you want a full rebuild.
