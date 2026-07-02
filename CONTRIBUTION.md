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

Releases are issued by CI: pushing a version tag (`v*`) runs the full pipeline — tests, PyInstaller bundles, the Inno installer, the **GitHub release**, and the **PyPI upload** (see the next section). The recommended flow is therefore:

1. Bump the version with `bump-my-version bump {patch|minor|major}` (updates `talks_reducer/__about__.py`, `version.txt`, and `.bumpversion.toml`).
2. Commit the bump (`Bump version: <old> → <new>`).
3. Tag it `v<new-version>` and push both the commit and the tag: `git push origin master --tags`.

CI takes over from the tag — no manual build or upload step is needed. (The committed `CHANGELOG.md` is optional; CI generates the release notes with git-cliff at build time. Regenerate it with `git-cliff -o CHANGELOG.md` only if you want the in-repo changelog refreshed.)

**Manual alternative.** If you need to build and publish by hand, run `python scripts/deploy.py` (optionally with `patch`, `minor`, or `major` to bump the version). The deploy helper runs the test suite, rebuilds the distribution artifacts, validates them with `twine check`, and uploads the release. Provide `TWINE_REPOSITORY_URL` to target TestPyPI instead of PyPI, and ensure you have valid credentials configured in `~/.pypirc` before running the publish step. Install the dev dependencies first: `pip install build twine bump-my-version pytest git-cliff`.

### PyPI publishing (automated by CI)

Pushing a version tag (`v*`) triggers the CI workflow, which builds the PyInstaller bundles and Inno installer, generates release notes with git-cliff, creates the **GitHub release** with those binaries attached, **and publishes the Python package to PyPI**. The `pypi-publish` job runs `python -m build`, `twine check`, and `twine upload` automatically (authenticating with the `PYPI_API_TOKEN` repository secret), so `pip install -U talks-reducer` picks up the new version once the tag build finishes — no manual upload step is needed.

Verify the upload at `https://pypi.org/project/talks-reducer/<version>/` — note the main `/json` endpoint is CDN-cached for a few minutes, so check the version-specific page or the simple index to confirm.

If you ever need to publish by hand (e.g. the `PYPI_API_TOKEN` secret is missing or the job fails), run `python scripts/deploy.py` — or `python -m build && twine check dist/* && twine upload dist/talks_reducer-<version>*` — with valid credentials in `~/.pypirc`.

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
