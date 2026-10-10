# Intel QSV and AMD AMF Hardware Encoding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Encode H.265 and AV1 on Intel QSV or AMD AMF when no NVENC GPU is present, detected by a cached per-codec trial encode that also fixes the false CUDA detection.

**Architecture:** `talks_reducer/ffmpeg.py` gains a per-codec `detect_hardware_backend(codec, ffmpeg_path)` that trial-encodes one frame per candidate (NVENC → AMF → QSV → VideoToolbox), caching the answer in memory and in `settings.json` (keyed by an FFmpeg fingerprint, 30-day TTL). `build_video_commands` takes one `hardware_backend` value instead of two booleans and builds QSV/AMF arguments from a table. `pipeline.py` detects once per job and invalidates the codec's cache entry when a GPU encode falls back to CPU.

**Tech Stack:** Python 3, FFmpeg (bundled `static-ffmpeg` gyan.dev 8.0.1 build), pytest, black, isort.

**Spec:** `docs/superpowers/specs/2026-10-10-qsv-amf-hardware-encoding-design.md`

## Global Constraints

- Backends: `"cuda"`, `"amf"`, `"qsv"`, `"videotoolbox"`; display labels `CUDA`, `AMF`, `QSV`, `VideoToolbox`.
- Per-codec candidates, in order: `h264` → `cuda`; `hevc` → `cuda`, `amf`, `qsv`, `videotoolbox`; `av1` → `cuda`, `amf`, `qsv`.
- Platforms: `cuda`/`amf`/`qsv` only on `win32` or `linux*`; `videotoolbox` only on `darwin`.
- QSV and AMF encode H.265 and AV1 only; H.264 stays on libx264 for them.
- Trial encode: `-f lavfi -i color=black:size=256x144:duration=0.04 -frames:v 1 -c:v <encoder> -f null -`, timeout 10 s, success means exit code 0.
- Cache key in `settings.json`: `"hardware_backend"`; TTL 30 days; record shape `{"backend": <name|null>, "checked_at": <int unix seconds>}` under `"codecs"`, entry carries `"ffmpeg": {"path", "size", "mtime"}`.
- On `SettingsReadError` never write `settings.json`.
- QSV is decoded on the CPU; `-hwaccel cuda` only when the backend is `"cuda"`.
- Tests must never touch the real `settings.json`.
- Use `.venv` for every Python command: `.venv\Scripts\python.exe -m pytest ...`.
- Run `black` and `isort` on changed Python files before each commit.
- Commit messages: angular format; end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. `feat:`/`fix:` only for user-visible changes; tests/refactors that ship together go in the same commit as the feature.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `talks_reducer/config.py` | Shared settings path and IO | Add `HARDWARE_BACKEND_KEY` |
| `talks_reducer/ffmpeg.py` | FFmpeg discovery, capability probes, command building | Cache helpers, detection, QSV/AMF table, `hardware_backend` parameter |
| `talks_reducer/pipeline.py` | Job orchestration | Use detection, invalidate on GPU fallback |
| `talks_reducer/gui/preferences.py` | GUI settings persistence | Protect the cache key from wholesale rewrites |
| `tests/conftest.py` | Global fixtures | Redirect the cache to `tmp_path` for every test |
| `tests/test_ffmpeg.py` | ffmpeg unit tests | New cache/detection/command tests; migrate old kwargs |
| `tests/test_pipeline_service.py`, `tests/test_pipeline.py` | Pipeline tests | Migrate dependencies; new detection/invalidation tests |
| `tests/test_gui_preferences.py` | Preferences tests | Cache key survives `save()` |
| `README.md`, `docs/cli.md`, `AGENTS.md`, `CLAUDE.md` | Docs | Describe backends and cache |
| spec "Calibration results" | Rationale for QSV numbers | Fill in |

---

### Task 1: On-disk detection cache primitives

**Files:**
- Modify: `talks_reducer/config.py` (after the imports, before `determine_config_path`)
- Modify: `talks_reducer/ffmpeg.py:1-13` (imports) and after `_ENCODER_OPTIONS` (line ~256)
- Modify: `talks_reducer/gui/preferences.py:11-36`
- Modify: `tests/conftest.py`
- Test: `tests/test_ffmpeg.py`, `tests/test_gui_preferences.py`

**Interfaces:**
- Produces (used by Task 2):
  - `config.HARDWARE_BACKEND_KEY: str = "hardware_backend"`
  - `ffmpeg.HARDWARE_BACKENDS: tuple[str, ...]`
  - `ffmpeg.HARDWARE_BACKEND_LABELS: dict[str, str]`
  - `ffmpeg.HARDWARE_CACHE_MAX_AGE_SECONDS: int`
  - `ffmpeg._HARDWARE_BACKEND_CACHE: dict[tuple, Optional[str]]`, `ffmpeg._HARDWARE_BACKEND_LOCK: threading.Lock`
  - `ffmpeg._hardware_cache_path() -> Path`
  - `ffmpeg._ffmpeg_fingerprint(ffmpeg_path: str) -> Optional[dict[str, object]]`
  - `ffmpeg._read_cached_backend(fingerprint: dict, codec: str, now: float) -> Tuple[bool, Optional[str]]`
  - `ffmpeg._write_cached_backend(fingerprint: dict, codec: str, record: Optional[dict]) -> bool`

- [ ] **Step 1: Add the global test isolation fixture**

Replace `tests/conftest.py` with:

```python
"""Pytest configuration for local package imports."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(autouse=True)
def isolate_hardware_backend_cache(monkeypatch, tmp_path):
    """Keep GPU detection from reading or writing the real ``settings.json``."""

    from talks_reducer import ffmpeg

    monkeypatch.setattr(
        ffmpeg, "_hardware_cache_path", lambda: tmp_path / "settings.json"
    )
    monkeypatch.setattr(ffmpeg, "_HARDWARE_BACKEND_CACHE", {})
```

- [ ] **Step 2: Write the failing cache tests**

Append to `tests/test_ffmpeg.py` (add `import json`, `import os` and `from pathlib import Path` to the imports at the top):

```python
def _fake_ffmpeg_binary(tmp_path) -> str:
    """Create a file that stands in for the FFmpeg binary so it can be stat'ed."""

    binary = tmp_path / "ffmpeg.exe"
    binary.write_bytes(b"binary")
    return str(binary)


def test_ffmpeg_fingerprint_describes_binary(tmp_path):
    path = _fake_ffmpeg_binary(tmp_path)

    fingerprint = ffmpeg._ffmpeg_fingerprint(path)

    assert fingerprint == {
        "path": os.path.abspath(path),
        "size": 6,
        "mtime": int(Path(path).stat().st_mtime),
    }


def test_ffmpeg_fingerprint_is_none_for_missing_binary(tmp_path):
    assert ffmpeg._ffmpeg_fingerprint(str(tmp_path / "missing.exe")) is None


def test_cached_backend_round_trip(tmp_path):
    fingerprint = ffmpeg._ffmpeg_fingerprint(_fake_ffmpeg_binary(tmp_path))

    assert ffmpeg._write_cached_backend(
        fingerprint, "hevc", {"backend": "qsv", "checked_at": 1000}
    )

    assert ffmpeg._read_cached_backend(fingerprint, "hevc", now=1060) == (True, "qsv")
    assert ffmpeg._read_cached_backend(fingerprint, "av1", now=1060) == (False, None)


def test_cached_backend_stores_absent_gpu(tmp_path):
    fingerprint = ffmpeg._ffmpeg_fingerprint(_fake_ffmpeg_binary(tmp_path))
    ffmpeg._write_cached_backend(
        fingerprint, "hevc", {"backend": None, "checked_at": 1000}
    )

    assert ffmpeg._read_cached_backend(fingerprint, "hevc", now=1060) == (True, None)


def test_cached_backend_expires_after_thirty_days(tmp_path):
    fingerprint = ffmpeg._ffmpeg_fingerprint(_fake_ffmpeg_binary(tmp_path))
    ffmpeg._write_cached_backend(
        fingerprint, "hevc", {"backend": "qsv", "checked_at": 1000}
    )
    max_age = ffmpeg.HARDWARE_CACHE_MAX_AGE_SECONDS

    assert ffmpeg._read_cached_backend(fingerprint, "hevc", now=1000 + max_age - 1)[0]
    assert not ffmpeg._read_cached_backend(fingerprint, "hevc", now=1000 + max_age)[0]


def test_cached_backend_rejects_changed_ffmpeg(tmp_path):
    path = _fake_ffmpeg_binary(tmp_path)
    old = ffmpeg._ffmpeg_fingerprint(path)
    ffmpeg._write_cached_backend(old, "hevc", {"backend": "qsv", "checked_at": 1000})

    Path(path).write_bytes(b"a newer and longer binary")
    new = ffmpeg._ffmpeg_fingerprint(path)

    assert ffmpeg._read_cached_backend(new, "hevc", now=1060) == (False, None)


@pytest.mark.parametrize(
    "record",
    [
        {"backend": "vulkan", "checked_at": 1000},
        {"backend": "qsv", "checked_at": "yesterday"},
        {"backend": "qsv", "checked_at": True},
        {"backend": "qsv"},
        "qsv",
    ],
)
def test_cached_backend_rejects_malformed_record(tmp_path, record):
    fingerprint = ffmpeg._ffmpeg_fingerprint(_fake_ffmpeg_binary(tmp_path))
    ffmpeg._hardware_cache_path().write_text(
        json.dumps(
            {"hardware_backend": {"ffmpeg": fingerprint, "codecs": {"hevc": record}}}
        ),
        encoding="utf-8",
    )

    assert ffmpeg._read_cached_backend(fingerprint, "hevc", now=1060) == (False, None)


def test_cached_backend_rejects_malformed_entry(tmp_path):
    fingerprint = ffmpeg._ffmpeg_fingerprint(_fake_ffmpeg_binary(tmp_path))
    ffmpeg._hardware_cache_path().write_text(
        json.dumps({"hardware_backend": "qsv"}), encoding="utf-8"
    )

    assert ffmpeg._read_cached_backend(fingerprint, "hevc", now=1060) == (False, None)


def test_write_cached_backend_keeps_other_settings(tmp_path):
    settings_path = ffmpeg._hardware_cache_path()
    settings_path.write_text(
        json.dumps({"presets": [], "theme": "dark"}), encoding="utf-8"
    )
    fingerprint = ffmpeg._ffmpeg_fingerprint(_fake_ffmpeg_binary(tmp_path))

    assert ffmpeg._write_cached_backend(
        fingerprint, "hevc", {"backend": "qsv", "checked_at": 1000}
    )

    stored = json.loads(settings_path.read_text(encoding="utf-8"))
    assert stored["presets"] == []
    assert stored["theme"] == "dark"


def test_write_cached_backend_skips_unreadable_settings(tmp_path):
    settings_path = ffmpeg._hardware_cache_path()
    settings_path.write_text("{not json", encoding="utf-8")
    fingerprint = ffmpeg._ffmpeg_fingerprint(_fake_ffmpeg_binary(tmp_path))

    assert not ffmpeg._write_cached_backend(
        fingerprint, "hevc", {"backend": "qsv", "checked_at": 1000}
    )
    assert settings_path.read_text(encoding="utf-8") == "{not json"


def test_write_cached_backend_removes_one_codec(tmp_path):
    fingerprint = ffmpeg._ffmpeg_fingerprint(_fake_ffmpeg_binary(tmp_path))
    record = {"backend": "qsv", "checked_at": 1000}
    ffmpeg._write_cached_backend(fingerprint, "hevc", record)
    ffmpeg._write_cached_backend(fingerprint, "av1", record)

    assert ffmpeg._write_cached_backend(fingerprint, "hevc", None)

    assert ffmpeg._read_cached_backend(fingerprint, "hevc", now=1060) == (False, None)
    assert ffmpeg._read_cached_backend(fingerprint, "av1", now=1060) == (True, "qsv")


def test_write_cached_backend_resets_entry_for_new_ffmpeg(tmp_path):
    path = _fake_ffmpeg_binary(tmp_path)
    old = ffmpeg._ffmpeg_fingerprint(path)
    ffmpeg._write_cached_backend(old, "hevc", {"backend": "qsv", "checked_at": 1000})
    Path(path).write_bytes(b"a newer and longer binary")
    new = ffmpeg._ffmpeg_fingerprint(path)

    ffmpeg._write_cached_backend(new, "av1", {"backend": None, "checked_at": 1000})

    stored = json.loads(ffmpeg._hardware_cache_path().read_text(encoding="utf-8"))
    assert stored["hardware_backend"] == {
        "ffmpeg": new,
        "codecs": {"av1": {"backend": None, "checked_at": 1000}},
    }
```

Append to `tests/test_gui_preferences.py`:

```python
def test_save_preserves_hardware_backend_cache(tmp_path):
    """GPU detection writes its cache out-of-band; a preference save keeps it."""

    from talks_reducer.config import HARDWARE_BACKEND_KEY, save_settings

    config_path = tmp_path / "settings.json"
    prefs = GUIPreferences(config_path)
    prefs.update("small_video", False)

    on_disk = load_settings(config_path)
    on_disk[HARDWARE_BACKEND_KEY] = {"ffmpeg": None, "codecs": {}}
    assert save_settings(config_path, on_disk)

    prefs.update("small_video", True)

    reloaded = load_settings(config_path)
    assert reloaded["small_video"] is True
    assert reloaded[HARDWARE_BACKEND_KEY] == {"ffmpeg": None, "codecs": {}}
```

- [ ] **Step 3: Run the new tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_ffmpeg.py -k "fingerprint or cached_backend" tests/test_gui_preferences.py::test_save_preserves_hardware_backend_cache -v`
Expected: FAIL — `AttributeError: module 'talks_reducer.ffmpeg' has no attribute '_ffmpeg_fingerprint'` (and the conftest fixture errors with `_hardware_cache_path` missing for every test until Step 4 lands), and `ImportError: cannot import name 'HARDWARE_BACKEND_KEY'`.

- [ ] **Step 4: Implement the cache primitives**

In `talks_reducer/config.py`, after the `from typing import Mapping, Optional` line, add:

```python


# Settings key under which ``ffmpeg.detect_hardware_backend`` caches its
# per-codec trial-encode results. Lives here so the GUI can protect it from
# wholesale rewrites without importing the FFmpeg module.
HARDWARE_BACKEND_KEY = "hardware_backend"
```

In `talks_reducer/ffmpeg.py`, change the import block to:

```python
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from shutil import which as _shutil_which
from typing import List, NamedTuple, Optional, Sequence, Tuple

from . import config
from .progress import ProgressReporter, TqdmProgressReporter
```

(`time` and `NamedTuple` are used by Tasks 2 and 3; adding them now keeps the import block edit in one place.)

Directly after `_ENCODER_OPTIONS: dict[tuple[str, str], str] = {}`, add:

```python

HARDWARE_BACKENDS = ("cuda", "amf", "qsv", "videotoolbox")
HARDWARE_BACKEND_LABELS = {
    "cuda": "CUDA",
    "amf": "AMF",
    "qsv": "QSV",
    "videotoolbox": "VideoToolbox",
}
HARDWARE_CACHE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60

# (fingerprint-or-path, codec) -> backend. Guarded by the lock because the GUI
# renders on a worker thread and the server can run several jobs at once.
_HARDWARE_BACKEND_CACHE: dict[tuple, Optional[str]] = {}
_HARDWARE_BACKEND_LOCK = threading.Lock()


def _hardware_cache_path() -> Path:
    """Return the settings file that stores the hardware detection cache."""

    return config.determine_config_path()


def _ffmpeg_fingerprint(ffmpeg_path: str) -> Optional[dict[str, object]]:
    """Identify the FFmpeg binary so a cached probe is dropped when it changes.

    Returns ``None`` when the binary cannot be stat'ed (for example a bare
    ``ffmpeg`` name); such runs keep their probe results in memory only.
    """

    try:
        resolved = os.path.abspath(ffmpeg_path)
        stat = os.stat(resolved)
    except OSError:
        return None
    return {"path": resolved, "size": stat.st_size, "mtime": int(stat.st_mtime)}


def _read_cached_backend(
    fingerprint: dict[str, object], codec: str, now: float
) -> Tuple[bool, Optional[str]]:
    """Return ``(hit, backend)`` for *codec* from the on-disk cache.

    A record only counts when it belongs to the same FFmpeg binary, names a
    known backend (or ``None`` for "no GPU"), and is younger than
    :data:`HARDWARE_CACHE_MAX_AGE_SECONDS`. Anything else is a miss.
    """

    settings = config.load_settings(_hardware_cache_path())
    entry = settings.get(config.HARDWARE_BACKEND_KEY)
    if not isinstance(entry, dict) or entry.get("ffmpeg") != fingerprint:
        return False, None
    codecs = entry.get("codecs")
    record = codecs.get(codec) if isinstance(codecs, dict) else None
    if not isinstance(record, dict) or "backend" not in record:
        return False, None

    backend = record["backend"]
    checked_at = record.get("checked_at")
    if backend is not None and backend not in HARDWARE_BACKENDS:
        return False, None
    if isinstance(checked_at, bool) or not isinstance(checked_at, (int, float)):
        return False, None
    if not 0 <= now - checked_at < HARDWARE_CACHE_MAX_AGE_SECONDS:
        return False, None
    return True, backend


def _write_cached_backend(
    fingerprint: dict[str, object], codec: str, record: Optional[dict[str, object]]
) -> bool:
    """Store *record* for *codec* on disk, or remove it when *record* is ``None``.

    The settings file is shared with the GUI and presets, so it is re-read
    strictly first and left untouched when that read fails — rewriting it from
    an empty dict would delete every other setting. An entry written for a
    different FFmpeg binary is replaced wholesale, since its other codec
    records describe that old binary.
    """

    path = _hardware_cache_path()
    try:
        settings = config.read_settings_strict(path)
    except config.SettingsReadError:
        return False

    entry = settings.get(config.HARDWARE_BACKEND_KEY)
    codecs: dict[str, object] = {}
    if (
        isinstance(entry, dict)
        and entry.get("ffmpeg") == fingerprint
        and isinstance(entry.get("codecs"), dict)
    ):
        codecs = dict(entry["codecs"])

    if record is None:
        if codec not in codecs:
            return True
        codecs.pop(codec)
    else:
        codecs[codec] = record

    settings[config.HARDWARE_BACKEND_KEY] = {"ffmpeg": fingerprint, "codecs": codecs}
    return config.save_settings(path, settings)
```

In `talks_reducer/gui/preferences.py`, change the config import and the owned-keys tuple:

```python
from ..config import (
    HARDWARE_BACKEND_KEY,
    SettingsReadError,
    determine_config_path,
    load_settings,
    read_settings_strict,
    save_settings,
)
```

```python
# Keys written independently of ``GUIPreferences`` through their own
# read-modify-write cycles: presets by :mod:`talks_reducer.presets`, the GPU
# detection cache by :mod:`talks_reducer.ffmpeg`. ``GUIPreferences`` snapshots
# ``settings.json`` once at construction and rewrites the whole file on every
# ``save()``, so it must not clobber these keys with its stale snapshot.
_EXTERNALLY_OWNED_KEYS = (PRESETS_KEY, SELECTED_PRESET_KEY, HARDWARE_BACKEND_KEY)
```

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_ffmpeg.py -k "fingerprint or cached_backend" tests/test_gui_preferences.py -v`
Expected: PASS

- [ ] **Step 6: Run the full suite to confirm the conftest fixture breaks nothing**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: all tests PASS (same count as before plus the new ones).

- [ ] **Step 7: Format and commit**

```bash
.venv\Scripts\python.exe -m black talks_reducer/config.py talks_reducer/ffmpeg.py talks_reducer/gui/preferences.py tests/conftest.py tests/test_ffmpeg.py tests/test_gui_preferences.py
.venv\Scripts\python.exe -m isort talks_reducer/config.py talks_reducer/ffmpeg.py talks_reducer/gui/preferences.py tests/conftest.py tests/test_ffmpeg.py tests/test_gui_preferences.py
git add talks_reducer/config.py talks_reducer/ffmpeg.py talks_reducer/gui/preferences.py tests/conftest.py tests/test_ffmpeg.py tests/test_gui_preferences.py
git commit -m "refactor(ffmpeg): Add on-disk cache for hardware encoder detection" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Per-codec trial-encode detection

**Files:**
- Modify: `talks_reducer/ffmpeg.py` — replace `check_cuda_available` (lines ~346-362); add detection after `check_videotoolbox_available` (line ~384); extend `__all__`
- Test: `tests/test_ffmpeg.py` — replace the four `test_check_cuda_available_*` tests (lines ~282-352)

**Interfaces:**
- Consumes (Task 1): `_hardware_cache_path`, `_ffmpeg_fingerprint`, `_read_cached_backend`, `_write_cached_backend`, `_HARDWARE_BACKEND_CACHE`, `_HARDWARE_BACKEND_LOCK`, `HARDWARE_BACKENDS`.
- Produces (used by Tasks 3-4):
  - `ffmpeg.normalize_video_codec(value: Optional[str]) -> str` → `"h264" | "hevc" | "av1"`
  - `ffmpeg.detect_hardware_backend(codec: str, ffmpeg_path: Optional[str] = None) -> Optional[str]`
  - `ffmpeg.invalidate_hardware_backend_cache(codec: str, ffmpeg_path: Optional[str] = None) -> None`
  - `ffmpeg.check_cuda_available(ffmpeg_path: Optional[str] = None) -> bool` (now trial-based)

- [ ] **Step 1: Write the failing detection tests**

In `tests/test_ffmpeg.py`, delete `test_check_cuda_available_detects_nvenc`, `test_check_cuda_available_handles_missing_nvenc`, `test_check_cuda_available_requires_cuda_hwaccel` and `test_check_cuda_available_handles_errors`, and put this in their place:

```python
def _stub_hardware_probe(
    monkeypatch, *, platform="win32", listed=(), working=(), trial_error=None
):
    """Fake the encoder listing and trial encodes; return the encoders trialled."""

    monkeypatch.setattr(ffmpeg.sys, "platform", platform)
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    trials: List[str] = []

    def fake_run(args, **kwargs):
        if "-encoders" in args:
            listing = "\n".join(f" V..... {name}" for name in listed)
            return SimpleNamespace(stdout=listing, returncode=0)
        if "-hwaccels" in args:
            return SimpleNamespace(stdout="videotoolbox\n", returncode=0)
        if "-c:v" in args:
            encoder = args[args.index("-c:v") + 1]
            trials.append(encoder)
            if trial_error is not None:
                raise trial_error
            return SimpleNamespace(
                stdout="", stderr="", returncode=0 if encoder in working else 1
            )
        raise AssertionError(f"Unexpected args: {args}")

    monkeypatch.setattr(ffmpeg.subprocess, "run", fake_run)
    return trials


ALL_HEVC = ("hevc_nvenc", "hevc_amf", "hevc_qsv")


def test_detect_hardware_backend_prefers_first_working_candidate(monkeypatch):
    trials = _stub_hardware_probe(
        monkeypatch, listed=ALL_HEVC, working=("hevc_amf", "hevc_qsv")
    )

    assert ffmpeg.detect_hardware_backend("hevc") == "amf"
    assert trials == ["hevc_nvenc", "hevc_amf"]


def test_detect_hardware_backend_skips_unlisted_encoders(monkeypatch):
    trials = _stub_hardware_probe(
        monkeypatch, listed=("hevc_qsv",), working=("hevc_qsv",)
    )

    assert ffmpeg.detect_hardware_backend("hevc") == "qsv"
    assert trials == ["hevc_qsv"]


def test_detect_hardware_backend_h264_only_probes_nvenc(monkeypatch):
    """QSV/AMF H.264 stays on libx264, so probing them would be wasted time."""

    trials = _stub_hardware_probe(
        monkeypatch,
        listed=("h264_nvenc", "h264_amf", "h264_qsv"),
        working=("h264_qsv",),
    )

    assert ffmpeg.detect_hardware_backend("h264") is None
    assert trials == ["h264_nvenc"]


def test_detect_hardware_backend_probes_each_codec_separately(monkeypatch):
    """Pre-Arc Intel encodes HEVC but not AV1."""

    _stub_hardware_probe(
        monkeypatch, listed=("hevc_qsv", "av1_qsv"), working=("hevc_qsv",)
    )

    assert ffmpeg.detect_hardware_backend("hevc") == "qsv"
    assert ffmpeg.detect_hardware_backend("av1") is None


def test_detect_hardware_backend_ignores_non_video_codecs(monkeypatch):
    def unexpected_run(*args, **kwargs):
        raise AssertionError("mp3 must not probe GPU encoders")

    monkeypatch.setattr(ffmpeg.subprocess, "run", unexpected_run)
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    assert ffmpeg.detect_hardware_backend("mp3") is None


def test_detect_hardware_backend_normalises_codec_name(monkeypatch):
    trials = _stub_hardware_probe(
        monkeypatch, listed=("hevc_qsv",), working=("hevc_qsv",)
    )

    assert ffmpeg.detect_hardware_backend(" HEVC ") == "qsv"
    assert trials == ["hevc_qsv"]


def test_detect_hardware_backend_uses_videotoolbox_on_macos(monkeypatch):
    trials = _stub_hardware_probe(
        monkeypatch,
        platform="darwin",
        listed=("hevc_videotoolbox", "hevc_nvenc", "av1_qsv"),
    )

    assert ffmpeg.detect_hardware_backend("hevc") == "videotoolbox"
    assert ffmpeg.detect_hardware_backend("av1") is None
    assert trials == []


def test_detect_hardware_backend_treats_timeout_as_unavailable(monkeypatch):
    _stub_hardware_probe(
        monkeypatch,
        listed=ALL_HEVC,
        trial_error=ffmpeg.subprocess.TimeoutExpired(cmd="ffmpeg", timeout=10),
    )

    assert ffmpeg.detect_hardware_backend("hevc") is None


def test_detect_hardware_backend_memoizes_in_process(monkeypatch):
    trials = _stub_hardware_probe(
        monkeypatch, listed=ALL_HEVC, working=("hevc_qsv",)
    )

    assert ffmpeg.detect_hardware_backend("hevc") == "qsv"
    assert ffmpeg.detect_hardware_backend("hevc") == "qsv"
    assert trials == ["hevc_nvenc", "hevc_amf", "hevc_qsv"]


def test_detect_hardware_backend_reads_disk_cache_without_probing(
    monkeypatch, tmp_path
):
    binary = _fake_ffmpeg_binary(tmp_path)
    ffmpeg._write_cached_backend(
        ffmpeg._ffmpeg_fingerprint(binary),
        "hevc",
        {"backend": "qsv", "checked_at": int(ffmpeg.time.time())},
    )

    def unexpected_run(*args, **kwargs):
        raise AssertionError("a fresh cache entry must not re-probe")

    monkeypatch.setattr(ffmpeg.subprocess, "run", unexpected_run)

    assert ffmpeg.detect_hardware_backend("hevc", binary) == "qsv"


def test_detect_hardware_backend_writes_disk_cache(monkeypatch, tmp_path):
    binary = _fake_ffmpeg_binary(tmp_path)
    _stub_hardware_probe(monkeypatch, listed=ALL_HEVC)

    assert ffmpeg.detect_hardware_backend("hevc", binary) is None

    stored = json.loads(ffmpeg._hardware_cache_path().read_text(encoding="utf-8"))
    record = stored["hardware_backend"]["codecs"]["hevc"]
    assert record["backend"] is None
    assert isinstance(record["checked_at"], int)


def test_invalidate_hardware_backend_cache_forces_reprobe(monkeypatch, tmp_path):
    binary = _fake_ffmpeg_binary(tmp_path)
    trials = _stub_hardware_probe(
        monkeypatch, listed=("hevc_qsv",), working=("hevc_qsv",)
    )
    ffmpeg.detect_hardware_backend("hevc", binary)

    ffmpeg.invalidate_hardware_backend_cache("hevc", binary)

    assert ffmpeg.detect_hardware_backend("hevc", binary) == "qsv"
    assert trials == ["hevc_qsv", "hevc_qsv"]


def test_check_cuda_available_requires_working_nvenc(monkeypatch):
    """Listing NVENC is not enough: gyan.dev builds list it on every machine."""

    _stub_hardware_probe(monkeypatch, listed=("h264_nvenc",))

    assert not ffmpeg.check_cuda_available()


def test_check_cuda_available_detects_working_nvenc(monkeypatch):
    _stub_hardware_probe(
        monkeypatch, listed=("h264_nvenc",), working=("h264_nvenc",)
    )

    assert ffmpeg.check_cuda_available()


def test_check_cuda_available_handles_listing_failure(monkeypatch):
    monkeypatch.setattr(ffmpeg.sys, "platform", "linux")
    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(
        ffmpeg.subprocess,
        "run",
        lambda args, **kwargs: SimpleNamespace(stdout="", returncode=1),
    )

    assert not ffmpeg.check_cuda_available()


def test_normalize_video_codec():
    assert ffmpeg.normalize_video_codec(" HEVC ") == "hevc"
    assert ffmpeg.normalize_video_codec("av1") == "av1"
    assert ffmpeg.normalize_video_codec(None) == "h264"
    assert ffmpeg.normalize_video_codec("vp9") == "h264"
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_ffmpeg.py -k "detect_hardware_backend or invalidate or check_cuda or normalize_video_codec" -v`
Expected: FAIL — `AttributeError: module 'talks_reducer.ffmpeg' has no attribute 'detect_hardware_backend'`.

- [ ] **Step 3: Implement detection**

In `talks_reducer/ffmpeg.py`, replace the whole `check_cuda_available` function with:

```python
def check_cuda_available(ffmpeg_path: Optional[str] = None) -> bool:
    """Return whether NVENC can actually encode on this machine.

    Kept for callers outside the pipeline; it now delegates to the trial-encode
    detection, because the encoder listing alone reports NVENC on machines
    without an NVIDIA GPU.
    """

    return detect_hardware_backend("h264", ffmpeg_path) == "cuda"
```

Directly after `check_videotoolbox_available`, add:

```python
_HARDWARE_CANDIDATES = {
    # H.264 lists only NVENC: QSV, AMF and VideoToolbox H.264 stay on libx264
    # (see ``resolve_encoder_plan``), so probing them would cost time for nothing.
    "h264": ("cuda",),
    "hevc": ("cuda", "amf", "qsv", "videotoolbox"),
    # No Apple AV1 encoder exists.
    "av1": ("cuda", "amf", "qsv"),
}
_TRIAL_ENCODER_SUFFIXES = {"cuda": "nvenc", "amf": "amf", "qsv": "qsv"}
_TRIAL_ENCODE_TIMEOUT_SECONDS = 10


def normalize_video_codec(value: Optional[str]) -> str:
    """Return ``h264``, ``hevc`` or ``av1`` for a user-supplied codec name.

    Unknown values map to ``h264``, matching the encoder plan's default.
    """

    codec = (value or "h264").strip().lower()
    return codec if codec in _HARDWARE_CANDIDATES else "h264"


def _backend_supported_on_platform(backend: str) -> bool:
    """Return whether *backend* can exist on the current operating system."""

    if backend == "videotoolbox":
        return sys.platform == "darwin"
    return sys.platform == "win32" or sys.platform.startswith("linux")


def _trial_encode(ffmpeg_path: str, encoder: str) -> bool:
    """Encode one tiny frame with *encoder*; True only when FFmpeg exits 0.

    The encoder listing is not a capability signal: the gyan.dev builds that
    ``static-ffmpeg`` bundles list every NVENC, AMF and QSV encoder whatever GPU
    is installed, and only fail once the encoder is opened.
    """

    creationflags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
    try:
        result = subprocess.run(
            [
                ffmpeg_path,
                "-hide_banner",
                "-v",
                "quiet",
                "-f",
                "lavfi",
                "-i",
                "color=black:size=256x144:duration=0.04",
                "-frames:v",
                "1",
                "-c:v",
                encoder,
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            timeout=_TRIAL_ENCODE_TIMEOUT_SECONDS,
            creationflags=creationflags,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


def _probe_backend(backend: str, codec: str, ffmpeg_path: str) -> bool:
    """Return whether *backend* can encode *codec* on this machine."""

    if not _backend_supported_on_platform(backend):
        return False
    if backend == "videotoolbox":
        return check_videotoolbox_available(ffmpeg_path)
    encoder = f"{codec}_{_TRIAL_ENCODER_SUFFIXES[backend]}"
    return encoder_available(encoder, ffmpeg_path=ffmpeg_path) and _trial_encode(
        ffmpeg_path, encoder
    )


def _hardware_memory_key(
    ffmpeg_path: str, fingerprint: Optional[dict[str, object]], codec: str
) -> tuple:
    """Key the in-process cache by binary identity, falling back to its path."""

    identity = (
        tuple(sorted(fingerprint.items()))
        if fingerprint is not None
        else os.path.abspath(ffmpeg_path)
    )
    return (identity, codec)


def detect_hardware_backend(
    codec: str, ffmpeg_path: Optional[str] = None
) -> Optional[str]:
    """Return the hardware backend that will encode *codec*, or ``None``.

    Candidates are tried in priority order (discrete GPUs before Intel's iGPU)
    with a one-frame trial encode, and the answer is cached per codec in memory
    and in ``settings.json`` for :data:`HARDWARE_CACHE_MAX_AGE_SECONDS`, keyed by
    the FFmpeg binary's fingerprint. Detection is per codec because support
    differs: Intel before Arc, AMD before RDNA3 and NVIDIA before RTX 40 encode
    HEVC but not AV1. Non-video codecs such as ``mp3`` return ``None`` without
    probing.
    """

    codec = (codec or "").strip().lower()
    candidates = _HARDWARE_CANDIDATES.get(codec)
    if candidates is None:
        return None

    ffmpeg_path = ffmpeg_path or get_ffmpeg_path()
    fingerprint = _ffmpeg_fingerprint(ffmpeg_path)
    memory_key = _hardware_memory_key(ffmpeg_path, fingerprint, codec)

    with _HARDWARE_BACKEND_LOCK:
        if memory_key in _HARDWARE_BACKEND_CACHE:
            return _HARDWARE_BACKEND_CACHE[memory_key]

        now = time.time()
        if fingerprint is not None:
            hit, cached = _read_cached_backend(fingerprint, codec, now)
            if hit:
                _HARDWARE_BACKEND_CACHE[memory_key] = cached
                return cached

        backend = next(
            (
                candidate
                for candidate in candidates
                if _probe_backend(candidate, codec, ffmpeg_path)
            ),
            None,
        )
        _HARDWARE_BACKEND_CACHE[memory_key] = backend
        if fingerprint is not None:
            _write_cached_backend(
                fingerprint, codec, {"backend": backend, "checked_at": int(now)}
            )
        return backend


def invalidate_hardware_backend_cache(
    codec: str, ffmpeg_path: Optional[str] = None
) -> None:
    """Forget the cached backend for *codec* so the next run probes again.

    Called when a GPU encode fails for real, which means the cached answer no
    longer matches the machine (a removed eGPU, a broken driver).
    """

    codec = (codec or "").strip().lower()
    ffmpeg_path = ffmpeg_path or get_ffmpeg_path()
    fingerprint = _ffmpeg_fingerprint(ffmpeg_path)
    with _HARDWARE_BACKEND_LOCK:
        _HARDWARE_BACKEND_CACHE.pop(
            _hardware_memory_key(ffmpeg_path, fingerprint, codec), None
        )
        if fingerprint is not None:
            _write_cached_backend(fingerprint, codec, None)
```

Extend `__all__` with `"detect_hardware_backend"`, `"invalidate_hardware_backend_cache"`, `"normalize_video_codec"`, `"HARDWARE_BACKEND_LABELS"` (keep alphabetical order of the existing list if it is sorted; otherwise add after `"check_videotoolbox_available"`).

- [ ] **Step 4: Run the detection tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_ffmpeg.py -k "detect_hardware_backend or invalidate or check_cuda or check_videotoolbox or normalize_video_codec" -v`
Expected: PASS (the existing `test_check_videotoolbox_available_*` tests still pass unchanged).

- [ ] **Step 5: Run the whole suite**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: PASS. Pipeline tests still inject `check_cuda_available`, which still exists.

- [ ] **Step 6: Format and commit**

```bash
.venv\Scripts\python.exe -m black talks_reducer/ffmpeg.py tests/test_ffmpeg.py
.venv\Scripts\python.exe -m isort talks_reducer/ffmpeg.py tests/test_ffmpeg.py
git add talks_reducer/ffmpeg.py tests/test_ffmpeg.py
git commit -m "fix(ffmpeg): Detect GPU encoders with a cached trial encode" -m "The bundled gyan.dev FFmpeg lists every NVENC, AMF and QSV encoder regardless of the installed GPU, so CUDA was reported on machines without NVIDIA and every encode failed over to the CPU." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: QSV and AMF encoder plans in `build_video_commands`

**Files:**
- Modify: `talks_reducer/ffmpeg.py` — `build_video_commands` (lines ~798-1080) and a new table above it
- Test: `tests/test_ffmpeg.py`

**Interfaces:**
- Consumes (Task 2): `normalize_video_codec`.
- Produces (used by Task 4): `build_video_commands(input_file, audio_file, filter_script, output_file, *, ffmpeg_path=None, hardware_backend: Optional[str] = None, optimize, small, frame_rate=None, keyframe_interval_seconds=30.0, video_codec="h264", keep_input_audio=False, cut_start_seconds=0.0, cut_end_seconds=0.0) -> Tuple[str, Optional[str], bool]`. The `cuda_available` and `videotoolbox_available` keywords are removed.

- [ ] **Step 1: Migrate the existing tests to the new keyword**

Save as `%TEMP%\migrate_ffmpeg_tests.py` (outside the repo) and run it with `.venv\Scripts\python.exe -I %TEMP%\migrate_ffmpeg_tests.py tests/test_ffmpeg.py`:

```python
"""Rewrite cuda_available/videotoolbox_available kwargs to hardware_backend."""

import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
text = re.sub(
    r"cuda_available=True,\n\s*videotoolbox_available=(?:True|False),\n",
    'hardware_backend="cuda",\n',
    text,
)
text = re.sub(
    r"cuda_available=False,\n\s*videotoolbox_available=True,\n",
    'hardware_backend="videotoolbox",\n',
    text,
)
text = re.sub(
    r"cuda_available=False,\n\s*videotoolbox_available=False,\n",
    "hardware_backend=None,\n",
    text,
)
text = text.replace("cuda_available=True,", 'hardware_backend="cuda",')
text = text.replace("cuda_available=False,", "hardware_backend=None,")
path.write_text(text, encoding="utf-8")
```

Then delete `test_build_video_commands_cuda_takes_priority_over_videotoolbox` entirely: with one backend value the two can no longer be passed together, so the test has nothing left to check.

Verify nothing was missed:

Run: `git grep -n "cuda_available=\|videotoolbox_available=" -- tests/test_ffmpeg.py`
Expected: no output.

- [ ] **Step 2: Write the failing QSV/AMF command tests**

Append to `tests/test_ffmpeg.py`:

```python
def _build_with_backend(monkeypatch, backend, *, codec, optimize=True, listed=True):
    """Build commands with every encoder reported as present (or absent)."""

    monkeypatch.setattr(ffmpeg, "get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(
        ffmpeg, "encoder_available", lambda name, ffmpeg_path=None: listed
    )
    return ffmpeg.build_video_commands(
        "input.mp4",
        "audio.wav",
        "filter.txt",
        "output.mp4",
        hardware_backend=backend,
        optimize=optimize,
        small=False,
        frame_rate=30.0,
        video_codec=codec,
    )


def test_build_video_commands_hevc_qsv_optimized(monkeypatch):
    command, fallback, use_gpu = _build_with_backend(monkeypatch, "qsv", codec="hevc")

    assert "-c:v hevc_qsv" in command
    assert "-preset medium" in command
    assert "-global_quality 28" in command
    assert "-g 900" in command
    assert "-hwaccel" not in command
    assert use_gpu
    assert fallback is not None and "-c:v libx265" in fallback


def test_build_video_commands_av1_qsv_fast(monkeypatch):
    command, fallback, use_gpu = _build_with_backend(
        monkeypatch, "qsv", codec="av1", optimize=False
    )

    assert "-c:v av1_qsv" in command
    assert "-preset veryfast" in command
    assert "-global_quality 32" in command
    assert use_gpu
    assert fallback is not None and "-c:v libaom-av1" in fallback


def test_build_video_commands_hevc_amf_optimized(monkeypatch):
    command, fallback, use_gpu = _build_with_backend(monkeypatch, "amf", codec="hevc")

    assert "-c:v hevc_amf" in command
    assert "-quality balanced" in command
    assert "-rc cqp" in command
    assert "-qp_i 26" in command
    assert "-qp_p 28" in command
    assert use_gpu
    assert fallback is not None and "-c:v libx265" in fallback


def test_build_video_commands_av1_amf_fast(monkeypatch):
    command, _fallback, use_gpu = _build_with_backend(
        monkeypatch, "amf", codec="av1", optimize=False
    )

    assert "-c:v av1_amf" in command
    assert "-quality speed" in command
    assert "-qp_i 30" in command
    assert "-qp_p 32" in command
    assert use_gpu


@pytest.mark.parametrize("backend", ["qsv", "amf"])
def test_build_video_commands_h264_stays_on_libx264(monkeypatch, backend):
    """H.264 on QSV was slower and larger than libx264 veryfast in benchmarks."""

    command, fallback, use_gpu = _build_with_backend(monkeypatch, backend, codec="h264")

    assert "-c:v libx264" in command
    assert backend not in command
    assert fallback is None
    assert not use_gpu


def test_build_video_commands_qsv_without_listed_encoder_uses_cpu(monkeypatch):
    command, fallback, use_gpu = _build_with_backend(
        monkeypatch, "qsv", codec="hevc", listed=False
    )

    assert "-c:v libx265" in command
    assert fallback is None
    assert not use_gpu


def test_build_video_commands_cuda_decodes_on_gpu(monkeypatch):
    command, fallback, _use_gpu = _build_with_backend(monkeypatch, "cuda", codec="hevc")

    assert "-hwaccel cuda" in command
    assert fallback is not None and "-hwaccel" not in fallback
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_ffmpeg.py -k build_video_commands -v`
Expected: FAIL — `TypeError: build_video_commands() got an unexpected keyword argument 'hardware_backend'`.

- [ ] **Step 4: Implement the table and the new parameter**

In `talks_reducer/ffmpeg.py`, directly above `def build_video_commands(`, add:

```python
class _HardwareEncoderSpec(NamedTuple):
    """FFmpeg arguments for one hardware encoder, per quality profile."""

    encoder: str
    optimized: Tuple[str, ...]
    fast: Tuple[str, ...]


# QSV quality was calibrated to VMAF ~91 — the level the CPU H.264/H.265
# defaults reach — on a 1080p60 screen recording scaled to 720p; see
# "Calibration results" in
# docs/superpowers/specs/2026-10-10-qsv-amf-hardware-encoding-design.md.
# The AMF values mirror the NVENC fast-profile QP scale used above and are NOT
# calibrated on real AMD hardware. CQP is used because every VCN generation
# supports it, unlike QVBR.
_HARDWARE_ENCODER_ARGS: dict[Tuple[str, str], _HardwareEncoderSpec] = {
    ("qsv", "hevc"): _HardwareEncoderSpec(
        "hevc_qsv",
        optimized=("-preset medium", "-global_quality 28"),
        fast=("-preset veryfast", "-global_quality 28"),
    ),
    ("qsv", "av1"): _HardwareEncoderSpec(
        "av1_qsv",
        optimized=("-preset medium", "-global_quality 32"),
        fast=("-preset veryfast", "-global_quality 32"),
    ),
    ("amf", "hevc"): _HardwareEncoderSpec(
        "hevc_amf",
        optimized=("-quality balanced", "-rc cqp", "-qp_i 26", "-qp_p 28"),
        fast=("-quality speed", "-rc cqp", "-qp_i 26", "-qp_p 28"),
    ),
    ("amf", "av1"): _HardwareEncoderSpec(
        "av1_amf",
        optimized=("-quality balanced", "-rc cqp", "-qp_i 30", "-qp_p 32"),
        fast=("-quality speed", "-rc cqp", "-qp_i 30", "-qp_p 32"),
    ),
}


def _table_encoder_args(
    backend: Optional[str],
    codec: str,
    *,
    profile: str,
    extra_keyframe_args: Sequence[str],
    ffmpeg_path: Optional[str],
) -> Optional[List[str]]:
    """Return QSV/AMF encoder flags for *codec*, or ``None`` when not applicable."""

    spec = _HARDWARE_ENCODER_ARGS.get((backend or "", codec))
    if spec is None or not encoder_available(spec.encoder, ffmpeg_path=ffmpeg_path):
        return None
    profile_args = spec.fast if profile == "fast" else spec.optimized
    return [f"-c:v {spec.encoder}", *profile_args, *extra_keyframe_args]
```

In `build_video_commands`:

1. Replace the two parameters

```python
    cuda_available: bool,
    videotoolbox_available: bool = False,
```

with

```python
    hardware_backend: Optional[str] = None,
```

2. In the docstring, replace the `cuda_available:` and `videotoolbox_available:` entries with:

```
        hardware_backend: The backend :func:`detect_hardware_backend` returned
            for this codec (``"cuda"``, ``"amf"``, ``"qsv"``, ``"videotoolbox"``)
            or ``None`` for the CPU. Only CUDA also decodes on the GPU; QSV and
            AMF decode on the CPU because the filter graph runs there anyway.
```

3. Replace `if cuda_available and not small:` with `if hardware_backend == "cuda" and not small:`.

4. Replace

```python
    codec_choice = (video_codec or "h264").strip().lower()
    if codec_choice not in {"h264", "hevc", "av1"}:
        codec_choice = "h264"
```

with

```python
    codec_choice = normalize_video_codec(video_codec)
```

5. In `resolve_encoder_plan`, replace the parameters `prefer_cuda: bool,` and `prefer_videotoolbox: bool,` with `backend: Optional[str],`.

6. In the `av1` branch, replace

```python
            if prefer_cuda and encoder_available("av1_nvenc", ffmpeg_path=ffmpeg_path):
```

with

```python
            table_args = _table_encoder_args(
                backend,
                "av1",
                profile=profile,
                extra_keyframe_args=extra_keyframe_args,
                ffmpeg_path=ffmpeg_path,
            )
            if backend == "cuda" and encoder_available(
                "av1_nvenc", ffmpeg_path=ffmpeg_path
            ):
```

and directly after that `if` block's closing `fallback_args = cpu_encoder_args` line, add:

```python
            elif table_args is not None:
                uses_gpu = True
                primary_args = table_args
                fallback_args = cpu_encoder_args
```

7. In the `hevc` branch, replace

```python
            if prefer_cuda and encoder_available("hevc_nvenc", ffmpeg_path=ffmpeg_path):
```

with

```python
            table_args = _table_encoder_args(
                backend,
                "hevc",
                profile=profile,
                extra_keyframe_args=extra_keyframe_args,
                ffmpeg_path=ffmpeg_path,
            )
            if backend == "cuda" and encoder_available(
                "hevc_nvenc", ffmpeg_path=ffmpeg_path
            ):
```

replace `elif prefer_videotoolbox and encoder_available(` with `elif backend == "videotoolbox" and encoder_available(`, and after the VideoToolbox block's `fallback_args = cpu_encoder_args` line add:

```python
            elif table_args is not None:
                uses_gpu = True
                primary_args = table_args
                fallback_args = cpu_encoder_args
```

8. In the `h264` branch, replace `if prefer_cuda:` with `if backend == "cuda":` and extend the trailing comment so it reads:

```python
            # H.264 deliberately stays on libx264 even when VideoToolbox, QSV or
            # AMF is available: Apple's media engine caps out around 290 fps at
            # 1080p, and Intel QSV on a Core Ultra 5 125H managed 390 fps with a
            # 55% larger file, while libx264 -preset veryfast reaches 500-600 fps
            # across the CPU cores. HEVC and AV1 are the opposite — see above.
```

9. Replace the call

```python
    primary_plan, primary_fallback, primary_uses_gpu = resolve_encoder_plan(
        prefer_cuda=cuda_available,
        prefer_videotoolbox=videotoolbox_available and not cuda_available,
        codec=codec_choice,
```

with

```python
    primary_plan, primary_fallback, primary_uses_gpu = resolve_encoder_plan(
        backend=hardware_backend,
        codec=codec_choice,
```

- [ ] **Step 5: Run the ffmpeg tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_ffmpeg.py -v`
Expected: PASS

- [ ] **Step 6: Check nothing else still passes the old keywords**

Run: `git grep -n "cuda_available=\|videotoolbox_available=" -- talks_reducer`
Expected: only `talks_reducer/pipeline.py` lines (fixed in Task 4).

- [ ] **Step 7: Format and commit**

Task 4 must land before the suite is fully green again (pipeline still passes the old keywords), so commit Tasks 3 and 4 together: do not commit here, continue with Task 4.

---

### Task 4: Pipeline integration and invalidation on GPU fallback

**Files:**
- Modify: `talks_reducer/pipeline.py` — imports (lines 21-29), `PipelineDependencies` (lines 38-58), `speed_up_video` (lines ~299-302, ~352-357, ~392-394, ~552-570, ~650-653)
- Test: `tests/test_pipeline_service.py`, `tests/test_pipeline.py`

**Interfaces:**
- Consumes (Tasks 2-3): `detect_hardware_backend(codec, ffmpeg_path)`, `invalidate_hardware_backend_cache(codec, ffmpeg_path)`, `normalize_video_codec(value)`, `HARDWARE_BACKEND_LABELS`, `build_video_commands(..., hardware_backend=...)`.
- Produces: `PipelineDependencies.detect_hardware_backend: Callable[[str, str], Optional[str]]`, `PipelineDependencies.invalidate_hardware_backend_cache: Callable[[str, str], None]`. The `check_cuda_available` / `check_videotoolbox_available` fields are removed.

- [ ] **Step 1: Migrate pipeline tests to the new dependency fields**

Save as `%TEMP%\migrate_pipeline_tests.py` and run `.venv\Scripts\python.exe -I %TEMP%\migrate_pipeline_tests.py tests/test_pipeline.py tests/test_pipeline_service.py`:

```python
"""Replace check_cuda/check_videotoolbox dependencies with detect_hardware_backend."""

import re
import sys
from pathlib import Path

for name in sys.argv[1:]:
    path = Path(name)
    text = path.read_text(encoding="utf-8")
    text = re.sub(
        r"check_cuda_available=lambda \w+: False,",
        "detect_hardware_backend=lambda _codec, _path: None,",
        text,
    )
    text = re.sub(
        r"check_cuda_available=lambda \w+: True,",
        'detect_hardware_backend=lambda _codec, _path: "cuda",',
        text,
    )
    text = re.sub(r"\n\s*check_videotoolbox_available=lambda \w+: (?:True|False),", "", text)
    path.write_text(text, encoding="utf-8")
```

Run: `git grep -n "check_cuda_available\|check_videotoolbox_available" -- tests/test_pipeline.py tests/test_pipeline_service.py`
Expected: no output.

- [ ] **Step 2: Write the failing pipeline tests**

In `tests/test_pipeline_service.py`, add `from dataclasses import replace` to the imports.

In `test_speed_up_video_falls_back_to_cpu`, change the dependencies and assertions to:

```python
    invalidated: List[tuple] = []

    dependencies = PipelineDependencies(
        get_ffmpeg_path=positional_get_ffmpeg_path,
        detect_hardware_backend=lambda _codec, _path: "cuda",
        invalidate_hardware_backend_cache=lambda codec, path: invalidated.append(
            (codec, path)
        ),
        build_extract_audio_command=lambda *args, **kwargs: "extract",
        build_video_commands=lambda *args, **kwargs: ("render", "render-cpu", True),
        run_timed_ffmpeg_command=fake_run,
    )

    result = speed_up_video(options, reporter=reporter, dependencies=dependencies)

    assert commands == ["extract", "render", "render-cpu"]
    assert result.output_file.read_bytes() == b"fallback"
    assert any("CUDA encoding failed" in msg for msg in reporter.messages)
    assert ffmpeg_calls == [options.prefer_global_ffmpeg]
    # A real GPU failure means the cached answer is stale: re-probe next run.
    assert invalidated == [("h264", "ffmpeg")]
    assert result.gpu_backend is None
```

Append after `_stub_pipeline_externals`:

```python
def test_speed_up_video_detects_backend_for_requested_codec(monkeypatch, tmp_path):
    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"fake")
    options = ProcessingOptions(
        input_file=input_path,
        temp_folder=tmp_path / "temp",
        output_file=tmp_path / "output.mp4",
        video_codec="HEVC",
    )
    detected: List[tuple] = []
    build_kwargs: dict = {}

    def fake_detect(codec, path):
        detected.append((codec, path))
        return "qsv"

    def fake_build(*args, **kwargs):
        build_kwargs.update(kwargs)
        return ("render", "render-cpu", True)

    dependencies = replace(
        _stub_pipeline_externals(monkeypatch, options),
        detect_hardware_backend=fake_detect,
        build_video_commands=fake_build,
    )
    reporter = DummyReporter()

    result = speed_up_video(options, reporter=reporter, dependencies=dependencies)

    assert detected == [("hevc", "ffmpeg")]
    assert build_kwargs["hardware_backend"] == "qsv"
    assert "Processing on: GPU (QSV)" in reporter.messages
    assert result.gpu_backend == "QSV"


def test_speed_up_video_skips_detection_for_mp3(monkeypatch, tmp_path):
    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"fake")
    options = ProcessingOptions(
        input_file=input_path,
        temp_folder=tmp_path / "temp",
        output_file=tmp_path / "output.mp3",
        video_codec="mp3",
    )

    def fail_detect(codec, path):
        raise AssertionError("mp3 output must not probe GPU encoders")

    dependencies = replace(
        _stub_pipeline_externals(monkeypatch, options),
        detect_hardware_backend=fail_detect,
        build_audio_only_command=lambda *args, **kwargs: "render",
    )

    speed_up_video(options, reporter=DummyReporter(), dependencies=dependencies)


def test_speed_up_video_uses_cuda_hwaccel_only_for_cuda(monkeypatch, tmp_path):
    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"fake")
    options = ProcessingOptions(
        input_file=input_path,
        temp_folder=tmp_path / "temp",
        output_file=tmp_path / "output.mp4",
        video_codec="hevc",
    )
    hwaccels: List[list] = []

    def fake_extract(_input, _wav, _rate, _bitrate, hwaccel, **_kwargs):
        hwaccels.append(list(hwaccel))
        return "extract"

    dependencies = replace(
        _stub_pipeline_externals(monkeypatch, options),
        detect_hardware_backend=lambda _codec, _path: "qsv",
        build_extract_audio_command=fake_extract,
    )

    speed_up_video(options, reporter=DummyReporter(), dependencies=dependencies)

    assert hwaccels == [[]]
```

- [ ] **Step 3: Run the pipeline tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_pipeline_service.py tests/test_pipeline.py -q`
Expected: FAIL — `TypeError: PipelineDependencies.__init__() got an unexpected keyword argument 'detect_hardware_backend'`.

- [ ] **Step 4: Implement the pipeline changes**

In `talks_reducer/pipeline.py`:

1. Replace the ffmpeg import block with:

```python
from .ffmpeg import (
    HARDWARE_BACKEND_LABELS,
    build_audio_only_command,
    build_extract_audio_command,
    build_video_commands,
    detect_hardware_backend,
    get_ffmpeg_path,
    invalidate_hardware_backend_cache,
    normalize_video_codec,
    run_timed_ffmpeg_command,
)
```

2. In `PipelineDependencies`, replace

```python
    check_cuda_available: Callable[[str], bool] = check_cuda_available
    check_videotoolbox_available: Callable[[str], bool] = check_videotoolbox_available
```

with

```python
    detect_hardware_backend: Callable[[str, str], str | None] = detect_hardware_backend
    invalidate_hardware_backend_cache: Callable[[str, str], None] = (
        invalidate_hardware_backend_cache
    )
```

3. Delete the lines

```python
    cuda_available = dependencies.check_cuda_available(ffmpeg_path)
    videotoolbox_available = (
        not cuda_available and dependencies.check_videotoolbox_available(ffmpeg_path)
    )
```

4. Delete the block

```python
    if cuda_available:
        gpu_backend: str | None = "CUDA"
    elif videotoolbox_available:
        gpu_backend = "VideoToolbox"
    else:
        gpu_backend = None
```

5. Directly before `neutral_speeds = math.isclose(`, add:

```python
    # Detected per codec (not every GPU encodes AV1) and only once the job is
    # known to need a video encode, so mp3 exports never spawn a probe.
    encode_codec = normalize_video_codec(options.video_codec)
    hardware_backend = (
        None
        if is_mp3_output
        else dependencies.detect_hardware_backend(encode_codec, ffmpeg_path)
    )
    gpu_backend: str | None = (
        HARDWARE_BACKEND_LABELS.get(hardware_backend) if hardware_backend else None
    )
```

6. Replace

```python
    hwaccel = (
        ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"] if cuda_available else []
    )
```

with

```python
    hwaccel = (
        ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
        if hardware_backend == "cuda"
        else []
    )
```

7. In the `dependencies.build_video_commands(` call, replace

```python
                cuda_available=cuda_available,
                videotoolbox_available=videotoolbox_available,
```

with

```python
                hardware_backend=hardware_backend,
```

8. In the `except subprocess.CalledProcessError:` branch, change

```python
            if use_gpu_encoder:
                reporter.log(
                    f"{gpu_backend} encoding failed, retrying with CPU encoder..."
                )
```

to

```python
            if use_gpu_encoder:
                reporter.log(
                    f"{gpu_backend} encoding failed, retrying with CPU encoder..."
                )
                # The cached detection said this GPU works; it just did not.
                dependencies.invalidate_hardware_backend_cache(
                    encode_codec, ffmpeg_path
                )
```

- [ ] **Step 5: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: PASS

- [ ] **Step 6: Confirm no stale references remain**

Run: `git grep -n "cuda_available\|videotoolbox_available\|check_videotoolbox_available\b" -- talks_reducer tests`
Expected: only the definitions/tests of `check_cuda_available` and `check_videotoolbox_available` in `talks_reducer/ffmpeg.py` and `tests/test_ffmpeg.py` (and `_probe_backend`'s call to `check_videotoolbox_available`).

- [ ] **Step 7: Format and commit Tasks 3 + 4**

```bash
.venv\Scripts\python.exe -m black talks_reducer/ffmpeg.py talks_reducer/pipeline.py tests/test_ffmpeg.py tests/test_pipeline.py tests/test_pipeline_service.py
.venv\Scripts\python.exe -m isort talks_reducer/ffmpeg.py talks_reducer/pipeline.py tests/test_ffmpeg.py tests/test_pipeline.py tests/test_pipeline_service.py
git add talks_reducer/ffmpeg.py talks_reducer/pipeline.py tests/test_ffmpeg.py tests/test_pipeline.py tests/test_pipeline_service.py
git commit -m "feat: Add Intel QSV and AMD AMF hardware encoding" -m "H.265 and AV1 encode on QSV or AMF when no NVENC GPU is present; H.264 stays on libx264, which beat QSV on both speed and size." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Calibrate QSV quality and verify keyframes

**Files:**
- Modify: `talks_reducer/ffmpeg.py` — `_HARDWARE_ENCODER_ARGS` QSV values
- Modify: `tests/test_ffmpeg.py` — the `-global_quality` assertions in `test_build_video_commands_hevc_qsv_optimized` / `test_build_video_commands_av1_qsv_fast`
- Modify: `docs/superpowers/specs/2026-10-10-qsv-amf-hardware-encoding-design.md` — "Calibration results"

**Interfaces:**
- Consumes: `_HARDWARE_ENCODER_ARGS` from Task 3.
- Produces: final QSV `-global_quality` values `H` (hevc) and `A` (av1).

Requires the Intel machine and the source `C:\Users\popstas\Videos\2026-03-04 15-43-22.mp4` (2:38, 1080p60). Scripts and outputs live under `%TEMP%\talks-reducer-calibration`, never in the repo.

- [ ] **Step 1: Write the sweep script**

Save as `%TEMP%\talks-reducer-calibration\sweep.py`:

```python
"""Sweep QSV -global_quality and report size and VMAF at a target height."""

import json
import subprocess
import sys
from pathlib import Path

SRC, OUT, HEIGHT = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3])
JOBS = [(codec, gq) for codec, values in json.loads(sys.argv[4]).items() for gq in values]
OUT.mkdir(parents=True, exist_ok=True)
SCALE = f"scale=-2:{HEIGHT}"


def vmaf(path: Path) -> float:
    """Mean VMAF against the source scaled to HEIGHT, every 5th frame."""

    log = path.with_suffix(".json")
    graph = (
        f"[0:v]setpts=PTS-STARTPTS[d];[1:v]{SCALE},setpts=PTS-STARTPTS[r];"
        f"[d][r]libvmaf=n_subsample=5:n_threads=16:log_fmt=json:log_path={log.name}"
    )
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-v", "error", "-i", str(path), "-i", SRC,
         "-lavfi", graph, "-f", "null", "-"],
        check=True, cwd=OUT,
    )
    return json.loads(log.read_text())["pooled_metrics"]["vmaf"]["mean"]


for codec, gq in JOBS:
    dst = OUT / f"{codec}_{HEIGHT}p_gq{gq}.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-v", "error", "-y", "-i", SRC, "-vf", SCALE,
         "-c:v", f"{codec}_qsv", "-preset", "medium", "-global_quality", str(gq),
         "-an", str(dst)],
        check=True,
    )
    row = {"codec": codec, "height": HEIGHT, "gq": gq,
           "mb": round(dst.stat().st_size / 1e6, 2), "vmaf": round(vmaf(dst), 2)}
    print(json.dumps(row), flush=True)
```

- [ ] **Step 2: Run the 720p sweep (~12 min, run in background)**

```bash
.venv\Scripts\python.exe -I "%TEMP%\talks-reducer-calibration\sweep.py" "C:\Users\popstas\Videos\2026-03-04 15-43-22.mp4" "%TEMP%\talks-reducer-calibration\out" 720 "{\"hevc\": [27, 28, 29, 30], \"av1\": [28, 29, 30, 31, 32]}"
```

Expected: nine JSON lines. Known anchors from the original benchmark: hevc gq 28 → 3.91 MB / VMAF 91.7; av1 gq 32 → 3.67 MB / VMAF 90.0.

- [ ] **Step 3: Pick H and A**

For each codec choose the `gq` whose VMAF is closest to 91.0; on a tie (within 0.2) take the higher `gq` (smaller file). Record both values.

- [ ] **Step 4: Confirm the choice at 480p**

```bash
.venv\Scripts\python.exe -I "%TEMP%\talks-reducer-calibration\sweep.py" "C:\Users\popstas\Videos\2026-03-04 15-43-22.mp4" "%TEMP%\talks-reducer-calibration\out" 480 "{\"hevc\": [H], \"av1\": [A]}"
```

(substitute the chosen numbers). Expected: VMAF ≥ 88 for both. If either is below 88, lower that codec's value by 1 and re-run Steps 2-4 for it.

- [ ] **Step 5: Verify `-force_key_frames` works with QSV**

```bash
ffmpeg -hide_banner -v error -y -t 20 -i "C:\Users\popstas\Videos\2026-03-04 15-43-22.mp4" -vf scale=-2:720 -c:v hevc_qsv -preset medium -global_quality 28 -g 1800 -keyint_min 1800 -force_key_frames "expr:gte(t,n_forced*5)" -an "%TEMP%\talks-reducer-calibration\kf.mp4"
```

```bash
ffprobe -v error -select_streams v:0 -skip_frame nokey -show_entries frame=pts_time -of csv=p=0 "%TEMP%\talks-reducer-calibration\kf.mp4"
```

Expected: keyframes at roughly `0`, `5`, `10`, `15`. Repeat with `-c:v av1_qsv`. If keyframes appear only at `0`, `-force_key_frames` is ignored: in `_table_encoder_args`, drop entries starting with `-force_key_frames` from `extra_keyframe_args` when `backend == "qsv"`, and add a test asserting `-force_key_frames` is absent from the QSV command. If keyframes are present, change nothing.

- [ ] **Step 6: Apply the values**

In `_HARDWARE_ENCODER_ARGS`, set `-global_quality H` on both `("qsv", "hevc")` profiles and `-global_quality A` on both `("qsv", "av1")` profiles. Update the matching assertions in `test_build_video_commands_hevc_qsv_optimized` (`"-global_quality H"`) and `test_build_video_commands_av1_qsv_fast` (`"-global_quality A"`).

- [ ] **Step 7: Record the results in the spec**

Replace the `To be filled in during implementation (§2.1).` line in the spec with a table of every sweep row (codec, height, gq, MB, VMAF), the chosen `H` and `A`, and the keyframe check outcome for `hevc_qsv` and `av1_qsv`.

- [ ] **Step 8: Run tests, format, commit**

Run: `.venv\Scripts\python.exe -m pytest tests/test_ffmpeg.py -q`
Expected: PASS

```bash
.venv\Scripts\python.exe -m black talks_reducer/ffmpeg.py tests/test_ffmpeg.py
.venv\Scripts\python.exe -m isort talks_reducer/ffmpeg.py tests/test_ffmpeg.py
git add talks_reducer/ffmpeg.py tests/test_ffmpeg.py docs/superpowers/specs/2026-10-10-qsv-amf-hardware-encoding-design.md
git commit -m "perf(ffmpeg): Calibrate QSV quality against VMAF" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: End-to-end verification and documentation

**Files:**
- Modify: `README.md:18-19`
- Modify: `docs/cli.md:142-160`
- Modify: `AGENTS.md:148`, `AGENTS.md:161`, `AGENTS.md:167`
- Modify: `CLAUDE.md` — the matching `ffmpeg.py`, "Highlights" and "Processing Pipeline" lines

**Interfaces:**
- Consumes: the finished feature from Tasks 1-5.

- [ ] **Step 1: Real run — HEVC on QSV, first run probes**

Remove any existing cache entry first: open `%APPDATA%\talks-reducer\settings.json` and delete the `"hardware_backend"` key if present (keep every other key).

```bash
.venv\Scripts\python.exe -m talks_reducer --video-codec hevc "C:\Users\popstas\Videos\2026-03-04 15-43-22.mp4" -o "%TEMP%\talks-reducer-calibration\e2e_hevc.mp4"
```

Expected log lines: `Processing on: GPU (QSV)`, the FFmpeg command contains `-c:v hevc_qsv` and no `-hwaccel cuda`; no `CUDA encoding failed`. `settings.json` now contains `hardware_backend.codecs.hevc.backend == "qsv"`.

- [ ] **Step 2: Real run — cache reuse and AV1**

Run the same command again and time it against Step 1's start-up (the ~0.85 s probe must be gone). Then:

```bash
.venv\Scripts\python.exe -m talks_reducer --video-codec av1 "C:\Users\popstas\Videos\2026-03-04 15-43-22.mp4" -o "%TEMP%\talks-reducer-calibration\e2e_av1.mp4"
```

Expected: `Processing on: GPU (QSV)`, `-c:v av1_qsv`; `settings.json` gains `codecs.av1`.

- [ ] **Step 3: Real run — H.264 stays on the CPU**

```bash
.venv\Scripts\python.exe -m talks_reducer --video-codec h264 "C:\Users\popstas\Videos\2026-03-04 15-43-22.mp4" -o "%TEMP%\talks-reducer-calibration\e2e_h264.mp4"
```

Expected: `Processing on: CPU`, `-c:v libx264`, no `-hwaccel cuda`, no fallback message; `codecs.h264.backend` is `null`.

- [ ] **Step 4: Update README.md**

Replace lines 18-19 with:

```markdown
- **Fast** — in-memory audio/video processing, auto GPU encoding (NVENC on
  NVIDIA, AMF on AMD, Quick Sync on Intel, VideoToolbox for HEVC on macOS).
```

- [ ] **Step 5: Update docs/cli.md**

Replace the paragraph at lines 142-143 ("When CUDA-capable hardware is available …") with:

```markdown
The pipeline picks a hardware encoder automatically, trying NVIDIA NVENC, then AMD AMF,
then Intel Quick Sync (QSV), and still runs great on CPUs. Each candidate is checked by
encoding a single tiny frame, because the bundled FFmpeg lists NVENC, AMF and QSV encoders
on every machine whether or not the GPU exists. The check runs per codec — older GPUs
encode HEVC but not AV1 — and its result is cached in `settings.json` under
`hardware_backend` for 30 days, or until the FFmpeg binary changes. A GPU encode that fails
falls back to the CPU and clears that codec's cache entry; delete the `hardware_backend`
key to force a fresh check after installing a new GPU or driver.

AMF and QSV handle `--video-codec hevc` and `--video-codec av1` only. H.264 stays on `libx264` with
them: on an Intel Core Ultra 5 125H, `h264_qsv` encoded a 1080p60 recording at 390 fps
with a 55% larger file, while `libx264 -preset veryfast` reached 504 fps. HEVC and AV1 are
the reverse — QSV was 3.6× faster than `libx265` and 15× faster than `libaom` while
producing smaller files. The AMF settings are not yet calibrated on AMD hardware.
```

- [ ] **Step 6: Update AGENTS.md and CLAUDE.md**

In both files, replace the `ffmpeg.py` bullet with:

```markdown
  - `ffmpeg.py` discovers the FFmpeg binary, detects the hardware encoder per codec (`detect_hardware_backend`: NVENC → AMF → QSV → VideoToolbox, verified by a one-frame trial encode because the bundled build lists every GPU encoder regardless of hardware, cached in `settings.json` under `hardware_backend` for 30 days keyed by the FFmpeg fingerprint), and assembles command strings. QSV/AMF arguments live in `_HARDWARE_ENCODER_ARGS`.
```

replace the Highlights GPU bullet with:

```markdown
- Automatically detects GPU encoders — NVENC on NVIDIA, AMF on AMD and Quick Sync on Intel for HEVC/AV1, VideoToolbox for HEVC on macOS — so you no longer need to pass `--cuda`
```

and replace Processing Pipeline step 4 with:

```markdown
4. Stitch the processed audio and video together with FFmpeg on the detected hardware encoder: NVENC for every codec, AMF or QSV for HEVC and AV1, VideoToolbox for HEVC on macOS. H.264 stays on `libx264` for AMF, QSV and VideoToolbox, where it is both faster and smaller. A failed GPU encode re-runs on the CPU and clears that codec's detection cache.
```

- [ ] **Step 7: Final checks**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: PASS

Run: `.venv\Scripts\python.exe -m black --check talks_reducer tests` and `.venv\Scripts\python.exe -m isort --check-only talks_reducer tests`
Expected: no changes needed.

- [ ] **Step 8: Commit**

```bash
git add README.md docs/cli.md AGENTS.md CLAUDE.md
git commit -m "docs: Document QSV and AMF hardware encoding" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
