# CLI reference

Full flag reference for the `talks-reducer` command. See the
[README](../README.md#command-line) for the common invocations.

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

## FFmpeg selection

Bundled FFmpeg builds prioritise compatibility, but they may lack newer GPU encoders such as
`av1_nvenc`. When your local FFmpeg install exposes additional hardware options, add
`--prefer-global-ffmpeg` so the CLI and GUI prefer the binary on your `PATH` before falling
back to the static package.

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

## GUI-only flags

`--open-location` and `--auto-close` control what happens after a seeded GUI conversion
finishes. See [gui.md](gui.md#seeded-launches-and-shortcuts).
