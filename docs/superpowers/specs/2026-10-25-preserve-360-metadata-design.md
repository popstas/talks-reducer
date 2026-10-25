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
| concat demuxer `-c copy -map 0 -strict unofficial` | kept | kept |

Two causes: the MOV muxer only writes `sv3d`/`st3d` under
`-strict unofficial`, and `scale` drops Spherical Mapping because it is
frame-size-dependent side data. `v360` (equirect → equirect) rescales while
keeping it, at the same speed as `scale` (≈8 s for the 3 s 8K clip either way;
decoding dominates).

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
  returns `v360=e:e:w={W}:h={target_height}` where `W` keeps the source aspect
  ratio, rounded to an even number (same contract as `scale=-2:H`).
- `PRESERVE_SPHERICAL_ARGS = "-strict unofficial"`.

### 2. Gluing (`glue.py`)

- `concatenate_media` probes the first input once with `probe_spherical`.
- When it is spherical, `build_concat_copy_command(..., preserve_spherical=True)`
  adds `-strict unofficial`. (The existing `-c copy` already copies the video
  stream's side data; no extra `-map` is needed for the single video stream.)
- The re-encode path (`filter_complex` with `scale`+`pad`, used only when parts
  disagree) loses the tags. It is not fixed; when the source is spherical the
  reporter logs: `360° metadata will not be preserved: the parts use different
  stream parameters.`

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
- The pipeline logs `Preserving 360° metadata (equirectangular)` when active.

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
  - Both filter graphs emit `v360=...` for a spherical source and the unchanged
    `scale=-2:H` otherwise.
- Manual check with the bundled FFmpeg on a short 360 clip: glue two clips, run
  the 720p preset with libx264 and libx265, confirm with ffprobe that the output
  has both Stereo 3D and Spherical Mapping (`projection=equirectangular`).
- **Not verified:** GPU encoders (NVENC/QSV/AMF) — unavailable on the dev
  machine. Also unverified: macOS/Linux `static_ffmpeg` builds, which may be a
  different FFmpeg version.

## Docs

`README.md` gets a short note that 360° videos keep their metadata, including
the limitations from §4.
