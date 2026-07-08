# Web UI (PWA) cleanup — design

## Goal

Reduce clutter and improve mobile/installed-app fit of the Gradio web UI
(`build_interface` in `talks_reducer/server.py`). The default view should show
only the essentials; advanced knobs and verbose result details collapse into
accordions. The result summary becomes a compact one-glance format. Also enable
Gradio's built-in PWA support so the installed app is a real PWA (service
worker + manifest wiring), not just a browser "add to home screen" shortcut.

Constraint: `talks_reducer/service_client.py` submits **13 positional args in
the current `process_video` order** to `api_name="/process_video"` and consumes
the response as **exactly four outputs** (it skips stream frames whose length
!= 4 and unpacks `video, log, summary, download = prediction`). Therefore the
programmatic endpoint MUST keep that input order and 4-tuple output.

Because the browser handler's inputs change (radios) and it gains a fifth
Details output, `api_name` cannot ride on the browser `.upload` listener. The
API is instead registered independently with `gr.api(...)` (available in the
pinned Gradio 6.6.0), so the browser UI and the stable programmatic contract
are decoupled. Both call one shared internal core so the pipeline/setup logic
is not duplicated.

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
  into an internal generator `_stream_pipeline(...)` that yields semantic
  events: `("log", full_log_str)` on each log update (including the initial
  upload receipt), `("progress", (current, total, desc))`, and finally
  `("done", (result, full_log_str))`. It raises the collected `gr.Error` on
  failure, exactly as today. Both public handlers drive this core so the
  pipeline wiring lives in one place.
- `process_video(...)` — unchanged public signature and default args; still a
  generator yielding 4-tuples `(video, log, summary, download)`, where `summary`
  is the full text (compact headline + detail lines) so API consumers lose
  nothing. It maps core events: `"log"` → `(gr.update(), log, gr.update(),
  gr.update())`, `"progress"` → drives the `progress` widget, `"done"` →
  the final 4-tuple.
- The programmatic endpoint is registered with
  `gr.api(process_video, api_name="process_video")` inside `build_interface`,
  keeping the input order and 4-tuple output the client expects. (If `gr.api`
  signature introspection rejects the `progress`/`dependencies` params, wrap it
  in a clean-signature generator `process_video_api(...)` that `yield from`s
  `process_video(...)` and register that instead.)
- `process_video_ui(...)` — the browser `.upload` handler, NOT exposed under
  `api_name`. Takes the new controls, maps them (below), and yields 5-tuples
  `(video, log, summary_compact, details, download)`. It maps the same core
  events but formats the compact summary and details separately on `"done"`.

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
- Update the existing `test_process_video_streams_events_and_returns_result`,
  which currently asserts the old summary substrings `"25.0%"`/`"30.0%"`, to
  match the new compact format (integer percent, and size percent derived from
  the actual output/input byte sizes of the test's files).

End-to-end (must actually run, not just unit tests):
- Launch `talks-reducer server` on a port and run
  `python -m talks_reducer.service_client --server http://127.0.0.1:<port>/
  --input <small clip> --output <tmp>` to confirm the `gr.api`-registered
  endpoint still accepts the 13-arg call and returns a downloadable file. This
  guards the decoupled-API change that unit tests cannot cover.
- Load the page and confirm the Gradio Settings panel no longer shows the
  "PWA is not enabled" warning (the `pwa=True` change).

Manual/visual (Gradio layout, can't be asserted headlessly): launch
`talks-reducer server`, confirm the accordions collapse, the cut row toggles
with the checkbox, the radios drive processing, and the summary renders in the
new format. This is called out because it is not covered by automated tests.

## Enable Gradio PWA

Both `demo.launch(...)` calls omit `pwa=True`, so Gradio never registers a
service worker or its PWA wiring and its Settings panel reports "Progressive Web
App is not enabled" — even inside an Android install obtained via the browser's
generic "add to home screen." The custom `PWAManifestMiddleware` still serves
`/manifest.json` + the branded icon regardless.

Change:
- Pass `pwa=True` to `demo.launch(...)` in `talks_reducer/server.py` (`main`)
  and in `talks_reducer/server_tray.py` (the tray launch).
- The `PWAManifestMiddleware` continues to override the manifest content at the
  ASGI layer, so Gradio supplies the service worker + wiring and Talks Reducer
  keeps its branding/icon. No manifest logic changes.

Verified: `pwa` is a valid `Blocks.launch` parameter in the pinned Gradio
(6.6.0). This is server launch configuration, exercised manually (the Settings
panel should stop showing the warning and offer install); no unit test asserts
a live service worker.

## Out of scope

- No change to the desktop GUI or CLI.
- No change to the PWA manifest/icon/standalone plumbing (already works).
- No new dependencies.
