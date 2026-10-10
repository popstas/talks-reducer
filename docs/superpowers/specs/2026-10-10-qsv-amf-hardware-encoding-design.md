# Intel QSV and AMD AMF hardware encoding — design

Date: 2026-10-10
Status: approved in brainstorming, awaiting spec review

## Goal

Use Intel Quick Sync Video (QSV) and AMD AMF for H.265 and AV1 when no NVENC
GPU is present, and replace the encoder-listing heuristic that currently
misdetects CUDA with a real trial encode whose result is cached on disk.

## Background

### The CUDA misdetection

`check_cuda_available` returns `True` when `-hwaccels` lists `cuda` and
`-encoders` lists an `*_nvenc` encoder. The gyan.dev build that `static-ffmpeg`
bundles lists `cuda`, `qsv` and `amf` hwaccels and every `*_nvenc`, `*_qsv` and
`*_amf` encoder **regardless of the installed hardware**. On an Intel-only laptop
(Core Ultra 5 125H, Arc iGPU) the check returns `True`, so every run starts
NVENC with `-hwaccel cuda`, fails with `Cannot load nvcuda.dll`, and re-encodes
on the CPU fallback, logging "CUDA encoding failed".

Listing presence is therefore not a capability signal. A one-frame trial encode
is: on that laptop `hevc_nvenc` and `hevc_amf` exit non-zero, `hevc_qsv` exits 0.

### Benchmark (source for the codec split)

Source: 2:38, 1920×1080 at 60 fps, encoded to 720p, video only, VMAF against the
source scaled to 720p (every 5th frame). Intel Core Ultra 5 125H, 18 threads.

| Codec | Encoder | Time | fps | Size | VMAF |
|---|---|---|---|---|---|
| h264 | CPU libx264 veryfast crf 24 | 19 s | 504 | 6.04 MB | 90.2 |
| h264 | QSV gq 24 | 25 s | 390 | 9.38 MB | 93.8 |
| h265 | CPU libx265 medium crf 28 | 98 s | 98 | 4.26 MB | 90.8 |
| h265 | QSV gq 28 | 27 s | 355 | 3.91 MB | 91.7 |
| av1 | CPU libaom crf 32 cpu-used 6 | 392 s | 24 | 5.37 MB | 95.1 |
| av1 | QSV gq 32 | 26 s | 371 | 3.67 MB | 90.0 |

H.264 on QSV is slower than libx264 veryfast and produces a larger file, so
H.264 stays on the CPU — the same decision the project already made for
VideoToolbox. H.265 and AV1 gain 3.6× and 15× respectively.

### Trial-encode cost

One frame at 256×144: `hevc_nvenc` 52 ms (fail), `hevc_amf` 40 ms (fail),
`hevc_qsv` 750 ms (success). A full detection on this machine costs ~0.85 s,
which motivates the on-disk cache.

## Scope

In scope:

- Backends NVENC (existing), AMF (new), QSV (new), VideoToolbox (existing).
- QSV and AMF encode **H.265 and AV1 only**; H.264 stays on libx264 for them.
- Trial-encode detection with an in-process and an on-disk cache.
- Replacing the `cuda_available` / `videotoolbox_available` booleans with a
  single `hardware_backend` value.

Out of scope:

- VAAPI (Linux) and MediaFoundation (`*_mf`).
- Hardware decoding or hardware filters for QSV/AMF.
- A CLI flag or GUI control to force a backend or re-run detection.
- Changing NVENC or VideoToolbox encoder settings.

## Design

### 1. Backend detection (`talks_reducer/ffmpeg.py`)

Detection is **per codec**. Hardware support differs by codec: Intel before
Arc, AMD before RDNA3 and NVIDIA before RTX 40 encode HEVC but not AV1. A
HEVC-only probe would send every AV1 run to a failing GPU encoder on those
machines and wipe the cache each time.

New public function:

```python
def detect_hardware_backend(codec: str, ffmpeg_path: Optional[str] = None) -> Optional[str]
```

`codec` is stripped and lowercased; for anything other than `h264`, `hevc` or
`av1` (e.g. `mp3`) it returns `None` without probing. Callers pass the value of
`normalize_video_codec` (see §2).
It returns one of `"cuda"`, `"amf"`, `"qsv"`, `"videotoolbox"` or `None`: the
backend that will encode **this codec**.

Candidates per codec, in priority order (discrete GPUs first, because a machine
can have an Intel iGPU and an NVIDIA/AMD dGPU and the discrete encoder is
normally faster):

| codec | candidates |
|---|---|
| `h264` | `cuda` |
| `hevc` | `cuda`, `amf`, `qsv`, `videotoolbox` |
| `av1` | `cuda`, `amf`, `qsv` |

H.264 lists only `cuda` because QSV, AMF and VideoToolbox H.264 stay on libx264
(§2), so probing them would cost time for nothing. Candidates are further
limited by platform: `cuda`/`amf`/`qsv` on Windows and Linux, `videotoolbox` on
macOS only.

Steps:

1. Return the in-process cached value for this (ffmpeg fingerprint, codec) if
   present.
2. Return the on-disk cached value if it is valid (see §3).
3. Otherwise probe the codec's candidates in order and stop at the first
   success:
   - `cuda`, `amf`, `qsv`: the encoder `<codec>_<nvenc|amf|qsv>` must appear in
     the `-encoders` listing (cheap filter via `encoder_available`) **and** a
     trial encode must exit 0:
     `ffmpeg -hide_banner -v quiet -f lavfi -i color=black:size=256x144:duration=0.04 -frames:v 1 -c:v <encoder> -f null -`
     with a 10 s timeout.
   - `videotoolbox`: the existing `check_videotoolbox_available` logic (macOS
     only, listing-based, no trial encode — it has no false positives).
4. Store the result, including `None`, in the in-process cache. Store it
   on disk too only when every probe was conclusive (see §3).

Probing is lazy: an H.264 run probes only NVENC (~50 ms); HEVC and AV1 are
probed the first time they are requested.

New public function:

```python
def invalidate_hardware_backend_cache(codec: str, ffmpeg_path: Optional[str] = None) -> None
```

Clears that codec's in-process entry and removes it from the on-disk entry.

`check_cuda_available(ffmpeg_path)` stays as a thin wrapper,
`detect_hardware_backend("h264", ffmpeg_path) == "cuda"`, so external callers
keep working and inherit the corrected detection. `check_videotoolbox_available`
keeps its listing logic unchanged; detection calls it.

### 2. Command building

`build_video_commands` replaces `cuda_available` and `videotoolbox_available`
with `hardware_backend: Optional[str] = None` — the value `detect_hardware_backend`
returned for the codec being encoded.

A new public helper `normalize_video_codec(value) -> str` returns `"h264"`,
`"hevc"` or `"av1"` (unknown values map to `"h264"`, matching today's inline
normalisation in `build_video_commands`), so the pipeline and the command
builder agree on which codec was probed.

- `-hwaccel cuda -hwaccel_output_format cuda` is added only for `"cuda"`
  (unchanged condition: not in small mode). QSV and AMF decode on the CPU,
  because `filter_script` (`select`/`setpts`/`scale`) runs on the CPU and
  round-tripping frames through GPU memory would gain nothing.
- `resolve_encoder_plan` keeps its existing CPU argument lists and NVENC /
  VideoToolbox branches. For H.265 and AV1 with `"qsv"` or `"amf"` it takes the
  primary arguments from a table and sets the CPU arguments as the fallback:

```python
_HARDWARE_ENCODER_ARGS: dict[tuple[str, str], dict[str, list[str]]]
# key: (backend, codec) with codec in {"hevc", "av1"}
# value: {"optimized": [...], "fast": [...]}
```

- H.264 with `"qsv"` or `"amf"` uses libx264 with no fallback and
  `uses_gpu=False`.
- The existing `extra_keyframe_args` (`-g`, `-keyint_min`, `-force_key_frames`)
  are appended as for NVENC. During implementation, verify with ffprobe that
  `-force_key_frames` produces keyframes with `*_qsv`; if it does not, drop it
  for QSV and keep `-g`.

#### QSV arguments

ICQ rate control via `-global_quality`:

| | optimized | fast |
|---|---|---|
| `hevc_qsv` | `-preset medium -global_quality H` | `-preset veryfast -global_quality H` |
| `av1_qsv` | `-preset medium -global_quality A` | `-preset veryfast -global_quality A` |

`H` and `A` are set by calibration (§2.1).

#### AMF arguments

CQP rate control, chosen over QVBR because every VCN generation and driver
version supports it:

| | optimized | fast |
|---|---|---|
| `hevc_amf` | `-quality balanced -rc cqp -qp_i 26 -qp_p 28` | `-quality speed -rc cqp -qp_i 26 -qp_p 28` |
| `av1_amf` | `-quality balanced -rc cqp -qp_i 30 -qp_p 32` | `-quality speed -rc cqp -qp_i 30 -qp_p 32` |

The QP values mirror the NVENC fast-profile scale already used in the project
(`-qp 28` for HEVC, `-qp 32` for AV1). A code comment next to the table states
that the AMF values are not calibrated on real hardware.

#### 2.1 QSV calibration

Target VMAF ≈ 91, the level the CPU H.265 (90.8) and H.264 (90.2) defaults reach
in the benchmark. Sweep `-global_quality` for `hevc_qsv` and `av1_qsv` on the
benchmark source at 720p with the `optimized` arguments; pick the value closest
to VMAF 91, preferring the smaller file on a tie. Run one 480p check with the
chosen values to confirm quality does not collapse at the smaller size.

AV1 is calibrated against the VMAF target rather than against libaom (95.1 at
5.37 MB): the point of AV1 is the same quality in fewer bytes, not reproducing
libaom's overspend.

The sweep table is appended to this spec under "Calibration results", and the
code comment above `_HARDWARE_ENCODER_ARGS` refers to it.

### 3. On-disk cache

Stored in the shared `settings.json` (`config.determine_config_path()`):

```json
"hardware_backend": {
  "ffmpeg": {"path": "C:\\...\\ffmpeg.exe", "size": 123456789, "mtime": 1767000000},
  "codecs": {
    "hevc": {"backend": "qsv", "checked_at": 1791590400},
    "av1": {"backend": "qsv", "checked_at": 1791590400}
  }
}
```

- `ffmpeg` is the fingerprint of the resolved binary: absolute path, size and
  integer mtime. When the binary cannot be stat'ed (e.g. a bare `ffmpeg` name),
  there is no fingerprint and only the in-process cache is used.
- `codecs` holds one record per probed codec; `backend` may be `null`, so a
  GPU-less machine is cached too. `checked_at` is a Unix timestamp in seconds.
  Inconclusive probes (a trial that times out or cannot be spawned, or a
  failed encoder listing) stay in memory only and are re-checked next run;
  a codec is written to disk only when every candidate probed conclusively.

A codec record is valid only when the entry's fingerprint matches the current
binary, the record's age is under **30 days**, and `backend` is `null` or one of
the four known names. Anything else — missing key, wrong shape, unknown backend
— means re-detect that codec.

The key name lives in `config.py` as `HARDWARE_BACKEND_KEY = "hardware_backend"`
so both `ffmpeg.py` and `gui/preferences.py` import it without a GUI dependency.

Writing:

1. Read the file with `read_settings_strict`.
2. On `SettingsReadError`, do not write; keep the in-process value only, so a
   transient lock or partial write never clobbers other keys.
3. If the stored fingerprint differs from the current one, start a fresh entry
   (dropping other codecs' records, which belonged to the old binary).
4. Set or remove the one codec record and write with `save_settings`.

`gui/preferences.py` adds `"hardware_backend"` to `_EXTERNALLY_OWNED_KEYS`, so
`GUIPreferences.save()` re-reads the key from disk instead of overwriting it
with its stale in-memory snapshot.

The in-process cache is a module-level dict keyed by the fingerprint, guarded
by a `threading.Lock` (the GUI runs the pipeline on a worker thread and the
server may run several jobs).

### 4. Pipeline (`talks_reducer/pipeline.py`)

- `PipelineDependencies` replaces `check_cuda_available` and
  `check_videotoolbox_available` with `detect_hardware_backend` and adds
  `invalidate_hardware_backend_cache`.
- `speed_up_video` calls `detect_hardware_backend(codec, ffmpeg_path)` once,
  with `codec = normalize_video_codec(options.video_codec)`, and skips detection
  entirely for `mp3` output. It passes `hardware_backend=` to
  `build_video_commands`.
- Display names come from one mapping:
  `{"cuda": "CUDA", "amf": "AMF", "qsv": "QSV", "videotoolbox": "VideoToolbox"}`,
  feeding the existing `Processing on: GPU (...)`, `Encoder plan` and
  `"<backend> encoding failed"` logs and `ProcessingResult.gpu_backend`.
- The audio-extraction `hwaccel` list stays `cuda`-only.
- When the primary GPU command raises `CalledProcessError` and the CPU fallback
  runs, call `invalidate_hardware_backend_cache(codec, ffmpeg_path)` so the next
  run re-probes that codec. A stale "GPU present" record therefore costs at most
  one failed attempt.

### 5. Error handling

Detection and caching must never block a conversion:

| Situation | Behaviour |
|---|---|
| Corrupt or unrecognised cache entry | Re-detect |
| Settings file unreadable | Detect, keep result in memory, skip the write |
| Settings write fails | Keep result in memory |
| Trial encode times out (10 s) or exits non-zero | Treat the backend as unavailable, try the next |
| ffmpeg binary missing during fingerprinting | Treat as cache miss; detection then fails as it does today |
| GPU encode fails during a real run | Existing CPU fallback, then invalidate the cache |

A newly installed GPU or driver is picked up when the 30-day entry expires or
the ffmpeg binary changes; deleting the `hardware_backend` key forces it
immediately. This trade-off was accepted in brainstorming.

## Testing

`tests/test_ffmpeg.py`:

- Detection order and short-circuit: with stubbed process runs, the first
  successful candidate wins and later ones are not probed.
- Per-codec candidates: H.264 probes only NVENC; AV1 never probes VideoToolbox;
  a machine whose `av1_qsv` trial fails reports `None` for AV1 and `"qsv"` for
  HEVC; `mp3` returns `None` without running FFmpeg.
- A backend whose `<codec>_*` encoder is absent from `-encoders` is not trial-run.
- A trial encode that exits non-zero is treated as unavailable. A trial that
  times out or cannot be spawned, or a failed `-encoders` listing, is
  inconclusive: it counts as unavailable for that run, and the answer is
  kept out of the disk cache.
- Cache: a valid on-disk entry is used without running ffmpeg; a changed
  fingerprint, an entry older than 30 days, an unknown backend name and a
  malformed entry each trigger re-detection; `None` is cached;
  `invalidate_hardware_backend_cache` forces re-detection; a
  `SettingsReadError` skips the write.
- `build_video_commands` for every backend × codec × profile: correct encoder
  and arguments; H.264 with QSV/AMF uses libx264 with no fallback and
  `uses_gpu=False`; `-hwaccel cuda` appears only for `"cuda"`; QSV/AMF
  fallback commands are the CPU encoder.
- `check_cuda_available` / `check_videotoolbox_available` delegate to detection.

`tests/test_pipeline.py` / `tests/test_pipeline_service.py`:

- A failing GPU command runs the fallback, calls the invalidate dependency and
  reports `gpu_backend=None`.
- `Processing on: GPU (QSV)` is logged for `"qsv"` with an H.265 plan.
- Existing tests move from `cuda_available=` / `videotoolbox_available=` to
  `hardware_backend=`.

GUI preferences tests: `GUIPreferences.save()` preserves a `hardware_backend`
key written to disk after construction.

Tests must not touch the real `settings.json`; the cache path is injectable or
patched.

Manual verification on the Intel laptop:

- CLI run with `--video-codec hevc` and with `av1` logs
  `Processing on: GPU (QSV)` and nothing about CUDA.
- A second run reuses the cache (no trial-encode delay; detection is not logged
  as a probe).
- H.264 logs `Processing on: CPU`.

## Documentation

- `README.md`: the GPU section lists NVENC, AMF, QSV and VideoToolbox, which
  codecs each one handles, and where the detection cache lives and how to reset
  it.
- `CLAUDE.md` / `AGENTS.md`: update the `ffmpeg.py` description and step 4 of
  "Processing Pipeline".
- PR title: `feat: Add Intel QSV and AMD AMF hardware encoding`. The description
  mentions the CUDA misdetection fix, which is inseparable from the new
  detection.

## Calibration results

To be filled in during implementation (§2.1).
