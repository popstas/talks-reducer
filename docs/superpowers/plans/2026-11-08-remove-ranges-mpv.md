# Remove Middle Fragments via mpv.net — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user mark fragments to remove in mpv.net (keys `c`/`C`) and drop them either while converting a source or in a fast "Remove only" pass over a finished file.

**Architecture:** Marks live in a `<video>.cuts.json` sidecar handled by a new pure module `talks_reducer/cut_marks.py`. A Lua script shipped in `talks_reducer/resources/` does the marking inside the player. The pipeline turns remove ranges into chunks with an infinite speed (zero output samples, frames collapsed by `setpts`), so both scenarios use the normal pipeline; "Remove only" is just speeds 1/1, orig resolution and fps.

**Tech Stack:** Python 3.13 (`.venv`), NumPy, FFmpeg, Tkinter/ttk, mpv Lua API, pytest.

**Spec:** `docs/superpowers/specs/2026-11-08-remove-ranges-mpv-design.md`

## Global Constraints

- Python commands run from the repo root with `.venv/Scripts/python.exe` (Windows) — never the system Python.
- Run `.venv/Scripts/python.exe -m black talks_reducer tests` and `.venv/Scripts/python.exe -m isort talks_reducer tests` before every commit.
- New logic gets function-level docstrings, not inline comments.
- Every `subprocess.run/Popen/...` passes `**hidden_subprocess_kwargs()` (`tests/test_no_console_windows.py` enforces it).
- Remove ranges are **local-only**: remote runs with ranges fail with exactly `Remove ranges are local-only`.
- A GUI run with ranges and more than one resolved file fails with exactly `Remove ranges apply to a single file`.
- Sidecar name: `<video file name>.cuts.json`; JSON `{"version": 1, "source": "<name>", "remove": [[start, end], ...]}`.
- Lua script file name: `talks_reducer_cuts.lua`; script-opts key: `talks_reducer_cuts-file`.
- Output name token for runs with ranges: `cut` (e.g. `lecture_speedup_cut.mp4`).
- Simple mode ignores ranges; ranges apply only with **Cut video** on in Advanced mode.
- mpv.net releases URL: `https://github.com/mpvnet-player/mpv.net/releases`.
- Commit messages use the angular format; end each with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## File Structure

| File | Responsibility |
| --- | --- |
| `talks_reducer/cut_marks.py` (new) | Range normalisation, text parse/format, marks JSON + sidecar I/O, player discovery and launch command. No Tk. |
| `talks_reducer/resources/talks_reducer_cuts.lua` (new) | In-player marking UI. |
| `talks_reducer/chunks.py` | `REMOVED_SPEED_INDEX`, `apply_remove_ranges`. |
| `talks_reducer/audio.py` | Infinite speed → zero samples, never sent to the worker pool. |
| `talks_reducer/models.py` | `ProcessingOptions.remove_ranges`. |
| `talks_reducer/pipeline.py` | Shift ranges into the trim window, mark chunks, force the speed path, `cut` output token. |
| `talks_reducer/cli.py` | `--remove`, `--remove-file`, remote rejection. |
| `talks_reducer/gui/cut_marks_ui.py` (new) | GUI glue: load/commit/open-player/remove-only overrides; takes the `gui` object. |
| `talks_reducer/gui/layout.py`, `gui/app.py` | Widgets in the Cut panel and wiring. |
| `pyproject.toml`, `talks-reducer.spec` | Ship the Lua script. |
| `README.md`, `CLAUDE.md` | Docs. |

---

### Task 1: `cut_marks` — ranges, text and sidecar I/O

**Files:**
- Create: `talks_reducer/cut_marks.py`
- Test: `tests/test_cut_marks.py`

**Interfaces:**
- Produces:
  - `RemoveRange = Tuple[float, float]`
  - `normalize_ranges(ranges: Iterable[Sequence[float]]) -> List[RemoveRange]`
  - `parse_ranges_text(text: str) -> List[RemoveRange]` (raises `ValueError`)
  - `format_ranges_text(ranges: Iterable[Sequence[float]]) -> str`
  - `sidecar_path(video: Path) -> Path`
  - `read_marks_file(path: Path) -> List[RemoveRange]`
  - `write_marks_file(path: Path, ranges, source_name: str) -> None`
  - `load_marks(video: Path) -> List[RemoveRange]`
  - `save_marks(video: Path, ranges) -> None`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for remove-range marks: parsing, formatting and the sidecar file."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from talks_reducer import cut_marks


def test_normalize_ranges_sorts_merges_and_drops_invalid() -> None:
    ranges = [(30, 40), (10, 20), (15, 25), (50, 50), (60, 55), ("x", 1), (-5, 2)]

    assert cut_marks.normalize_ranges(ranges) == [(0.0, 2.0), (10.0, 25.0), (30.0, 40.0)]


def test_normalize_ranges_merges_touching_ranges() -> None:
    assert cut_marks.normalize_ranges([(1, 2), (2, 3)]) == [(1.0, 3.0)]


def test_parse_ranges_text_accepts_clock_and_seconds() -> None:
    text = "1:20-1:45, 12:00 - 12:30.5,5–7"

    assert cut_marks.parse_ranges_text(text) == [
        (5.0, 7.0),
        (80.0, 105.0),
        (720.0, 750.5),
    ]


def test_parse_ranges_text_empty_is_empty_list() -> None:
    assert cut_marks.parse_ranges_text("  ") == []


@pytest.mark.parametrize("text", ["1:20", "a-b", "1:45-1:20", "1-2-3"])
def test_parse_ranges_text_rejects_bad_tokens(text: str) -> None:
    with pytest.raises(ValueError):
        cut_marks.parse_ranges_text(text)


def test_format_ranges_text_round_trips() -> None:
    ranges = [(80.0, 105.0), (720.0, 750.5)]

    text = cut_marks.format_ranges_text(ranges)

    assert text == "00:01:20-00:01:45, 00:12:00-00:12:30.500"
    assert cut_marks.parse_ranges_text(text) == ranges


def test_sidecar_path_appends_suffix() -> None:
    assert cut_marks.sidecar_path(Path("/v/lecture.mp4")) == Path(
        "/v/lecture.mp4.cuts.json"
    )


def test_save_and_load_marks(tmp_path: Path) -> None:
    video = tmp_path / "лекция.mp4"
    video.write_bytes(b"")

    cut_marks.save_marks(video, [(30, 40), (10, 20)])

    payload = json.loads(cut_marks.sidecar_path(video).read_text("utf-8"))
    assert payload == {
        "version": 1,
        "source": "лекция.mp4",
        "remove": [[10.0, 20.0], [30.0, 40.0]],
    }
    assert cut_marks.load_marks(video) == [(10.0, 20.0), (30.0, 40.0)]


def test_save_empty_marks_deletes_sidecar(tmp_path: Path) -> None:
    video = tmp_path / "a.mp4"
    cut_marks.save_marks(video, [(1, 2)])

    cut_marks.save_marks(video, [])

    assert not cut_marks.sidecar_path(video).exists()


def test_read_marks_file_tolerates_missing_and_bad_files(tmp_path: Path) -> None:
    assert cut_marks.read_marks_file(tmp_path / "missing.json") == []

    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert cut_marks.read_marks_file(bad) == []

    future = tmp_path / "future.json"
    future.write_text(json.dumps({"version": 2, "remove": [[1, 2]]}), "utf-8")
    assert cut_marks.read_marks_file(future) == []


def test_read_marks_file_accepts_empty_object_from_lua(tmp_path: Path) -> None:
    path = tmp_path / "m.json"
    path.write_text('{"version": 1, "source": "a.mp4", "remove": {}}', "utf-8")

    assert cut_marks.read_marks_file(path) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cut_marks.py -v`
Expected: FAIL — `ImportError: cannot import name 'cut_marks'`.

- [ ] **Step 3: Implement**

```python
"""Remove-range marks: parsing, the ``.cuts.json`` sidecar and the mpv launcher.

A *remove range* is a ``(start, end)`` pair in seconds of one specific file.
Marks made on a source and on its processed output are different files with
different timelines, so each video keeps its own sidecar next to it.
"""

from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

from .timecode import format_timecode, parse_timecode

RemoveRange = Tuple[float, float]

MARKS_VERSION = 1
SIDECAR_SUFFIX = ".cuts.json"

_LOGGER = logging.getLogger(__name__)


def normalize_ranges(ranges: Iterable[Sequence[float]]) -> List[RemoveRange]:
    """Return *ranges* validated, sorted and with overlapping ranges merged.

    Pairs that are not two finite numbers, or whose end is not after the start,
    are dropped. Negative starts are clamped to zero. Touching ranges merge.
    """

    cleaned: List[RemoveRange] = []
    for item in ranges:
        try:
            start, end = float(item[0]), float(item[1])
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        if not (math.isfinite(start) and math.isfinite(end)):
            continue
        start = max(0.0, start)
        if end <= start:
            continue
        cleaned.append((start, end))

    cleaned.sort()
    merged: List[RemoveRange] = []
    for start, end in cleaned:
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def parse_ranges_text(text: str) -> List[RemoveRange]:
    """Parse ``"1:20-1:45, 12:00-12:30.5"`` into normalised ranges.

    Each bound accepts anything :func:`talks_reducer.timecode.parse_timecode`
    does. An en dash is accepted as the separator because the player's OSD
    shows one. Raises :class:`ValueError` naming the offending token.
    """

    ranges: List[RemoveRange] = []
    for token in str(text or "").replace("–", "-").split(","):
        token = token.strip()
        if not token:
            continue
        bounds = token.split("-")
        if len(bounds) != 2:
            raise ValueError(f"Invalid range {token!r}: use START-END")
        try:
            start = parse_timecode(bounds[0].strip())
            end = parse_timecode(bounds[1].strip())
        except ValueError as exc:
            raise ValueError(f"Invalid range {token!r}: {exc}") from exc
        if end <= start:
            raise ValueError(f"Invalid range {token!r}: end must be after start")
        ranges.append((start, end))
    return normalize_ranges(ranges)


def _format_bound(seconds: float) -> str:
    """Format one bound, adding milliseconds only when the value has them."""

    if abs(seconds - round(seconds)) < 0.0005:
        return format_timecode(int(round(seconds)))
    return format_timecode(seconds, milliseconds=True)


def format_ranges_text(ranges: Iterable[Sequence[float]]) -> str:
    """Return the editable ``START-END, START-END`` text for *ranges*."""

    return ", ".join(
        f"{_format_bound(start)}-{_format_bound(end)}"
        for start, end in normalize_ranges(ranges)
    )


def sidecar_path(video: Path) -> Path:
    """Return the ``<video name>.cuts.json`` path next to *video*."""

    video = Path(video)
    return video.with_name(video.name + SIDECAR_SUFFIX)


def read_marks_file(path: Path) -> List[RemoveRange]:
    """Return the ranges stored in a marks JSON file, or ``[]``.

    A missing file is silent; unreadable JSON or an unknown version is logged
    as a warning and treated as no marks.
    """

    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        _LOGGER.warning("Cannot read marks file %s: %s", path, exc)
        return []
    try:
        data = json.loads(text)
    except ValueError as exc:
        _LOGGER.warning("Ignoring malformed marks file %s: %s", path, exc)
        return []
    if not isinstance(data, dict) or data.get("version") != MARKS_VERSION:
        _LOGGER.warning("Ignoring marks file %s with unknown version", path)
        return []
    remove = data.get("remove") or []
    if not isinstance(remove, list):
        return []
    return normalize_ranges(remove)


def write_marks_file(
    path: Path, ranges: Iterable[Sequence[float]], source_name: str
) -> None:
    """Atomically write *ranges* to *path* in the marks JSON format."""

    path = Path(path)
    payload = {
        "version": MARKS_VERSION,
        "source": source_name,
        "remove": [[start, end] for start, end in normalize_ranges(ranges)],
    }
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def load_marks(video: Path) -> List[RemoveRange]:
    """Return the marks saved next to *video*."""

    return read_marks_file(sidecar_path(video))


def save_marks(video: Path, ranges: Iterable[Sequence[float]]) -> None:
    """Save *ranges* next to *video*; an empty list deletes the sidecar."""

    video = Path(video)
    normalized = normalize_ranges(ranges)
    target = sidecar_path(video)
    if not normalized:
        target.unlink(missing_ok=True)
        return
    write_marks_file(target, normalized, video.name)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cut_marks.py -v`
Expected: all PASS.

- [ ] **Step 5: Format and commit**

```bash
.venv/Scripts/python.exe -m black talks_reducer tests && .venv/Scripts/python.exe -m isort talks_reducer tests
git add talks_reducer/cut_marks.py tests/test_cut_marks.py
git commit -m "feat: Add remove-range marks module with .cuts.json sidecar"
```

---

### Task 2: `chunks.apply_remove_ranges`

**Files:**
- Modify: `talks_reducer/chunks.py`
- Test: `tests/test_chunks.py`

**Interfaces:**
- Consumes: normalised `List[RemoveRange]` (Task 1) — but must also sort defensively.
- Produces:
  - `REMOVED_SPEED_INDEX = 2`
  - `apply_remove_ranges(chunks: Sequence[Sequence[int]], ranges: Sequence[Tuple[float, float]], frame_rate: float) -> List[List[int]]` — chunks are `[start_frame, end_frame, speed_index]`; returned pieces inside a range carry `REMOVED_SPEED_INDEX`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_chunks.py`; extend the import line to `from talks_reducer.chunks import REMOVED_SPEED_INDEX, apply_remove_ranges, build_chunks, detect_loud_frames, get_tree_expression`)

```python
R = REMOVED_SPEED_INDEX


def test_apply_remove_ranges_no_ranges_returns_copy() -> None:
    chunks = [[0, 10, 1]]

    result = apply_remove_ranges(chunks, [], 10.0)

    assert result == [[0, 10, 1]]
    assert result[0] is not chunks[0]


def test_apply_remove_ranges_inside_one_chunk() -> None:
    assert apply_remove_ranges([[0, 100, 1]], [(2.0, 3.0)], 10.0) == [
        [0, 20, 1],
        [20, 30, R],
        [30, 100, 1],
    ]


def test_apply_remove_ranges_spanning_chunks_merges_removed_pieces() -> None:
    chunks = [[0, 20, 1], [20, 40, 0], [40, 60, 1]]

    assert apply_remove_ranges(chunks, [(1.5, 4.5)], 10.0) == [
        [0, 15, 1],
        [15, 45, R],
        [45, 60, 1],
    ]


def test_apply_remove_ranges_at_start_and_end() -> None:
    assert apply_remove_ranges([[0, 50, 1]], [(0.0, 1.0), (4.0, 9.0)], 10.0) == [
        [0, 10, R],
        [10, 40, 1],
        [40, 50, R],
    ]


def test_apply_remove_ranges_ignores_ranges_past_the_end() -> None:
    assert apply_remove_ranges([[0, 50, 1]], [(6.0, 8.0)], 10.0) == [[0, 50, 1]]


def test_apply_remove_ranges_unsorted_input() -> None:
    assert apply_remove_ranges([[0, 100, 1]], [(5.0, 6.0), (1.0, 2.0)], 10.0) == [
        [0, 10, 1],
        [10, 20, R],
        [20, 50, 1],
        [50, 60, R],
        [60, 100, 1],
    ]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_chunks.py -v`
Expected: FAIL — `ImportError: cannot import name 'REMOVED_SPEED_INDEX'`.

- [ ] **Step 3: Implement** (in `talks_reducer/chunks.py`, before `get_tree_expression`; add both names to `__all__`)

```python
REMOVED_SPEED_INDEX = 2


def apply_remove_ranges(
    chunks: Sequence[Sequence[int]],
    ranges: Sequence[Tuple[float, float]],
    frame_rate: float,
) -> List[List[int]]:
    """Split *chunks* at the remove ranges and mark the pieces inside them.

    Chunks are ``[start_frame, end_frame, speed_index]`` in source frames.
    Each range in seconds becomes ``[round(start * fps), round(end * fps))``;
    pieces inside a range get :data:`REMOVED_SPEED_INDEX`, whose speed the
    pipeline sets to infinity so the piece produces no output. Adjacent removed
    pieces are merged and zero-length pieces are never emitted.
    """

    if not ranges or frame_rate <= 0:
        return [list(chunk) for chunk in chunks]

    frame_ranges = sorted(
        (max(0, int(round(start * frame_rate))), int(round(end * frame_rate)))
        for start, end in ranges
    )
    frame_ranges = [(a, b) for a, b in frame_ranges if b > a]

    pieces: List[List[int]] = []
    for chunk in chunks:
        start, end, speed = int(chunk[0]), int(chunk[1]), int(chunk[2])
        cursor = start
        for cut_start, cut_end in frame_ranges:
            if cut_end <= cursor or cut_start >= end:
                continue
            if cut_start > cursor:
                pieces.append([cursor, cut_start, speed])
            piece_end = min(cut_end, end)
            pieces.append([max(cut_start, cursor), piece_end, REMOVED_SPEED_INDEX])
            cursor = piece_end
        if cursor < end:
            pieces.append([cursor, end, speed])

    merged: List[List[int]] = []
    for piece in pieces:
        if (
            merged
            and piece[2] == REMOVED_SPEED_INDEX
            and merged[-1][2] == REMOVED_SPEED_INDEX
            and merged[-1][1] == piece[0]
        ):
            merged[-1][1] = piece[1]
        else:
            merged.append(piece)
    return merged
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_chunks.py -v`
Expected: all PASS.

- [ ] **Step 5: Format and commit**

```bash
.venv/Scripts/python.exe -m black talks_reducer tests && .venv/Scripts/python.exe -m isort talks_reducer tests
git add talks_reducer/chunks.py tests/test_chunks.py
git commit -m "feat: Split chunks at remove ranges"
```

---

### Task 3: Audio — infinite speed emits nothing

**Files:**
- Modify: `talks_reducer/audio.py` (`render_chunk` ~L110, `_collect_vocoder_jobs` ~L146)
- Test: `tests/test_audio.py`

**Interfaces:**
- Consumes: `speeds[2] == math.inf` for `REMOVED_SPEED_INDEX` chunks (Task 2).
- Produces: `render_chunk(chunk, math.inf, ...)` returns `np.zeros((0, channels), dtype=np.float32)`; `_collect_vocoder_jobs` never returns jobs with infinite speed.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_audio.py`; add `import math` at the top)

```python
def test_render_chunk_infinite_speed_returns_no_samples() -> None:
    chunk = np.ones((500, 2), dtype=np.float32)

    result = audio.render_chunk(chunk, math.inf, 10, 1.0)

    assert result.shape == (0, 2)


def test_collect_vocoder_jobs_skips_removed_chunks() -> None:
    jobs, estimated = audio._collect_vocoder_jobs(
        [[0, 10, 0], [10, 20, 2]], 100.0, [4.0, 1.0, math.inf]
    )

    assert [job[0] for job in jobs] == [0]
    assert estimated == 250


def test_process_audio_chunks_drops_removed_chunk() -> None:
    audio_data = np.ones((3000, 2), dtype=np.float32)
    chunks = [[0, 10, 0], [10, 20, 2], [20, 30, 1]]

    output, updated = audio.process_audio_chunks(
        audio_data, chunks, 100.0, [1.0, 1.0, math.inf], 10, 1.0
    )

    assert output.shape[0] == 2000
    assert updated[1][2] == updated[1][3] == 10
    assert updated[2][2:] == [10, 20]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_audio.py -k "infinite or removed" -v`
Expected: FAIL (phase vocoder error / job included).

- [ ] **Step 3: Implement**

In `render_chunk`, as the first statement after the docstring:

```python
    if math.isinf(speed):
        channels = audio_chunk.shape[1] if audio_chunk.ndim > 1 else 1
        return np.zeros((0, channels), dtype=np.float32)
```

and extend its docstring with: "An infinite *speed* marks a removed fragment and yields no samples."

In `_collect_vocoder_jobs`, replace

```python
        if math.isclose(speed, 1.0, rel_tol=1e-9, abs_tol=1e-9):
            continue
```

with

```python
        if math.isinf(speed) or math.isclose(speed, 1.0, rel_tol=1e-9, abs_tol=1e-9):
            continue
```

and add to its docstring: "Removed fragments (infinite speed) emit nothing and are excluded too."

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_audio.py tests/test_audio_workers.py -v`
Expected: all PASS.

- [ ] **Step 5: Format and commit**

```bash
.venv/Scripts/python.exe -m black talks_reducer tests && .venv/Scripts/python.exe -m isort talks_reducer tests
git add talks_reducer/audio.py tests/test_audio.py
git commit -m "feat: Emit no audio for removed chunks"
```

---

### Task 4: Pipeline — `remove_ranges` end to end (risk check first)

**Files:**
- Modify: `talks_reducer/models.py:36-73`
- Modify: `talks_reducer/pipeline.py` (`resolve_output_path` L342, `_input_to_output_filename` L849, speed path ~L520–650)
- Test: `tests/test_pipeline.py`, new `tests/test_pipeline_remove_ranges_ffmpeg.py`

**Interfaces:**
- Consumes: `cut_marks.normalize_ranges` (Task 1), `chunks.apply_remove_ranges` / `REMOVED_SPEED_INDEX` (Task 2), audio infinite speed (Task 3).
- Produces:
  - `ProcessingOptions.remove_ranges: Tuple[Tuple[float, float], ...] = ()`
  - `pipeline._resolve_remove_ranges(options, cut_start: float, effective_duration: float, reporter) -> list[tuple[float, float]]`
  - `_input_to_output_filename(..., has_cut: bool = False)`; `resolve_output_path` passes `has_cut=bool(options.remove_ranges)`.

- [ ] **Step 1: Write the real-FFmpeg integration test first (this is the risk check)**

Create `tests/test_pipeline_remove_ranges_ffmpeg.py`:

```python
"""End-to-end check that remove ranges really drop frames and audio.

Runs the real pipeline on a generated clip, so it is skipped when FFmpeg is
not available. It verifies the assumption the feature rests on: frames whose
``setpts`` timestamps collapse are dropped, not muxed as duplicates.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from talks_reducer.models import ProcessingOptions
from talks_reducer.pipeline import speed_up_video
from talks_reducer.subprocess_utils import hidden_subprocess_kwargs

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="needs ffmpeg and ffprobe on PATH",
)


def _make_clip(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=size=160x120:rate=30:duration=10",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=10",
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            str(path),
        ],
        check=True,
        **hidden_subprocess_kwargs(),
    )


def _probe(path: Path) -> tuple[float, int]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
            "-show_entries", "format=duration:stream=nb_read_frames",
            "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        **hidden_subprocess_kwargs(),
    )
    data = json.loads(result.stdout)
    return float(data["format"]["duration"]), int(data["streams"][0]["nb_read_frames"])


@pytest.mark.parametrize("max_frame_rate, expected_frames", [(None, 240), (15.0, 120)])
def test_remove_range_shortens_output(
    tmp_path: Path, max_frame_rate: float | None, expected_frames: int
) -> None:
    source = tmp_path / "clip.mp4"
    _make_clip(source)
    output = tmp_path / "out.mp4"

    speed_up_video(
        ProcessingOptions(
            input_file=source,
            output_file=output,
            temp_folder=tmp_path / "temp",
            silent_speed=1.0,
            sounded_speed=1.0,
            max_frame_rate=max_frame_rate,
            remove_ranges=((3.0, 5.0),),
            prefer_global_ffmpeg=True,
        )
    )

    duration, frames = _probe(output)
    assert duration == pytest.approx(8.0, abs=0.15)
    assert abs(frames - expected_frames) <= 2
```

- [ ] **Step 2: Add the model field**

In `talks_reducer/models.py`, add the import `Tuple` to the `typing` import and append to `ProcessingOptions` after `cut_end_seconds`:

```python
    remove_ranges: Tuple[Tuple[float, float], ...] = ()
```

and add to the docstring: "``remove_ranges`` lists ``(start, end)`` fragments, in seconds of the input file, that are dropped from the output; they are applied inside the keep-range trim window."

- [ ] **Step 3: Write the unit tests for the pipeline helpers** (append to `tests/test_pipeline.py`)

```python
def test_resolve_remove_ranges_shifts_and_clips_to_trim_window() -> None:
    logs: list[str] = []
    reporter = SimpleNamespace(log=logs.append)
    options = ProcessingOptions(
        input_file=Path("in.mp4"),
        remove_ranges=((5.0, 15.0), (25.0, 40.0), (100.0, 110.0), (1.0, 2.0)),
    )

    result = pipeline._resolve_remove_ranges(
        options, cut_start=10.0, effective_duration=20.0, reporter=reporter
    )

    assert result == [(0.0, 5.0), (15.0, 20.0)]
    assert any("Ignoring 2 remove range" in line for line in logs)


def test_resolve_remove_ranges_empty_when_unset() -> None:
    reporter = SimpleNamespace(log=lambda _m: None)
    options = ProcessingOptions(input_file=Path("in.mp4"))

    assert pipeline._resolve_remove_ranges(options, 0.0, 10.0, reporter) == []


@pytest.mark.parametrize(
    "name, speeds, expected",
    [
        ("lecture.mp4", (10.0, 1.0), "lecture_speedup_cut.mp4"),
        ("lecture_speedup.mp4", (1.0, 1.0), "lecture_speedup_cut.mp4"),
    ],
)
def test_input_to_output_filename_adds_cut_token(name, speeds, expected) -> None:
    output = pipeline._input_to_output_filename(
        Path(name), silent_speed=speeds[0], sounded_speed=speeds[1], has_cut=True
    )

    assert output.name == expected
```

(If `SimpleNamespace` / `ProcessingOptions` are not yet imported in `tests/test_pipeline.py`, add `from types import SimpleNamespace` and `from talks_reducer.models import ProcessingOptions`.)

- [ ] **Step 4: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_pipeline.py -k "remove_ranges or cut_token" tests/test_pipeline_remove_ranges_ffmpeg.py -v`
Expected: FAIL — `_resolve_remove_ranges` missing, `has_cut` unexpected keyword; the ffmpeg test fails on duration ≈ 10.

- [ ] **Step 5: Implement the helpers**

In `talks_reducer/pipeline.py` add `from .cut_marks import normalize_ranges` to the imports and, after `_resolve_trim`:

```python
def _resolve_remove_ranges(
    options: ProcessingOptions,
    cut_start: float,
    effective_duration: float,
    reporter: ProgressReporter,
) -> list[tuple[float, float]]:
    """Return the remove ranges in the timeline of the trimmed input.

    Ranges are given in seconds of the input file; the keep-range trim starts
    the processed audio at ``cut_start``, so each range is shifted by it and
    clipped to ``[0, effective_duration]``. Ranges left empty are dropped and
    counted in the log.
    """

    ranges = normalize_ranges(getattr(options, "remove_ranges", ()) or ())
    if not ranges:
        return []

    shifted: list[tuple[float, float]] = []
    dropped = 0
    for start, end in ranges:
        start = max(0.0, start - cut_start)
        end = end - cut_start
        if effective_duration > 0:
            end = min(end, effective_duration)
        if end <= start:
            dropped += 1
            continue
        shifted.append((start, end))

    if dropped:
        reporter.log(f"Ignoring {dropped} remove range(s) outside the kept fragment")
    if shifted:
        total = sum(end - start for start, end in shifted)
        reporter.log(f"Removing {len(shifted)} fragment(s), {total:.2f}s in total")
    return shifted
```

In `_input_to_output_filename` add the keyword `has_cut: bool = False` after `prefer_clean_audio_name`, change

```python
    force_codec_suffix = not include_speed_marker and not small
```

to

```python
    force_codec_suffix = not include_speed_marker and not small and not has_cut
```

and right after the `if not optimize and not small:` block add:

```python
    if has_cut:
        suffix_tokens.append("cut")
```

In `resolve_output_path` pass `has_cut=bool(getattr(options, "remove_ranges", ())),` to `_input_to_output_filename`.

- [ ] **Step 6: Wire the speed path in `speed_up_video`**

1. Right after the `_resolve_trim(...)` call, add:

```python
    remove_ranges = _resolve_remove_ranges(
        options, cut_start_seconds, effective_duration, reporter
    )
```

2. In the `if not has_audio:` block (after the `reporter.log("No audio stream found...")`), add:

```python
        if remove_ranges:
            reporter.log("Warning: Remove ranges need an audio stream; ignoring them.")
            remove_ranges = []
```

3. Change `if has_audio and not neutral_speeds:` to `if has_audio and (not neutral_speeds or remove_ranges):`.

4. Replace

```python
        chunks, _ = chunk_utils.build_chunks(has_loud_audio, options.frame_spreadage)
```

with

```python
        chunks, _ = chunk_utils.build_chunks(has_loud_audio, options.frame_spreadage)
        if remove_ranges:
            chunks = chunk_utils.apply_remove_ranges(chunks, remove_ranges, frame_rate)
```

5. Replace `new_speeds = [options.silent_speed, options.sounded_speed]` with

```python
        # Index 2 is chunk_utils.REMOVED_SPEED_INDEX: removed fragments emit nothing.
        new_speeds = [options.silent_speed, options.sounded_speed, math.inf]
```

6. Change `keep_input_audio = has_audio and neutral_speeds` to `keep_input_audio = has_audio and neutral_speeds and not remove_ranges`.

7. In the `else:` branch, the `if has_audio and neutral_speeds:` log stays as is (it is only reached without ranges).

- [ ] **Step 7: Run the unit tests and the risk check**

Run: `.venv/Scripts/python.exe -m pytest tests/test_pipeline.py tests/test_pipeline_remove_ranges_ffmpeg.py -v`
Expected: all PASS, and the ffmpeg test reports ≈8 s / 240 and 120 frames.

**If the ffmpeg test fails with extra frames** (collapsed frames muxed with duplicate timestamps instead of dropped): add `-fps_mode cfr` to the output arguments of the final encode in `ffmpeg.build_video_commands` whenever a filter graph with `setpts` is used (both the primary and the fallback command), which makes FFmpeg drop frames that land on an already-filled output slot. Re-run the test. Do **not** try a `select` filter before `setpts`: it renumbers `N`, which the `setpts` expression indexes. If `-fps_mode cfr` is still not enough, stop and report — the design needs revisiting. Record which fix was needed in the commit message.

The GPU-encoder variant of this check runs in Task 6 Step 5, once `--remove` exists on the CLI.

- [ ] **Step 8: Run the whole suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all PASS.

- [ ] **Step 9: Format and commit**

```bash
.venv/Scripts/python.exe -m black talks_reducer tests && .venv/Scripts/python.exe -m isort talks_reducer tests
git add talks_reducer/models.py talks_reducer/pipeline.py tests/test_pipeline.py tests/test_pipeline_remove_ranges_ffmpeg.py
git commit -m "feat: Drop remove ranges inside the processing pipeline"
```

---

### Task 5: mpv Lua script, player discovery and packaging

**Files:**
- Create: `talks_reducer/resources/talks_reducer_cuts.lua`
- Modify: `talks_reducer/cut_marks.py`
- Modify: `pyproject.toml:66-71`, `talks-reducer.spec:27-44`
- Test: `tests/test_cut_marks.py`

**Interfaces:**
- Consumes: Task 1 module.
- Produces:
  - `LUA_SCRIPT_NAME = "talks_reducer_cuts.lua"`, `MPV_NET_RELEASES_URL`
  - `find_player(preferred: str | None = None, *, platform: str = sys.platform, which=shutil.which, environ: Mapping[str, str] = os.environ, exists=os.path.isfile) -> Optional[Path]`
  - `script_path() -> Optional[Path]`
  - `build_player_command(player: Path, video: Path, marks_file: Path, script: Path) -> list[str]`
  - `open_player(player: Path, video: Path, marks_file: Path) -> subprocess.Popen` (raises `FileNotFoundError` when the script is missing)

- [ ] **Step 1: Write the failing tests** (append to `tests/test_cut_marks.py`)

```python
def test_find_player_prefers_configured_path() -> None:
    found = cut_marks.find_player(
        "D:/tools/mpvnet.exe",
        platform="win32",
        which=lambda _n: None,
        environ={},
        exists=lambda p: p == "D:/tools/mpvnet.exe",
    )

    assert found == Path("D:/tools/mpvnet.exe")


def test_find_player_uses_path_before_install_dirs() -> None:
    found = cut_marks.find_player(
        None,
        platform="win32",
        which=lambda n: "C:/bin/mpv.exe" if n == "mpv" else None,
        environ={"ProgramFiles": "C:/Program Files"},
        exists=lambda _p: True,
    )

    assert found == Path("C:/bin/mpv.exe")


def test_find_player_falls_back_to_program_files() -> None:
    expected = str(Path("C:/Program Files") / "mpv.net" / "mpvnet.exe")

    found = cut_marks.find_player(
        None,
        platform="win32",
        which=lambda _n: None,
        environ={"ProgramFiles": "C:/Program Files"},
        exists=lambda p: p == expected,
    )

    assert found == Path(expected)


def test_find_player_returns_none_when_missing() -> None:
    assert (
        cut_marks.find_player(
            None, platform="linux", which=lambda _n: None, environ={}, exists=lambda _p: False
        )
        is None
    )


def test_build_player_command_for_mpvnet_forces_new_instance() -> None:
    command = cut_marks.build_player_command(
        Path("C:/mpv.net/mpvnet.exe"), Path("v.mp4"), Path("m.json"), Path("s.lua")
    )

    assert command == [
        str(Path("C:/mpv.net/mpvnet.exe")),
        "--process-instance=multi",
        f"--script={Path('s.lua')}",
        f"--script-opts=talks_reducer_cuts-file={Path('m.json')}",
        str(Path("v.mp4")),
    ]


def test_build_player_command_for_mpv_has_no_instance_flag() -> None:
    command = cut_marks.build_player_command(
        Path("/usr/bin/mpv"), Path("v.mp4"), Path("m.json"), Path("s.lua")
    )

    assert "--process-instance=multi" not in command


def test_lua_script_is_bundled() -> None:
    path = cut_marks.script_path()

    assert path is not None and path.name == "talks_reducer_cuts.lua"
    text = path.read_text(encoding="utf-8")
    assert 'read_options(opts, "talks_reducer_cuts")' in text
    assert "add_forced_key_binding" in text


def test_lua_script_is_packaged() -> None:
    root = Path(__file__).resolve().parents[1]

    assert '"*.lua"' in (root / "pyproject.toml").read_text(encoding="utf-8")
    assert "talks_reducer_cuts.lua" in (root / "talks-reducer.spec").read_text(
        encoding="utf-8"
    )
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cut_marks.py -v`
Expected: new tests FAIL (`find_player` missing).

- [ ] **Step 3: Write the Lua script** — `talks_reducer/resources/talks_reducer_cuts.lua`

```lua
-- talks-reducer: mark fragments to remove from the current video.
--   c  start / finish a fragment
--   C  undo the open mark, else the newest fragment
-- Marks go to the file named by the "file" script option (talks-reducer passes
-- a temp file under the user's temp folder, because Lua's io.open is not
-- guaranteed to handle non-ASCII paths on Windows). Run standalone, they go to
-- "<video path>.cuts.json".
local mp = require "mp"
local utils = require "mp.utils"
local options = require "mp.options"
local msg = require "mp.msg"

local opts = { file = "" }
options.read_options(opts, "talks_reducer_cuts")

local marks = {}     -- fragments in insertion order, so undo drops the newest
local pending = nil  -- start of a fragment that is not closed yet
local marks_path = nil
local source_name = ""

local function clock(t)
  local minutes = math.floor(t / 60)
  return string.format("%02d:%04.1f", minutes, t - minutes * 60)
end

local function merged()
  local sorted = {}
  for _, r in ipairs(marks) do sorted[#sorted + 1] = { r[1], r[2] } end
  table.sort(sorted, function(a, b) return a[1] < b[1] end)
  local out = {}
  for _, r in ipairs(sorted) do
    local last = out[#out]
    if last and r[1] <= last[2] then
      if r[2] > last[2] then last[2] = r[2] end
    else
      out[#out + 1] = r
    end
  end
  return out
end

local function show()
  local parts = {}
  for _, r in ipairs(merged()) do
    parts[#parts + 1] = clock(r[1]) .. "–" .. clock(r[2])
  end
  local text = "Cuts: " .. #parts
  if #parts > 0 then text = text .. " | " .. table.concat(parts, ", ") end
  if pending then text = text .. " | [mark " .. clock(pending) .. "…]" end
  mp.osd_message(text, 4)
end

local function save()
  if not marks_path then return end
  local text = utils.format_json({ version = 1, source = source_name, remove = merged() })
  if not text then
    msg.error("cannot encode marks")
    return
  end
  local tmp = marks_path .. ".tmp"
  local f = io.open(tmp, "w")
  if not f then
    msg.error("cannot write " .. tmp)
    return
  end
  f:write(text)
  f:close()
  os.remove(marks_path)
  local ok, err = os.rename(tmp, marks_path)
  if not ok then msg.error("cannot save marks: " .. tostring(err)) end
end

local function load()
  marks, pending = {}, nil
  if not marks_path then return end
  local f = io.open(marks_path, "r")
  if not f then return end
  local data = utils.parse_json(f:read("*a") or "")
  f:close()
  if type(data) ~= "table" or type(data.remove) ~= "table" then return end
  for _, r in ipairs(data.remove) do
    if type(r) == "table" then
      local a, b = tonumber(r[1]), tonumber(r[2])
      if a and b and b > a then marks[#marks + 1] = { a, b } end
    end
  end
end

local function toggle_mark()
  local t = mp.get_property_number("time-pos")
  if not t then return end
  if pending == nil then
    pending = t
  else
    local a, b = pending, t
    if b < a then a, b = b, a end
    pending = nil
    if b - a > 0.01 then
      marks[#marks + 1] = { a, b }
      save()
    end
  end
  show()
end

local function undo()
  if pending ~= nil then
    pending = nil
  elseif #marks > 0 then
    table.remove(marks)
    save()
  end
  show()
end

mp.register_event("file-loaded", function()
  local path = mp.get_property("path") or ""
  source_name = mp.get_property("filename") or ""
  if opts.file ~= "" then
    marks_path = opts.file
  elseif path ~= "" and not path:find("://", 1, true) then
    marks_path = utils.join_path(mp.get_property("working-directory") or "", path) .. ".cuts.json"
  else
    marks_path = nil
  end
  load()
  if #marks > 0 then show() end
end)

mp.add_forced_key_binding("c", "talks-reducer-mark", toggle_mark)
mp.add_forced_key_binding("C", "talks-reducer-undo", undo)
mp.register_event("shutdown", save)
```

- [ ] **Step 4: Add discovery and launch to `cut_marks.py`**

Add imports `import shutil`, `import subprocess`, `import sys`, `from typing import Callable, Mapping, Optional` and `from .icons import find_icon_path`, `from .subprocess_utils import hidden_subprocess_kwargs`, then:

```python
LUA_SCRIPT_NAME = "talks_reducer_cuts.lua"
MPV_NET_RELEASES_URL = "https://github.com/mpvnet-player/mpv.net/releases"

_SCRIPT_RELATIVE_PATHS = (
    Path("resources"),
    Path("talks_reducer") / "resources",
)


def find_player(
    preferred: Optional[str] = None,
    *,
    platform: str = sys.platform,
    which: Callable[[str], Optional[str]] = shutil.which,
    environ: Mapping[str, str] = os.environ,
    exists: Callable[[str], bool] = os.path.isfile,
) -> Optional[Path]:
    """Return the player to mark cuts with, or ``None`` when none is installed.

    Order: the configured *preferred* path, ``mpvnet``/``mpv`` on ``PATH``,
    mpv.net's Windows install folders, then Homebrew's ``mpv`` on macOS. The
    keyword arguments exist so tests can describe a machine without touching
    the real one.
    """

    if preferred and exists(preferred):
        return Path(preferred)

    for name in ("mpvnet", "mpv"):
        found = which(name)
        if found:
            return Path(found)

    candidates: list[str] = []
    if platform == "win32":
        program_files = environ.get("ProgramFiles")
        local_app_data = environ.get("LOCALAPPDATA")
        if program_files:
            candidates.append(str(Path(program_files) / "mpv.net" / "mpvnet.exe"))
        if local_app_data:
            candidates.append(
                str(Path(local_app_data) / "Programs" / "mpv.net" / "mpvnet.exe")
            )
    elif platform == "darwin":
        candidates.extend(["/opt/homebrew/bin/mpv", "/usr/local/bin/mpv"])

    for candidate in candidates:
        if exists(candidate):
            return Path(candidate)
    return None


def script_path() -> Optional[Path]:
    """Return the bundled Lua marking script, or ``None`` when it is missing."""

    return find_icon_path(
        filenames=[LUA_SCRIPT_NAME], relative_paths=_SCRIPT_RELATIVE_PATHS
    )


def build_player_command(
    player: Path, video: Path, marks_file: Path, script: Path
) -> list[str]:
    """Return the command line that opens *video* with the marking script.

    mpv.net defaults to a single instance: a second launch hands the file to
    the running window and exits at once, which would make the caller read the
    marks before any were made. ``--process-instance=multi`` keeps the new
    process alive until its window closes.
    """

    command = [str(player)]
    if Path(player).stem.lower() == "mpvnet":
        command.append("--process-instance=multi")
    command.append(f"--script={script}")
    command.append(f"--script-opts=talks_reducer_cuts-file={marks_file}")
    command.append(str(video))
    return command


def open_player(player: Path, video: Path, marks_file: Path) -> subprocess.Popen:
    """Launch *player* on *video*, writing marks to *marks_file*."""

    script = script_path()
    if script is None:
        raise FileNotFoundError(f"Bundled {LUA_SCRIPT_NAME} is missing")
    return subprocess.Popen(
        build_player_command(player, video, marks_file, script),
        **hidden_subprocess_kwargs(),
    )
```

Verify `find_icon_path`'s signature with `grep -n "def find_icon_path" -A12 talks_reducer/icons.py` and match the keyword names it uses (`dock_server.resolve_dock_html` already calls it with `filenames=` and `relative_paths=`).

- [ ] **Step 5: Package the script**

`pyproject.toml` — in `[tool.setuptools.package-data]` `"talks_reducer.resources"` list, add `"*.lua",` (and `"dock.html",` is not part of this task — leave it).

`talks-reducer.spec` — append to `base_datas`:

```python
    (
        PROJECT_DIR / "talks_reducer" / "resources" / "talks_reducer_cuts.lua",
        "talks_reducer/resources",
    ),
```

- [ ] **Step 6: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cut_marks.py tests/test_no_console_windows.py tests/test_pyinstaller_spec.py -v`
Expected: all PASS.

- [ ] **Step 7: Manual check in mpv.net**

Write the marks file and launch from Python (replace the video path with any local mp4, ideally one with a Cyrillic name):

```bash
.venv/Scripts/python.exe -c "from pathlib import Path; from talks_reducer import cut_marks as c; import tempfile; m=Path(tempfile.gettempdir())/'tr-cuts-test.json'; c.write_marks_file(m, [(5, 8)], 'x'); p=c.find_player(); print(p); c.open_player(p, Path(r'C:\path\to\видео.mp4'), m).wait(); print(m.read_text('utf-8'))"
```

Expected: OSD shows `Cuts: 1 | 00:05.0–00:08.0` on load; `c` twice adds a fragment; `C` undoes; after closing, the printed JSON lists the fragments. Repeat with mpv.net already open in another window — the call must still block until this window closes.

- [ ] **Step 8: Format and commit**

```bash
.venv/Scripts/python.exe -m black talks_reducer tests && .venv/Scripts/python.exe -m isort talks_reducer tests
git add talks_reducer/resources/talks_reducer_cuts.lua talks_reducer/cut_marks.py pyproject.toml talks-reducer.spec tests/test_cut_marks.py
git commit -m "feat: Add mpv.net marking script and player launcher"
```

---

### Task 6: CLI `--remove` / `--remove-file`

**Files:**
- Modify: `talks_reducer/cli.py` (parser after `--cut-end` ~L273, `_run` ~L441, local option build ~L589, remote ~L660)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `cut_marks.parse_ranges_text`, `cut_marks.read_marks_file`, `cut_marks.normalize_ranges`, `ProcessingOptions.remove_ranges`.
- Produces: parsed args `remove_text: list[RemoveRange] | None`, `remove_file: Path | None`; internal args key `remove_ranges: tuple`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_cli.py`)

```python
def test_build_parser_parses_remove_ranges() -> None:
    parser = cli._build_parser()

    parsed = parser.parse_args(["--remove", "1:20-1:45,12:00-12:30", "input.mp4"])

    assert parsed.remove_text == [(80.0, 105.0), (720.0, 750.0)]


def test_build_parser_rejects_bad_remove_range() -> None:
    with pytest.raises(SystemExit):
        cli._build_parser().parse_args(["--remove", "1:45-1:20", "input.mp4"])


def _run_with(parsed_args):
    speed_calls: list[cli.ProcessingOptions] = []

    def fake_speed_up(options, reporter):
        speed_calls.append(options)
        return SimpleNamespace(output_file=Path("/videos/output.mp4"))

    class DummyReporter:
        def log(self, message: str) -> None:
            pass

    app = cli.CliApplication(
        gather_files=lambda paths, **_kwargs: ["/videos/input.mp4"],
        send_video=None,
        speed_up=fake_speed_up,
        reporter_factory=DummyReporter,
    )
    return app.run(parsed_args), speed_calls


def test_cli_merges_remove_and_remove_file(tmp_path: Path) -> None:
    marks = tmp_path / "input.mp4.cuts.json"
    marks.write_text('{"version": 1, "source": "input.mp4", "remove": [[30, 40]]}', "utf-8")

    (exit_code, errors), calls = _run_with(
        SimpleNamespace(input_file=["input.mp4"], remove_text=[(10.0, 20.0)], remove_file=marks)
    )

    assert exit_code == 0, errors
    assert calls[0].remove_ranges == ((10.0, 20.0), (30.0, 40.0))


def test_cli_rejects_missing_remove_file(tmp_path: Path) -> None:
    (exit_code, errors), calls = _run_with(
        SimpleNamespace(input_file=["input.mp4"], remove_file=tmp_path / "nope.json")
    )

    assert exit_code == 1
    assert "nope.json" in errors[0]
    assert calls == []


def test_cli_rejects_remove_ranges_with_server() -> None:
    (exit_code, errors), calls = _run_with(
        SimpleNamespace(
            input_file=["input.mp4"], remove_text=[(1.0, 2.0)], server_url="http://h:9005"
        )
    )

    assert exit_code == 1
    assert errors == ["Error: Remove ranges are local-only"]
    assert calls == []
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli.py -k remove -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Imports: `from .cut_marks import normalize_ranges, parse_ranges_text, read_marks_file`.

Next to `_parse_fps_arg`:

```python
def _parse_remove_arg(text: str):
    """argparse ``type`` for ``--remove``: a list of ``(start, end)`` seconds."""

    try:
        return parse_ranges_text(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
```

Parser, after `--cut-end`:

```python
    parser.add_argument(
        "--remove",
        dest="remove_text",
        type=_parse_remove_arg,
        default=None,
        metavar="RANGES",
        help=(
            "Drop fragments from the middle of the video, e.g. "
            "'1:20-1:45,12:00-12:30.5' (times of the input file). Local processing only."
        ),
    )
    parser.add_argument(
        "--remove-file",
        dest="remove_file",
        type=Path,
        default=None,
        metavar="PATH",
        help="Read fragments to drop from a .cuts.json file (as written by the mpv marking script).",
    )
```

In `_run`, right after the `--cut-end` validation block:

```python
        remove_ranges = list(getattr(parsed_args, "remove_text", None) or [])
        remove_file = getattr(parsed_args, "remove_file", None)
        if remove_file is not None:
            if not Path(remove_file).is_file():
                return 1, [f"Error: --remove-file '{remove_file}' does not exist."]
            remove_ranges.extend(read_marks_file(Path(remove_file)))
        remove_ranges = normalize_ranges(remove_ranges)
        if remove_ranges and getattr(parsed_args, "server_url", None):
            return 1, ["Error: Remove ranges are local-only"]
```

After `del args["input_file"]`:

```python
        args.pop("remove_text", None)
        args.pop("remove_file", None)
        if remove_ranges:
            args["remove_ranges"] = tuple(remove_ranges)
```

In the per-file option build, after the `cut_end_seconds` block:

```python
            if local_options.get("remove_ranges"):
                option_kwargs["remove_ranges"] = tuple(local_options["remove_ranges"])
```

Check how `server_url` is set when `--host` is used (`grep -n "server_url" talks_reducer/cli.py`): if `--host` is resolved into `server_url` only later in `_run`, move the local-only check to after that resolution so `--host` is rejected too.

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli.py -v`
Expected: all PASS.

- [ ] **Step 5: GPU risk check (continues Task 4 Step 7)**

Generate a clip with the `ffmpeg` command from `_make_clip` in `tests/test_pipeline_remove_ranges_ffmpeg.py` (write it to the scratch folder), then:

```bash
.venv/Scripts/python.exe -m talks_reducer --silent-speed 1 --sounded-speed 1 --remove 3-5 --video-codec hevc --prefer-global-ffmpeg clip.mp4
ffprobe -v error -count_frames -select_streams v:0 -show_entries format=duration:stream=nb_read_frames -of json clip_cut.mp4
```

Expected: the log shows `Processing on: GPU (...)` (on a machine with a GPU encoder), duration ≈ 8 s, ≈ 240 frames. Check the real flag name for global FFmpeg with `.venv/Scripts/python.exe -m talks_reducer --help` and adjust if it differs.

- [ ] **Step 6: Format and commit**

```bash
.venv/Scripts/python.exe -m black talks_reducer tests && .venv/Scripts/python.exe -m isort talks_reducer tests
git add talks_reducer/cli.py tests/test_cli.py
git commit -m "feat: Add --remove and --remove-file CLI options"
```

---

### Task 7: GUI — Mark cuts, Remove field, Remove only

**Files:**
- Create: `talks_reducer/gui/cut_marks_ui.py`
- Modify: `talks_reducer/gui/app.py` (vars ~L361-417, `_on_inputs_updated` ~L855, `_update_cut_convert_button` ~L947, `_start_run` ~L508, worker after `gather_input_files`, `_collect_arguments` ~L1632)
- Modify: `talks_reducer/gui/layout.py` (`build_cut_panel` L543)
- Test: `tests/test_gui_cut_marks_ui.py`, `tests/test_gui_app.py`

**Interfaces:**
- Consumes: Task 1 and Task 5 `cut_marks` API.
- Produces (all take the `TalksReducerGUI` instance as `gui`):
  - `current_input_video(gui) -> Optional[Path]`
  - `set_ranges(gui, ranges) -> None`
  - `load_for_current_input(gui) -> None`
  - `commit_text(gui) -> None`
  - `open_marker(gui) -> None`
  - `remove_only_overrides(args: dict) -> dict`
  - GUI attributes: `gui.remove_ranges: list[RemoveRange]`, `gui.remove_ranges_text_var`, `gui.remove_ranges_entry`, `gui.mark_cuts_button`, `gui.remove_only_button`.

- [ ] **Step 1: Write the failing tests** — `tests/test_gui_cut_marks_ui.py`

```python
"""Tests for the GUI glue around remove-range marks."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from talks_reducer import cut_marks
from talks_reducer.gui import cut_marks_ui


class Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def _gui(tmp_path: Path, files: list[str]):
    logs: list[str] = []
    gui = SimpleNamespace(
        input_files=files,
        remove_ranges=[],
        remove_ranges_text_var=Var(),
        _update_cut_convert_button=lambda: None,
        _append_log=logs.append,
    )
    return gui, logs


def test_current_input_video_needs_exactly_one_file(tmp_path: Path) -> None:
    video = tmp_path / "a.mp4"
    video.write_bytes(b"")

    assert cut_marks_ui.current_input_video(_gui(tmp_path, [str(video)])[0]) == video
    assert cut_marks_ui.current_input_video(_gui(tmp_path, [str(tmp_path)])[0]) is None
    assert cut_marks_ui.current_input_video(_gui(tmp_path, [str(video)] * 2)[0]) is None


def test_load_for_current_input_fills_field(tmp_path: Path) -> None:
    video = tmp_path / "a.mp4"
    video.write_bytes(b"")
    cut_marks.save_marks(video, [(80, 105)])
    gui, _ = _gui(tmp_path, [str(video)])

    cut_marks_ui.load_for_current_input(gui)

    assert gui.remove_ranges == [(80.0, 105.0)]
    assert gui.remove_ranges_text_var.get() == "00:01:20-00:01:45"


def test_commit_text_saves_sidecar(tmp_path: Path) -> None:
    video = tmp_path / "a.mp4"
    video.write_bytes(b"")
    gui, _ = _gui(tmp_path, [str(video)])
    gui.remove_ranges_text_var.set("5-7, 1-2")

    cut_marks_ui.commit_text(gui)

    assert gui.remove_ranges == [(1.0, 2.0), (5.0, 7.0)]
    assert gui.remove_ranges_text_var.get() == "00:00:01-00:00:02, 00:00:05-00:00:07"
    assert cut_marks.load_marks(video) == [(1.0, 2.0), (5.0, 7.0)]


def test_commit_text_rejects_bad_input_and_reverts(tmp_path: Path) -> None:
    video = tmp_path / "a.mp4"
    video.write_bytes(b"")
    gui, logs = _gui(tmp_path, [str(video)])
    cut_marks_ui.set_ranges(gui, [(1.0, 2.0)])
    gui.remove_ranges_text_var.set("garbage")

    cut_marks_ui.commit_text(gui)

    assert gui.remove_ranges == [(1.0, 2.0)]
    assert gui.remove_ranges_text_var.get() == "00:00:01-00:00:02"
    assert any("Invalid remove ranges" in line for line in logs)


def test_remove_only_overrides_keep_codec_and_drop_scaling() -> None:
    args = {
        "silent_speed": 10.0,
        "sounded_speed": 1.5,
        "small": True,
        "small_target_height": 720,
        "max_frame_rate": 30.0,
        "video_codec": "hevc",
        "remove_ranges": ((1.0, 2.0),),
    }

    result = cut_marks_ui.remove_only_overrides(args)

    assert result == {
        "silent_speed": 1.0,
        "sounded_speed": 1.0,
        "video_codec": "hevc",
        "remove_ranges": ((1.0, 2.0),),
    }
    assert args["small"] is True
```

And in `tests/test_gui_app.py`, next to the cut tests:

```python
def test_collect_arguments_includes_remove_ranges_when_cut_enabled():
    gui = _make_collect_gui(
        cut_enabled_var=SimpleNamespace(get=lambda: True),
        cut_start_var=SimpleNamespace(get=lambda: 0.0),
        cut_end_var=SimpleNamespace(get=lambda: 0.0),
        remove_ranges=[(1.0, 2.0)],
    )

    args = app.TalksReducerGUI._collect_arguments(gui)

    assert args["remove_ranges"] == ((1.0, 2.0),)


def test_collect_arguments_ignores_remove_ranges_in_simple_mode():
    gui = _make_collect_gui(
        cut_enabled_var=SimpleNamespace(get=lambda: True),
        cut_start_var=SimpleNamespace(get=lambda: 0.0),
        cut_end_var=SimpleNamespace(get=lambda: 0.0),
        simple_mode_var=SimpleNamespace(get=lambda: True),
        remove_ranges=[(1.0, 2.0)],
    )

    args = app.TalksReducerGUI._collect_arguments(gui)

    assert "remove_ranges" not in args
```

(Check `_make_collect_gui` accepts arbitrary overrides; if it builds a `SimpleNamespace(**defaults, **overrides)`, `remove_ranges=` works as written.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gui_cut_marks_ui.py tests/test_gui_app.py -k "remove" -v`
Expected: FAIL.

- [ ] **Step 3: Implement `talks_reducer/gui/cut_marks_ui.py`**

```python
"""GUI glue for marking remove ranges in mpv.net and editing them by hand.

Every helper takes the ``TalksReducerGUI`` instance so ``app.py`` only wires
callbacks. The sidecar next to the video is the source of truth: the field is
filled from it on input change and every committed edit is written back.
"""

from __future__ import annotations

import os
import tempfile
import threading
import webbrowser
from pathlib import Path
from typing import Iterable, Optional, Sequence

from .. import cut_marks

_OVERRIDDEN_KEYS = ("small", "small_target_height", "max_frame_rate")


def current_input_video(gui) -> Optional[Path]:
    """Return the single queued input file, or ``None`` for zero, many or a folder."""

    files = list(getattr(gui, "input_files", []) or [])
    if len(files) != 1:
        return None
    path = Path(files[0])
    return path if path.is_file() else None


def set_ranges(gui, ranges: Iterable[Sequence[float]]) -> None:
    """Store *ranges* on the GUI, mirror them into the field, refresh buttons."""

    gui.remove_ranges = cut_marks.normalize_ranges(ranges)
    gui.remove_ranges_text_var.set(cut_marks.format_ranges_text(gui.remove_ranges))
    gui._update_cut_convert_button()


def load_for_current_input(gui) -> None:
    """Fill the field from the current input's sidecar (empty when absent)."""

    video = current_input_video(gui)
    set_ranges(gui, cut_marks.load_marks(video) if video else [])


def commit_text(gui) -> None:
    """Parse the field; save valid ranges to the sidecar, revert invalid text."""

    try:
        ranges = cut_marks.parse_ranges_text(gui.remove_ranges_text_var.get())
    except ValueError as exc:
        gui._append_log(f"Invalid remove ranges: {exc}")
        set_ranges(gui, gui.remove_ranges)
        return
    set_ranges(gui, ranges)
    video = current_input_video(gui)
    if video is not None:
        cut_marks.save_marks(video, ranges)


def remove_only_overrides(args: dict) -> dict:
    """Return *args* for a pass that only drops fragments from a finished file.

    Speeds go to 1 so remaining silence is not sped up a second time, and
    scaling and the fps cap are removed so the picture is left as it is. The
    codec stays as selected.
    """

    result = {key: value for key, value in args.items() if key not in _OVERRIDDEN_KEYS}
    result["silent_speed"] = 1.0
    result["sounded_speed"] = 1.0
    return result


def open_marker(gui) -> None:
    """Open the current input in mpv.net with the marking script.

    The marks travel through a temp file (see the Lua script for why). When the
    player exits, the result is saved to the sidecar and shown in the field.
    """

    video = current_input_video(gui)
    if video is None:
        gui.messagebox.showwarning("Mark cuts", "Add exactly one video file first.")
        return

    preferred = gui.preferences.get("mpv_path", None) or None
    player = cut_marks.find_player(preferred)
    if player is None:
        if gui.messagebox.askyesno(
            "Mark cuts",
            "Marking cuts needs mpv.net (or mpv).\n\nOpen the mpv.net download page?",
        ):
            webbrowser.open(cut_marks.MPV_NET_RELEASES_URL)
        return

    handle, name = tempfile.mkstemp(prefix="talks-reducer-cuts-", suffix=".json")
    os.close(handle)
    marks_file = Path(name)
    cut_marks.write_marks_file(marks_file, gui.remove_ranges, video.name)

    try:
        process = cut_marks.open_player(player, video, marks_file)
    except (OSError, FileNotFoundError) as exc:
        marks_file.unlink(missing_ok=True)
        gui.messagebox.showerror("Mark cuts", f"Could not start {player.name}: {exc}")
        return

    def wait_for_player() -> None:
        process.wait()
        ranges = cut_marks.read_marks_file(marks_file)
        marks_file.unlink(missing_ok=True)

        def apply() -> None:
            cut_marks.save_marks(video, ranges)
            if current_input_video(gui) == video:
                set_ranges(gui, ranges)

        gui._schedule_on_ui_thread(apply)

    threading.Thread(target=wait_for_player, daemon=True).start()
```

- [ ] **Step 4: Wire into `app.py`**

1. Import: `from . import cut_marks_ui` (follow the file's two import blocks — relative at L~50 and absolute at L~102 — add to both).
2. After the cut vars (~L375): 

```python
        self.remove_ranges: list[tuple[float, float]] = []
        self.remove_ranges_text_var = tk.StringVar(value="")
```

3. `_on_inputs_updated`: insert `cut_marks_ui.load_for_current_input(self)` right after the `if not getattr(self, "cut_enabled_var", None): return` guard and before `if self.cut_enabled_var.get():`, so the field matches the input even while the panel is hidden.
4. `_update_cut_convert_button`: after showing/hiding `button`, add:

```python
        remove_only = getattr(self, "remove_only_button", None)
        if remove_only is not None:
            if show and getattr(self, "remove_ranges", None):
                remove_only.grid()
            else:
                remove_only.grid_remove()
```

5. `_start_run(self, *, remove_only: bool = False)`: right after `args = self._collect_arguments()` succeeds:

```python
        if remove_only:
            args = cut_marks_ui.remove_only_overrides(args)
        if args.get("remove_ranges") and self.processing_mode_var.get() == "remote":
            self.messagebox.showerror("Remote mode", "Remove ranges are local-only")
            return
```

6. In `worker()`, right after the `if not files:` block:

```python
                if args.get("remove_ranges") and len(files) != 1:
                    self._schedule_on_ui_thread(
                        lambda: self.messagebox.showerror(
                            "Remove ranges", "Remove ranges apply to a single file"
                        )
                    )
                    self._set_status("Idle")
                    return
```

7. `_collect_arguments`, inside the `if self.cut_enabled_var.get() and not self.simple_mode_var.get():` block, after the cut args:

```python
            remove_ranges = getattr(self, "remove_ranges", None) or []
            if remove_ranges:
                args["remove_ranges"] = tuple(remove_ranges)
```

- [ ] **Step 5: Widgets in `layout.build_cut_panel`**

After the `cut_convert_button.grid(...)` call:

```python
    gui.ttk.Label(panel, text="Remove").grid(row=2, column=0, sticky="w", pady=(4, 0))
    gui.remove_ranges_entry = gui.ttk.Entry(panel, textvariable=gui.remove_ranges_text_var)
    gui.remove_ranges_entry.grid(
        row=2, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=(4, 0)
    )
    gui.remove_ranges_entry.bind("<Return>", lambda _e: cut_marks_ui.commit_text(gui))
    gui.remove_ranges_entry.bind("<FocusOut>", lambda _e: cut_marks_ui.commit_text(gui))
    gui.mark_cuts_button = gui.ttk.Button(
        panel, text="Mark cuts…", command=lambda: cut_marks_ui.open_marker(gui)
    )
    gui.mark_cuts_button.grid(row=2, column=3, sticky="ew", padx=(8, 0), pady=(4, 0))
    gui.remove_only_button = gui.ttk.Button(
        panel, text="Remove only", command=lambda: gui._start_run(remove_only=True)
    )
    gui.remove_only_button.grid(
        row=0, column=4, rowspan=2, sticky="nsew", padx=(8, 0)
    )
```

Import `cut_marks_ui` in `layout.py` the same way `layout.py` imports other `gui` helpers. Note `_update_cut_convert_button()` is already called at the end of `build_cut_panel`, so `remove_only_button` must be created before that call (it is, given the placement above). Update the `build_cut_panel` docstring to describe the Remove row, **Mark cuts…** and **Remove only**.

- [ ] **Step 6: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gui_cut_marks_ui.py tests/test_gui_app.py tests/test_gui_layout.py tests/test_gui_inputs.py -v`
Expected: all PASS. If `test_gui_layout.py` stubs fail on the new `cut_marks_ui` callbacks or missing `remove_ranges_text_var`, add `remove_ranges_text_var` and `remove_ranges` to the stub GUI there rather than guarding production code.

- [ ] **Step 7: Real window check (required by the GUI Layout Convention)**

Run: `.venv/Scripts/python.exe -m talks_reducer.gui`, switch to Advanced, enable **Cut video**, add one video. Check:
- the Remove row sits under End, entry stretches, **Mark cuts…** aligns with the Convert column, nothing overlaps;
- **Remove only** appears only once the field has ranges;
- **Mark cuts…** opens mpv.net; after `c c` and closing, the field fills and `<video>.cuts.json` exists;
- typing `garbage` + Enter reverts and logs `Invalid remove ranges`;
- **Remove only** on a `_speedup` file produces `<name>_cut.mp4` that is shorter by the removed time;
- Mode=Remote + ranges → error `Remove ranges are local-only`.
Take a screenshot of the panel for the PR.

- [ ] **Step 8: Full suite, format, commit**

```bash
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m black talks_reducer tests && .venv/Scripts/python.exe -m isort talks_reducer tests
git add talks_reducer/gui/cut_marks_ui.py talks_reducer/gui/app.py talks_reducer/gui/layout.py tests/test_gui_cut_marks_ui.py tests/test_gui_app.py tests/test_gui_layout.py
git commit -m "feat: Mark and remove middle fragments from the Cut video panel"
```

---

### Task 8: Docs

**Files:**
- Modify: `README.md` (Cut video section and CLI options list)
- Modify: `CLAUDE.md` (Graphical Interface → **Cut video** bullet; Repository Structure → add `cut_marks.py`)

- [ ] **Step 1: README** — under Cut video add a "Removing fragments from the middle" subsection covering: **Mark cuts…** opens mpv.net (`c` start/finish, `C` undo), the `<video>.cuts.json` sidecar and its format, the editable **Remove** field, **Convert** vs **Remove only** (`_cut` suffix, speeds ×1, orig resolution/fps), local-only, mpv.net download link; in the CLI options add `--remove RANGES` and `--remove-file PATH` with the example `talks-reducer --silent-speed 1 --sounded-speed 1 --no-small --fps orig --remove "1:20-1:45" lecture_speedup.mp4`.

- [ ] **Step 2: CLAUDE.md** — extend the **Cut video** bullet with: remove ranges live in `gui.remove_ranges` mirrored by `remove_ranges_text_var`, the sidecar is the source of truth (`cut_marks_ui.load_for_current_input` on input change, `commit_text` writes back), marks travel through a temp file because Lua `io.open` may not handle non-ASCII paths, `--process-instance=multi` is required for mpv.net, **Remove only** = `cut_marks_ui.remove_only_overrides`, and ranges become `REMOVED_SPEED_INDEX` chunks at infinite speed in the pipeline (zero samples, collapsed `setpts`). Add `cut_marks.py` to Repository Structure.

- [ ] **Step 3: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: Document removing middle fragments via mpv.net"
```
