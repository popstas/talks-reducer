# Web UI (PWA) Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Declutter the Gradio web UI (radios + collapsible accordions + compact result summary), enable Gradio's built-in PWA, all without breaking the `service_client` API contract.

**Architecture:** Extract the pipeline-run body of `process_video` into a shared `_stream_pipeline` generator that yields semantic events. `process_video` keeps its 4-tuple generator behavior; a new `process_video_ui` browser handler produces a 5-tuple (adds a Details output) and maps the new radio controls; a clean-signature `process_video_api` wrapper is registered via `gr.api(api_name="process_video")` so the programmatic contract is decoupled from the browser UI.

**Tech Stack:** Python 3.12, Gradio 6.6.0, pytest, black, isort.

## Global Constraints

- The programmatic endpoint MUST accept 13 positional args in the current `process_video` order (`file, small, small_480, optimize, video_codec, add_codec_suffix, use_global_ffmpeg, silent_threshold, sounded_speed, silent_speed, cut_enabled, cut_start, cut_end`) and return a 4-tuple `(video, log, summary, download)`. Verified by `service_client.send_video`.
- `gr.api` requires a type hint on every parameter and rejects `gr.Progress`/`dependencies` params — use the clean-signature `process_video_api` wrapper.
- No new dependencies. Run `black` and `isort` (configured in `pyproject.toml`) before each commit.
- Virtualenv is `.venv`; run tests with `.venv/bin/python -m pytest`.
- Do not modify the desktop GUI, CLI, or the PWA manifest/icon middleware.

---

### Task 1: Compact result formatters + summary split

**Files:**
- Modify: `talks_reducer/server.py` (near `_format_duration`/`_format_file_size`/`_format_summary`, ~lines 716-769)
- Test: `tests/test_server.py`

**Interfaces:**
- Produces: `_format_duration_compact(seconds: float) -> str`, `_format_size_compact(num_bytes: int) -> str`, `_format_summary_compact(result: ProcessingResult) -> str`, `_format_details(result: ProcessingResult) -> str`, and a rewritten `_format_summary(result) -> str` returning compact + details.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_server.py`:

```python
def test_format_duration_compact_has_no_spaces() -> None:
    assert server._format_duration_compact(0) == "0s"
    assert server._format_duration_compact(12) == "12s"
    assert server._format_duration_compact(3574) == "59m34s"
    assert server._format_duration_compact(4332) == "1h12m12s"


def test_format_size_compact() -> None:
    assert server._format_size_compact(0) == "0B"
    assert server._format_size_compact(506 * 1024 * 1024) == "506M"
    assert server._format_size_compact(int(1.2 * 1024 * 1024 * 1024)) == "1.2G"


def test_format_summary_compact_and_details(tmp_path: Path) -> None:
    import os

    input_file = tmp_path / "in.mp4"
    output_file = tmp_path / "out.mp4"
    # Sparse files: set apparent size without writing hundreds of MB.
    input_file.write_bytes(b"")
    output_file.write_bytes(b"")
    os.truncate(input_file, 500 * 1024 * 1024)
    os.truncate(output_file, 250 * 1024 * 1024)
    result = ProcessingResult(
        input_file=input_file,
        output_file=output_file,
        frame_rate=30.0,
        original_duration=4332.0,
        output_duration=3574.0,
        chunk_count=7,
        used_cuda=True,
        max_audio_volume=0.5,
        time_ratio=0.825,
        size_ratio=0.5,
    )
    compact = server._format_summary_compact(result)
    assert "Duration:" in compact and "1h12m12s -> 59m34s (82%)" in compact
    assert "Size:" in compact and "500M -> 250M (50%)" in compact

    details = server._format_details(result)
    assert "`in.mp4`" in details and "`out.mp4`" in details
    assert "Chunks merged:** 7" in details
    assert "Encoder:** CUDA" in details

    full = server._format_summary(result)
    assert compact in full and "Chunks merged:** 7" in full
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_server.py::test_format_duration_compact_has_no_spaces tests/test_server.py::test_format_size_compact tests/test_server.py::test_format_summary_compact_and_details -v`
Expected: FAIL with `AttributeError: module 'talks_reducer.server' has no attribute '_format_duration_compact'`.

- [ ] **Step 3: Implement the formatters**

In `talks_reducer/server.py`, add after `_format_file_size` (keep the existing `_format_duration` and `_format_file_size` as-is — other code uses them):

```python
def _format_duration_compact(seconds: float) -> str:
    """Return a no-space compact duration like ``1h12m12s`` or ``59m34s``."""

    if seconds <= 0:
        return "0s"
    total_seconds = int(round(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes or hours:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return "".join(parts)


def _format_size_compact(num_bytes: int) -> str:
    """Return a compact single-letter size like ``506M`` or ``1.2G``."""

    size = float(max(0, int(num_bytes)))
    for unit in ("B", "K", "M", "G"):
        if size < 1024.0:
            if unit == "B":
                return f"{int(size)}{unit}"
            if size >= 10:
                return f"{int(round(size))}{unit}"
            return f"{size:.1f}{unit}"
        size /= 1024.0
    return f"{size:.1f}T"
```

Then replace the existing `_format_summary` with these three functions:

```python
def _format_summary_compact(result: ProcessingResult) -> str:
    """Produce the two headline result lines (duration + size)."""

    lines: list[str] = []

    duration_suffix = ""
    if result.original_duration > 0:
        pct = round(result.output_duration / result.original_duration * 100)
        duration_suffix = f" ({pct}%)"
    lines.append(
        "**Duration:** "
        f"{_format_duration_compact(result.original_duration)} -> "
        f"{_format_duration_compact(result.output_duration)}{duration_suffix}"
    )

    try:
        input_bytes = result.input_file.stat().st_size
        output_bytes = result.output_file.stat().st_size
    except OSError:
        input_bytes = output_bytes = 0
    if input_bytes > 0 and output_bytes > 0:
        size_pct = round(output_bytes / input_bytes * 100)
        lines.append(
            "**Size:** "
            f"{_format_size_compact(input_bytes)} -> "
            f"{_format_size_compact(output_bytes)} ({size_pct}%)"
        )

    return "\n".join(lines)


def _format_details(result: ProcessingResult) -> str:
    """Produce the collapsible detail lines shown under the summary."""

    return "\n".join(
        [
            f"**Input:** `{result.input_file.name}`",
            f"**Output:** `{result.output_file.name}`",
            f"**Chunks merged:** {result.chunk_count}",
            f"**Encoder:** {'CUDA' if result.used_cuda else 'CPU'}",
        ]
    )


def _format_summary(result: ProcessingResult) -> str:
    """Full summary for the API path: compact headline plus detail lines."""

    compact = _format_summary_compact(result)
    details = _format_details(result)
    return f"{compact}\n{details}" if compact else details
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_server.py::test_format_duration_compact_has_no_spaces tests/test_server.py::test_format_size_compact tests/test_server.py::test_format_summary_compact_and_details -v`
Expected: PASS.

- [ ] **Step 5: Update the existing summary-format assertions**

The current `test_process_video_streams_events_and_returns_result` asserts the old percentages `"25.0%"`/`"30.0%"` in `final[2]`. The stub does not create the output file, so the Size line is omitted and duration percent is now integer. Edit those two assertions (near `tests/test_server.py:388-389`):

```python
    assert "25%" in final[2]
    assert "Chunks merged:** 5" in final[2]
```

(Remove the `"30.0%"` assertion.)

- [ ] **Step 6: Run the affected test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_server.py::test_process_video_streams_events_and_returns_result -v`
Expected: PASS.

- [ ] **Step 7: Format and commit**

```bash
.venv/bin/python -m black talks_reducer/server.py tests/test_server.py
.venv/bin/python -m isort talks_reducer/server.py tests/test_server.py
git add talks_reducer/server.py tests/test_server.py
git commit -m "feat: Add compact web UI result summary with collapsible details"
```

---

### Task 2: Extract the shared `_stream_pipeline` core

**Files:**
- Modify: `talks_reducer/server.py` (`process_video`, ~lines 874-1023)
- Test: `tests/test_server.py`

**Interfaces:**
- Produces: `_stream_pipeline(...)` generator with the SAME leading parameters as `process_video` (minus the gradio outputs), yielding `("log", str)`, `("progress", tuple[int,int,str])`, and finally `("done", tuple[ProcessingResult, str])`; raises `gr.Error` on failure.
- `process_video(...)` keeps its exact public signature and 4-tuple output, now delegating to `_stream_pipeline`.

- [ ] **Step 1: Write a regression test for the 4-tuple contract**

Add to `tests/test_server.py` (reuses the `_speed_up`/`dependencies` pattern already in the file):

```python
def test_process_video_still_yields_four_tuples(tmp_path: Path) -> None:
    input_file = tmp_path / "clip.mp4"
    input_file.write_bytes(b"data")

    def _speed_up(options: ProcessingOptions, reporter: server.SignalProgressReporter):
        reporter.log("working")
        return ProcessingResult(
            input_file=options.input_file,
            output_file=options.output_file or input_file,
            frame_rate=24.0,
            original_duration=100.0,
            output_duration=50.0,
            chunk_count=2,
            used_cuda=False,
            max_audio_volume=0.6,
            time_ratio=0.5,
            size_ratio=0.5,
        )

    dependencies = server.ProcessVideoDependencies(
        speed_up=_speed_up,
        reporter_factory=server._default_reporter_factory,
        queue_factory=SimpleQueue,
        run_pipeline_job_func=server.run_pipeline_job,
        start_in_thread=False,
    )
    try:
        outputs = list(
            server.process_video(
                str(input_file),
                small_video=False,
                progress=None,
                dependencies=dependencies,
            )
        )
    finally:
        server._cleanup_workspaces()

    assert outputs, "process_video should yield at least once"
    assert all(isinstance(o, tuple) and len(o) == 4 for o in outputs)
```

- [ ] **Step 2: Run it to confirm it passes on the current code**

Run: `.venv/bin/python -m pytest tests/test_server.py::test_process_video_still_yields_four_tuples -v`
Expected: PASS (this is a characterization test guarding the refactor).

- [ ] **Step 3: Extract `_stream_pipeline`**

In `talks_reducer/server.py`, replace the body of `process_video` (from the `if not file_path:` guard through the final `yield`) so the setup + streaming lives in a shared generator. Add `_stream_pipeline` just above `process_video`:

```python
def _stream_pipeline(
    file_path: Optional[str],
    small_video: bool,
    small_480: bool,
    optimize: bool,
    video_codec: str,
    add_codec_suffix: bool,
    use_global_ffmpeg: bool,
    silent_threshold: Optional[float],
    sounded_speed: Optional[float],
    silent_speed: Optional[float],
    cut_enabled: bool,
    cut_start_seconds: Optional[float],
    cut_end_seconds: Optional[float],
    dependencies: Optional["ProcessVideoDependencies"],
) -> Iterator[tuple[str, object]]:
    """Run the pipeline, yielding semantic events shared by both handlers.

    Yields ``("log", full_log)`` on each log update (including the initial
    upload receipt), ``("progress", (current, total, desc))`` for progress, and
    finally ``("done", (result, full_log))``. Raises ``gr.Error`` on failure.
    """

    if not file_path:
        raise gr.Error("Please upload a video file to begin processing.")

    input_path = Path(file_path)
    if not input_path.exists():
        raise gr.Error("The uploaded file is no longer available on the server.")

    upload_size = input_path.stat().st_size
    upload_received_message = (
        f"Upload received: {input_path.name} ({_format_file_size(upload_size)})"
    )

    codec_value = (video_codec or "h264").strip().lower()
    if codec_value not in {"h264", "hevc", "av1", "mp3"}:
        codec_value = "h264"

    normalized_sounded_speed: Optional[float] = None
    if sounded_speed is not None:
        normalized_sounded_speed = float(sounded_speed)

    normalized_silent_speed: Optional[float] = None
    if silent_speed is not None:
        normalized_silent_speed = float(silent_speed)

    workspace = _allocate_workspace()
    temp_folder = workspace / "temp"
    output_file = _build_output_path(
        input_path,
        workspace,
        small_video,
        small_480=small_480,
        add_codec_suffix=add_codec_suffix,
        video_codec=codec_value,
        silent_speed=normalized_silent_speed,
        sounded_speed=normalized_sounded_speed,
    )

    deps = dependencies or ProcessVideoDependencies()
    events = deps.queue_factory()

    option_kwargs: dict[str, float | str | bool] = {
        "video_codec": codec_value,
        "prefer_global_ffmpeg": bool(use_global_ffmpeg),
        "optimize": bool(optimize),
    }
    if add_codec_suffix:
        option_kwargs["add_codec_suffix"] = True
    if silent_threshold is not None:
        option_kwargs["silent_threshold"] = float(silent_threshold)
    if normalized_sounded_speed is not None:
        option_kwargs["sounded_speed"] = normalized_sounded_speed
    if normalized_silent_speed is not None:
        option_kwargs["silent_speed"] = normalized_silent_speed
    if small_video and small_480:
        option_kwargs["small_target_height"] = 480
    if cut_enabled:
        option_kwargs["cut_start_seconds"] = float(cut_start_seconds or 0.0)
        option_kwargs["cut_end_seconds"] = float(cut_end_seconds or 0.0)

    options = ProcessingOptions(
        input_file=input_path,
        output_file=output_file,
        temp_folder=temp_folder,
        small=small_video,
        **option_kwargs,
    )

    event_stream = deps.run_pipeline_job_func(
        options,
        speed_up=deps.speed_up,
        reporter_factory=deps.reporter_factory,
        events=events,
        enable_progress=True,
        start_in_thread=deps.start_in_thread,
    )

    collected_logs: list[str] = [upload_received_message]
    final_result: Optional[ProcessingResult] = None
    error: Optional[gr.Error] = None

    yield ("log", "\n".join(collected_logs))

    for kind, payload in event_stream:
        if kind == "log":
            text = str(payload).strip()
            if text:
                collected_logs.append(text)
                yield ("log", "\n".join(collected_logs))
        elif kind == "progress":
            yield ("progress", payload)
        elif kind == "result":
            final_result = payload  # type: ignore[assignment]
        elif kind == "error":
            error = payload  # type: ignore[assignment]

    if error is not None:
        raise error
    if final_result is None:
        raise gr.Error("Failed to process the video.")

    yield ("done", (final_result, "\n".join(collected_logs)))
```

Note: `_stream_pipeline` always passes `enable_progress=True`; the caller decides whether to drive a progress widget. This matches prior behavior because `process_video` only called `progress(...)` when `progress is not None`.

- [ ] **Step 4: Rewrite `process_video` to delegate**

Replace `process_video`'s body (keep the signature and docstring) with:

```python
    for kind, payload in _stream_pipeline(
        file_path,
        small_video,
        small_480,
        optimize,
        video_codec,
        add_codec_suffix,
        use_global_ffmpeg,
        silent_threshold,
        sounded_speed,
        silent_speed,
        cut_enabled,
        cut_start_seconds,
        cut_end_seconds,
        dependencies,
    ):
        if kind == "log":
            yield (gr.update(), cast(str, payload), gr.update(), gr.update())
        elif kind == "progress":
            if progress is not None:
                current, total, desc = cast(tuple[int, int, str], payload)
                percent = current / total if total > 0 else 0
                progress(percent, total=total, desc=desc)
        elif kind == "done":
            final_result, log_text = cast(
                tuple[ProcessingResult, str], payload
            )
            summary = _format_summary(final_result)
            output_path = str(final_result.output_file)
            is_audio_only = (
                Path(final_result.output_file).suffix.lower() == ".mp3"
            )
            yield (
                None if is_audio_only else output_path,
                log_text,
                summary,
                output_path,
            )
```

- [ ] **Step 5: Run the process_video tests**

Run: `.venv/bin/python -m pytest tests/test_server.py -k process_video -v`
Expected: PASS (including `test_process_video_still_yields_four_tuples` and the updated summary test).

- [ ] **Step 6: Format and commit**

```bash
.venv/bin/python -m black talks_reducer/server.py tests/test_server.py
.venv/bin/python -m isort talks_reducer/server.py tests/test_server.py
git add talks_reducer/server.py tests/test_server.py
git commit -m "refactor: Extract shared _stream_pipeline core from process_video"
```

---

### Task 3: Control-mapping helpers + `process_video_ui` + `process_video_api`

**Files:**
- Modify: `talks_reducer/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `_stream_pipeline`, `_format_summary_compact`, `_format_details` (Tasks 1-2).
- Produces:
  - `_resolution_to_flags(resolution: str) -> tuple[bool, bool]`
  - `_speedup_to_silent_speed(label: str) -> float`
  - `process_video_ui(...)` generator yielding 5-tuples `(video, log, summary_compact, details, download)`
  - `process_video_api(...)` clean-signature generator that `yield from process_video(...)`

- [ ] **Step 1: Write failing tests for the mappings**

Add to `tests/test_server.py`:

```python
import pytest as _pytest


@_pytest.mark.parametrize(
    "resolution, expected",
    [("No change", (False, False)), ("720p", (True, False)), ("480p", (True, True))],
)
def test_resolution_to_flags(resolution, expected) -> None:
    assert server._resolution_to_flags(resolution) == expected


@_pytest.mark.parametrize(
    "label, expected", [("1×", 1.0), ("5×", 5.0), ("10×", 10.0), ("???", 10.0)]
)
def test_speedup_to_silent_speed(label, expected) -> None:
    assert server._speedup_to_silent_speed(label) == expected


def test_process_video_ui_yields_five_tuples(tmp_path: Path) -> None:
    input_file = tmp_path / "clip.mp4"
    input_file.write_bytes(b"data")

    def _speed_up(options: ProcessingOptions, reporter: server.SignalProgressReporter):
        assert options.small is True and options.small_target_height != 480
        return ProcessingResult(
            input_file=options.input_file,
            output_file=options.output_file or input_file,
            frame_rate=24.0,
            original_duration=100.0,
            output_duration=50.0,
            chunk_count=2,
            used_cuda=False,
            max_audio_volume=0.6,
            time_ratio=0.5,
            size_ratio=0.5,
        )

    dependencies = server.ProcessVideoDependencies(
        speed_up=_speed_up,
        reporter_factory=server._default_reporter_factory,
        queue_factory=SimpleQueue,
        run_pipeline_job_func=server.run_pipeline_job,
        start_in_thread=False,
    )
    try:
        outputs = list(
            server.process_video_ui(
                str(input_file),
                "720p",
                10.0,
                "hevc",
                True,
                False,
                False,
                1.0,
                0.01,
                False,
                0.0,
                0.0,
                progress=None,
                dependencies=dependencies,
            )
        )
    finally:
        server._cleanup_workspaces()

    assert outputs and all(len(o) == 5 for o in outputs)
    final = outputs[-1]
    assert "Duration:" in final[2]  # compact summary
    assert "Chunks merged:** 2" in final[3]  # details slot
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_server.py -k "resolution_to_flags or speedup_to_silent_speed or process_video_ui" -v`
Expected: FAIL (`_resolution_to_flags`/`process_video_ui` undefined).

- [ ] **Step 3: Implement mappings and handlers**

In `talks_reducer/server.py`, add near `process_video`:

```python
def _resolution_to_flags(resolution: str) -> tuple[bool, bool]:
    """Map the Resolution radio to ``(small, small_480)``."""

    if resolution == "480p":
        return True, True
    if resolution == "720p":
        return True, False
    return False, False


_SPEEDUP_SILENT_SPEEDS: dict[str, float] = {"1×": 1.0, "5×": 5.0, "10×": 10.0}


def _speedup_to_silent_speed(label: str) -> float:
    """Map the Speedup radio label to a silent-speed multiplier."""

    return _SPEEDUP_SILENT_SPEEDS.get(label, 10.0)


def process_video_ui(
    file_path: Optional[str],
    resolution: str,
    silent_speed: Optional[float],
    video_codec: str,
    optimize: bool,
    add_codec_suffix: bool,
    use_global_ffmpeg: bool,
    sounded_speed: Optional[float],
    silent_threshold: Optional[float],
    cut_enabled: bool,
    cut_start_seconds: Optional[float],
    cut_end_seconds: Optional[float],
    progress: Optional[gr.Progress] = gr.Progress(track_tqdm=False),
    *,
    dependencies: Optional[ProcessVideoDependencies] = None,
) -> Iterator[tuple[Optional[str], str, str, str, Optional[str]]]:
    """Browser handler: map the new controls and yield 5-tuples.

    The 5-tuple is ``(video, log, summary_compact, details, download)``.
    ``silent_speed`` is the Advanced slider value (the Speedup radio writes into
    that slider), so a custom slider value is honored.
    """

    small_video, small_480 = _resolution_to_flags(resolution)

    for kind, payload in _stream_pipeline(
        file_path,
        small_video,
        small_480,
        optimize,
        video_codec,
        add_codec_suffix,
        use_global_ffmpeg,
        silent_threshold,
        sounded_speed,
        silent_speed,
        cut_enabled,
        cut_start_seconds,
        cut_end_seconds,
        dependencies,
    ):
        if kind == "log":
            yield (
                gr.update(),
                cast(str, payload),
                gr.update(),
                gr.update(),
                gr.update(),
            )
        elif kind == "progress":
            if progress is not None:
                current, total, desc = cast(tuple[int, int, str], payload)
                percent = current / total if total > 0 else 0
                progress(percent, total=total, desc=desc)
        elif kind == "done":
            final_result, log_text = cast(
                tuple[ProcessingResult, str], payload
            )
            compact = _format_summary_compact(final_result)
            details = _format_details(final_result)
            output_path = str(final_result.output_file)
            is_audio_only = (
                Path(final_result.output_file).suffix.lower() == ".mp3"
            )
            yield (
                None if is_audio_only else output_path,
                log_text,
                compact,
                details,
                output_path,
            )


def process_video_api(
    file_path: Optional[str],
    small_video: bool,
    small_480: bool = False,
    optimize: bool = True,
    video_codec: str = "h264",
    add_codec_suffix: bool = False,
    use_global_ffmpeg: bool = False,
    silent_threshold: Optional[float] = None,
    sounded_speed: Optional[float] = None,
    silent_speed: Optional[float] = None,
    cut_enabled: bool = False,
    cut_start_seconds: Optional[float] = None,
    cut_end_seconds: Optional[float] = None,
) -> Iterator[tuple[Optional[str], str, str, Optional[str]]]:
    """Clean-signature wrapper registered via ``gr.api`` (requires type hints).

    Preserves the 13-arg positional contract and 4-tuple output that
    ``service_client`` depends on.
    """

    yield from process_video(
        file_path,
        small_video,
        small_480,
        optimize,
        video_codec,
        add_codec_suffix,
        use_global_ffmpeg,
        silent_threshold,
        sounded_speed,
        silent_speed,
        cut_enabled,
        cut_start_seconds,
        cut_end_seconds,
    )
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_server.py -k "resolution_to_flags or speedup_to_silent_speed or process_video_ui" -v`
Expected: PASS.

- [ ] **Step 5: Add exports and format/commit**

Add `"process_video_ui"` and `"process_video_api"` to the `__all__` list in `server.py`.

```bash
.venv/bin/python -m black talks_reducer/server.py tests/test_server.py
.venv/bin/python -m isort talks_reducer/server.py tests/test_server.py
git add talks_reducer/server.py tests/test_server.py
git commit -m "feat: Add web UI handler and decoupled API wrapper for process_video"
```

---

### Task 4: Rebuild `build_interface` layout and wiring

**Files:**
- Modify: `talks_reducer/server.py` (`build_interface`, ~lines 1026-1173)

**Interfaces:**
- Consumes: `process_video_ui`, `process_video_api`, `_resolution_to_flags`, `_speedup_to_silent_speed` (Task 3).

This task is mostly Gradio layout with no unit-testable logic; it is verified manually in Task 6. Keep the changes minimal and follow the existing component style.

- [ ] **Step 1: Replace the controls block**

Inside `with gr.Blocks(...) as demo:`, restructure to (in order): shortened title/markdown + collapsed About accordion; file input; Resolution radio; Speedup radio; codec dropdown (with `elem_classes`); Cut checkbox + hidden start/end row; collapsed Advanced accordion (optimize, use-global, add-suffix, silent-speed slider, sounded-speed slider, threshold slider); processed video; compact summary markdown; collapsed Details accordion; download; collapsed Log accordion.

Replace the region from the intro `gr.Markdown(...)` through the `log_output = ...` line with:

```python
        gr.Markdown(f"## Talks Reducer Web UI{version_suffix}")
        with gr.Accordion("About", open=False):
            gr.Markdown(
                f"""
                Drop a video or audio file below. Pick a **Resolution** and
                **Speedup**, choose the **Video codec**, and processing starts on
                upload. Open **Advanced** for encoder toggles and fine-grained
                speed/threshold controls.

                Video will be rendered on server **{server_identity}**.
                """.strip()
            )

        file_input = gr.File(
            label="Video or audio file",
            file_types=["video", "audio"],
            type="filepath",
        )

        resolution_radio = gr.Radio(
            choices=["No change", "720p", "480p"],
            value="720p",
            label="Resolution",
        )
        speedup_radio = gr.Radio(
            choices=["1×", "5×", "10×"],
            value="10×",
            label="Speedup",
        )
        codec_dropdown = gr.Dropdown(
            choices=[
                ("h.265 (25% smaller)", "hevc"),
                ("h.264 (10% faster)", "h264"),
                ("av1 (no advantages)", "av1"),
                ("mp3 (audio only)", "mp3"),
            ],
            value="hevc",
            label="Video codec",
            elem_classes=["tr-codec"],
        )

        cut_enabled_checkbox = gr.Checkbox(label="Cut video", value=False)
        with gr.Row(visible=False) as cut_row:
            cut_start_input = gr.Number(value=0.0, minimum=0.0, label="Cut start (seconds)")
            cut_end_input = gr.Number(value=0.0, minimum=0.0, label="Cut end (seconds)")

        global_ffmpeg_info = (
            "Prefer the FFmpeg binary from PATH instead of the bundled build."
            if global_ffmpeg_available
            else "Global FFmpeg not detected; the bundled build will be used."
        )
        with gr.Accordion("Advanced", open=False):
            optimize_checkbox = gr.Checkbox(label="Optimized encoding", value=True)
            use_global_ffmpeg_checkbox = gr.Checkbox(
                label="Use global FFmpeg",
                value=False,
                info=global_ffmpeg_info,
                interactive=global_ffmpeg_available,
            )
            add_codec_suffix_checkbox = gr.Checkbox(
                label="Append codec to filename",
                value=False,
                info="Append the selected codec (e.g. _h264) to the output filename.",
            )
            silent_speed_input = gr.Slider(
                minimum=1.0, maximum=10.0, value=10.0, step=0.1, label="Silent speed"
            )
            sounded_speed_input = gr.Slider(
                minimum=0.5, maximum=3.0, value=1.0, step=0.01, label="Sounded speed"
            )
            silent_threshold_input = gr.Slider(
                minimum=0.0, maximum=1.0, value=0.01, step=0.01, label="Silent threshold"
            )

        video_output = gr.Video(label="Processed video")
        summary_output = gr.Markdown()
        with gr.Accordion("Details", open=False):
            details_output = gr.Markdown()
        download_output = gr.File(label="Download processed file", interactive=False)
        with gr.Accordion("Log", open=False):
            log_output = gr.Textbox(label="Log", lines=12, interactive=False)
```

- [ ] **Step 2: Add the codec-height CSS to the Blocks**

Change the Blocks constructor to pass `css`:

```python
    with gr.Blocks(
        title=f"Talks Reducer Web UI{version_suffix}",
        css=".tr-codec { max-width: 22rem; } .tr-codec .wrap { min-height: 0; }",
    ) as demo:
```

- [ ] **Step 3: Wire the dynamic behaviors and handlers**

Replace the `file_input.upload(process_video, ...)` block with the radio→slider sync, the cut-row toggle, the browser upload handler, and the decoupled API registration:

```python
        speedup_radio.change(
            lambda label: gr.update(value=_speedup_to_silent_speed(label)),
            inputs=speedup_radio,
            outputs=silent_speed_input,
        )
        cut_enabled_checkbox.change(
            lambda enabled: gr.update(visible=bool(enabled)),
            inputs=cut_enabled_checkbox,
            outputs=cut_row,
        )

        file_input.upload(
            process_video_ui,
            inputs=[
                file_input,
                resolution_radio,
                silent_speed_input,
                codec_dropdown,
                optimize_checkbox,
                add_codec_suffix_checkbox,
                use_global_ffmpeg_checkbox,
                sounded_speed_input,
                silent_threshold_input,
                cut_enabled_checkbox,
                cut_start_input,
                cut_end_input,
            ],
            outputs=[
                video_output,
                log_output,
                summary_output,
                details_output,
                download_output,
            ],
            queue=True,
        )

        gr.api(process_video_api, api_name="process_video")
```

Note the `inputs` order matches `process_video_ui`'s positional parameters exactly: file, resolution, silent_speed (slider), codec, optimize, add_suffix, use_global, sounded_speed, silent_threshold, cut_enabled, cut_start, cut_end.

- [ ] **Step 4: Import-sanity check**

Run: `.venv/bin/python -c "import talks_reducer.server as s; d = s.build_interface(); print('build_interface OK')"`
Expected: prints `build_interface OK` with no exception.

- [ ] **Step 5: Run the full server test module**

Run: `.venv/bin/python -m pytest tests/test_server.py -q`
Expected: PASS (no test asserts the old flat layout; if any references removed component variables, update it to the new structure).

- [ ] **Step 6: Format and commit**

```bash
.venv/bin/python -m black talks_reducer/server.py
.venv/bin/python -m isort talks_reducer/server.py
git add talks_reducer/server.py
git commit -m "feat: Declutter web UI with resolution/speedup radios and accordions"
```

---

### Task 5: Enable Gradio PWA on both launches

**Files:**
- Modify: `talks_reducer/server.py` (`main`, `demo.launch(...)` ~line 1183)
- Modify: `talks_reducer/server_tray.py` (`demo.launch(...)` ~line 349)

- [ ] **Step 1: Add `pwa=True` in `server.py`**

In `main`, add `pwa=True` to the `demo.launch(...)` call:

```python
    demo.launch(
        server_name=args.host,
        server_port=args.port,
        share=args.share,
        inbrowser=args.open_browser,
        favicon_path=_FAVICON_PATH_STR,
        app_kwargs=build_launch_app_kwargs(),
        pwa=True,
    )
```

- [ ] **Step 2: Add `pwa=True` in `server_tray.py`**

Add `pwa=True` to the `demo.launch(...)` call there (keep the other kwargs unchanged):

```python
        server = demo.launch(
            ...,
            app_kwargs=_build_launch_app_kwargs(),
            pwa=True,
        )
```

(Replace `...` with the existing kwargs; only add the `pwa=True` line.)

- [ ] **Step 3: Import-sanity check**

Run: `.venv/bin/python -c "import talks_reducer.server, talks_reducer.server_tray; print('imports OK')"`
Expected: `imports OK`.

- [ ] **Step 4: Commit**

```bash
git add talks_reducer/server.py talks_reducer/server_tray.py
git commit -m "feat: Enable Gradio PWA on server and tray launches"
```

---

### Task 6: Full verification (suite + live API round-trip + UI)

**Files:** none (verification only).

- [ ] **Step 1: Run the full test suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all pass (previous baseline was 791 passed + the tests added here).

- [ ] **Step 2: Confirm formatting is clean**

Run: `.venv/bin/python -m black --check talks_reducer/server.py talks_reducer/server_tray.py tests/test_server.py && .venv/bin/python -m isort --check-only talks_reducer/server.py talks_reducer/server_tray.py tests/test_server.py`
Expected: no reformatting needed.

- [ ] **Step 2b: Prepare a tiny test clip**

Run: `.venv/bin/python -c "import subprocess,talks_reducer.ffmpeg as f; exe=f.find_ffmpeg(); subprocess.run([exe,'-y','-f','lavfi','-i','testsrc=duration=3:size=320x240:rate=10','-f','lavfi','-i','sine=frequency=440:duration=3','-shortest','/tmp/tr_clip.mp4'],check=True); print('clip ready')"`
Expected: `clip ready` and `/tmp/tr_clip.mp4` exists. (If `find_ffmpeg` differs, use the bundled binary discovery already used by the project.)

- [ ] **Step 3: Live API round-trip (guards the gr.api decoupling)**

Start the server in the background on a test port, then run the client:

```bash
.venv/bin/python -m talks_reducer.server --host 127.0.0.1 --port 9099 --no-browser &
sleep 8
.venv/bin/python -m talks_reducer.service_client \
  --server http://127.0.0.1:9099/ \
  --input /tmp/tr_clip.mp4 \
  --output /tmp/tr_out.mp4 --print-log
kill %1
```

Expected: the client uploads, processing completes, and `/tmp/tr_out.mp4` is written. This proves the `gr.api`-registered `process_video` endpoint still accepts the 13-arg call and returns the 4-tuple. If the client errors with "Unexpected response from server" or an endpoint-not-found, the API decoupling regressed — revisit Task 3/4.

- [ ] **Step 4: Manual UI/PWA check**

Open `http://127.0.0.1:9099/` (re-launch if needed). Confirm:
- The About, Advanced, Details, and Log sections are collapsed by default.
- The Cut start/end row is hidden until "Cut video" is checked.
- Selecting a Speedup radio updates the Advanced silent-speed slider.
- Uploading the clip processes it and the summary reads like
  `Duration: 3s -> Ns (NN%)` with the Details accordion holding Input/Output/Chunks/Encoder.
- Gradio **Settings** no longer shows "Progressive Web App is not enabled".

- [ ] **Step 5: Update the TODO and commit (finalize)**

Remove the "Clean up the PWA mode interface" line from `docs/TODO.md`.

```bash
git add docs/TODO.md
git commit -m "task: clear completed PWA cleanup item"
```

---

## Self-Review

**Spec coverage:**
- Clutter → accordions + radios: Task 4. ✓
- Compact summary format: Task 1. ✓
- Details collapsed below video: Tasks 1 (format) + 3 (5th output) + 4 (accordion). ✓
- Cut collapse-until-checked + remove info text: Task 4. ✓
- Speedup radio (1/5/10, default 10) + Advanced silent-speed slider: Tasks 3-4. ✓
- Resolution radio (No change/720/480, default 720): Tasks 3-4. ✓
- Extra toggles into Advanced: Task 4. ✓
- Shorten + collapse description: Task 4. ✓
- Reduce codec dropdown height: Task 4 (CSS). ✓
- API stability (service_client): Tasks 2-3 + Task 6 live round-trip. ✓
- Enable PWA (`pwa=True`): Task 5. ✓

**Placeholder scan:** No TBD/TODO-in-code; every code step shows complete code. The only `...` is in Task 5 Step 2 with an explicit instruction to preserve existing kwargs. ✓

**Type consistency:** `_stream_pipeline` event tuples (`"log"`/`"progress"`/`"done"`) are produced in Task 2 and consumed identically in `process_video` (Task 2) and `process_video_ui` (Task 3). `process_video_ui` input order matches the Task 4 `inputs=[...]` list. `process_video_api` mirrors `process_video`'s 13-arg order. ✓
