# Contributing to Talks Reducer

## Installing Dependencies
Use your preferred virtual environment and install the required Python packages:

```
pip install -r requirements.txt
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

## Publishing a Release
1. Update `pyproject.toml` with the new version number.
2. Run the usual test and formatting commands.
3. Build the distributions: `scripts/build-dist.sh`.
4. Publish to PyPI (or TestPyPI by setting `TWINE_REPOSITORY_URL`): `scripts/publish.sh`.

The scripts install required build tools, clean the `dist/` directory, and upload all artifacts. Ensure you have valid PyPI credentials configured in `~/.pypirc` before running the publish step.

Feel free to open pull requests with enhancements or bug fixes.
