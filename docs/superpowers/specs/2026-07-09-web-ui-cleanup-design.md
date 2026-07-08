# Web UI (PWA) cleanup — design

## Goal

Reduce clutter and improve mobile/installed-app fit of the Gradio web UI
(`build_interface` in `talks_reducer/server.py`). The default view should show
only the essentials; advanced knobs and verbose result details collapse into
accordions. The result summary becomes a compact one-glance format.

Constraint: `talks_reducer/service_client.py` consumes the server response as
**exactly four outputs** (it skips stream frames whose length != 4 and unpacks
`video, log, summary, download = prediction`). Therefore `process_video` MUST
keep its 4-tuple generator contract and `api_name="process_video"` unchanged.
The browser gets a separate handler (`process_video_ui`) that adds the extra
Details output and translates the new radios; both share one internal core so
the pipeline/setup logic is not duplicated.

## Layout (top to bottom)

1. Title + "rendered on server X" line — visible.
2. **About** — `gr.Accordion(open=False)`. One short intro line stays visible;
   the rest of the current descriptive prose moves inside.
3. File drop zone (video/audio).
4. **Resolution** radio: `No change / 720p / 480p`, default **720p**. Replaces
   the Small + Target 480p checkboxes.
5. **Speedup** radio: `1× / 5× / 10×`, default **10×**. Replaces the primary
   silent-speed slider.
6. **Video codec** dropdown — reduced height via CSS (`elem_classes`).
7. **Cut video** checkbox (no info text). The start/end row is hidden until the
   checkbox is checked; the cut-end info text is removed.
8. **Advanced** — `gr.Accordion(open=False)`:
   - Optimized encoding (checkbox)
   - Use global FFmpeg (checkbox)
   - Append codec to filename (checkbox)
   - Silent speed (slider) — custom override; the Speedup radio writes into it
   - Sounded speed (slider)
   - Silent threshold (slider)
9. **Processed video** output.
10. **Results** summary (visible), reformatted (see below).
11. **Details** — `gr.Accordion(open=False)`: Input, Output, Chunks merged,
    Encoder.
12. Download processed file.
13. **Log** — `gr.Accordion(open=False)` wrapping the existing log textbox.

## Handlers and shared core

- Extract the setup + event-stream consumption from today's `process_video`
  into an internal generator, e.g. `_iter_processing(...)`, that yields
  `("frame", collected_logs)` progress updates and finally a
  `("result", ProcessingResult)`. Both public handlers drive this core so the
  pipeline wiring lives in one place.
- `process_video(...)` — unchanged public signature, `api_name="process_video"`,
  still yields 4-tuples `(video, log, summary, download)`. Its `summary` keeps
  the full text (compact headline + the detail lines) so API consumers lose
  nothing.
- `process_video_ui(...)` — the browser `.upload` handler. Takes the new
  controls, maps them (below), and yields 5-tuples
  `(video, log, summary_compact, details, download)` for the UI components. It
  is NOT exposed under `api_name`.

### Control → argument mapping (in `process_video_ui`)

- Resolution radio → `(small, small_480)`:
  - `No change` → `small=False, small_480=False`
  - `720p` → `small=True, small_480=False`
  - `480p` → `small=True, small_480=True`
- Speedup radio → writes the matching value (1.0 / 5.0 / 10.0) into the
  silent-speed slider via a `.change` handler. The **slider value** is what is
  passed as `silent_speed`, so a custom slider value is honored even if it no
  longer matches a radio option. Default slider value = 10.0.

## Summary reformat

`_format_summary_compact(result)` returns the two headline lines:

```
Duration: 1h12m12s -> 59m34s (72%)
Size: 506M -> 258M (50%)
```

- Duration uses a no-space compact form (`1h12m12s`, `59m34s`, `12s`); order is
  `original -> output (pct%)` where pct = `output_duration / original_duration`.
- Size reads byte sizes from `result.input_file.stat()` and
  `result.output_file.stat()`, formats them compactly (`506M`, `1.2G`, integer
  MB with no decimal where whole), and pct = `output / input`. When a file is
  missing or a ratio is undefined, that line is omitted.

`_format_details(result)` returns the Input / Output / Chunks merged / Encoder
lines shown inside the UI Details accordion.

`_format_summary(result)` (kept for the API path) returns
`_format_summary_compact(result)` followed by the `_format_details(result)`
lines, preserving today's information for `process_video`'s `summary` output.

## Testing

Unit tests (pure functions, no Gradio/browser needed):
- `_format_duration_compact`: 0s, seconds-only, minutes, hours; no spaces.
- `_format_summary_compact`: given a `ProcessingResult` + real temp files,
  asserts the exact `Duration:`/`Size:` lines and percentages.
- `_format_details`: asserts Input/Output/Chunks/Encoder lines.
- `_format_summary` (API path): still contains the detail lines so the
  `process_video` output stays informative.
- Resolution mapping: the three radio values → correct `(small, small_480)`.
- Speedup mapping: the three radio values → 1.0 / 5.0 / 10.0.
- Regression guard: a `process_video` run still yields 4-tuples (protects the
  `service_client` contract).

Manual/visual (Gradio layout, can't be asserted headlessly): launch
`talks-reducer server`, confirm the accordions collapse, the cut row toggles
with the checkbox, the radios drive processing, and the summary renders in the
new format. This is called out because it is not covered by automated tests.

## Out of scope

- No change to the desktop GUI or CLI.
- No change to the PWA manifest/icon/standalone plumbing (already works).
- No new dependencies.
