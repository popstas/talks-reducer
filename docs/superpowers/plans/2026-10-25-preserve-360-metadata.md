# Preserve 360° Metadata Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 360° sources keep their Spherical Mapping / Stereo 3D tags in the glued intermediate and in the final processed output.

**Architecture:** A new `talks_reducer/spherical.py` probes the source's side data once. When the source is spherical, gluing and the final encode add `-strict unofficial` (the MOV muxer only writes `sv3d`/`st3d` with it), and the final encode replaces `scale=-2:H` with `v360=e:e:w=W:h=H` for equirectangular sources, because `scale` drops Spherical Mapping. Non-360 inputs produce exactly the same FFmpeg commands as before.

**Tech Stack:** Python 3, FFmpeg/ffprobe (bundled `static_ffmpeg`, 8.0.1 on Windows), pytest, black, isort.

Spec: `docs/superpowers/specs/2026-10-25-preserve-360-metadata-design.md`.

## Global Constraints

- Use the project virtualenv: run everything through `.venv/Scripts/python` (Windows) / `.venv/bin/python`.
- Non-360 inputs: generated FFmpeg commands and filter graphs must stay byte-for-byte unchanged.
- `probe_spherical` must never raise; any probe failure returns `None`.
- Only equirectangular is rescaled with `v360`; other projections keep `scale` and log `360° metadata will not be preserved`.
- mp3 / audio-only outputs: no spherical probe, no warning.
- Glue re-encode path is not fixed; it only logs a warning for spherical sources.
- Format with `black` and `isort` (configured in `pyproject.toml`) before each commit.
- Favor function-level docstrings over inline comments for new logic.
- Commit messages: Angular format; end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## File Structure

- Create `talks_reducer/spherical.py` — probe + filter helpers, no dependencies on pipeline/glue.
- Create `tests/test_spherical.py` — unit tests for the module.
- Modify `tests/conftest.py` — autouse fixture stubbing `spherical.probe_spherical` so other tests never spawn ffprobe on fake files.
- Modify `talks_reducer/ffmpeg.py` — `build_video_commands(..., preserve_spherical=False)`.
- Modify `talks_reducer/glue.py` — `build_concat_copy_command(..., preserve_spherical=False)`, probe in `concatenate_media`.
- Modify `talks_reducer/pipeline.py` — `PipelineDependencies.probe_spherical`, shared `_scale_filter_part`, pass `preserve_spherical`.
- Modify `tests/test_ffmpeg.py`, `tests/test_glue.py`, `tests/test_pipeline.py`.
- Modify `README.md` — short 360° note.

---

### Task 1: `spherical` module

**Files:**
- Create: `talks_reducer/spherical.py`
- Create: `tests/test_spherical.py`
- Modify: `tests/conftest.py`

**Interfaces:**
- Produces:
  - `EQUIRECTANGULAR: str = "equirectangular"`
  - `PRESERVE_SPHERICAL_ARGS: str = "-strict unofficial"`
  - `@dataclass(frozen=True) class SphericalInfo: projection: str; stereo: Optional[str] = None`
  - `parse_spherical_side_data(payload: str) -> Optional[SphericalInfo]`
  - `probe_spherical(path: Path | str) -> Optional[SphericalInfo]`
  - `spherical_scale_filter(source_width: int, source_height: int, target_height: int) -> str`

- [ ] **Step 1: Write the failing tests**

`tests/test_spherical.py`:

```python
"""Tests for detecting and preserving 360° (spherical) video metadata."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from talks_reducer import spherical

_STEREO = {"side_data_type": "Stereo 3D", "type": "2D", "inverted": 0}
_SPHERICAL = {
    "side_data_type": "Spherical Mapping",
    "projection": "equirectangular",
    "yaw": 0,
    "pitch": 0,
    "roll": 0,
}


def _payload(*side_data):
    """Build ffprobe ``-of json`` output for one video stream."""

    stream = {"side_data_list": list(side_data)} if side_data else {}
    return json.dumps({"streams": [stream]})


def test_parse_detects_equirectangular_with_stereo() -> None:
    info = spherical.parse_spherical_side_data(_payload(_STEREO, _SPHERICAL))

    assert info == spherical.SphericalInfo(projection="equirectangular", stereo="2D")


def test_parse_without_stereo_entry() -> None:
    info = spherical.parse_spherical_side_data(_payload(_SPHERICAL))

    assert info == spherical.SphericalInfo(projection="equirectangular", stereo=None)


def test_parse_returns_none_for_flat_video() -> None:
    assert spherical.parse_spherical_side_data(_payload()) is None
    assert spherical.parse_spherical_side_data(_payload(_STEREO)) is None


def test_parse_returns_none_for_garbage() -> None:
    assert spherical.parse_spherical_side_data("not json") is None
    assert spherical.parse_spherical_side_data(json.dumps({"streams": []})) is None


def test_probe_spherical_runs_ffprobe(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(stdout=_payload(_SPHERICAL))

    monkeypatch.setattr(spherical, "_ffprobe_path", lambda: "ffprobe")
    monkeypatch.setattr(spherical.subprocess, "run", fake_run)

    info = spherical.probe_spherical("clip.mp4")

    assert info == spherical.SphericalInfo(projection="equirectangular")
    assert calls[0][0] == "ffprobe"
    assert "stream_side_data" in " ".join(calls[0])
    assert calls[0][-1] == "clip.mp4"


def test_probe_spherical_swallows_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_run(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(spherical, "_ffprobe_path", lambda: "ffprobe")
    monkeypatch.setattr(spherical.subprocess, "run", failing_run)

    assert spherical.probe_spherical("missing.mp4") is None


@pytest.mark.parametrize(
    ("width", "height", "target", "expected"),
    [
        (7680, 3840, 720, "v360=e:e:w=1440:h=720"),
        (7680, 3840, 480, "v360=e:e:w=960:h=480"),
        (5760, 2880, 720, "v360=e:e:w=1440:h=720"),
        # Non-2:1 source: width follows the source ratio, rounded to even.
        (1000, 562, 480, "v360=e:e:w=854:h=480"),
    ],
)
def test_spherical_scale_filter_keeps_aspect_and_even_width(
    width: int, height: int, target: int, expected: str
) -> None:
    assert spherical.spherical_scale_filter(width, height, target) == expected
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_spherical.py -v`
Expected: FAIL / ERROR with `ImportError: cannot import name 'spherical'`.

- [ ] **Step 3: Implement `talks_reducer/spherical.py`**

```python
"""Detect and preserve 360° (spherical) video metadata.

360° cameras tag the video stream with *Spherical Mapping* and *Stereo 3D*
side data (MP4 ``sv3d``/``st3d`` boxes). FFmpeg's MOV muxer only writes those
boxes under ``-strict unofficial``, and the ``scale`` filter drops Spherical
Mapping because it depends on the frame size. ``v360`` rescales an
equirectangular frame while keeping it, so the pipeline swaps it in.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

EQUIRECTANGULAR = "equirectangular"
PRESERVE_SPHERICAL_ARGS = "-strict unofficial"


@dataclass(frozen=True)
class SphericalInfo:
    """360° metadata found on a source's first video stream."""

    projection: str
    stereo: Optional[str] = None


def _ffprobe_path() -> str:
    """Return the ffprobe binary the rest of the app uses."""

    from .ffmpeg import get_ffprobe_path

    return get_ffprobe_path()


def parse_spherical_side_data(payload: str) -> Optional[SphericalInfo]:
    """Return the spherical metadata in ffprobe JSON *payload*, if any.

    *payload* is the output of ``ffprobe -show_entries stream_side_data -of
    json`` for one video stream. ``None`` means the stream is a flat video or
    the payload could not be read.
    """

    try:
        streams = json.loads(payload).get("streams") or []
    except (ValueError, AttributeError):
        return None
    if not streams:
        return None

    projection: Optional[str] = None
    stereo: Optional[str] = None
    for entry in streams[0].get("side_data_list") or []:
        kind = entry.get("side_data_type")
        if kind == "Spherical Mapping":
            projection = entry.get("projection") or "unknown"
        elif kind == "Stereo 3D":
            stereo = entry.get("type")

    if projection is None:
        return None
    return SphericalInfo(projection=projection, stereo=stereo)


def probe_spherical(path: Path | str) -> Optional[SphericalInfo]:
    """Probe *path* for 360° metadata; never raises.

    Any probe failure (missing ffprobe, unreadable file) returns ``None`` so a
    flat-video run is never broken by this check.
    """

    command = [
        _ffprobe_path(),
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream_side_data=side_data_type,projection,type",
        "-of",
        "json",
        str(path),
    ]
    creationflags = 0x08000000 if sys.platform == "win32" else 0
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            creationflags=creationflags,
        )
    except Exception:
        return None
    return parse_spherical_side_data(completed.stdout or "")


def spherical_scale_filter(
    source_width: int, source_height: int, target_height: int
) -> str:
    """Return a ``v360`` filter rescaling an equirectangular frame to *target_height*.

    The width follows the source aspect ratio and is rounded to an even number,
    matching what ``scale=-2:H`` would produce for a flat video.
    """

    width = int(round(source_width * target_height / source_height / 2.0)) * 2
    return f"v360=e:e:w={width}:h={target_height}"


__all__ = [
    "EQUIRECTANGULAR",
    "PRESERVE_SPHERICAL_ARGS",
    "SphericalInfo",
    "parse_spherical_side_data",
    "probe_spherical",
    "spherical_scale_filter",
]
```

Check the parametrized expectation `(1000, 562, 480)`: `1000*480/562/2 = 427.05` → `427*2 = 854`. OK.

- [ ] **Step 4: Stub the probe for every other test**

Append to `tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def stub_spherical_probe(request, monkeypatch):
    """Report every input as a flat video unless a test opts in.

    Pipeline and glue tests run on fake files; without this the real probe
    would spawn ffprobe for each of them. ``test_spherical`` exercises the
    real function, so it is left alone there.
    """

    if request.module.__name__.endswith("test_spherical"):
        return

    from talks_reducer import spherical

    monkeypatch.setattr(spherical, "probe_spherical", lambda path: None)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_spherical.py -v`
Expected: all PASS.

- [ ] **Step 6: Format and commit**

```bash
.venv/Scripts/python -m black talks_reducer/spherical.py tests/test_spherical.py tests/conftest.py
.venv/Scripts/python -m isort talks_reducer/spherical.py tests/test_spherical.py tests/conftest.py
git add talks_reducer/spherical.py tests/test_spherical.py tests/conftest.py
git commit -m "feat: Detect 360 video metadata with ffprobe"
```

---

### Task 2: `-strict unofficial` in the final encode command

**Files:**
- Modify: `talks_reducer/ffmpeg.py` (`build_video_commands`, ~line 1178 and the `audio_parts` block ~line 1455)
- Test: `tests/test_ffmpeg.py`

**Interfaces:**
- Consumes: `spherical.PRESERVE_SPHERICAL_ARGS`
- Produces: `build_video_commands(..., preserve_spherical: bool = False)` — when `True`, both the primary and the fallback command contain `-strict unofficial` placed in the output options (before the output path).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ffmpeg.py`:

```python
def test_build_video_commands_preserves_spherical_metadata(monkeypatch):
    """360° sources need ``-strict unofficial`` for the muxer to write sv3d/st3d."""

    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(
        ffmpeg, "encoder_available", lambda name, ffmpeg_path=None: True
    )

    command, fallback, _ = ffmpeg.build_video_commands(
        "input.mp4",
        "audio.wav",
        "filter.txt",
        "output.mp4",
        hardware_backend="cuda",
        optimize=True,
        small=True,
        frame_rate=30.0,
        preserve_spherical=True,
    )

    assert fallback is not None
    for built in (command, fallback):
        assert "-strict unofficial" in built
        assert built.index("-strict unofficial") < built.index('"output.mp4"')


def test_build_video_commands_flat_video_has_no_strict_flag(monkeypatch):
    """Flat videos keep exactly the commands they had before."""

    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(
        ffmpeg, "encoder_available", lambda name, ffmpeg_path=None: True
    )

    command, fallback, _ = ffmpeg.build_video_commands(
        "input.mp4",
        "audio.wav",
        "filter.txt",
        "output.mp4",
        hardware_backend="cuda",
        optimize=True,
        small=True,
        frame_rate=30.0,
    )

    assert "-strict" not in command
    assert fallback is not None and "-strict" not in fallback
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_ffmpeg.py -k spherical_metadata -v`
Expected: FAIL with `TypeError: build_video_commands() got an unexpected keyword argument 'preserve_spherical'`.

- [ ] **Step 3: Implement**

In `talks_reducer/ffmpeg.py`:

1. Add `preserve_spherical: bool = False,` as the last keyword parameter of `build_video_commands` (after `cut_end_seconds`), and document it in the docstring's Args:

```
        preserve_spherical: When True the source carries 360° metadata and
            ``-strict unofficial`` is added so the MOV muxer writes its
            ``sv3d``/``st3d`` boxes into the output.
```

2. Replace the `audio_parts.extend([...])` block with:

```python
    if preserve_spherical:
        from .spherical import PRESERVE_SPHERICAL_ARGS

        audio_parts.append(PRESERVE_SPHERICAL_ARGS)

    audio_parts.extend(
        [
            f'"{output_file}"',
            "-loglevel warning -stats -hide_banner",
        ]
    )
```

`audio_parts` is shared by the primary and fallback command, so both get the flag. (Local import avoids a cycle: `spherical` imports `ffmpeg` lazily too.)

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest tests/test_ffmpeg.py -v`
Expected: all PASS.

- [ ] **Step 5: Format and commit**

```bash
.venv/Scripts/python -m black talks_reducer/ffmpeg.py tests/test_ffmpeg.py
.venv/Scripts/python -m isort talks_reducer/ffmpeg.py tests/test_ffmpeg.py
git add talks_reducer/ffmpeg.py tests/test_ffmpeg.py
git commit -m "feat: Keep 360 metadata in the final encode command"
```

---

### Task 3: Gluing keeps 360° metadata

**Files:**
- Modify: `talks_reducer/glue.py` (`build_concat_copy_command` ~line 119, `concatenate_media` ~line 214)
- Test: `tests/test_glue.py`

**Interfaces:**
- Consumes: `spherical.probe_spherical`, `spherical.PRESERVE_SPHERICAL_ARGS`, `spherical.SphericalInfo`
- Produces: `build_concat_copy_command(list_file, destination, *, ffmpeg_path=None, preserve_spherical: bool = False) -> str`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_glue.py` (add `from talks_reducer import spherical` to the imports):

```python
def _spherical_first_part(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every probed part look like an equirectangular 360° video."""

    monkeypatch.setattr(
        spherical,
        "probe_spherical",
        lambda path: spherical.SphericalInfo(projection="equirectangular"),
    )


def test_concatenate_media_copy_keeps_360_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _spherical_first_part(monkeypatch)
    monkeypatch.setattr(glue, "_probe_streams", lambda path: _signature(320, 240))
    runner = _RecordingRunner()

    glue.concatenate_media(
        _make_inputs(tmp_path),
        tmp_path / "glued.mp4",
        ffmpeg_path="/usr/bin/ffmpeg",
        runner=runner,
    )

    command = runner.commands[0]
    assert "-c copy" in command
    assert "-strict unofficial" in command
    assert command.index("-strict unofficial") < command.index("glued.mp4")


def test_concatenate_media_copy_of_flat_video_has_no_strict_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(glue, "_probe_streams", lambda path: _signature(320, 240))
    runner = _RecordingRunner()

    glue.concatenate_media(
        _make_inputs(tmp_path),
        tmp_path / "glued.mp4",
        ffmpeg_path="/usr/bin/ffmpeg",
        runner=runner,
    )

    assert "-strict" not in runner.commands[0]


def test_concatenate_media_warns_when_reencode_drops_360_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _spherical_first_part(monkeypatch)
    inputs = _make_inputs(tmp_path)
    sizes = {inputs[0]: _signature(320, 240), inputs[1]: _signature(640, 480)}
    monkeypatch.setattr(glue, "_probe_streams", lambda path: sizes[Path(path)])
    reporter = _StubReporter()

    glue.concatenate_media(
        inputs,
        tmp_path / "glued.mp4",
        ffmpeg_path="/usr/bin/ffmpeg",
        reporter=reporter,
        runner=_RecordingRunner(),
    )

    assert any(
        "360° metadata will not be preserved" in message
        for message in reporter.messages
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_glue.py -k "360" -v`
Expected: `test_concatenate_media_copy_keeps_360_metadata` and the warning test FAIL (no `-strict unofficial`, no warning); the flat-video test passes already.

- [ ] **Step 3: Implement**

In `talks_reducer/glue.py`:

1. Import: `from . import spherical` (next to the other relative imports).

2. Replace `build_concat_copy_command` with:

```python
def build_concat_copy_command(
    list_file: Path | str,
    destination: Path | str,
    *,
    ffmpeg_path: Optional[str] = None,
    preserve_spherical: bool = False,
) -> str:
    """Build the stream-copy concatenation command for a demuxer *list_file*.

    ``preserve_spherical`` adds ``-strict unofficial`` so the MOV muxer writes
    the 360° ``sv3d``/``st3d`` boxes the copied video stream carries.
    """

    ffmpeg_path = ffmpeg_path or get_ffmpeg_path()
    parts = [
        f'"{ffmpeg_path}"',
        "-y",
        "-f concat",
        "-safe 0",
        f'-i "{list_file}"',
        "-c copy",
    ]
    if preserve_spherical:
        parts.append(spherical.PRESERVE_SPHERICAL_ARGS)
    parts.extend([f'"{destination}"', _FFMPEG_LOG_ARGS])
    return " ".join(parts)
```

3. In `concatenate_media`, after `list_file.write_text(...)`, add:

```python
    spherical_info = spherical.probe_spherical(inputs[0])
```

4. At the start of the inner `_reencode()` function body add:

```python
        if spherical_info is not None and reporter is not None:
            reporter.log(
                "360° metadata will not be preserved: "
                "the parts use different stream parameters."
            )
```

5. In the copy branch pass the flag:

```python
                _run(
                    build_concat_copy_command(
                        list_file,
                        destination,
                        ffmpeg_path=ffmpeg_path,
                        preserve_spherical=spherical_info is not None,
                    ),
                    "Gluing:",
                )
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest tests/test_glue.py -v`
Expected: all PASS.

- [ ] **Step 5: Format and commit**

```bash
.venv/Scripts/python -m black talks_reducer/glue.py tests/test_glue.py
.venv/Scripts/python -m isort talks_reducer/glue.py tests/test_glue.py
git add talks_reducer/glue.py tests/test_glue.py
git commit -m "feat: Keep 360 metadata when gluing videos"
```

---

### Task 4: Pipeline uses `v360` and passes `preserve_spherical`

**Files:**
- Modify: `talks_reducer/pipeline.py` (`PipelineDependencies` ~line 41, `_build_scale_only_filter_graph` ~line 123, `speed_up_video` metadata ~line 307, speed-up filter graph ~line 512, `build_video_commands` call ~line 560)
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `spherical.probe_spherical`, `spherical.spherical_scale_filter`, `spherical.EQUIRECTANGULAR`, `spherical.SphericalInfo`, `build_video_commands(..., preserve_spherical=...)` from Task 2.
- Produces:
  - `PipelineDependencies.probe_spherical: Callable[[Path], SphericalInfo | None] | None = None` (resolved in `__post_init__` to `spherical.probe_spherical`, looked up at instantiation so the conftest stub applies).
  - `_scale_filter_part(options, *, original_width: float, original_height: float, spherical_info: SphericalInfo | None, reporter) -> str | None`
  - `_build_scale_only_filter_graph(..., original_width: float = 0.0, spherical_info: SphericalInfo | None = None)`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pipeline.py` (add `from talks_reducer import spherical` to the imports if missing). The helper mirrors `_run_no_audio_pipeline` but returns the filter graph text too:

```python
def _run_spherical_pipeline(tmp_path, monkeypatch, *, info, small=True):
    """Drive the no-audio branch with a stubbed spherical probe.

    Returns ``(video_kwargs, filter_text, log_lines)``.
    """

    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"fake")
    metadata = {
        "frame_rate": 30.0,
        "duration": 10.0,
        "frame_count": 300,
        "width": 7680.0,
        "height": 3840.0,
    }
    monkeypatch.setattr(
        pipeline, "_extract_video_metadata", lambda path, frame_rate: dict(metadata)
    )
    monkeypatch.setattr(audio_module, "has_audio_stream", lambda path: False)

    captured = {}

    def fake_build_video_commands(*args, **kwargs):
        captured.update(kwargs)
        filter_script = args[2]
        captured["filter_text"] = (
            Path(filter_script).read_text(encoding="utf-8") if filter_script else ""
        )
        return "video-command", None, False

    dependencies = pipeline.PipelineDependencies(
        get_ffmpeg_path=lambda prefer_global=False: "ffmpeg",
        detect_hardware_backend=lambda _codec, _path: None,
        build_video_commands=fake_build_video_commands,
        run_timed_ffmpeg_command=lambda command, **kwargs: None,
        probe_spherical=lambda path: info,
    )

    class _Reporter(NullProgressReporter):
        def __init__(self):
            super().__init__()
            self.lines = []

        def log(self, message):
            self.lines.append(message)

    reporter = _Reporter()
    options = ProcessingOptions(
        input_file=input_file,
        output_file=tmp_path / "output.mp4",
        temp_folder=tmp_path / "temp",
        small=small,
        small_target_height=720,
    )

    pipeline.speed_up_video(options, reporter=reporter, dependencies=dependencies)

    return captured, captured["filter_text"], reporter.lines


def test_speed_up_video_scales_equirectangular_with_v360(tmp_path, monkeypatch):
    info = spherical.SphericalInfo(projection="equirectangular", stereo="2D")

    kwargs, filter_text, lines = _run_spherical_pipeline(
        tmp_path, monkeypatch, info=info
    )

    assert "v360=e:e:w=1440:h=720" in filter_text
    assert "scale=" not in filter_text
    assert kwargs["preserve_spherical"] is True
    assert any("Preserving 360° metadata (equirectangular)" in l for l in lines)


def test_speed_up_video_flat_video_keeps_scale_filter(tmp_path, monkeypatch):
    kwargs, filter_text, _ = _run_spherical_pipeline(tmp_path, monkeypatch, info=None)

    assert "scale=-2:720" in filter_text
    assert "v360" not in filter_text
    assert kwargs["preserve_spherical"] is False


def test_speed_up_video_warns_for_unsupported_projection(tmp_path, monkeypatch):
    info = spherical.SphericalInfo(projection="cubemap")

    kwargs, filter_text, lines = _run_spherical_pipeline(
        tmp_path, monkeypatch, info=info
    )

    assert "scale=-2:720" in filter_text
    assert kwargs["preserve_spherical"] is True
    assert any("360° metadata will not be preserved" in l for l in lines)


def test_speed_up_video_spherical_without_scaling_keeps_flag(tmp_path, monkeypatch):
    info = spherical.SphericalInfo(projection="equirectangular")

    kwargs, filter_text, _ = _run_spherical_pipeline(
        tmp_path, monkeypatch, info=info, small=False
    )

    assert "v360" not in filter_text and "scale=" not in filter_text
    assert kwargs["preserve_spherical"] is True
```

Also add a test for the speed-up (audio) branch's filter graph by reusing the existing audio-path test helper in `tests/test_pipeline.py`, if one exists: search with `grep -n "filterGraph\|setpts" tests/test_pipeline.py`. If a test already drives the audio branch and reads `filterGraph.txt`, copy it into `test_speed_up_video_audio_branch_uses_v360_for_equirectangular`, pass `probe_spherical=lambda path: spherical.SphericalInfo(projection="equirectangular")` and metadata `width=7680.0, height=3840.0`, and assert `"v360=e:e:w=1440:h=720" in filter_text` and `"setpts=" in filter_text`. If no such test exists, the shared `_scale_filter_part` (Step 3) is the single code path for both branches and the no-audio tests cover it; note that in the commit message.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_pipeline.py -k "spherical or v360 or projection" -v`
Expected: FAIL with `TypeError: PipelineDependencies.__init__() got an unexpected keyword argument 'probe_spherical'`.

- [ ] **Step 3: Implement**

In `talks_reducer/pipeline.py`:

1. Imports: `from . import spherical as spherical_utils` and `from .spherical import SphericalInfo` (module alias avoids clashing with local names).

2. `PipelineDependencies`: add a field after `delete_path`:

```python
    probe_spherical: Callable[[Path], SphericalInfo | None] | None = None
```

and in `__post_init__`:

```python
        if self.probe_spherical is None:
            # Looked up now, not at class definition, so tests can stub it.
            self.probe_spherical = spherical_utils.probe_spherical
```

3. Add the shared helper above `_build_scale_only_filter_graph`:

```python
def _scale_filter_part(
    options: ProcessingOptions,
    *,
    original_width: float,
    original_height: float,
    spherical_info: SphericalInfo | None,
    reporter: ProgressReporter,
) -> str | None:
    """Return the downscale filter for ``--small``, or ``None`` when not scaling.

    Flat videos get ``scale=-2:H``. Equirectangular 360° sources get ``v360``
    instead, because ``scale`` drops their Spherical Mapping metadata; other
    360° projections still use ``scale`` and the loss is logged.
    """

    if not options.small:
        return None
    target_height = options.small_target_height or 720
    if target_height <= 0:
        target_height = 720
    if not (original_height > 0 and original_height >= target_height):
        reporter.log(
            f"Keeping original resolution {int(original_height)}p (smaller than target {target_height}p)"
        )
        return None

    reporter.log(f"Scaling down from {int(original_height)}p to {target_height}p")
    if spherical_info is not None:
        if (
            spherical_info.projection == spherical_utils.EQUIRECTANGULAR
            and original_width > 0
        ):
            return spherical_utils.spherical_scale_filter(
                int(original_width), int(original_height), target_height
            )
        reporter.log(
            "360° metadata will not be preserved: scaling a "
            f"{spherical_info.projection} projection is not supported."
        )
    return f"scale=-2:{target_height}"
```

4. `_build_scale_only_filter_graph`: add keyword params `original_width: float = 0.0, spherical_info: SphericalInfo | None = None`, and replace its whole `if options.small: ...` block with:

```python
    filter_parts: list[str] = []
    scale_part = _scale_filter_part(
        options,
        original_width=original_width,
        original_height=original_height,
        spherical_info=spherical_info,
        reporter=reporter,
    )
    if scale_part:
        filter_parts.append(scale_part)
```

5. In `speed_up_video`, right after `is_mp3_output = ...` (line ~361), add:

```python
    spherical_info = (
        dependencies.probe_spherical(input_path)
        if has_video_stream and not is_mp3_output
        else None
    )
    if spherical_info is not None:
        reporter.log(f"Preserving 360° metadata ({spherical_info.projection})")
```

6. In the speed-up filter graph block (~line 512), replace the `if options.small: ...` block with:

```python
            filter_parts = []
            scale_part = _scale_filter_part(
                options,
                original_width=original_width,
                original_height=original_height,
                spherical_info=spherical_info,
                reporter=reporter,
            )
            if scale_part:
                filter_parts.append(scale_part)
```

7. In the `_build_scale_only_filter_graph(...)` call add `original_width=original_width, spherical_info=spherical_info,`.

8. In the `dependencies.build_video_commands(...)` call add `preserve_spherical=spherical_info is not None,`.

- [ ] **Step 4: Run the whole suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all PASS. The log text for flat videos ("Scaling down from …", "Keeping original resolution …") is unchanged, so existing assertions still hold.

- [ ] **Step 5: Format and commit**

```bash
.venv/Scripts/python -m black talks_reducer/pipeline.py tests/test_pipeline.py
.venv/Scripts/python -m isort talks_reducer/pipeline.py tests/test_pipeline.py
git add talks_reducer/pipeline.py tests/test_pipeline.py
git commit -m "feat: Keep 360 metadata in processed videos"
```

---

### Task 5: Real-file verification and README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Make two short 360° clips** (any equirectangular source; the dev machine has `C:\Users\popstas\Videos\360\VID_20261024_144609_00_027.mp4`). Use the bundled FFmpeg so the version matches the app:

```bash
FF=".venv/Lib/site-packages/static_ffmpeg/bin/win32/ffmpeg.exe"
SRC="C:/Users/popstas/Videos/360/VID_20261024_144609_00_027.mp4"
"$FF" -v error -y -ss 10 -t 3 -i "$SRC" -c copy -strict unofficial "$TMP/a.mp4"
"$FF" -v error -y -ss 20 -t 3 -i "$SRC" -c copy -strict unofficial "$TMP/b.mp4"
```

(`$TMP` = a scratch directory outside the repo.)

- [ ] **Step 2: Glue + process with the CLI** (720p, h.264 and h.265):

```bash
.venv/Scripts/python -m talks_reducer --glue --small --720 "$TMP/a.mp4" "$TMP/b.mp4" -o "$TMP/out_h264.mp4"
.venv/Scripts/python -m talks_reducer --glue --small --720 --video-codec hevc "$TMP/a.mp4" "$TMP/b.mp4" -o "$TMP/out_hevc.mp4"
```

Check the exact flag names first with `.venv/Scripts/python -m talks_reducer --help` (`--glue`, codec option) and adjust.

- [ ] **Step 3: Verify the tags**

```bash
FP=".venv/Lib/site-packages/static_ffmpeg/bin/win32/ffprobe.exe"
for f in "$TMP"/out_*.mp4; do "$FP" -v error -select_streams v:0 -show_entries stream=width,height:stream_side_data=side_data_type,projection -of compact "$f"; done
```

Expected for each: `width=1440|height=720|…Stereo 3D…|…Spherical Mapping…|projection=equirectangular`. If the hardware encoder ran (log says `Processing on: GPU`), record which one in the PR description; GPU encoders were not verified during design.

- [ ] **Step 4: Update README.md**

Add a short subsection near the processing/glue docs:

```markdown
### 360° videos

Equirectangular 360° recordings keep their 360° metadata (Spherical Mapping
and Stereo 3D) through gluing and processing, so players still show them as
a sphere. With a smaller resolution preset the frame is rescaled with FFmpeg's
`v360` filter instead of `scale`, which would drop the metadata.

Limitations: other projections (cubemap, EAC) keep the metadata only at
`orig` resolution; gluing 360° parts with different resolutions or codecs
re-encodes them and drops it. Both cases are reported in the log.
```

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: Describe 360 video metadata support"
```
