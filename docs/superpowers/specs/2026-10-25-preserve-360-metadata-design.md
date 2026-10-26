# Preserve 360° metadata through gluing and processing

## Problem

360° recordings (e.g. Insta360 `VID_*_00_*.mp4`, HEVC 7680×3840) carry two
stream side-data entries that players use to render them as spheres:
**Spherical Mapping** (`projection=equirectangular`, MP4 `sv3d` box) and
**Stereo 3D** (`2D`/mono, MP4 `st3d` box). Talks Reducer loses both, so the
output plays as a flat stretched panorama.

Measured with the bundled FFmpeg (`static_ffmpeg`, 8.0.1) on a 3 s clip:

| Command | Stereo 3D | Spherical Mapping |
|---|---|---|
| any encode / copy without `-strict unofficial` | lost | lost |
| `-strict unofficial`, no scaling (`setpts` only) | kept | kept |
| `-strict unofficial`, `scale=1280:-2` | kept | **lost** |
| `-strict unofficial`, `v360=e:e:w=1280:h=640` | kept | kept |
| `-strict unofficial`, `gblur=sigma=2,v360=e:e:w=1440:h=720` | kept | kept |
| `-strict unofficial`, `scale=3840:1920,v360=e:e:w=1440:h=720` | kept | **lost** |
| concat demuxer `-c copy -map 0 -strict unofficial` | kept | kept |

Two causes: the MOV muxer only writes `sv3d`/`st3d` under
`-strict unofficial`, and `scale` drops Spherical Mapping because it is
frame-size-dependent side data. `v360` (equirect → equirect) rescales while
keeping it. So does any filter chain ending in `v360` whose earlier filters keep
the frame size; one that resizes before `v360` loses Spherical Mapping just as
`scale` does.

### Anti-aliasing (`gblur` before `v360`)

`v360` picks source pixels with no low-pass filter, so a large downscale
aliases. Measured on a 60-frame (2 s) clip of the real 7680×3840 source, cut
with `-c copy` at the 10.010 s keyframe, encoded with `libx264 -preset veryfast
-crf 24 -strict unofficial`. *Filter PSNR* is the luma PSNR of the filter's own
output (encoded losslessly, `-qp 0`) against `scale=W:H:flags=area`; it
isolates the filter. *Encoded PSNR* is the crf 24 file against the same
reference, where the encoder caps every row near 33–34 dB. Times are wall-clock
for the crf 24 encode of the 60 frames.

| Target | Filter | Size | Filter PSNR | Encoded PSNR | Time | Tags |
|---|---|---|---|---|---|---|
| 720p (5.33×) | `scale=-2:720` | 1.53 MB | 45.44 dB | 33.92 dB | 2.1–2.9 s | st3d only |
| 720p | `v360=e:e:w=1440:h=720` | 2.39 MB | 35.45 dB | 33.56 dB | 2.4–3.8 s | both |
| 720p | `gblur=sigma=1.33,v360=…` | 1.78 MB | 42.35 dB | 34.16 dB | 5.6 s | both |
| 720p | `gblur=sigma=1.67,v360=…` | 1.61 MB | 44.73 dB | 33.90 dB | 5.4 s | both |
| 720p | **`gblur=sigma=2,v360=…`** | **1.47 MB** | **44.84 dB** | 33.54 dB | 5.5–6.7 s | both |
| 720p | `gblur=sigma=2.17,v360=…` | 1.40 MB | 44.01 dB | 33.33 dB | 5.7 s | both |
| 720p | `gblur=sigma=2.67,v360=…` | 1.25 MB | 40.89 dB | 32.69 dB | 5.7 s | both |
| 720p | `avgblur=sizeX=2,v360=…` | 1.61 MB | 44.82 dB | 33.95 dB | 4.7 s | both |
| 720p | `avgblur=sizeX=3,v360=…` | 1.32 MB | 41.25 dB | 33.02 dB | 5.0 s | both |
| 480p (8×) | `scale=-2:480` | 0.68 MB | 43.50 dB | 33.28 dB | 3.3–3.8 s | st3d only |
| 480p | `v360=e:e:w=960:h=480` | 1.41 MB | 32.02 dB | 31.89 dB | 3.4–3.5 s | both |
| 480p | `gblur=sigma=2.5,v360=…` | 0.76 MB | 42.94 dB | 33.43 dB | 5.9 s | both |
| 480p | **`gblur=sigma=3,v360=…`** | **0.67 MB** | **43.77 dB** | 33.04 dB | 5.6 s | both |
| 480p | `gblur=sigma=3.5,v360=…` | 0.61 MB | 42.22 dB | 32.59 dB | 5.3 s | both |
| 480p | `gblur=sigma=4,v360=…` | 0.55 MB | 40.16 dB | 32.14 dB | 5.7 s | both |
| 480p | `avgblur=sizeX=3,v360=…` | 0.78 MB | 44.54 dB | 33.63 dB | 4.8 s | both |

The filter is `gblur=sigma=S,v360=e:e:w=W:h=H` with `S = 0.375 × source_height /
target_height`, rounded to two decimals; that gives the bold rows, the only
ones within 1 dB of `scale` and no larger than it at both heights (`avgblur`
is larger than `scale` at both). Below a 1.5× downscale the blur is skipped. The
cost is speed: the blur roughly doubles the time of an 8K encode compared with
`scale`, about 3 s more per 60 frames here. A 5.7K (5760×2880) source, where the
formula gives sigma 1.5 at 720p, was not available and is untested.

## Goal

A 360° source keeps its 360° tags in the glued intermediate **and** in the final
processed output, on every surface (GUI, CLI, Web UI/remote, OBS dock). Non-360
inputs produce byte-for-byte the same FFmpeg commands as today.

## Design

### 1. `talks_reducer/spherical.py` (new)

- `SphericalInfo` — frozen dataclass: `projection: str` (e.g.
  `"equirectangular"`), `stereo: Optional[str]`.
- `probe_spherical(path) -> Optional[SphericalInfo]` — runs `ffprobe -v error
  -select_streams v:0 -show_entries stream_side_data=side_data_type,projection
  -of json`. Returns `None` when there is no Spherical Mapping entry or the probe
  fails (probe failure must never break processing).
- `spherical_scale_filter(source_width, source_height, target_height) -> str` —
  returns `gblur=sigma={S},v360=e:e:w={W}:h={target_height}` where `W` keeps the
  source aspect ratio, rounded to an even number (same contract as
  `scale=-2:H`), and `S` follows the anti-aliasing formula above; under a 1.5×
  downscale it returns the bare `v360=…`.
- `PRESERVE_SPHERICAL_ARGS = "-strict unofficial"`.

### 2. Gluing (`glue.py`)

- `concatenate_media` probes the first input once with `probe_spherical`.
- When it is spherical, `build_concat_copy_command(..., preserve_spherical=True)`
  adds `-strict unofficial`. (The existing `-c copy` already copies the video
  stream's side data; no extra `-map` is needed for the single video stream.)
- The re-encode path (`filter_complex` with `scale`+`pad`, used only when parts
  disagree, or as the fallback when the copy fails) loses the tags. It is not
  fixed; when the source is spherical the reporter logs: `360° metadata will
  not be preserved: re-encoding the parts drops it.`

### 3. Pipeline (`pipeline.py`, `ffmpeg.py`)

- After `_extract_video_metadata`, the pipeline calls `probe_spherical` once for
  video inputs and keeps the result.
- The duplicated scale logic in `_build_scale_only_filter_graph` and the
  speed-up filter graph (currently both append `scale=-2:{target_height}`) is
  extracted into one helper, e.g. `_scale_filter_part(options, original_width,
  original_height, spherical, reporter) -> Optional[str]`. It returns
  `spherical_scale_filter(...)` for an equirectangular source and
  `scale=-2:{target_height}` otherwise; the existing "Scaling down" /
  "Keeping original resolution" log lines stay.
- `build_video_commands` gains `preserve_spherical: bool = False`; when true it
  adds `-strict unofficial` to the output arguments of **both** the primary and
  the CPU fallback command.
- The pipeline logs `360° video detected (<projection>)` once it probes a
  spherical source. Whether the metadata survives is decided later, by the
  scale step, which logs `360° metadata will not be preserved: …` with its
  reason (an unsupported projection, or an unknown source width).

### 4. Out of scope (log a warning, do not fix)

- Projections other than equirectangular (cubemap, EAC, …): tags are kept only
  when no scaling happens (`orig` resolution); with scaling the pipeline logs
  that 360° metadata will not be preserved.
- mp3 / audio-only outputs — nothing to preserve; no probe, no warning.
- Glue re-encode path (see §2).

### 5. Remote mode

The server runs the same pipeline, so the fix applies there. Gluing happens on
the client before upload via the copy path, which keeps the tags.

## Testing

- Unit tests (stubbed probe, no FFmpeg):
  - `probe_spherical` parses ffprobe JSON with/without Spherical Mapping and
    returns `None` on probe errors.
  - `spherical_scale_filter` widths for 2:1 and odd-ratio sources (even width).
  - `build_concat_copy_command` / `build_video_commands` contain
    `-strict unofficial` only when `preserve_spherical=True`, in both primary and
    fallback commands.
  - Both filter graphs emit `gblur=…,v360=...` for a spherical source and the
    unchanged `scale=-2:H` otherwise.
- Manual check with the bundled FFmpeg on a short 360 clip: glue two clips, run
  the 720p preset with libx264 and libx265, confirm with ffprobe that the output
  has both Stereo 3D and Spherical Mapping (`projection=equirectangular`).
- **Not verified:** GPU encoders (NVENC/QSV/AMF) — unavailable on the dev
  machine. Also unverified: macOS/Linux `static_ffmpeg` builds, which may be a
  different FFmpeg version.

## Docs

`README.md` gets a short note that 360° videos keep their metadata, including
the limitations from §4.
