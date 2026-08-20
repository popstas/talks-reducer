# CLI reference

Full flag reference for the `talks-reducer` command. See the
[README](../README.md#command-line) for the common invocations.

## Named presets

A **preset** is a saved bundle of processing settings — resolution, silent/sounded speed,
silent threshold, and video codec — authored once in the desktop GUI (Advanced mode) and
applied read-only on every other surface, including the CLI. Presets live in the shared
`settings.json` (the same file the GUI, Web UI, and OBS dock read), so one canonical list
appears everywhere.

- `--list-presets` prints the stored preset names, one per line, and exits (no input file
  required). On a fresh install the five seeded defaults are printed:

  ```sh
  talks-reducer --list-presets
  # Compatible
  # Optimal
  # Smallest
  # Compress
  # mp3
  ```

- `--preset "NAME"` loads that preset and applies its fields as the **base configuration**
  before any explicit flags. Explicit flags still win, so precedence is
  **explicit flag > preset > default**:

  ```sh
  talks-reducer --preset "Smallest" talk.mp4                   # apply the whole preset
  talks-reducer --preset "Smallest" --silent-speed 8 talk.mp4  # override just the speed
  ```

The preset's resolution is expanded to the explicit tri-state (`1080p` → `--no-small`,
`720p` → `--small --720`, `480p` → `--small --480`) so a 1080p preset overrides a stored
`--small` preference rather than inheriting it. An unknown `--preset NAME` errors and lists
the valid names.

## Encoding presets

By default the CLI applies the same tuned encoder settings everywhere: adaptive keyframes,
128 kbps AAC audio, and NVENC fallbacks that previously lived behind `--small`.

- `--small` layers on a 720p scale for a smaller output.
- `--480` scales down to 480p instead.
- `--720` forces the 720p scale explicitly — handy on a seeded GUI launch, where it unchecks
  the **Target 480p** box even if your stored preference enabled it.
- `--no-small` force-disables the preset, overriding a stored `--small` preference and
  unchecking the **Small video** box on a seeded launch.
- `--no-optimize` switches to a speed-focused CUDA preset that prioritizes turnaround time
  over compression efficiency, adding a `_fast` suffix when applicable.

```sh
talks-reducer input.mp4  # optimized encoding at the source resolution
talks-reducer --small input.mp4  # optimized encoding plus 720p scaling
talks-reducer --no-small input.mp4  # force the small preset off, overriding a stored preference
talks-reducer --no-optimize input.mp4  # fastest CUDA preset with a _fast suffix when applicable
```

## Video codec

Need a different compression target? H.264 (`--video-codec h264`) is the default: it is
about 10% faster and the most widely compatible option. Switch to `--video-codec hevc`
(H.265) to target roughly 25% smaller files with tuned presets, adaptive quantization, and
multipass lookahead, or `--video-codec av1` to experiment with modern AV1 output.

Choose `--video-codec mp3` to skip video entirely and export an **audio-only `.mp3`**
(encoded with `libmp3lame -q:a 2`, ~190 kbps VBR): the talk is still silence-trimmed and
speed-adjusted exactly as usual, but the result is a `<name>.mp3` file instead of a
`<name>.mp4`. When the mp3 codec is selected you can also feed **audio-only inputs** (for
example `.m4a`, `.wav`, or `.aac`) — files without a video stream are accepted only in this
mode; the other codecs still require a video stream.

Every interface — the CLI, GUI, and browser UI — shares the same encoder choices so you can
pick once and get consistent results everywhere.

Pass `--add-codec-suffix` to append the selected codec to the default output filename.

## Keyframe interval

Pass `--keyframe-interval 15` (or any other positive number of seconds) to space keyframes
further apart when using `--small`, trading seek responsiveness for a smaller output file.
The advanced GUI slider defaults to 30 seconds and lets you pick anywhere between snappy
one-second GOPs and ultra-light 60-second spacing.

## Trimming: `--cut-start` / `--cut-end`

Only need a fragment of a recording? Trim it down before the speed-up encode with
`--cut-start` and `--cut-end`. Both accept either seconds (`12.5`) or a timecode
(`HH:MM:SS[.ms]`, `MM:SS`, or `SS`) and define a *keep range* like a video editor:
`--cut-start` is the timestamp to start keeping and `--cut-end` is the timestamp to stop
keeping. Leave `--cut-end` at its `0` default to keep everything to the end of the file.
Both default to `0`, so omitting them leaves the input untouched (no `-ss`/`-t` is added to
FFmpeg). The trimmed span is what drives progress and target-duration reporting, so the bars
stay accurate.

```sh
talks-reducer --cut-start 00:00:10 --cut-end 00:01:00 demo.mp4  # keep 10s–60s
talks-reducer --cut-start 90 demo.mp4  # drop the first 90 seconds, keep to EOF
```

## Gluing several parts: `--glue`

A talk recorded in several files becomes one video with `--glue`: the parts are concatenated
*before* the speed-up pipeline runs, so silence detection spans the seams and a single summary
describes the whole talk. Without the flag each input is still processed on its own.

The parts are joined in the order you list them and the output is named after the **first**
one, next to it — `part1.mp4 part2.mp4` produces `part1_speedup.mp4`. Directories expand
first, so `--glue recordings/` glues everything the folder holds.

```sh
talks-reducer --glue part1.mp4 part2.mp4 part3.mp4  # one part1_speedup.mp4
talks-reducer --glue --small recordings/            # glue a folder, scaled to 720p
```

Parts that share their codec, resolution and audio parameters are stream-copied, which is
close to instant. When they disagree — a different resolution or frame rate between takes —
the parts are re-encoded and scaled to the first part's frame size instead, since a
stream copy would otherwise produce a file that changes size mid-playback. The glued file
lives in the temporary working folder and is deleted when the run finishes.

## Timing and silence detection

- `--silent_threshold` (`-t`) — the volume below which a segment counts as silence.
- `--sounded_speed` (`-S`) — playback speed applied to segments with speech.
- `--silent_speed` (`-s`) — playback speed applied to silent segments.
- `--frame_margin` (`-fm`) — frames of padding kept around each sounded segment.
- `--sample_rate` (`-sr`) — audio sample rate used while analysing.
- `-o` / `--output_file`, `--temp_folder` — where the result and the scratch files go.

Flag names accept either hyphens or underscores where both spellings exist
(`--silent-speed` and `--silent_speed` both work).

### Speech detection

Talks Reducer relies on its built-in volume thresholding to detect speech. Adjust
`--silent_threshold` if you need to fine-tune when segments count as silence. Dropping the
optional Silero VAD integration keeps the install lightweight and avoids pulling in PyTorch.

When CUDA-capable hardware is available the pipeline leans on GPU encoders to keep export
times low, but it still runs great on CPUs.

On macOS the pipeline uses Apple VideoToolbox for `--codec hevc` only, and falls back to
`libx265` if the hardware encoder rejects the job. H.264 stays on `libx264` even though
`h264_videotoolbox` exists: Apple's media engine tops out near 290 fps at 1080p regardless
of the requested quality, while `libx264 -preset veryfast` spreads across the CPU cores and
reaches roughly twice that, so at matched output size the hardware encoder finishes later.
HEVC is the reverse — `libx265 -preset medium` is the slow part of the export, and moving it
onto the media engine cut a 29-minute 1080p30 recording from 387 s to 107 s at the same
output size. AV1 always uses the software encoder because Apple ships no AV1 encoder.

## FFmpeg selection

Bundled FFmpeg builds prioritise compatibility, but they may lack newer GPU encoders such as
`av1_nvenc`. The bundled `static-ffmpeg` package currently ships FFmpeg 7.0, so the
VideoToolbox commands stay within the options that release understands. When your local
FFmpeg install exposes additional hardware options, add `--prefer-global-ffmpeg` so the CLI
and GUI prefer the binary on your `PATH` before falling back to the static package.

## Remote processing

Pass `--url` with the server address and the CLI will upload the input, wait for processing
to finish, and download the rendered video. You can also provide `--host` to expand to the
default Talks Reducer port (`http://<host>:9005`):

```sh
talks-reducer --url http://localhost:9005 demo.mp4
talks-reducer --host 192.168.1.42 demo.mp4
```

Remote jobs respect the same timing controls as the local CLI. Provide
`--silent_threshold`, `--sounded_speed`, or `--silent_speed` to tweak how the server trims
and accelerates segments without falling back to local mode.

Want to see progress as the remote server works? Add `--server-stream` so the CLI prints
live progress bars and log lines while you wait for the download. The stream walks through
every stage of the job: an `Uploading:` bar that advances incrementally with the bytes sent
(instead of jumping straight to 100%) while the file is sent to the server, an
`Extracting audio:` bar once the upload is received, an `Audio processing:` bar driven by
the real phase-vocoder work (instead of a synthetic estimate), and a `Generating final:` bar
for the encode. Progress keeps advancing after audio processing finishes rather than
stalling until the encode completes. Once processing is done a `Downloading:` bar reports
the finished file being fetched back from the server. The client fetches the processed file
exactly once (it previously downloaded it twice, since the server exposes the same file as
both a preview and a download), so downloads finish in about half the time.

## Audio processing performance

The audio stage only runs the phase vocoder where it changes something. A chunk played at
normal speed — which is what `--sounded_speed` defaults to — is copied instead, because a
phase vocoder at speed 1.0 reproduces its input. That alone takes the stage from roughly 77
to 3 seconds per hour of video.

When speeds other than 1.0 leave real work to do, the chunks are rendered in worker
processes: an eight-minute recording processed with `--sounded_speed 1.5` spends 2.6 seconds
in the audio stage instead of 13.8. The pool starts only when the workload is large enough
to pay for itself, and a machine that cannot spawn workers falls back to in-process
rendering with identical output.

Set `TALKS_REDUCER_AUDIO_WORKERS` to choose the worker count yourself; `1` disables the pool
entirely. Without it, one CPU core is left free and no more than eight workers are used.

## GUI-only flags

`--open-location` and `--auto-close` control what happens after a seeded GUI conversion
finishes. See [gui.md](gui.md#seeded-launches-and-shortcuts).
