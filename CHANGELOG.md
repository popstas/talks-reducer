# Changelog


## v0.10.4 - 2026-04-22

### Bug Fixes

- server: Wire add_codec_suffix checkbox in UI

## v0.10.3 - 2026-04-22

### Features

- gui: Widen simple mode window to 470px

## v0.10.2 - 2026-04-22

### Features

- gui: Wire up progress bar during FFmpeg encoding
- ffmpeg: Show 10% progress milestones
- pipeline: Log fallback FFmpeg command
- ffmpeg: Abort stuck FFmpeg processes after 10 minutes of no output

### Bug Fixes

- build: Include fsspec in PyInstaller bundle
- pipeline: Isolate temp workspace per job
- Change gui status to "Processing" in fallback mode
- ffmpeg: Log progress when total frames unknown

### Documentation

- Update changelog

### Miscellaneous

- build: Bump version to 0.10.2

## v0.10.1 - 2026-02-21

### Bug Fixes

- server: Remove spurious final progress call

### Miscellaneous

- build: Bump version to 0.10.1

## v0.10.0 - 2026-02-21

### Features

- gui: Add video codec dropdown in simple mode
- gui: Add speedup preset dropdown in simple mode
- Show absolute duration and file size in result output
- Add Windows update checker to GUI

### Bug Fixes

- gui: Improve combobox appearance in dark theme
- server: Stop progress bar flashing
- Extend server startup timeout and correct video codec dropdown choices
- gui: Higher contrast selected preset button
- GUI stop button doesn't kill ffmpeg
- Progress bug
- Update tests to match recent code changes

### Miscellaneous

- build: Bump version to 0.10.0

### Refactor

- gui: Improve simple mode layout
- Centralize progress callbacks (#134)
- Share server argument parser (#133)
- Split gui/app.py

### Styling

- gui: Wrap long run_defaults_command signature

## v0.9.5 - 2025-11-14

### Bug Fixes

- Convert video without audio

## v0.9.4 - 2025-11-13

### Bug Fixes

- Change default silent threshold from 0.05 to 0.01

## v0.9.3 - 2025-11-08

### Bug Fixes

- Change default codec from h265 to h264

## v0.9.1 - 2025-11-01

### Features

- Add --no-optimize mode, fastest and largest size (default optimize) (#129)
- Add silence speed presets to GUI (#130)

### Bug Fixes

- Don't upscale video when original size smaller than defined
- Handle videos with multiple streams and correct fps filter syntax

## v0.9.0 - 2025-10-20

### Features

- Add codec suffix option (#128)
- Smooth gui progress and 480 suffix (#126)
- Add h265 and av1 codecs selection, -25% size (#124)
- Add keyframe interval tuning controls (#123)
- Add 480p small preset option (#121)

### Bug Fixes

- Add _480 suffix to filename

### Documentation

- Add PR naming for Codex

### Miscellaneous

- Rename macos zip artifact in CI (#125)

## v0.8.6 - 2025-10-17

### Bug Fixes

- Improve CUDA capability detection (#117)
- Larger log textarea
- Enable Windows HiDPI awareness for GUI (removes blur on 100+% monitor scale) (#116)
- Switch to static-ffmpeg for bundled ffprobe (#115)
- Remove freezes on rewind small video (#114)

## v0.8.4 - 2025-10-15

### Features

- Add Windows installer (#112)

## v0.8.0 - 2025-10-11

### Testing

- Expand CLI coverage (#93)
- Expand CLI coverage (#89)

## v0.7.2 - 2025-10-10

### Bug Fixes

- Fast show tray icon in --server mode (#76)

## v0.7.0 - 2025-10-10

### Bug Fixes

- Web UI now display progress (#71)
- Working Stop command in remote mode (#69)
- Show conversion time, better logger output (#68)
- Better remote server ping and switch to local mode

### Refactor

- Split gui.py, step 3: extract layout, discovery, remote, create package (#75)
- Split gui.py, step 2: GUI remote utilities (#73)
- Split gui.py, step 1: GUI settings management and theme utilities (#72)

## v0.6.1 - 2025-10-09

### Bug Fixes

- Better options styles (#63)

## v0.6.0 - 2025-10-09

### Features

- Add --host to cli for quick point to remote server (#55)
- Seamless streaming on remote processing (#53)

### Bug Fixes

- Rearrange options, add sliders, changes in full mode, advanced mode (#60)
- Show uploading and audio processing progress at first 5%, no freezes longer that 15s (#57)
- Favicon and better webui (#50)

## v0.5.4 - 2025-10-08

### Features

- Add remote server conversion and discovery support (#47)
- Add --server argument to gui app, for autorun talks-reducer service (#45)

## v0.5.2 - 2025-10-08

### Features

- Add system tray launcher for web server, open tray icon in gui and talks-reducer-server-tray mode (#43)

## v0.5.1 - 2025-10-07

### Features

- Make woking MacOS app, with python 3.13.5 (#42)
- Add client part for send video to server via remote command line (#40)

## v0.5.0 - 2025-10-07

### Features

- Open gui converter on drag file to app icon in Windows(#39)
- Remove Silero VAD option, because it's make too heavy app size
- Better progress: show current time and total time, precision progress bar
- Add simple web interface with Gradio server (#33)
- Add Silero VAD option for speech detection (#35)

## v0.4.0 - 2025-10-07

### Bump

- Regex = true

## v0.3.3 - 2025-10-06

### Features

- Show compress ratio in time and size (#27)

### Bug Fixes

- Success ratios, return simple mode, remove animation

### Documentation

- Add gif
- Changelog

## v0.3.1 - 2025-10-06

### Features

- Allow clicking the drop zone to open the file picker (#22)

### Bug Fixes

- Improve ffprobe validation to accept Windows output, use internal ffmpeg (#21)

## v0.3.0 - 2025-10-06

### Features

- Prettify ui without layout switches
- Add persistent config, GUI toggle for opening exports, better colors (#20)
- Stop button
- Add progress bar with percentage, fix colors
- Show detailed elapsed progress

## v0.2.5 - 2025-10-05

### Miscellaneous

- Create launcher.py, build-gui.sh

## v0.2.3 - 2025-10-05

### Documentation

- Update readme

## v0.2.0 - 2025-10-05

### Features

- Add GUI and releases (#9)

## v0.1.4 - 2025-10-05

### Features

- --small mode: 720p and 128k
- --cuda support

### Bug Fixes

- Better --small args

### Documentation

- AGENTS.md, update README (#1)

