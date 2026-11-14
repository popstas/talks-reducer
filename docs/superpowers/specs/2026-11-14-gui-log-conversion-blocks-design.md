# GUI log: one readable block per conversion

## Intent

The GUI log panel accumulates every run in a window session and is never cleared. Today
it is hard to find where one conversion ends and the next begins, and it carries noise
(duplicated `… completed` lines, a trailing `All jobs finished successfully.`). The goal
is that each conversion reads as a self-contained block that can be found by eye.

## Goals

- Each conversion (one file, or one glued input) opens with a header:
  `### Processing <filename>: <params>`
  where `<params>` always lists the effective settings (option B):
  resolution (`orig`/`1080p`/`720p`/`480p`), codec, fps (`30 fps`/`60 fps`/`orig fps`),
  `silent ×N`, `sounded ×N`, then `threshold N` — or `no voice` instead of the threshold
  when voice detection is on — plus `cut HH:MM:SS–HH:MM:SS` / `remove N ranges` when set.
  Example: `### Processing VID_20260220_145517_DOLBY.mp4: 480p, h.265, 30 fps, silent ×10, sounded ×1, threshold 0.01`
- Two empty lines precede every header except the first one in the log widget.
- Each conversion ends with a two-line summary:
  ```
  Completed: C:\Users\…\VID_20260220_145517_DOLBY_speedup_small_480.mp4
  Duration: 00:11:22, Time: 99.31% (00:12:13), Size: 1.57% (1.5 MB)
  ```
  `Duration` = wall-clock conversion time of that file; `Time` = output/input duration
  ratio with the output duration; `Size` = output/input size ratio with the output size.
  Percentages to two decimals, times as `HH:MM:SS`.
- `All jobs finished successfully.` is no longer written.
- `Extracting audio: completed` and `Generating final: completed` appear once each.
- Local and remote runs produce the same header and summary shape.

## Non-goals

- CLI output is unchanged (the CLI's own `Completed:`/`Result:` lines stay).
- The status bar text, progress bar, taskbar and bell behaviour stay as they are.
- The streamed `Server log:` dump in remote mode stays.

## Anti-goals

- Removing the marker line must not lose the success status, the 100% bar, the taskbar
  finish or the completion bell.
- The per-file progress reset must keep working when the `Processing:` line changes shape.

## Approaches

**Duplicate `completed` lines** — root cause: `run_timed_ffmpeg_command` calls
`progress.finish()` inside `with task_manager as progress`, and `__exit__` calls
`finish()` again.
- *Chosen:* make `CallbackProgressHandle.finish()` idempotent (fire `on_finish` once).
  Fixes every caller, including future `with … finish()` patterns.
- *Rejected:* delete the explicit `finish()` in `ffmpeg.py` — leaves the trap in place.

**Replacing the `All jobs finished successfully.` marker** — `SummaryManager.handle_status_transitions`
uses that log text to set the success status; the `processing` prefix branch resets the bar
per file.
- *Chosen:* move the success branch into an explicit method (e.g. `gui._finish_run()`)
  called directly by the local worker and `_process_files_via_server`; the per-file header
  triggers an explicit reset rather than relying on the `processing` log prefix. State no
  longer depends on log wording.
- *Rejected:* keep a hidden marker that the parser sees but the widget does not show —
  smaller diff, but log text keeps driving state.

## Decided

- Header params: option B (always the effective settings), format as above.
- Idempotent `finish()`; explicit `_finish_run()` instead of the log marker.
- Remote summaries switch from the server's Markdown `**Duration:**`/`**Size:**` lines to
  the same two-line `Completed:` format.

## Calls made by Claude (check these)

- Blank-line separator is inserted by the header writer when the log widget is non-empty,
  so it also separates consecutive runs, not only files within one batch.
- Remote summary numbers are computed locally: size ratio from the local input and
  downloaded output sizes, time ratio and output duration from `get_video_duration` on both
  files — the server rounds its percentages to integers, which would not match the
  two-decimal format. `Duration` for remote covers upload + processing + download.
- `Processing aborted by user.` / `Processing failed: …` stay as they are and end the block.

## Left to the builder

- Exact helper names and where the header/summary formatters live (likely
  `gui/summaries.py`, next to `format_file_size`).
- Updating the GUI tests that assert on `All jobs finished successfully.` or the old
  `Completed: … (Time: …, Size: …)` line, and adding tests for the header, separator,
  summary and the single `completed` line.
- README sync if it documents the log lines.
