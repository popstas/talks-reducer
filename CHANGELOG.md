# Changelog


## v1.9.0 - 2026-11-14

### Features

- Speed up non-voice parts with Silero VAD (Speedup no voice) (#167)

## v1.8.0 - 2026-11-08

### Features

- Remove fragments from the middle of a video via mpv.net (#166)

## v1.7.1 - 2026-11-08

### Bug Fixes

- Stop console windows flashing during conversion on Windows (#165)

## v1.7.0 - 2026-11-05

### Features

- Add orig, 1080p and FPS options to the OBS dock
- Offer 1080p in the Create link dialog
- Add 1080p resolution and FPS row to the desktop GUI
- Add 1080p and FPS options to the Web UI
- Send 1080p and fps cap to remote servers
- Add --1080 and --fps CLI options
- Cap output frame rate and downscale to 1080p in the pipeline

### Bug Fixes

- Reset fps for presets that predate the fps field
- Send explicit --720 from the OBS dock
- Keep presets_version when the GUI saves preferences

## v1.6.0 - 2026-11-03

### Features

- Choose the order of glued videos

### Bug Fixes

- Keep the GPU encoder for glued videos

## v1.5.0 - 2026-10-27

### Features

- Keep 360° video metadata when gluing and processing (#162)

## v1.4.1 - 2026-10-10

### Bug Fixes

- Open last selects files whose path contains spaces (#161)

## v1.4.0 - 2026-10-10

### Features

- Add Intel QSV and AMD AMF hardware encoding (#160)

### Bug Fixes

- gui: Size the custom slot entry like its button

## v1.3.2 - 2026-10-08

### Bug Fixes

- gui: Narrow full-mode window to 1070px

## v1.3.0 - 2026-08-21

### Bug Fixes

- Keep the audio progress counting through the real stage
- Pace audio progress by chunks and rebalance the stage bands

## v1.2.0 - 2026-08-19

### Features

- Add option to glue multiple inputs into one video

### Bug Fixes

- gui: Match dark blue, tidy options rows

## v1.1.2 - 2026-08-05

### Features

- ffmpeg: Use VideoToolbox for HEVC

## v1.1.1 - 2026-08-03

### Bug Fixes

- Remove Advanced group headings and rebalance option spacing

## v1.1.0 - 2026-08-03

### Features

- Replace Advanced settings sliders with compact button groups (#154)

## v1.0.2 - 2026-07-12

### Features

- Keep clean mp3 output name when the filename is free

## v1.0.1 - 2026-07-09

### Bug Fixes

- Download remote result over HTTP instead of copying a server path
- Surface swallowed import error for server/tray/dock modes
- Keep pandas in bundle so gradio imports in frozen server/tray
- Prevent remote mode crash on Windows console checkmark

## v1.0.0 - 2026-07-09

### Features

- Reorder presets with up/down buttons in Advanced mode
- OBS dock defaults to first preset and matches OBS styling
- Web UI opens on remembered preset, else the first
- Default to first preset, remember last, move Open output to preset row
- Add param checkboxes to Save/Update preset dialog
- Make presets sparse (store/apply only selected params)
- Document cross-surface presets
- Verify preset cross-surface acceptance criteria
- Add OBS dock preset support
- Add Web UI preset dropdown
- Add Advanced mode preset management strip
- Add Simple mode preset dropdown
- Add CLI --preset and --list-presets flags
- Add preset store and model (talks_reducer/presets.py)
- Extract shared config module for settings load/save
- Enable Gradio PWA on server and tray launches
- Declutter web UI with resolution/speedup radios and accordions
- Add web UI handler and decoupled API wrapper for process_video
- Add compact web UI result summary with collapsible details
- Default to H.264 video codec
- Match the Windows title bar to the active dark/light theme
- Enable global FFmpeg by default on first start when detected
- Add tooltip to the GUI Optimized encoding checkbox

### Bug Fixes

- Use handle_file to silence gradio warning
- dock: Apply preset from OBS dock launches
- Include dock_server to installer
- Keep Simple-mode Open output right-aligned across mode toggles
- Tighten Simple-mode preset row and widen OBS dock preset select
- Apply web UI css compatibly across Gradio css argument moves
- Repair Update preset button ImportError
- Address code review findings
- review: Prevent GUI startup crash from build-time preset reverse-match
- review: Preserve externally-written presets on preference save
- review: Repair OBS dock preset visibility and surface preset write failures
- Keep dark combobox face dark on hover
- Parse compact server summary ratios in remote GUI status
- Apply web UI css via launch() instead of deprecated Blocks arg
- Accept FileData dict from gr.api file upload in web server
- Remove accidentally committed tatus file

## v0.23.0 - 2026-07-08

### Features

- Add built-in OBS dock-server with installer integration (#151)
- Show Windows taskbar progress and ring a bell when a run finishes (#150)
- Close app after launching installer on Windows update

## v0.22.1 - 2026-07-06

### Features

- Add "Auto close and open file location" option to Create lnk dialog

## v0.22.0 - 2026-07-04

### Features

- obs-dock: Add OBS processing browser dock
- Add --open-location and --auto-close GUI post-convert flags
- Remember GUI window position across launches
- Add --no-small flag to force-disable the small preset

## v0.21.0 - 2026-07-02

### Features

- Add watch-directory with dynamic Convert/Open-last button (#148)

## v0.20.2 - 2026-07-01

### Bug Fixes

- Hide macOS tray Dock icon and make update check work off Windows

## v0.20.1 - 2026-07-01

### Features

- Cancel remote upload and audio stage fast

### Bug Fixes

- Default context menu task to unchecked
- Remove Download portable link from updates
- Prevent window size flash on GUI launch

## v0.20.0 - 2026-07-01

### Features

- Add macOS update check button under Advanced settings (#144)

## v0.19.2 - 2026-07-01

### Bug Fixes

- Bundle the gradio server stack so the tray server works in frozen builds

## v0.19.1 - 2026-06-30

### Bug Fixes

- Prevent server-tray preference from bricking the GUI launcher

## v0.19.0 - 2026-06-30

### Features

- Run as server in tray toggle in the desktop GUI (#143)

## v0.18.0 - 2026-06-29

### Features

- Serve Talks Reducer icon for the web UI PWA manifest

## v0.17.2 - 2026-06-29

### Bug Fixes

- Render macOS tray icon as a two-tone silhouette

## v0.17.1 - 2026-06-29

### Features

- Use white-on-transparent silhouette for macOS tray icon
- Make macOS menu bar tray icon monochrome

## v0.17.0 - 2026-06-28

### Features

- Add mp3 audio-only option to the codec selector (#142)

## v0.16.0 - 2026-06-28

### Features

- Add "Create lnk" desktop shortcut button (Windows)

### Bug Fixes

- Align server URL field with Discover button
- Refresh seeded-launch slider value labels

## v0.15.0 - 2026-06-24

### Features

- Add Homebrew Cask distribution for macOS GUI (#135)

## v0.14.0 - 2026-06-24

### Features

- Add video trim (cut begin/end) before converting (#140)

## v0.13.0 - 2026-06-20

### Features

- GUI server-mode visibility and remote download progress fixes (#138)

## v0.12.0 - 2026-06-03

### Features

- GUI launch options and remote transfer progress (#137)

## v0.11.0 - 2026-06-02

### Features

- Improve progress reporting across GUI, remote, and pipeline (#136)

## v0.10.7 - 2026-05-12

### Bug Fixes

- pipeline: Pin output fps in neutral-speed path

## v0.10.5 - 2026-05-07

### Features

- pipeline: Always emit .mp4 for default output

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

## v0.10.1 - 2026-02-21

### Bug Fixes

- server: Remove spurious final progress call

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

## v0.7.2 - 2025-10-10

### Bug Fixes

- Fast show tray icon in --server mode (#76)

## v0.7.0 - 2025-10-10

### Bug Fixes

- Web UI now display progress (#71)
- Working Stop command in remote mode (#69)
- Show conversion time, better logger output (#68)
- Better remote server ping and switch to local mode

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

## v0.3.3 - 2025-10-06

### Features

- Show compress ratio in time and size (#27)

### Bug Fixes

- Success ratios, return simple mode, remove animation

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

## v0.2.0 - 2025-10-05

### Features

- Add GUI and releases (#9)

## v0.1.4 - 2025-10-05

### Features

- --small mode: 720p and 128k
- --cuda support

### Bug Fixes

- Better --small args

