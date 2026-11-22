# Full-mode layout polish — design

## Intent

The full (non-Simple) window jumps around and clips its own content: the drop
zone grows and shrinks as panels open, the Cut video panel spends two rows and
double-height buttons on what fits in one, and an open Advanced block runs off
the bottom of the window (the last visible row is *Voice padding, ms*). The goal
is a stable, everything-reachable full layout. Simple mode is out of scope.

## Goals

1. **Drop zone** — fixed 50px tall in full mode, independent of window height and
   of panels appearing (Cut video, Advanced). Scaled with display DPI so it does
   not shrink on 150% screens. Simple mode keeps the large, stretching zone.
2. **Cut video** — `Start [slider][time]  End [slider][time]  [Convert] [Remove only]`
   on one row, buttons single height. The Remove row stays below.
3. **Speedup x** — the two long-pause entries centre their text.
4. **Speedup no voice** — 12px gap from the Silence speedup buttons, the same as
   *Add codec suffix*; the 12px trailing gap becomes one shared constant.
5. **Advanced** — the block sits in a scrollable canvas whose height is what the
   window has left after the other rows, recomputed on resize. The log keeps a
   few visible lines; the scrollbar only shows when the content does not fit.

## Non-goals

- Simple mode layout, window default sizes, theme colours.

## Approaches (for the Advanced block)

- **Fills the remaining height (chosen)** — uses all available space on tall
  windows, scrolls only when needed. Needs a `<Configure>` handler.
- **Fixed max height (~250px)** — simpler, but wastes space on tall windows and
  still clips on short ones.

The user approved the first.

## Constraints

- The stub suite models no geometry, so layout is verified in a real window and,
  where feasible, in `tests/test_gui_real_tk.py`.
- Never mix geometry managers on one widget; the canvas wrapper, not
  `advanced_frame`, is what `toggle_advanced`/`apply_simple_mode` show and hide.
- Theme restyling must reach the new canvas background.

## Left to the builder

Exact log minimum, mouse-wheel binding scope, DPI scaling helper.
