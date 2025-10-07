# Contributing to Talks Reducer

## Installing Dependencies
Use your preferred virtual environment and install the required Python packages:

```
pip install -r requirements.txt
```

For reproducible GUI bundles, also install the pinned PyInstaller toolchain:

```
pip install -r scripts/requirements-pyinstaller.txt
```

Ensure FFmpeg is installed and available on your command line. Visit [ffmpeg.org](https://ffmpeg.org) for platform-specific guidance.

## Running the Tool from Source
Inspect the CLI options:

```
talks-reducer --help
```

Run with default settings:

```
talks-reducer /path/to/video
```

## Service Layer
The CLI is a thin wrapper over the reusable pipeline defined in
`talks_reducer.pipeline`. Construct `ProcessingOptions` and call
`speed_up_video` directly when writing integration tests or GUI front-ends.
Progress can be forwarded to custom UIs by implementing the
`ProgressReporter` protocol in `talks_reducer.progress`.

The `tests/test_pipeline_service.py` fixture demonstrates how to mock FFmpeg
interactions so the pipeline can be exercised without launching external
processes.

## Publishing a Release
1. Update `pyproject.toml` with the new version number or pass a bump rule to the deploy script.
2. Regenerate the changelog so it reflects the upcoming tag: `python scripts/generate_changelog.py`.
3. Ensure development dependencies are installed: `pip install build twine bumpversion pytest`.
4. Run `python scripts/deploy.py` (optionally with `patch`, `minor`, or `major` to bump the version).

The deploy helper automatically runs the test suite, rebuilds the distribution artifacts, validates them with `twine check`, and uploads the release. Provide `TWINE_REPOSITORY_URL` to target TestPyPI instead of PyPI. Ensure you have valid credentials configured in `~/.pypirc` before running the publish step.

Feel free to open pull requests with enhancements or bug fixes.

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
